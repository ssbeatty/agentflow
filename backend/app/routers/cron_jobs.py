from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CronJob, Script
from app.schemas import CronJobCreate, CronJobUpdate, CronJobOut
from services.scheduler import scheduler_service

router = APIRouter()


@router.get("/timezone")
def get_timezone():
    """The timezone cron expressions are interpreted in (so the UI can tell the
    user whether `0 9 * * *` means 9am local or 9am UTC). Configured via
    SCHEDULER_TIMEZONE / the container `TZ`; see services/scheduler.py."""
    from datetime import datetime

    from app.config import settings

    tz_name = scheduler_service.effective_timezone()
    offset = None
    try:
        from zoneinfo import ZoneInfo
        raw = datetime.now(ZoneInfo(tz_name)).strftime("%z")  # e.g. "+0800"
        offset = f"{raw[:3]}:{raw[3:]}" if raw else None       # -> "+08:00"
    except Exception:
        pass
    return {"timezone": tz_name, "utc_offset": offset,
            "configured": bool(settings.scheduler_timezone)}


@router.get("", response_model=list[CronJobOut])
def list_jobs(script_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(CronJob).order_by(CronJob.created_at)
    if script_id:
        q = q.filter_by(script_id=script_id)
    return q.all()


@router.post("", response_model=CronJobOut, status_code=201)
def create_job(body: CronJobCreate, db: Session = Depends(get_db)):
    if not db.query(Script).filter_by(id=body.script_id).first():
        raise HTTPException(404, "Script not found")
    _validate_cron(body.cron_expression)
    job = CronJob(**body.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    if job.enabled:
        scheduler_service.upsert_job(job.id, job.script_id, job.cron_expression, job.input_data or {})
    return job


@router.patch("/{job_id}", response_model=CronJobOut)
def update_job(job_id: str, body: CronJobUpdate, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)
    data = body.model_dump(exclude_none=True)
    if "cron_expression" in data:
        _validate_cron(data["cron_expression"])
    for k, v in data.items():
        setattr(job, k, v)
    db.commit()
    db.refresh(job)
    if job.enabled:
        scheduler_service.upsert_job(job.id, job.script_id, job.cron_expression, job.input_data or {})
    else:
        scheduler_service.remove_job(job.id)
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)
    scheduler_service.remove_job(job.id)
    db.delete(job)
    db.commit()


def _get_or_404(job_id: str, db: Session) -> CronJob:
    j = db.query(CronJob).filter_by(id=job_id).first()
    if not j:
        raise HTTPException(404, "Cron job not found")
    return j


def _validate_cron(expr: str) -> None:
    from apscheduler.triggers.cron import CronTrigger
    try:
        CronTrigger.from_crontab(expr)
    except Exception:
        raise HTTPException(400, f"Invalid cron expression: {expr!r}")
