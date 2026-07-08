"""End-to-end execution-engine regression tests.

Unlike the static example checks, these actually **drive `start_execution()`** —
they write a real `main.py`, spawn the runner subprocess, and assert on the
persisted `Execution` row + logs. This is the layer where "I ran a script and hit
a problem" bugs live, so this file is the home for those regressions.

No per-script venv is built: a script without a venv falls back to the backend
python (`sys.executable`, i.e. the interpreter running the tests), so a missing
import fails there too — reproducing the real error naturally and fast.

The seed case is **"missing dependency"**: a script that imports a package that
isn't installed must end `failed`, surface `ModuleNotFoundError` in
`execution.error`, AND persist it as an error log (so it's visible in the Logs
panel on reload, not just a transient toast) — a contract documented in CLAUDE.md.
"""
import asyncio

import pytest

from app.models import Execution, ExecutionLog, Script, ScriptFile
from services import execution_engine


@pytest.fixture(autouse=True)
def _fast_engine(monkeypatch):
    # Fresh semaphore inside this test's event loop; short timeout so a hung
    # subprocess can never stall the suite for the 600s production default.
    monkeypatch.setattr(execution_engine, "_semaphore", None)
    monkeypatch.setattr(execution_engine, "EXECUTION_TIMEOUT", 90.0)


def _run(db, main_py: str, *, entry: str = "run", input_data: dict | None = None) -> Execution:
    """Create a one-file script, run it to completion, return the Execution row."""
    script = Script(name="regression-test-script", entry_function=entry)
    db.add(script)
    db.flush()
    db.add(ScriptFile(script_id=script.id, filename="main.py", content=main_py, is_main=True))
    execution = Execution(script_id=script.id, status="pending", input_data=input_data or {})
    db.add(execution)
    db.commit()
    eid = execution.id

    asyncio.run(execution_engine.start_execution(eid))

    db.expire_all()  # re-read what start_execution's own session committed
    return db.query(Execution).filter_by(id=eid).first()


def test_missing_dependency_fails_with_visible_error(db):
    main_py = (
        "import totally_missing_dependency_xyz  # not installed anywhere\n\n"
        "def run(input):\n"
        "    return {'ok': True}\n"
    )

    execution = _run(db, main_py)

    assert execution.status == "failed"
    assert execution.error, "a failed run must never have a blank error"
    assert "No module named" in execution.error
    assert "totally_missing_dependency_xyz" in execution.error

    # The crash must ALSO be persisted as an error log (Logs panel / reload),
    # not only in execution.error.
    error_logs = (
        db.query(ExecutionLog)
        .filter_by(execution_id=execution.id, level="error")
        .all()
    )
    assert error_logs, "the crash should be persisted as an error-level log"
    assert any("No module named" in log.message for log in error_logs)


def test_stop_records_cancel_intent_for_inflight_run_without_live_proc():
    """A stop clicked while a run is in-flight but before it registers its
    subprocess (e.g. during a warm worker's cold boot) must still record the
    cancel intent, so finalization honors it instead of overwriting the row back
    to completed/failed. Regression for stop_execution returning early without
    marking _cancelled_ids."""
    eid = "cancel-race-inflight-no-proc"
    execution_engine._cancelled_ids.discard(eid)
    execution_engine._procs.pop(eid, None)
    execution_engine._inflight.add(eid)  # simulate a live coroutine, mid cold-boot
    try:
        stopped = asyncio.run(execution_engine.stop_execution(eid))
        assert stopped is False  # nothing live to kill yet…
        assert eid in execution_engine._cancelled_ids  # …but the intent IS recorded
    finally:
        execution_engine._cancelled_ids.discard(eid)
        execution_engine._inflight.discard(eid)


def test_stop_on_finished_run_does_not_leak_cancel_intent():
    """A stop targeting a run with no live coroutine (already finished — e.g. the
    run_sync timeout path calls stop_execution after the task ended) must NOT add
    to _cancelled_ids: nothing would ever discard it, so it would leak forever."""
    eid = "cancel-on-finished-run"
    execution_engine._cancelled_ids.discard(eid)
    execution_engine._procs.pop(eid, None)
    execution_engine._inflight.discard(eid)  # NOT in-flight

    stopped = asyncio.run(execution_engine.stop_execution(eid))

    assert stopped is False
    assert eid not in execution_engine._cancelled_ids  # no leak


def test_cancel_intent_wins_over_a_successful_run(db):
    """If a stop was recorded before/while the run finished, the row must end
    `cancelled`, never `completed` — a run must never be resurrected out of a
    cancel. Exercises the pre-dispatch guard + the _finalize_run cancel-honor."""
    script = Script(name="cancel-honor-script", entry_function="run")
    db.add(script)
    db.flush()
    db.add(ScriptFile(
        script_id=script.id, filename="main.py",
        content="def run(input):\n    return {'ok': True}\n", is_main=True,
    ))
    execution = Execution(script_id=script.id, status="pending", input_data={})
    db.add(execution)
    db.commit()
    eid = execution.id

    execution_engine._cancelled_ids.add(eid)  # simulate a stop recorded pre-run
    try:
        asyncio.run(execution_engine.start_execution(eid))
    finally:
        execution_engine._cancelled_ids.discard(eid)

    db.expire_all()
    row = db.query(Execution).filter_by(id=eid).first()
    assert row.status == "cancelled", f"expected cancelled, got {row.status}"


def test_successful_run_completes_and_returns_output(db):
    # Sanity anchor: the same harness produces a clean success, so a `failed`
    # result above is meaningful (not just "everything always fails").
    main_py = (
        "def run(input):\n"
        "    return {'echo': input.get('value')}\n"
    )

    execution = _run(db, main_py, input_data={"value": 42})

    assert execution.status == "completed"
    assert execution.error in (None, "")
    assert execution.output_data == {"echo": 42}


def test_metrics_counters_move_on_real_runs(db):
    """The Prometheus terminal-counter hook fires through the REAL engine (not
    just the unit-level observe_execution): a completed and a failed run each bump
    agentflow_executions_total for their status, and both bump _started_total."""
    from prometheus_client import REGISTRY

    def val(name, labels=None):
        return REGISTRY.get_sample_value(name, labels or {}) or 0.0

    started0 = val("agentflow_executions_started_total", {"trigger": "manual"})
    completed0 = val("agentflow_executions_total", {"status": "completed", "trigger": "manual"})
    failed0 = val("agentflow_executions_total", {"status": "failed", "trigger": "manual"})

    ok = _run(db, "def run(input):\n    return {'ok': 1}\n")
    assert ok.status == "completed"
    bad = _run(db, "import nope_missing_xyz\n\ndef run(input):\n    return {}\n")
    assert bad.status == "failed"

    assert val("agentflow_executions_started_total", {"trigger": "manual"}) == started0 + 2
    assert val("agentflow_executions_total", {"status": "completed", "trigger": "manual"}) == completed0 + 1
    assert val("agentflow_executions_total", {"status": "failed", "trigger": "manual"}) == failed0 + 1


def test_input_schema_mismatch_fails_before_running(db):
    # A script with an input_schema must reject a mismatched input with a clean
    # `failed` run (visible error), never reaching user code. Guards the
    # universal validation in start_execution (covers eval/cron/rerun too).
    script = Script(name="typed-script", entry_function="run")
    script.input_schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }
    db.add(script)
    db.flush()
    db.add(ScriptFile(
        script_id=script.id, filename="main.py", is_main=True,
        content="def run(input):\n    return {'ok': True}\n",  # would succeed if reached
    ))
    execution = Execution(script_id=script.id, status="pending", input_data={"wrong": 1})
    db.add(execution)
    db.commit()
    eid = execution.id

    asyncio.run(execution_engine.start_execution(eid))

    db.expire_all()
    row = db.query(Execution).filter_by(id=eid).first()
    assert row.status == "failed"
    assert "validation failed" in (row.error or "").lower()
    assert "city" in (row.error or "")

    # And a matching input still runs to completion (schema doesn't block valid input).
    good = Execution(script_id=script.id, status="pending", input_data={"city": "NYC"})
    db.add(good)
    db.commit()
    gid = good.id
    asyncio.run(execution_engine.start_execution(gid))
    db.expire_all()
    assert db.query(Execution).filter_by(id=gid).first().status == "completed"


def test_failure_triggers_notification_hook(db, monkeypatch):
    # A final failure must fire the failure-notification hook wired into
    # _finalize_run / _mark_failed. Record the call rather than actually sending.
    called = []
    monkeypatch.setattr(execution_engine, "schedule_failure_notification",
                        lambda eid: called.append(eid))
    execution = _run(db, "def run(input):\n    raise RuntimeError('boom')\n")
    assert execution.status == "failed"
    assert called == [execution.id], "a failed run must trigger the notification hook"


def test_success_does_not_trigger_notification_hook(db, monkeypatch):
    called = []
    monkeypatch.setattr(execution_engine, "schedule_failure_notification",
                        lambda eid: called.append(eid))
    execution = _run(db, "def run(input):\n    return {'ok': True}\n")
    assert execution.status == "completed"
    assert called == [], "a successful run must not notify"


def test_completion_callback_fires_on_terminal(db, monkeypatch):
    # The completion webhook must fire on EVERY terminal state — a caller that
    # submitted async (POST /run?wait=false) wants to be told when the run is
    # done, whatever the outcome. Record the call instead of POSTing.
    called = []
    monkeypatch.setattr(execution_engine, "schedule_completion_callback",
                        lambda eid: called.append(eid))
    ok = _run(db, "def run(input):\n    return {'ok': True}\n")
    assert ok.status == "completed"
    assert called == [ok.id], "a completed run must fire the completion webhook hook"

    called.clear()
    bad = _run(db, "def run(input):\n    raise RuntimeError('boom')\n")
    assert bad.status == "failed"
    assert called == [bad.id], "a failed run must also fire the completion webhook hook"
    # (The "don't fire while a retry is still pending" branch — status=="failed"
    #  and retry_count < max_retries → _schedule_retry, else callback — is a plain
    #  guard in _finalize_run; not exercised here to avoid orphaning a retry
    #  subprocess past the test's asyncio.run.)


def test_unserializable_return_stringifies_not_crashes(db):
    """Regression (F6): a run() returning a dict with a NESTED non-JSON-native
    value (an object / a set / bytes) must not crash the runner with a raw json
    TypeError from platform internals. `default=str` in the runner's _emit
    stringifies such values so the run still completes with a best-effort output
    (the top-level result guard only covered a non-container top level)."""
    main_py = (
        "def run(input):\n"
        "    return {'obj': object(), 'nums': {1, 2, 3}}\n"
    )
    execution = _run(db, main_py)
    assert execution.status == "completed", execution.error
    out = execution.output_data or {}
    assert isinstance(out.get("obj"), str) and "object" in out["obj"]
    assert isinstance(out.get("nums"), str)  # a set isn't JSON-native → stringified


def test_unchanged_script_file_not_rewritten(db):
    """Regression (F7 — concurrent same-script file race): every run materializes
    the script's files into the SHARED script_dir, which each run's subprocess
    imports. Rewriting main.py on every run means a concurrent run's subprocess can
    import it mid-truncate → 'module user_script has no attribute run'. The engine
    must SKIP the write when the on-disk content is already identical, so the shared
    file is never needlessly truncated out from under a concurrent importer."""
    import pathlib
    from services.venv_manager import get_script_dir

    script = Script(name="norace", entry_function="run")
    db.add(script)
    db.flush()
    db.add(ScriptFile(script_id=script.id, filename="main.py", is_main=True,
                      content="def run(input):\n    return {'ok': True}\n"))
    e1 = Execution(script_id=script.id, status="pending", input_data={})
    db.add(e1)
    db.commit()
    eid1 = e1.id

    asyncio.run(execution_engine.start_execution(eid1))
    db.expire_all()
    assert db.query(Execution).filter_by(id=eid1).first().status == "completed"

    shared_main = get_script_dir(script.id) / "main.py"
    assert shared_main.exists()

    # spy on writes to the SHARED main.py during a second run of the same script
    orig_write = pathlib.Path.write_text
    writes: list[str] = []

    def _spy(self, *a, **k):
        if str(self) == str(shared_main):
            writes.append(str(self))
        return orig_write(self, *a, **k)

    pathlib.Path.write_text = _spy
    try:
        execution_engine._semaphore = None  # fresh semaphore for the new loop below
        e2 = Execution(script_id=script.id, status="pending", input_data={})
        db.add(e2)
        db.commit()
        eid2 = e2.id
        asyncio.run(execution_engine.start_execution(eid2))
    finally:
        pathlib.Path.write_text = orig_write

    db.expire_all()
    assert db.query(Execution).filter_by(id=eid2).first().status == "completed"
    assert writes == [], "unchanged shared script_dir/main.py must not be rewritten"


def test_stopped_run_is_cancelled_not_failed(db):
    # Regression: stop_execution() kills the subprocess, which exits non-zero.
    # Without remembering the stop was deliberate, finalization marked it "failed"
    # with a misleading "Process exited with code 1 without reporting an error …"
    # synth message + a WARNING log. A user-initiated stop must record "cancelled"
    # and leave no error.
    main_py = (
        "import time\n\n"
        "def run(input):\n"
        "    time.sleep(30)\n"
        "    return {'done': True}\n"
    )
    script = Script(name="stoppable", entry_function="run")
    db.add(script)
    db.flush()
    db.add(ScriptFile(script_id=script.id, filename="main.py", content=main_py, is_main=True))
    execution = Execution(script_id=script.id, status="pending", input_data={})
    db.add(execution)
    db.commit()
    eid = execution.id

    async def _drive():
        task = execution_engine.spawn_execution(eid)
        # Wait until the subprocess is actually registered, then stop it mid-run.
        for _ in range(100):
            if eid in execution_engine._procs:
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)
        await execution_engine.stop_execution(eid)
        await task

    asyncio.run(_drive())

    db.expire_all()
    row = db.query(Execution).filter_by(id=eid).first()
    assert row.status == "cancelled"
    assert not (row.error or ""), "a cancelled run must not carry a synth failure error"
    # No engine-level error log should be persisted for a deliberate stop.
    err_logs = db.query(ExecutionLog).filter_by(execution_id=eid, level="error").all()
    assert err_logs == [], "a cancelled run should not log an error"
