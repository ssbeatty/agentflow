"""Warm worker pool (services/worker_pool.py) + engine routing.

Exercises the real per-script persistent worker on the backend python (no venv):
  - a worker runs a job and is REUSED for the next job (the whole point — run #2
    skips a fresh process),
  - a job that raises does NOT kill the worker (unlike the one-shot runner which
    exits(1)); the next job still succeeds,
  - invalidate/reuse-on-changed-python retires a worker,
  - the engine routes a warm script through the pool end-to-end and reuses.

These run without the langchain stack (trivial `run`), so they're fast.
"""
import asyncio
import json
from pathlib import Path

import pytest

from services import worker_pool
from services.venv_manager import get_script_dir

_PREFIX = "__AGENTFLOW__"


@pytest.fixture(autouse=True)
def _pool(monkeypatch):
    # Enable routing + start from a clean pool; always tear the workers down.
    monkeypatch.setattr(worker_pool, "WARM_WORKERS_ENABLED", True)
    worker_pool.manager.shutdown_all()
    yield
    worker_pool.manager.shutdown_all()


def _setup_script(sid: str, main_py: str) -> Path:
    d = get_script_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.py").write_text(main_py, encoding="utf-8")
    return d


async def _run_job(worker, run_dir: Path, input_obj: dict, entry: str = "run") -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "_input.json").write_text(json.dumps(input_obj), encoding="utf-8")
    out: dict = {"data": None, "error": None}

    async def handler(is_stderr: bool, line: str) -> None:
        if line.startswith(_PREFIX):
            p = json.loads(line[len(_PREFIX):])
            if p.get("type") == "result":
                out["data"] = p.get("data")
            elif p.get("type") == "error":
                out["error"] = p
    job = {"job_id": "j", "run_dir": str(run_dir), "entry_fn": entry,
           "env": {"AGENTFLOW_EXECUTION_ID": "j"}}
    out["ok"] = await worker.run_job(job, handler)
    return out


ECHO_MAIN = (
    "def run(input):\n"
    "    return {'echo': input.get('x'), 'n': input.get('n', 0) + 1}\n"
)


def test_worker_runs_and_is_reused():
    async def go():
        sid = "wp-reuse"
        sdir = _setup_script(sid, ECHO_MAIN)
        w1 = await worker_pool.manager.acquire(sid, "run", preheat=False)
        r1 = await _run_job(w1, sdir / "runs" / "e1", {"x": "hi", "n": 1})
        assert r1["ok"] is True
        assert r1["data"] == {"echo": "hi", "n": 2}
        assert w1.jobs_run == 1

        # Second acquire returns the SAME (warm) worker; job #2 runs on it.
        w2 = await worker_pool.manager.acquire(sid, "run", preheat=False)
        assert w2 is w1
        r2 = await _run_job(w2, sdir / "runs" / "e2", {"x": "again", "n": 41})
        assert r2["data"] == {"echo": "again", "n": 42}
        assert w1.jobs_run == 2
        assert w1.alive()
    asyncio.run(go())


def test_job_error_does_not_kill_worker():
    async def go():
        sid = "wp-error"
        main = (
            "def run(input):\n"
            "    if input.get('boom'):\n"
            "        raise ValueError('kaboom')\n"
            "    return {'ok': True}\n"
        )
        sdir = _setup_script(sid, main)
        w = await worker_pool.manager.acquire(sid, "run", preheat=False)

        bad = await _run_job(w, sdir / "runs" / "b", {"boom": True})
        assert bad["ok"] is False
        assert bad["error"] and "kaboom" in bad["error"]["traceback"]
        assert w.alive(), "a job error must NOT kill the warm worker"

        good = await _run_job(w, sdir / "runs" / "g", {"boom": False})
        assert good["ok"] is True and good["data"] == {"ok": True}
        assert w.jobs_run == 2
    asyncio.run(go())


def test_invalidate_retires_worker():
    async def go():
        sid = "wp-inv"
        _setup_script(sid, ECHO_MAIN)
        w = await worker_pool.manager.acquire(sid, "run", preheat=False)
        assert w.alive()
        assert worker_pool.manager.invalidate(sid) is True
        assert not w.alive()
        assert worker_pool.manager.get(sid) is None
        # Re-acquire spawns a fresh worker.
        w2 = await worker_pool.manager.acquire(sid, "run", preheat=False)
        assert w2 is not w
    asyncio.run(go())


def test_per_job_env_is_isolated():
    # Env vars set for one job must not leak into a job that doesn't set them.
    async def go():
        sid = "wp-env"
        main = (
            "import os\n"
            "def run(input):\n"
            "    return {'seen': os.environ.get('AGENTFLOW_SECRET_FOO')}\n"
        )
        sdir = _setup_script(sid, main)
        w = await worker_pool.manager.acquire(sid, "run", preheat=False)

        # job 1 sets the secret via env
        rd1 = sdir / "runs" / "j1"
        rd1.mkdir(parents=True, exist_ok=True)
        (rd1 / "_input.json").write_text("{}", encoding="utf-8")
        seen1 = {}

        async def h1(is_stderr, line):
            if line.startswith(_PREFIX):
                p = json.loads(line[len(_PREFIX):])
                if p.get("type") == "result":
                    seen1["v"] = p["data"]["seen"]
        await w.run_job({"job_id": "1", "run_dir": str(rd1), "entry_fn": "run",
                         "env": {"AGENTFLOW_SECRET_FOO": "sekret"}}, h1)
        assert seen1["v"] == "sekret"

        # job 2 does NOT set it → must be gone (not leaked from job 1)
        r2 = await _run_job(w, sdir / "runs" / "j2", {})
        assert r2["data"]["seen"] is None
    asyncio.run(go())


def test_token_stream_not_corrupted_by_raw_double_emit():
    """Regression: a warm worker must mark itself in-platform BEFORE importing
    agentflow. agentflow.token() decides whether to ALSO write the raw content to
    stdout (its non-platform fallback) from a module-level _IN_PLATFORM frozen at
    import time. The worker imports agentflow at boot, before any job env carries
    the execution id — so without the fix _IN_PLATFORM is False and token() emits
    BOTH the `__AGENTFLOW__` protocol line AND a bare, newline-less
    sys.stdout.write(content). The bare write glues onto the NEXT protocol line, so
    every token after the first arrives as a corrupt raw line (`aa__AGENTFLOW__…`)
    instead of a clean token event — exactly the chat-page corruption we saw once
    warm workers were enabled."""
    async def go():
        sid = "wp-token"
        main = (
            "import agentflow\n"
            "def run(input):\n"
            "    for t in ['aa', 'bb', 'cc']:\n"
            "        agentflow.token(t)\n"
            "    return {'reply': 'aabbcc'}\n"
        )
        sdir = _setup_script(sid, main)
        w = await worker_pool.manager.acquire(sid, "run", preheat=False)

        rd = sdir / "runs" / "t1"
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "_input.json").write_text("{}", encoding="utf-8")
        lines: list[tuple[bool, str]] = []

        async def handler(is_stderr, line):
            lines.append((is_stderr, line))

        job = {"job_id": "t", "run_dir": str(rd), "entry_fn": "run",
               "env": {"AGENTFLOW_EXECUTION_ID": "t"}}
        ok = await w.run_job(job, handler)
        assert ok is True

        tokens = [
            json.loads(l[len(_PREFIX):]).get("content")
            for _, l in lines
            if l.startswith(_PREFIX) and json.loads(l[len(_PREFIX):]).get("type") == "token"
        ]
        assert tokens == ["aa", "bb", "cc"], tokens
        # No non-protocol line may embed a protocol marker (the double-emit signature).
        corrupt = [l for _, l in lines if not l.startswith(_PREFIX) and _PREFIX in l]
        assert not corrupt, f"token() double-emitted raw content into the stream: {corrupt}"
    asyncio.run(go())


def test_engine_routes_through_worker_and_reuses(db, monkeypatch):
    """End-to-end: two runs of a warm script go through the pool, both complete,
    and the second reuses the first's worker (the whole point).

    Both runs are driven inside ONE event loop — matching production (a single
    long-lived uvicorn loop). A warm worker's asyncio.Queue is bound to the loop
    that spawned it, so reuse across separate `asyncio.run()` calls (a new loop
    each time) would fail; that's a test artifact, not a runtime issue."""
    from app.models import Execution, Script, ScriptFile
    from services import execution_engine

    monkeypatch.setattr(execution_engine, "EXECUTION_TIMEOUT", 90.0)
    execution_engine._semaphore = None  # fresh semaphore inside the loop below

    script = Script(name="warm-script", entry_function="run", warm=True)
    db.add(script)
    db.flush()
    db.add(ScriptFile(
        script_id=script.id, filename="main.py", is_main=True,
        content="def run(input):\n    return {'doubled': input.get('n', 0) * 2}\n",
    ))
    db.commit()
    sid = script.id

    def _new_exec(n: int) -> str:
        exc = Execution(script_id=sid, status="pending", input_data={"n": n})
        db.add(exc)
        db.commit()
        return exc.id

    async def go():
        eid1 = _new_exec(3)
        await execution_engine.start_execution(eid1)
        eid2 = _new_exec(21)
        await execution_engine.start_execution(eid2)
        return eid1, eid2

    eid1, eid2 = asyncio.run(go())
    db.expire_all()

    r1 = db.query(Execution).filter_by(id=eid1).first()
    r2 = db.query(Execution).filter_by(id=eid2).first()
    assert r1.status == "completed", r1.error
    assert r1.output_data == {"doubled": 6}
    assert r2.status == "completed", r2.error
    assert r2.output_data == {"doubled": 42}
    # one worker served both jobs → run #2 skipped a fresh process
    w = worker_pool.manager.get(sid)
    assert w is not None and w.jobs_run == 2


def test_worker_enabled_gating(db):
    from app.models import Script
    # flag on (fixture), warm script → enabled
    s = Script(name="w", warm=True)
    assert worker_pool.worker_enabled(s) is True
    # warm=False opts out
    s.warm = False
    assert worker_pool.worker_enabled(s) is False
    # global flag off → disabled regardless
    s.warm = True
    import services.worker_pool as wp
    orig = wp.WARM_WORKERS_ENABLED
    wp.WARM_WORKERS_ENABLED = False
    try:
        assert worker_pool.worker_enabled(s) is False
    finally:
        wp.WARM_WORKERS_ENABLED = orig
