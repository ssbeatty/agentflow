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
