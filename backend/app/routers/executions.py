import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Execution, Script
from app.schemas import ExecutionCreate, ExecutionDetail, ExecutionSummary
from services.execution_engine import spawn_execution, stop_execution

router = APIRouter()


@router.get("", response_model=list[ExecutionSummary])
def list_executions(script_id: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Execution).order_by(Execution.created_at.desc())
    if script_id:
        q = q.filter_by(script_id=script_id)
    return q.limit(limit).all()


@router.post("", response_model=ExecutionSummary, status_code=201)
async def create_execution(body: ExecutionCreate, db: Session = Depends(get_db)):
    script = db.query(Script).filter_by(id=body.script_id).first()
    if not script:
        raise HTTPException(404, "Script not found")

    exc = Execution(script_id=body.script_id, input_data=body.input_data or {})
    db.add(exc)
    db.commit()
    db.refresh(exc)

    spawn_execution(exc.id)
    return exc


@router.post("/run", status_code=200)
async def run_sync(body: ExecutionCreate, timeout: float = 300.0):
    """
    Synchronous execution endpoint for external callers. Blocks until the
    script finishes (or `timeout` seconds elapse). Returns the same shape as
    GET /executions/{id}, so a single round-trip yields the final result.

    Example:
      curl -X POST http://host/api/executions/run?timeout=60 \
           -d '{"script_id":"...","input_data":{...}}'
    """
    db = SessionLocal()
    try:
        if not db.query(Script).filter_by(id=body.script_id).first():
            raise HTTPException(404, "Script not found")
        exc = Execution(script_id=body.script_id, input_data=body.input_data or {})
        db.add(exc)
        db.commit()
        db.refresh(exc)
        execution_id = exc.id
    finally:
        db.close()

    task = spawn_execution(execution_id)
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        await stop_execution(execution_id)
        raise HTTPException(504, f"Execution exceeded {timeout}s timeout")

    db = SessionLocal()
    try:
        final = db.query(Execution).filter_by(id=execution_id).first()
        return {
            "id": final.id,
            "status": final.status,
            "output_data": final.output_data,
            "error": final.error,
            "started_at": final.started_at,
            "finished_at": final.finished_at,
        }
    finally:
        db.close()


@router.get("/{execution_id}", response_model=ExecutionDetail)
def get_execution(execution_id: str, db: Session = Depends(get_db)):
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")
    return exc


@router.post("/{execution_id}/stop", status_code=200)
async def stop(execution_id: str, db: Session = Depends(get_db)):
    from datetime import datetime
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")

    stopped = await stop_execution(execution_id)

    # if the row was left dangling (e.g. backend restart killed the process
    # before it could finalize), correct it here so the UI unsticks.
    if exc.status in ("running", "pending"):
        exc.status = "cancelled"
        exc.finished_at = datetime.utcnow()
        db.commit()

    return {"stopped": stopped, "status": exc.status}
