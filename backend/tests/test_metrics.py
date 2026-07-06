"""Prometheus /metrics surface (services/metrics.py + the auth gate).

Three layers, mirroring how the module is built:
  1. render()/enablement — the exposition endpoint works and is well-formed.
  2. record_* hook helpers — each increments the counter/histogram a hook site
     feeds (tested with before/after deltas since the counters are process-global
     module singletons shared across the suite).
  3. the live collector — DB-backed resource gauges reflect the current DB, read
     through a short-lived session at scrape time (uses the temp-sqlite `db`
     fixture).
Plus the require_metrics_access gate (public / token / api-key / reject).

No server is spun up — the collector and the auth dependency are exercised
directly, matching the rest of the suite.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from prometheus_client import REGISTRY
from starlette.requests import Request

from services import metrics


def _val(name: str, labels: dict | None = None) -> float:
    """Current value of a sample (triggers a fresh collect, so the live collector
    re-queries the DB). 0.0 when the series doesn't exist yet."""
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def _request(headers: dict | None = None, query: str = "", cookie: str | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookie:
        raw.append((b"cookie", cookie.encode()))
    return Request({
        "type": "http", "method": "GET", "path": "/metrics",
        "headers": raw, "query_string": query.encode(),
    })


# ── layer 1: render / enablement ──────────────────────────────────────────────

def test_module_enabled_and_renders():
    assert metrics.enabled() is True
    body, content_type = metrics.render()
    assert isinstance(body, bytes) and body
    assert "text/plain" in content_type
    # build info + a couple of always-present families
    assert b"agentflow_build_info" in body
    assert b"agentflow_warm_workers_enabled" in body


# ── layer 2: record helpers increment the right series ────────────────────────

def test_counter_helpers_increment():
    b = _val("agentflow_notifications_sent_total", {"provider": "bark", "outcome": "ok"})
    metrics.record_notification("bark", ok=True)
    assert _val("agentflow_notifications_sent_total", {"provider": "bark", "outcome": "ok"}) == b + 1

    b = _val("agentflow_callbacks_sent_total", {"outcome": "error"})
    metrics.record_callback(ok=False)
    assert _val("agentflow_callbacks_sent_total", {"outcome": "error"}) == b + 1

    b = _val("agentflow_execution_timeouts_total", {"path": "oneshot"})
    metrics.inc_timeout("oneshot")
    assert _val("agentflow_execution_timeouts_total", {"path": "oneshot"}) == b + 1

    b = _val("agentflow_execution_retries_total")
    metrics.inc_retry()
    assert _val("agentflow_execution_retries_total") == b + 1

    b = _val("agentflow_execution_stops_total", {"found": "false"})
    metrics.inc_stop(found=False)
    assert _val("agentflow_execution_stops_total", {"found": "false"}) == b + 1

    b = _val("agentflow_executions_pruned_total")
    metrics.inc_pruned(3)
    assert _val("agentflow_executions_pruned_total") == b + 3

    b = _val("agentflow_venv_builds_total", {"outcome": "ok"})
    metrics.record_venv_build(ok=True)
    assert _val("agentflow_venv_builds_total", {"outcome": "ok"}) == b + 1

    b = _val("agentflow_worker_jobs_total", {"ok": "true"})
    metrics.record_worker_job(True)
    assert _val("agentflow_worker_jobs_total", {"ok": "true"}) == b + 1

    b = _val("agentflow_worker_boots_total", {"preheat": "true"})
    bh = _val("agentflow_worker_boot_seconds_count", {"preheat": "true"})
    metrics.record_worker_boot(True, 1.5)
    assert _val("agentflow_worker_boots_total", {"preheat": "true"}) == b + 1
    assert _val("agentflow_worker_boot_seconds_count", {"preheat": "true"}) == bh + 1


def test_observe_profile_feeds_histograms():
    q = _val("agentflow_execution_queue_wait_seconds_count")
    c = _val("agentflow_execution_cold_import_seconds_count")
    metrics.observe_profile(queue_wait=0.4, prep=0.1, cold_import=2.0, script=3.0)
    assert _val("agentflow_execution_queue_wait_seconds_count") == q + 1
    assert _val("agentflow_execution_cold_import_seconds_count") == c + 1
    # negative / None values are ignored (no phantom observation)
    metrics.observe_profile(queue_wait=None, cold_import=-1)
    assert _val("agentflow_execution_cold_import_seconds_count") == c + 1


def test_observe_execution_counts_duration_and_tokens():
    start = datetime(2026, 1, 1, 12, 0, 0)
    row = SimpleNamespace(
        status="completed", trigger="cron",
        started_at=start, finished_at=start + timedelta(seconds=5),
        prompt_tokens=12, completion_tokens=8, llm_calls=2,
    )
    ct = _val("agentflow_executions_total", {"status": "completed", "trigger": "cron"})
    pt = _val("agentflow_llm_tokens_total", {"kind": "prompt"})
    calls = _val("agentflow_llm_calls_total")
    dur = _val("agentflow_execution_duration_seconds_count", {"status": "completed"})

    metrics.observe_execution(row)

    assert _val("agentflow_executions_total", {"status": "completed", "trigger": "cron"}) == ct + 1
    assert _val("agentflow_llm_tokens_total", {"kind": "prompt"}) == pt + 12
    assert _val("agentflow_llm_calls_total") == calls + 2
    assert _val("agentflow_execution_duration_seconds_count", {"status": "completed"}) == dur + 1


def test_observe_execution_is_defensive_on_partial_row():
    # A row that failed before running: no start/finish, no tokens. Must count
    # the terminal status but skip duration/tokens — and never raise.
    ct = _val("agentflow_executions_total", {"status": "failed", "trigger": "manual"})
    metrics.observe_execution(SimpleNamespace(status="failed", trigger="manual",
                                              started_at=None, finished_at=None))
    assert _val("agentflow_executions_total", {"status": "failed", "trigger": "manual"}) == ct + 1
    # a totally empty object still doesn't blow up (unknown status)
    metrics.observe_execution(SimpleNamespace())


# ── layer 3: live collector (DB-backed gauges) ────────────────────────────────

def test_live_collector_db_gauges(db):
    from app.models import ApiKey, Channel, CronJob, Execution, Script
    from app.security import generate_api_key

    s = Script(name="s1")
    db.add(s)
    db.flush()
    db.add(Execution(script_id=s.id, status="completed", trigger="cron"))
    db.add(Execution(script_id=s.id, status="failed", trigger="manual"))
    db.add(Execution(script_id=s.id, status="running", trigger="api"))
    _full, prefix, h = generate_api_key()
    db.add(ApiKey(name="scrape", prefix=prefix, key_hash=h, revoked=False))
    db.add(Channel(name="c", provider="openai", enabled=True, models=["gpt-4o"]))
    db.add(CronJob(script_id=s.id, cron_expression="* * * * *", enabled=False))
    db.commit()

    # the collector opens its OWN session against the same temp DB
    assert _val("agentflow_scripts") == 1
    assert _val("agentflow_executions_by_status", {"status": "completed"}) == 1
    assert _val("agentflow_executions_by_status", {"status": "failed"}) == 1
    assert _val("agentflow_executions_by_status", {"status": "running"}) == 1
    # zero-filled statuses that never occurred still report a series
    assert _val("agentflow_executions_by_status", {"status": "queued"}) == 0
    assert _val("agentflow_executions_by_trigger", {"trigger": "cron"}) == 1
    assert _val("agentflow_api_keys", {"state": "active"}) == 1
    assert _val("agentflow_api_keys", {"state": "revoked"}) == 0
    assert _val("agentflow_llm_channels", {"enabled": "true"}) == 1
    assert _val("agentflow_cron_jobs", {"enabled": "false"}) == 1


def test_no_duplicate_metric_families(db):
    """Every metric family name must appear exactly once. Two HELP/TYPE blocks for
    the same name is malformed exposition (scrapers can reject the page) — the
    trap when a collector yields one family per instance instead of one family
    with a series per instance (regression guard for the ws_* gauges)."""
    from prometheus_client.parser import text_string_to_metric_families
    from app.models import Script
    db.add(Script(name="s"))
    db.commit()  # ensure the DB section renders too, not just in-process gauges
    txt = metrics.render()[0].decode()
    names = [f.name for f in text_string_to_metric_families(txt) if f.name.startswith("agentflow")]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert dupes == [], f"duplicate metric families: {dupes}"


def test_render_survives_missing_tables():
    # With no `db` fixture the temp DB has no tables (dropped after the previous
    # test). The DB section must degrade silently — render still returns the
    # in-process gauges + build info, never an exception.
    body, _ = metrics.render()
    assert b"agentflow_build_info" in body


# ── the auth gate ─────────────────────────────────────────────────────────────

def test_metrics_gate_public(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_METRICS_PUBLIC", "true")
    from app.auth_deps import require_metrics_access
    assert require_metrics_access(_request(), db=None) == "metrics:public"


def test_metrics_gate_token(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_METRICS_PUBLIC", raising=False)
    monkeypatch.setenv("AGENTFLOW_METRICS_TOKEN", "s3cr3t")
    from app.auth_deps import require_metrics_access
    assert require_metrics_access(_request({"authorization": "Bearer s3cr3t"}), db=None) == "metrics:token"
    assert require_metrics_access(_request({"x-metrics-token": "s3cr3t"}), db=None) == "metrics:token"
    assert require_metrics_access(_request(query="token=s3cr3t"), db=None) == "metrics:token"


def test_metrics_gate_rejects_without_credentials(db, monkeypatch):
    monkeypatch.delenv("AGENTFLOW_METRICS_PUBLIC", raising=False)
    monkeypatch.delenv("AGENTFLOW_METRICS_TOKEN", raising=False)
    from fastapi import HTTPException
    from app.auth_deps import require_metrics_access
    with pytest.raises(HTTPException) as ei:
        require_metrics_access(_request(), db=db)
    assert ei.value.status_code == 401


def test_metrics_gate_accepts_api_key(db, monkeypatch):
    monkeypatch.delenv("AGENTFLOW_METRICS_PUBLIC", raising=False)
    monkeypatch.delenv("AGENTFLOW_METRICS_TOKEN", raising=False)
    from app.models import ApiKey
    from app.security import generate_api_key
    from app.auth_deps import require_metrics_access
    full, prefix, h = generate_api_key()
    db.add(ApiKey(name="scrape", prefix=prefix, key_hash=h, revoked=False))
    db.commit()
    subj = require_metrics_access(_request({"x-api-key": full}), db=db)
    assert subj.startswith("apikey:")
