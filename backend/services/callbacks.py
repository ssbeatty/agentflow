"""Completion webhooks (async run result delivery).

When a run finishes and `Execution.callback_url` is set, the engine calls
`schedule_completion_callback(execution_id)` from its terminal paths. That fires
a background task which opens its own DB session, loads the run, and POSTs the
final result to the URL — so an external caller can submit async
(`POST /executions/run?wait=false`) and be *pushed* the result instead of
polling.

Design mirrors services/notifications.py exactly (same reasons):
  - **fire-and-forget + best-effort**: the POST runs off the event loop via
    `asyncio.to_thread` (sync httpx), and **never raises into the engine** — a
    dead/slow webhook can't wedge run finalization or fail the run.
  - **de-duped** via a bounded `_delivered` set so a run's webhook fires at most
    once even if two terminal paths call in.
  - a couple of quick retries on transient failures, then give up (logged).

Unlike failure notifications, this fires on EVERY terminal state
(completed/failed/cancelled) — the caller asked to be told when the run is done,
whatever the outcome. It's gated purely on `callback_url` being present.
"""
from __future__ import annotations

import asyncio
import time

import httpx
from loguru import logger

from app.database import SessionLocal
from app.models import Execution
from services import metrics

# Bounded de-dup so a run's webhook fires at most once even if two terminal
# paths (finalize + mark_failed) both schedule it.
_delivered: set[str] = set()

_TIMEOUT = 15.0
_MAX_ATTEMPTS = 3


def _iso(dt) -> "str | None":
    return dt.isoformat() if dt else None


def build_payload(exc: Execution) -> dict:
    """The JSON pushed to the webhook — same fields as the sync /run response,
    plus script_id/trigger so a single endpoint can route many scripts."""
    return {
        "id": exc.id,
        "script_id": exc.script_id,
        "status": exc.status,
        "trigger": exc.trigger,
        "output_data": exc.output_data,
        "error": exc.error,
        "started_at": _iso(exc.started_at),
        "finished_at": _iso(exc.finished_at),
        "retry_count": exc.retry_count,
        "total_tokens": exc.total_tokens or 0,
    }


def schedule_completion_callback(execution_id: str) -> None:
    """Fire-and-forget: POST the run's result to its callback_url (if any).
    Safe to call from the engine's terminal paths; de-duped per run."""
    if execution_id in _delivered:
        return
    _delivered.add(execution_id)
    if len(_delivered) > 5000:  # keep the de-dup set from growing unbounded
        _delivered.clear()
        _delivered.add(execution_id)
    try:
        asyncio.get_running_loop().create_task(_deliver(execution_id))
    except RuntimeError:
        # No running loop (rare — the engine always has one). Best-effort inline.
        try:
            _deliver_sync(execution_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[callback] {} inline failed: {}", execution_id[:8], e)


async def _deliver(execution_id: str) -> None:
    try:
        await asyncio.to_thread(_deliver_sync, execution_id)
    except Exception as e:  # noqa: BLE001 — must never surface into the engine
        logger.warning("[callback] {} failed: {}", execution_id[:8], e)


def _deliver_sync(execution_id: str) -> None:
    db = SessionLocal()
    try:
        exc = db.query(Execution).filter_by(id=execution_id).first()
        if not exc:
            return
        url = (exc.callback_url or "").strip()
        if not url:
            return
        payload = build_payload(exc)
    finally:
        db.close()

    last_err: "Exception | None" = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            r = httpx.post(url, json=payload, timeout=_TIMEOUT)
            r.raise_for_status()
            metrics.record_callback(ok=True)
            logger.info("[callback] {} delivered to {} (status={})",
                        execution_id[:8], url, exc.status)
            return
        except Exception as e:  # noqa: BLE001 — retry transient failures, then give up
            last_err = e
            if attempt < _MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 5))  # 2s, 4s (capped) — off the event loop
    metrics.record_callback(ok=False)
    logger.warning("[callback] {} gave up after {} attempts to {}: {}",
                   execution_id[:8], _MAX_ATTEMPTS, url, last_err)
