import asyncio
import mimetypes
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Execution, Script
from app.schemas import ExecutionCreate, ExecutionDetail, ExecutionSummary
from app.auth_deps import require_admin, require_api_key_or_admin
from services.execution_engine import (
    spawn_execution, stop_execution, queue_stats, delete_run_dir,
    MAX_CONCURRENT, EXECUTION_TIMEOUT,
)
from services.venv_manager import get_script_dir

router = APIRouter()

# Management endpoints below require a logged-in operator; the public run
# endpoint (POST /run) overrides this with an API-key-or-admin gate.
_admin = [Depends(require_admin)]


@router.get("/queue-stats", dependencies=_admin)
def get_queue_stats(db: Session = Depends(get_db)):
    """Return current concurrency and queue depth."""
    queued = db.query(Execution).filter_by(status="queued").count()
    running = db.query(Execution).filter_by(status="running").count()
    stats = queue_stats()
    return {
        "max_concurrent": MAX_CONCURRENT,
        "execution_timeout_secs": EXECUTION_TIMEOUT,
        "running": running,
        "queued": queued,
        "slots_free": max(0, MAX_CONCURRENT - stats["running_slots_used"]),
    }


@router.get("", response_model=list[ExecutionSummary], dependencies=_admin)
def list_executions(script_id: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Execution).order_by(Execution.created_at.desc())
    if script_id:
        q = q.filter_by(script_id=script_id)
    return q.limit(limit).all()


@router.post("", response_model=ExecutionSummary, status_code=201, dependencies=_admin)
async def create_execution(body: ExecutionCreate, db: Session = Depends(get_db)):
    script = db.query(Script).filter_by(id=body.script_id).first()
    if not script:
        raise HTTPException(404, "Script not found")
    if body.max_retries < 0 or body.max_retries > 10:
        raise HTTPException(422, "max_retries must be between 0 and 10")

    exc = Execution(
        script_id=body.script_id,
        input_data=body.input_data or {},
        max_retries=body.max_retries,
    )
    db.add(exc)
    db.commit()
    db.refresh(exc)

    spawn_execution(exc.id)
    return exc


@router.post("/run", status_code=200, dependencies=[Depends(require_api_key_or_admin)])
async def run_sync(body: ExecutionCreate, timeout: float = 300.0):
    """
    Synchronous execution endpoint for external callers. Blocks until the
    script finishes (or `timeout` seconds elapse). Returns the same shape as
    GET /executions/{id}, so a single round-trip yields the final result.

    Auth: an issued API key (`X-API-Key: af_…` or `Authorization: Bearer af_…`)
    or a logged-in admin session.
    """
    db = SessionLocal()
    try:
        if not db.query(Script).filter_by(id=body.script_id).first():
            raise HTTPException(404, "Script not found")
        exc = Execution(
            script_id=body.script_id,
            input_data=body.input_data or {},
            max_retries=body.max_retries,
        )
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
            "retry_count": final.retry_count,
        }
    finally:
        db.close()


@router.delete("", status_code=200, dependencies=_admin)
def clear_executions(script_id: str, db: Session = Depends(get_db)):
    """Delete all finished (completed/failed/cancelled) execution records for a
    script, plus their per-run working dirs. In-flight runs are left untouched."""
    if not db.query(Script).filter_by(id=script_id).first():
        raise HTTPException(404, "Script not found")
    rows = (
        db.query(Execution)
        .filter(
            Execution.script_id == script_id,
            Execution.status.in_(["completed", "failed", "cancelled"]),
        )
        .all()
    )
    deleted = 0
    for r in rows:
        delete_run_dir(script_id, r.id)
        db.delete(r)  # cascade removes ExecutionLog rows
        deleted += 1
    db.commit()
    logger.info("Cleared {} execution record(s) for script {}", deleted, script_id)
    return {"deleted": deleted}


@router.get("/{execution_id}", response_model=ExecutionDetail, dependencies=_admin)
def get_execution(execution_id: str, db: Session = Depends(get_db)):
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")
    return exc


@router.delete("/{execution_id}", status_code=204, dependencies=_admin)
def delete_execution(execution_id: str, db: Session = Depends(get_db)):
    """Delete a single execution record + its per-run working dir. An in-flight
    run must be stopped first (409)."""
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")
    if exc.status in ("running", "queued", "pending"):
        raise HTTPException(409, "Stop the run before deleting it")
    delete_run_dir(exc.script_id, exc.id)
    db.delete(exc)  # cascade removes ExecutionLog rows
    db.commit()


@router.post("/{execution_id}/stop", status_code=200, dependencies=_admin)
async def stop(execution_id: str, db: Session = Depends(get_db)):
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")

    stopped = await stop_execution(execution_id)

    if exc.status in ("running", "pending", "queued"):
        exc.status = "cancelled"
        exc.finished_at = datetime.utcnow()
        db.commit()

    return {"stopped": stopped, "status": exc.status}


@router.post("/{execution_id}/rerun", response_model=ExecutionSummary, status_code=201, dependencies=_admin)
async def rerun(execution_id: str, db: Session = Depends(get_db)):
    """Create a new execution using the same script and input as an existing one."""
    orig = db.query(Execution).filter_by(id=execution_id).first()
    if not orig:
        raise HTTPException(404, "Execution not found")

    new_exc = Execution(
        script_id=orig.script_id,
        input_data=orig.input_data,
        max_retries=orig.max_retries,
    )
    db.add(new_exc)
    db.commit()
    db.refresh(new_exc)

    spawn_execution(new_exc.id)
    return new_exc


@router.get("/{execution_id}/artifacts/{filename}", dependencies=_admin)
def get_artifact(execution_id: str, filename: str, db: Session = Depends(get_db)):
    """Serve a file written by an artifact emitter (image/, etc.)."""
    exc = db.query(Execution).filter_by(id=execution_id).first()
    if not exc:
        raise HTTPException(404, "execution not found")

    base = (get_script_dir(exc.script_id) / "runs" / execution_id / "_artifacts").resolve()
    target = (base / filename).resolve()
    # path-traversal guard
    if base != target and base not in target.parents:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "artifact not found")
    mime, _ = mimetypes.guess_type(target.name)
    return FileResponse(target, media_type=mime or "application/octet-stream")
