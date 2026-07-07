"""
APScheduler wrapper.
Each enabled CronJob gets a job registered here.
On trigger → creates Execution row + kicks off start_execution().
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


def _resolve_timezone():
    """Timezone the scheduler should interpret crontabs in.

    ``SCHEDULER_TIMEZONE`` (an IANA name like ``Asia/Shanghai``) wins; empty →
    return ``None`` so APScheduler follows the process/container local zone (the
    standard ``TZ`` env var, or UTC if unset). A bad/unresolvable name never
    crashes startup — we log a warning and fall back to local. Requires the
    ``tzdata`` package so named zones resolve on the slim docker image.
    """
    from app.config import settings
    name = (settings.scheduler_timezone or "").strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception as e:  # ZoneInfoNotFoundError, bad name, missing tzdata …
        log.warning("Invalid SCHEDULER_TIMEZONE %r (%s); using local timezone", name, e)
        return None


class SchedulerService:
    def __init__(self):
        tz = _resolve_timezone()
        self._scheduler = AsyncIOScheduler(timezone=tz) if tz is not None else AsyncIOScheduler()
        log.info("Scheduler timezone: %s", self.effective_timezone())

    def effective_timezone(self) -> str:
        """IANA name of the timezone cron jobs actually fire in (for the UI)."""
        try:
            return str(self._scheduler.timezone)
        except Exception:
            return "UTC"

    def start(self) -> None:
        self._scheduler.start()
        self._reload_all()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    # ── public API ────────────────────────────────────────────────────────────

    def upsert_job(self, cron_job_id: str, script_id: str, cron_expr: str, input_data: dict) -> None:
        """Add or replace a scheduler job for this cron record."""
        job_id = f"cron_{cron_job_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        self._scheduler.add_job(
            self._fire,
            CronTrigger.from_crontab(cron_expr),
            id=job_id,
            args=[cron_job_id, script_id, input_data],
            replace_existing=True,
            misfire_grace_time=60,
        )

    def remove_job(self, cron_job_id: str) -> None:
        job_id = f"cron_{cron_job_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    # ── internals ─────────────────────────────────────────────────────────────

    def _reload_all(self) -> None:
        from app.database import SessionLocal
        from app.models import CronJob
        db = SessionLocal()
        try:
            jobs = db.query(CronJob).filter_by(enabled=True).all()
            for j in jobs:
                try:
                    self.upsert_job(j.id, j.script_id, j.cron_expression, j.input_data or {})
                except Exception as e:
                    log.warning("Failed to load cron job %s: %s", j.id, e)
            log.info("Loaded %d enabled cron job(s)", len(jobs))
        finally:
            db.close()

    async def _fire(self, cron_job_id: str, script_id: str, input_data: dict) -> None:
        from datetime import datetime
        from app.database import SessionLocal
        from app.models import Execution, CronJob
        from services.execution_engine import spawn_execution

        db = SessionLocal()
        try:
            exc = Execution(script_id=script_id, input_data=input_data, trigger="cron")
            db.add(exc)
            job = db.query(CronJob).filter_by(id=cron_job_id).first()
            if job:
                job.last_run_at = datetime.utcnow()
            db.commit()
            execution_id = exc.id
        finally:
            db.close()

        log.info("Cron job %s fired -> execution %s (script=%s)", cron_job_id, execution_id, script_id)
        spawn_execution(execution_id)


scheduler_service = SchedulerService()
