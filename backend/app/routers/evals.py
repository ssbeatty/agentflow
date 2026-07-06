"""Eval / regression endpoints: dataset (test case) CRUD + batch runs.

Admin-gated. Cases hold an input + assertions; a run executes every case through
the real engine and grades it, producing a pass/fail score that can be compared
across script revisions (services/eval_engine.py).
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EvalCase, EvalRun, Script
from app.schemas import (
    EvalCaseCreate, EvalCaseUpdate, EvalCaseOut,
    EvalRunCreate, EvalRunSummary, EvalRunDetail,
)
from app.auth_deps import require_admin
from services.eval_engine import start_eval_run

router = APIRouter()
_admin = [Depends(require_admin)]


def _validate_input_json(raw: str) -> None:
    try:
        obj = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"input_json is not valid JSON: {e}")
    if not isinstance(obj, dict):
        raise HTTPException(422, "input_json must be a JSON object")


# ── cases ─────────────────────────────────────────────────────────────────────

@router.get("/cases", response_model=list[EvalCaseOut], dependencies=_admin)
def list_cases(script_id: str, db: Session = Depends(get_db)):
    return (
        db.query(EvalCase).filter_by(script_id=script_id)
        .order_by(EvalCase.created_at).all()
    )


@router.post("/cases", response_model=EvalCaseOut, status_code=201, dependencies=_admin)
def create_case(body: EvalCaseCreate, db: Session = Depends(get_db)):
    if not db.query(Script).filter_by(id=body.script_id).first():
        raise HTTPException(404, "Script not found")
    _validate_input_json(body.input_json)
    case = EvalCase(
        script_id=body.script_id,
        name=body.name or "case",
        input_json=body.input_json or "{}",
        assertions=[a.model_dump() for a in body.assertions],
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.patch("/cases/{case_id}", response_model=EvalCaseOut, dependencies=_admin)
def update_case(case_id: str, body: EvalCaseUpdate, db: Session = Depends(get_db)):
    case = db.query(EvalCase).filter_by(id=case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    if body.name is not None:
        case.name = body.name
    if body.input_json is not None:
        _validate_input_json(body.input_json)
        case.input_json = body.input_json
    if body.assertions is not None:
        case.assertions = [a.model_dump() for a in body.assertions]
    db.commit()
    db.refresh(case)
    return case


@router.delete("/cases/{case_id}", status_code=204, dependencies=_admin)
def delete_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(EvalCase).filter_by(id=case_id).first()
    if case:
        db.delete(case)
        db.commit()


# ── runs ──────────────────────────────────────────────────────────────────────

@router.get("/runs", response_model=list[EvalRunSummary], dependencies=_admin)
def list_runs(script_id: str, limit: int = 20, db: Session = Depends(get_db)):
    return (
        db.query(EvalRun).filter_by(script_id=script_id)
        .order_by(EvalRun.created_at.desc()).limit(limit).all()
    )


@router.get("/runs/{run_id}", response_model=EvalRunDetail, dependencies=_admin)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(EvalRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs", response_model=EvalRunSummary, status_code=201, dependencies=_admin)
async def start_run(body: EvalRunCreate, db: Session = Depends(get_db)):
    # async so start_eval_run's asyncio.create_task has a running loop (a sync
    # handler runs in a threadpool thread with none → RuntimeError → 500).
    if not db.query(Script).filter_by(id=body.script_id).first():
        raise HTTPException(404, "Script not found")
    n_cases = db.query(EvalCase).filter_by(script_id=body.script_id).count()
    if n_cases == 0:
        raise HTTPException(422, "No eval cases to run")
    # Reap any stale "running" runs for this script (left over from a server
    # restart or an earlier error) so history doesn't accrue zombie rows. Only
    # one eval runs at a time from the UI, so a lingering "running" is dead.
    db.query(EvalRun).filter_by(script_id=body.script_id, status="running").update(
        {"status": "failed", "error": "did not complete (stale)", "finished_at": datetime.utcnow()},
        synchronize_session=False,
    )
    run = EvalRun(
        script_id=body.script_id,
        status="running",
        revision_number=body.revision_number,
        total=n_cases,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    start_eval_run(run.id)
    return run


@router.delete("/runs/{run_id}", status_code=204, dependencies=_admin)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(EvalRun).filter_by(id=run_id).first()
    if run:
        db.delete(run)
        db.commit()
