"""Eval router — the run-start path.

Regression: `POST /api/evals/runs` 500'd because `start_run` was a *sync* handler
(FastAPI runs those in a threadpool thread with no running event loop) while
`start_eval_run` used `asyncio.create_task`, which needs one. Each failed request
also left a committed `EvalRun` stuck at status="running" forever. Fixed by making
`start_run` async and reaping stale "running" runs on the next start.
"""
import asyncio

from app.models import EvalCase, EvalRun, Script
from app.routers import evals as evals_router
from app.schemas import EvalRunCreate
from services import eval_engine


def test_start_run_is_async():
    # The core guard: if this becomes a sync `def` again, the threadpool thread it
    # runs in has no event loop and start_eval_run's create_task 500s.
    assert asyncio.iscoroutinefunction(evals_router.start_run)


def test_start_run_schedules_task_and_reaps_zombies(db, monkeypatch):
    ran: list[str] = []

    async def _fake_run_eval(run_id):
        ran.append(run_id)

    # Replace the heavy engine-driven run with a no-op so we test only the
    # scheduling (asyncio.create_task) + zombie reaping, hermetically.
    monkeypatch.setattr(eval_engine, "run_eval", _fake_run_eval)

    script = Script(name="s")
    db.add(script)
    db.flush()
    db.add(EvalCase(script_id=script.id, name="c", input_json="{}",
                    assertions=[{"type": "contains", "value": "x"}]))
    zombie = EvalRun(script_id=script.id, status="running", total=1)  # stale leftover
    db.add(zombie)
    db.commit()
    zombie_id = zombie.id

    async def _call():
        run = await evals_router.start_run(EvalRunCreate(script_id=script.id), db=db)
        await asyncio.sleep(0.05)  # let the scheduled task run
        return run

    run = asyncio.run(_call())

    # the run was created and its task actually scheduled + executed (no 500)
    assert run.status == "running"
    assert ran == [run.id]
    # the pre-existing zombie was reaped so history doesn't accrue "running" rows
    db.expire_all()
    assert db.query(EvalRun).filter_by(id=zombie_id).first().status == "failed"


def test_start_run_rejects_when_no_cases(db):
    script = Script(name="empty")
    db.add(script)
    db.commit()

    async def _call():
        return await evals_router.start_run(EvalRunCreate(script_id=script.id), db=db)

    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        asyncio.run(_call())
    assert ei.value.status_code == 422
