"""Cron scheduler timezone resolution.

The cron scheduler must interpret crontab expressions in a *configurable* zone
(``SCHEDULER_TIMEZONE`` / the container ``TZ``), not silently in UTC — otherwise
a user in Beijing who writes ``0 9 * * *`` gets a run at 17:00 local. A blank
setting follows the process/container local zone; a bad name must warn and fall
back, never crash startup. ``tzdata`` (a pinned backend dep) makes named zones
resolve on the slim docker image, so these run identically in CI.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from services import scheduler as sched


def test_valid_timezone_resolves(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "Asia/Shanghai")
    tz = sched._resolve_timezone()
    assert isinstance(tz, ZoneInfo)
    assert str(tz) == "Asia/Shanghai"


def test_blank_timezone_follows_local(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "")
    assert sched._resolve_timezone() is None  # None → APScheduler uses local/TZ


def test_whitespace_timezone_treated_as_blank(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "   ")
    assert sched._resolve_timezone() is None


def test_bad_timezone_falls_back_without_crashing(monkeypatch):
    # An unresolvable name must degrade to local, not raise (which would crash
    # scheduler construction → app startup).
    monkeypatch.setattr(settings, "scheduler_timezone", "Not/A_Real_Zone")
    assert sched._resolve_timezone() is None


def test_service_uses_configured_timezone(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "Asia/Tokyo")
    svc = sched.SchedulerService()
    assert svc.effective_timezone() == "Asia/Tokyo"


def test_effective_timezone_always_round_trips(monkeypatch):
    # Even when blank (local/UTC), the reported name must be a real zone the
    # /timezone endpoint can feed back into ZoneInfo to compute the offset.
    monkeypatch.setattr(settings, "scheduler_timezone", "")
    name = sched.SchedulerService().effective_timezone()
    assert name
    datetime.now(ZoneInfo(name))  # must not raise


def test_upsert_job_trigger_carries_configured_timezone(monkeypatch):
    """Regression: a pre-constructed CronTrigger does NOT inherit the scheduler's
    default timezone — with no explicit tz it locks in `get_localzone()` at
    creation. So upsert_job MUST pass the scheduler tz into from_crontab, else
    SCHEDULER_TIMEZONE is silently ignored and cron fires in the host-local zone
    (UTC on the slim image). We assert with a configured zone DIFFERENT from this
    host's local zone, so a regression (trigger following local) is caught."""
    monkeypatch.setattr(settings, "scheduler_timezone", "America/New_York")
    svc = sched.SchedulerService()

    captured = {}
    monkeypatch.setattr(svc._scheduler, "get_job", lambda jid: None)
    monkeypatch.setattr(svc._scheduler, "add_job",
                        lambda func, trigger, **kw: captured.update(trigger=trigger))

    svc.upsert_job("cj1", "s1", "0 9 * * *", {})
    assert str(captured["trigger"].timezone) == "America/New_York"


def test_timezone_endpoint_shape(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "Asia/Shanghai")
    from app.routers import cron_jobs
    monkeypatch.setattr(cron_jobs, "scheduler_service", sched.SchedulerService())

    out = cron_jobs.get_timezone()
    assert out["timezone"] == "Asia/Shanghai"
    assert out["utc_offset"] == "+08:00"  # formatted "+HH:MM"
    assert out["configured"] is True
