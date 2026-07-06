"""Prometheus metrics for AgentFlow — exposed at ``GET /metrics``.

This is the platform's operational telemetry surface: a Prometheus scrape target
covering HTTP traffic, the execution engine (throughput / errors / latency / the
profiler's queue-wait→cold-import→script split), LLM token spend, the warm-worker
pool, failure-notification & completion-webhook delivery, venv builds, and a
scrape-time snapshot of DB-backed resource counts + live in-process state.

Design
------
Two kinds of series, on purpose:

  * **Process-lifetime counters / histograms** — incremented at hook sites in the
    engine / worker pool / notifications / callbacks / venv_manager. These are the
    rate/error/latency signals. A process restart resets them to 0 (standard
    Prometheus semantics; ``rate()`` handles it) — the DB still holds the history.

  * **Point-in-time gauges** — computed at scrape time by ``_LiveCollector`` from
    (a) cheap DB counts (retention-capped, dialect-agnostic ``count()``/``group_by``
    — works on sqlite AND postgres, no ``date_trunc``) and (b) live in-process
    state (the engine's semaphore/_procs, the WS managers, the warm-worker pool,
    the APScheduler). Never stored, always fresh.

Rules baked in here:
  * **Never label by ``script_id`` / ``execution_id``** — both are unbounded and
    would blow up cardinality. Only bounded labels (``status`` ×6, ``trigger`` ×5,
    ``kind``, ``outcome``, ``reason`` …). Per-script token/run breakdown already
    exists as the retention-capped DB aggregation at ``GET /api/executions/usage-stats``.
  * **Single-process assumption** — the in-process gauges (semaphore, _procs, WS
    managers, worker pool) are one uvicorn worker's view. That's AgentFlow's normal
    deployment (one long-lived event loop; the warm pool + WS replay buffers assume
    it too). Under ``uvicorn --workers N`` those gauges become per-worker partial
    views; use the DB-backed gauges (``executions_by_status`` etc.) for a
    cluster-wide picture and enable prometheus multiprocess mode for the counters.
  * **Never raises into a caller** — every record_* helper and the collector body
    swallow exceptions, so instrumentation can't fail a run or a scrape.
  * **Degrades if the dep is missing** — if ``prometheus_client`` isn't installed
    the module still imports, every helper is a no-op, and ``render()`` returns a
    short comment (mirrors the platform's sandbox/degrade philosophy).
"""
from __future__ import annotations

import os
import platform
from typing import Any

from loguru import logger

from app.config import APP_VERSION

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
    )
    from prometheus_client import disable_created_metrics
    from prometheus_client.core import GaugeMetricFamily
    # Drop the per-counter `_created` timestamp series — noise we don't use.
    try:
        disable_created_metrics()
    except Exception:
        pass
    _ENABLED = True
except Exception:  # pragma: no cover - dep missing → graceful no-op
    _ENABLED = False
    CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"


# The six/five bounded label domains, so a status/trigger that hasn't happened
# yet still reports a zero series (nicer dashboards).
_STATUSES = ("pending", "queued", "running", "completed", "failed", "cancelled")
_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
_TRIGGERS = ("manual", "api", "cron", "rerun", "eval")

_DURATION_BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1200)
_SPLIT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300)
_HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)


if _ENABLED:
    # ── HTTP ──────────────────────────────────────────────────────────────────
    HTTP_REQUESTS = Counter(
        "agentflow_http_requests_total",
        "HTTP requests handled, by method, matched-route template and status code.",
        ["method", "path", "status"],
    )
    HTTP_DURATION = Histogram(
        "agentflow_http_request_duration_seconds",
        "HTTP request handling latency, by method and matched-route template.",
        ["method", "path"],
        buckets=_HTTP_BUCKETS,
    )

    # ── Executions ────────────────────────────────────────────────────────────
    EXECUTIONS_STARTED = Counter(
        "agentflow_executions_started_total",
        "Runs that acquired a concurrency slot and began executing (past the queue).",
        ["trigger"],
    )
    EXECUTIONS_TOTAL = Counter(
        "agentflow_executions_total",
        "Runs that reached a terminal state, by final status and trigger.",
        ["status", "trigger"],
    )
    EXECUTION_DURATION = Histogram(
        "agentflow_execution_duration_seconds",
        "Wall-clock run duration (started_at → finished_at), by final status.",
        ["status"],
        buckets=_DURATION_BUCKETS,
    )
    EXECUTION_TIMEOUTS = Counter(
        "agentflow_execution_timeouts_total",
        "Runs killed by the per-execution wall-clock timeout (EXECUTION_TIMEOUT).",
        ["path"],  # oneshot | worker
    )
    EXECUTION_RETRIES = Counter(
        "agentflow_execution_retries_total",
        "Auto-retries scheduled after a failed run that still had retries left.",
    )
    EXECUTION_STOPS = Counter(
        "agentflow_execution_stops_total",
        "User-initiated stop requests, split by whether a live process was found.",
        ["found"],  # true | false
    )
    EXECUTIONS_PRUNED = Counter(
        "agentflow_executions_pruned_total",
        "Old terminal execution rows deleted by per-script retention (max_executions).",
    )

    # LLM spend (a live/rate view of the same usage the DB persists per row).
    LLM_TOKENS = Counter(
        "agentflow_llm_tokens_total",
        "LLM tokens consumed across all runs, by kind.",
        ["kind"],  # prompt | completion
    )
    LLM_CALLS = Counter(
        "agentflow_llm_calls_total",
        "LLM round-trips (model calls) across all runs.",
    )

    # Profiler split (queue-wait → prep → cold-import → script) — these numeric
    # splits previously existed only inside the _prof log string.
    EXEC_QUEUE_WAIT = Histogram(
        "agentflow_execution_queue_wait_seconds",
        "Time a run waited for a concurrency slot (semaphore contention).",
        buckets=_SPLIT_BUCKETS,
    )
    EXEC_PREP = Histogram(
        "agentflow_execution_prep_seconds",
        "Time from slot-acquired to subprocess spawned (write files + DB queries + skill copy).",
        buckets=_SPLIT_BUCKETS,
    )
    EXEC_COLD_IMPORT = Histogram(
        "agentflow_execution_cold_import_seconds",
        "Fresh python spawn + langchain/langgraph import before first output (the warm pool eliminates this on reuse).",
        buckets=_SPLIT_BUCKETS,
    )
    EXEC_SCRIPT = Histogram(
        "agentflow_execution_script_seconds",
        "The user's run() body time (first output → result) — the actual LLM/tool work.",
        buckets=_DURATION_BUCKETS,
    )

    # ── Warm worker pool ──────────────────────────────────────────────────────
    WORKER_ACQUIRES = Counter(
        "agentflow_worker_acquires_total",
        "WorkerManager.acquire() calls, by outcome.",
        ["result"],  # reused | spawned | failed
    )
    WORKER_BOOTS = Counter(
        "agentflow_worker_boots_total",
        "Warm-worker cold boots (spawn + import stack).",
        ["preheat"],  # true | false
    )
    WORKER_JOBS = Counter(
        "agentflow_worker_jobs_total",
        "Jobs completed by warm workers (monotonic across recycles).",
        ["ok"],  # true | false
    )
    WORKER_RETIREMENTS = Counter(
        "agentflow_worker_retirements_total",
        "Warm workers taken out of the pool, by reason.",
        ["reason"],  # invalidated | reaped | stale | shutdown
    )
    WORKER_BOOT_SECONDS = Histogram(
        "agentflow_worker_boot_seconds",
        "Warm-worker boot handshake time (spawn + imports, incl. preheat).",
        ["preheat"],
        buckets=_SPLIT_BUCKETS,
    )

    # ── Delivery (failure notifications + completion webhooks) ─────────────────
    NOTIFICATIONS = Counter(
        "agentflow_notifications_sent_total",
        "Failure-notification sends, by provider and outcome.",
        ["provider", "outcome"],  # provider ∈ pushplus|bark|email ; outcome ∈ ok|error
    )
    CALLBACKS = Counter(
        "agentflow_callbacks_sent_total",
        "Completion-webhook deliveries, by outcome.",
        ["outcome"],  # ok | error
    )

    # ── venv builds ───────────────────────────────────────────────────────────
    VENV_BUILDS = Counter(
        "agentflow_venv_builds_total",
        "Per-script venv creations (create + baseline install), by outcome.",
        ["outcome"],  # ok | error
    )
    VENV_INSTALLS = Counter(
        "agentflow_venv_installs_total",
        "Per-script requirements.txt installs, by outcome.",
        ["outcome"],  # ok | error
    )

    # ── Build info ────────────────────────────────────────────────────────────
    BUILD_INFO = Info("agentflow_build", "AgentFlow build information.")
    try:
        BUILD_INFO.info({"version": APP_VERSION, "python_version": platform.python_version()})
    except Exception:
        pass


# ── Recording helpers (hook sites call these; all are no-ops if dep missing) ──

def _b(v: bool) -> str:
    return "true" if v else "false"


def observe_execution(exc_row: Any) -> None:
    """Record a terminal execution: throughput counter + duration + token spend.

    Call from EACH terminal path exactly once (they are mutually exclusive per
    run by control flow): _finalize_run, both timeout handlers, _mark_failed,
    _mark_cancelled. Reads status/trigger/timestamps/tokens straight off the row,
    so a timed-out/early-failed run (no usage) records 0 tokens uniformly."""
    if not _ENABLED:
        return
    try:
        status = getattr(exc_row, "status", None) or "unknown"
        trigger = getattr(exc_row, "trigger", None) or "manual"
        EXECUTIONS_TOTAL.labels(status=status, trigger=trigger).inc()
        started, finished = getattr(exc_row, "started_at", None), getattr(exc_row, "finished_at", None)
        if started and finished:
            dur = (finished - started).total_seconds()
            if dur >= 0:
                EXECUTION_DURATION.labels(status=status).observe(dur)
        pt = int(getattr(exc_row, "prompt_tokens", 0) or 0)
        ct = int(getattr(exc_row, "completion_tokens", 0) or 0)
        calls = int(getattr(exc_row, "llm_calls", 0) or 0)
        if pt:
            LLM_TOKENS.labels(kind="prompt").inc(pt)
        if ct:
            LLM_TOKENS.labels(kind="completion").inc(ct)
        if calls:
            LLM_CALLS.inc(calls)
    except Exception:  # never let instrumentation break finalization
        pass


def observe_execution_started(trigger: str | None) -> None:
    if not _ENABLED:
        return
    try:
        EXECUTIONS_STARTED.labels(trigger=trigger or "manual").inc()
    except Exception:
        pass


def observe_profile(*, queue_wait=None, prep=None, cold_import=None, script=None) -> None:
    """Feed the profiler's per-run timing split into histograms (one-shot path)."""
    if not _ENABLED:
        return
    try:
        if queue_wait is not None and queue_wait >= 0:
            EXEC_QUEUE_WAIT.observe(queue_wait)
        if prep is not None and prep >= 0:
            EXEC_PREP.observe(prep)
        if cold_import is not None and cold_import >= 0:
            EXEC_COLD_IMPORT.observe(cold_import)
        if script is not None and script >= 0:
            EXEC_SCRIPT.observe(script)
    except Exception:
        pass


def inc_timeout(path: str) -> None:
    if _ENABLED:
        try:
            EXECUTION_TIMEOUTS.labels(path=path).inc()
        except Exception:
            pass


def inc_retry() -> None:
    if _ENABLED:
        try:
            EXECUTION_RETRIES.inc()
        except Exception:
            pass


def inc_stop(found: bool) -> None:
    if _ENABLED:
        try:
            EXECUTION_STOPS.labels(found=_b(found)).inc()
        except Exception:
            pass


def inc_pruned(n: int) -> None:
    if _ENABLED and n:
        try:
            EXECUTIONS_PRUNED.inc(n)
        except Exception:
            pass


def record_notification(provider: str, ok: bool) -> None:
    if _ENABLED:
        try:
            NOTIFICATIONS.labels(provider=provider or "unknown", outcome="ok" if ok else "error").inc()
        except Exception:
            pass


def record_callback(ok: bool) -> None:
    if _ENABLED:
        try:
            CALLBACKS.labels(outcome="ok" if ok else "error").inc()
        except Exception:
            pass


def record_venv_build(ok: bool) -> None:
    if _ENABLED:
        try:
            VENV_BUILDS.labels(outcome="ok" if ok else "error").inc()
        except Exception:
            pass


def record_venv_install(ok: bool) -> None:
    if _ENABLED:
        try:
            VENV_INSTALLS.labels(outcome="ok" if ok else "error").inc()
        except Exception:
            pass


def record_worker_acquire(result: str) -> None:
    if _ENABLED:
        try:
            WORKER_ACQUIRES.labels(result=result).inc()
        except Exception:
            pass


def record_worker_boot(preheat: bool, boot_seconds: float | None = None) -> None:
    if _ENABLED:
        try:
            WORKER_BOOTS.labels(preheat=_b(preheat)).inc()
            if boot_seconds is not None and boot_seconds >= 0:
                WORKER_BOOT_SECONDS.labels(preheat=_b(preheat)).observe(boot_seconds)
        except Exception:
            pass


def record_worker_job(ok: bool) -> None:
    if _ENABLED:
        try:
            WORKER_JOBS.labels(ok=_b(ok)).inc()
        except Exception:
            pass


def record_worker_retirement(reason: str, n: int = 1) -> None:
    if _ENABLED and n:
        try:
            WORKER_RETIREMENTS.labels(reason=reason).inc(n)
        except Exception:
            pass


def record_http(method: str, path: str, status: int, duration_s: float) -> None:
    if not _ENABLED:
        return
    try:
        HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
        HTTP_DURATION.labels(method=method, path=path).observe(duration_s)
    except Exception:
        pass


# ── Scrape-time live collector (DB counts + in-process state) ─────────────────

class _LiveCollector:
    """Yields point-in-time gauges computed fresh on each scrape. Every section
    is independently guarded so one failing source never blanks the whole page."""

    def collect(self):
        yield from self._engine_gauges()
        yield from self._worker_gauges()
        yield from self._scheduler_gauges()
        yield from self._config_gauges()
        yield from self._db_gauges()

    # -- engine in-process state --
    def _engine_gauges(self):
        try:
            from services import execution_engine as ee
        except Exception:
            return
        try:
            sem = getattr(ee, "_semaphore", None)
            slots_used = ee.MAX_CONCURRENT - (sem._value if sem is not None else ee.MAX_CONCURRENT)
            yield self._g("agentflow_concurrency_max", "Configured max concurrent runs.", ee.MAX_CONCURRENT)
            yield self._g("agentflow_concurrency_slots_in_use", "Concurrency slots currently held.", max(0, slots_used))
            yield self._g("agentflow_executions_in_flight_processes",
                          "Live user-script subprocesses/workers being drained now.", len(ee._procs))
            yield self._g("agentflow_engine_tasks_active",
                          "In-flight start_execution tasks (incl. queued, waiting for a slot).", len(ee._tasks))
            yield self._g("agentflow_execution_timeout_seconds",
                          "Configured per-execution wall-clock timeout.", ee.EXECUTION_TIMEOUT)
        except Exception:
            logger.opt(exception=True).debug("metrics: engine gauges failed")
        # WebSocket managers — ONE family per metric name, a series per stream
        # (emitting the same name twice would be malformed exposition).
        try:
            conns_fam = GaugeMetricFamily(
                "agentflow_ws_active_connections", "Open run-log WebSocket clients.", labels=["stream"])
            buf_fam = GaugeMetricFamily(
                "agentflow_ws_buffered_executions", "Executions retaining a WS replay buffer.", labels=["stream"])
            for inst_name, label in (("ws_manager", "run"), ("install_manager", "install")):
                mgr = getattr(ee, inst_name, None)
                if mgr is None:
                    continue
                conns = sum(len(s) for s in getattr(mgr, "_conns", {}).values())
                conns_fam.add_metric([label], float(conns))
                buf_fam.add_metric([label], float(len(getattr(mgr, "_buffers", {}))))
            yield conns_fam
            yield buf_fam
        except Exception:
            logger.opt(exception=True).debug("metrics: ws gauges failed")

    # -- warm worker pool --
    def _worker_gauges(self):
        try:
            from services import worker_pool as wp
        except Exception:
            return
        try:
            yield self._g("agentflow_warm_workers_enabled",
                          "1 if the warm-worker pool is globally enabled.",
                          1 if wp.WARM_WORKERS_ENABLED else 0)
            workers = list(getattr(wp.manager, "_workers", {}).values())
            alive = busy = 0
            for w in workers:
                try:
                    if w.alive():
                        alive += 1
                    if w.lock.locked():
                        busy += 1
                except Exception:
                    pass
            yield self._g("agentflow_warm_workers", "Warm workers registered in the pool.", len(workers))
            yield self._g("agentflow_warm_workers_alive", "Warm workers whose subprocess is booted and running.", alive)
            yield self._g("agentflow_warm_workers_busy", "Warm workers executing a job right now.", busy)
        except Exception:
            logger.opt(exception=True).debug("metrics: worker gauges failed")

    # -- scheduler --
    def _scheduler_gauges(self):
        try:
            from services.scheduler import scheduler_service
            sched = scheduler_service._scheduler
            running = 1 if getattr(sched, "running", False) else 0
            jobs = len(sched.get_jobs()) if running else 0
            yield self._g("agentflow_scheduler_running", "1 if the APScheduler is running.", running)
            yield self._g("agentflow_scheduler_registered_jobs",
                          "Cron jobs registered in the live scheduler.", jobs)
        except Exception:
            logger.opt(exception=True).debug("metrics: scheduler gauges failed")

    # -- static config / feature flags --
    def _config_gauges(self):
        try:
            from services.venv_manager import sandbox_enabled
            yield self._g("agentflow_sandbox_enabled",
                          "1 if the bwrap filesystem jail wraps user-script runs.",
                          1 if sandbox_enabled() else 0)
        except Exception:
            logger.opt(exception=True).debug("metrics: config gauges failed")

    # -- DB-backed resource counts (cheap, dialect-agnostic) --
    def _db_gauges(self):
        try:
            from sqlalchemy import func
            from app.database import SessionLocal
            from app import models as m
        except Exception:
            return
        db = None
        try:
            db = SessionLocal()

            # executions by status (zero-filled) + by trigger
            by_status = dict(db.query(m.Execution.status, func.count(m.Execution.id))
                             .group_by(m.Execution.status).all())
            g = GaugeMetricFamily("agentflow_executions_by_status",
                                  "Execution rows currently stored, by status.", labels=["status"])
            for st in _STATUSES:
                g.add_metric([st], float(by_status.get(st, 0)))
            for st, n in by_status.items():  # any unexpected status value
                if st not in _STATUSES:
                    g.add_metric([st or "unknown"], float(n))
            yield g

            by_trigger = dict(db.query(m.Execution.trigger, func.count(m.Execution.id))
                              .group_by(m.Execution.trigger).all())
            g = GaugeMetricFamily("agentflow_executions_by_trigger",
                                  "Execution rows currently stored, by trigger.", labels=["trigger"])
            for tg in _TRIGGERS:
                g.add_metric([tg], float(by_trigger.get(tg, 0)))
            for tg, n in by_trigger.items():
                if tg not in _TRIGGERS:
                    g.add_metric([tg or "manual"], float(n))
            yield g

            # simple resource totals
            yield self._count(db, m.Script, "agentflow_scripts", "User scripts.")
            yield self._count(db, m.Conversation, "agentflow_conversations", "Chat conversations.")
            yield self._count(db, m.Secret, "agentflow_secrets", "Stored external secrets.")
            yield self._count(db, m.EvalCase, "agentflow_eval_cases", "Eval dataset cases.")
            yield self._count(db, m.EvalRun, "agentflow_eval_runs", "Eval runs recorded.")
            yield self._count(db, m.UploadedFile, "agentflow_uploaded_files", "Uploaded files.")

            # enabled/disabled splits
            yield self._enabled_split(db, m.CronJob, "agentflow_cron_jobs", "Cron jobs, by enabled state.")
            yield self._enabled_split(db, m.Channel, "agentflow_llm_channels", "LLM channels, by enabled state.")
            yield self._enabled_split(db, m.MCPServerConfig, "agentflow_mcp_servers", "MCP servers, by enabled state.")
            yield self._enabled_split(db, m.NotificationChannel, "agentflow_notification_channels",
                                      "Notification channels, by enabled state.")

            # api keys active/revoked
            revoked = dict(db.query(m.ApiKey.revoked, func.count(m.ApiKey.id)).group_by(m.ApiKey.revoked).all())
            g = GaugeMetricFamily("agentflow_api_keys", "Issued API keys, by state.", labels=["state"])
            g.add_metric(["active"], float(revoked.get(False, 0)))
            g.add_metric(["revoked"], float(revoked.get(True, 0)))
            yield g
        except Exception:
            logger.opt(exception=True).debug("metrics: db gauges failed")
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    # -- helpers --
    @staticmethod
    def _g(name, doc, value, labels: dict | None = None):
        if labels:
            keys = list(labels.keys())
            g = GaugeMetricFamily(name, doc, labels=keys)
            g.add_metric([labels[k] for k in keys], float(value))
        else:
            g = GaugeMetricFamily(name, doc, value=float(value))
        return g

    @staticmethod
    def _count(db, model, name, doc):
        from sqlalchemy import func
        n = db.query(func.count(model.id)).scalar() or 0
        return GaugeMetricFamily(name, doc, value=float(n))

    @staticmethod
    def _enabled_split(db, model, name, doc):
        from sqlalchemy import func
        rows = dict(db.query(model.enabled, func.count(model.id)).group_by(model.enabled).all())
        g = GaugeMetricFamily(name, doc, labels=["enabled"])
        g.add_metric(["true"], float(rows.get(True, 0)))
        g.add_metric(["false"], float(rows.get(False, 0)))
        return g


_collector_registered = False


def _ensure_collector() -> None:
    global _collector_registered
    if _ENABLED and not _collector_registered:
        try:
            REGISTRY.register(_LiveCollector())
            _collector_registered = True
        except Exception:
            logger.opt(exception=True).debug("metrics: collector registration failed")


if _ENABLED:
    _ensure_collector()


def render() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics response."""
    if not _ENABLED:
        return (
            b"# prometheus_client is not installed; metrics are disabled.\n",
            CONTENT_TYPE_LATEST,
        )
    try:
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    except Exception:
        logger.opt(exception=True).warning("metrics: render failed")
        return b"# metrics render failed\n", CONTENT_TYPE_LATEST


def enabled() -> bool:
    return _ENABLED
