import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Execution, Script
from app.schemas import ExecutionCreate, ExecutionDetail, ExecutionSummary
from services.execution_engine import start_execution, stop_execution

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

    asyncio.create_task(start_execution(exc.id))
    return exc


@router.get("/{execution_id}", response_model=ExecutionDetail)
def get_execution(execution_id: str, db: Session = Depends(get_db)):
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")
    return exc


@router.post("/{execution_id}/stop", status_code=200)
async def stop(execution_id: str, db: Session = Depends(get_db)):
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")
    if exc.status not in ("running", "pending"):
        raise HTTPException(400, "Execution is not running")
    stopped = await stop_execution(execution_id)
    return {"stopped": stopped}
