"""Run-failure notifications (PushPlus / Bark / email).

When a run reaches a terminal `failed` state, the execution engine calls
`schedule_failure_notification(execution_id)`. That fires a background task which
opens its own DB session, loads every *enabled* `NotificationChannel`, and pings
each one. It is **best-effort and never raises into the engine**: a channel that
fails is logged and skipped, so a broken webhook can't wedge run finalization.

Eval sub-runs (`Execution.trigger == "eval"`) are skipped so a graded test case
can't spam the alert channels.

Senders are plain sync functions (httpx / smtplib) run off the event loop via
`asyncio.to_thread`. Adding a provider = write a `_send_*` and register it in
`_SENDERS` — keep it generic (no per-account logic beyond the provider's API).
"""
from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

import httpx
from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models import Execution, NotificationChannel, Script
from services import metrics

# Triggers whose failures never notify (see module docstring).
_SKIP_TRIGGERS = {"eval"}
# Bounded de-dup so a run notifies at most once even if two terminal paths fire.
_notified: set[str] = set()


# ── Providers ─────────────────────────────────────────────────────────────────

def _send_pushplus(config: dict, title: str, body: str) -> None:
    token = (config.get("token") or "").strip()
    if not token:
        raise ValueError("pushplus: missing token")
    payload = {"token": token, "title": title, "content": body, "template": "txt"}
    topic = (config.get("topic") or "").strip()
    if topic:
        payload["topic"] = topic
    r = httpx.post("https://www.pushplus.plus/send", json=payload, timeout=15)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        data = {}
    code = data.get("code")
    if code is not None and int(code) != 200:
        raise RuntimeError(f"pushplus rejected: {data.get('msg') or data}")


def _send_bark(config: dict, title: str, body: str) -> None:
    server = (config.get("server_url") or "https://api.day.app").strip().rstrip("/")
    key = (config.get("device_key") or "").strip()
    if not key:
        raise ValueError("bark: missing device_key")
    payload = {"title": title, "body": body}
    if config.get("sound"):
        payload["sound"] = str(config["sound"])
    if config.get("group"):
        payload["group"] = str(config["group"])
    r = httpx.post(f"{server}/{key}", json=payload, timeout=15)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        data = {}
    if data and int(data.get("code", 200)) != 200:
        raise RuntimeError(f"bark rejected: {data.get('message') or data}")


def _send_email(config: dict, title: str, body: str) -> None:
    host = (config.get("smtp_host") or "").strip()
    if not host:
        raise ValueError("email: missing smtp_host")
    port = int(config.get("smtp_port") or 587)
    username = (config.get("username") or "").strip()
    password = config.get("password") or ""
    from_addr = (config.get("from_addr") or username).strip()
    to_raw = config.get("to_addrs") or username
    if isinstance(to_raw, str):
        to_addrs = [a.strip() for a in to_raw.replace(";", ",").split(",") if a.strip()]
    else:
        to_addrs = [str(a).strip() for a in (to_raw or []) if str(a).strip()]
    if not to_addrs:
        raise ValueError("email: no recipients (to_addrs)")
    use_tls = config.get("use_tls")
    use_tls = True if use_tls is None else bool(use_tls)  # default STARTTLS

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = from_addr or username or "agentflow@localhost"
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(body)

    if port == 465:  # implicit TLS
        with smtplib.SMTP_SSL(host, port, timeout=20) as s:
            if username:
                s.login(username, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            if use_tls:
                s.starttls(context=ssl.create_default_context())
            if username:
                s.login(username, password)
            s.send_message(msg)


_SENDERS = {"pushplus": _send_pushplus, "bark": _send_bark, "email": _send_email}


def send_to_channel(ch_type: str, config: dict, title: str, body: str) -> None:
    """Dispatch to a provider. Raises on any failure (so callers can report it)."""
    fn = _SENDERS.get(ch_type)
    if fn is None:
        raise ValueError(f"unknown notification channel type: {ch_type!r}")
    fn(config or {}, title, body)


def send_test(channel: NotificationChannel) -> tuple[bool, str]:
    """Send a canned test message. Returns (ok, error) — never raises."""
    try:
        send_to_channel(
            channel.type, channel.config or {},
            "AgentFlow test notification",
            "This is a test alert from AgentFlow. If you can read this, the "
            "channel is configured correctly.",
        )
        return True, ""
    except Exception as e:  # noqa: BLE001 — report any provider error verbatim
        return False, str(e)


# ── Message + dispatch ────────────────────────────────────────────────────────

def build_failure_message(execution: Execution, script) -> tuple[str, str]:
    name = getattr(script, "name", None) or "(unknown script)"
    title = f"AgentFlow run failed: {name}"
    err = (execution.error or "").strip()
    if len(err) > 800:
        err = err[:800] + " …"
    when = execution.finished_at or execution.started_at or execution.created_at
    lines = [
        f"Script:  {name}",
        f"Status:  failed",
        f"Trigger: {execution.trigger or 'manual'}",
        f"Time:    {when.isoformat(sep=' ', timespec='seconds') if when else '-'}",
        f"Run:     {execution.id[:8]}",
        "",
        "Error:",
        err or "(no error message)",
    ]
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        lines += ["", f"{base}/script?id={execution.script_id}"]
    return title, "\n".join(lines)


def schedule_failure_notification(execution_id: str) -> None:
    """Fire-and-forget: notify enabled channels a run failed. Safe to call from
    the engine's terminal paths; de-duped so a run alerts at most once."""
    if execution_id in _notified:
        return
    _notified.add(execution_id)
    if len(_notified) > 5000:  # keep the de-dup set from growing unbounded
        _notified.clear()
        _notified.add(execution_id)
    try:
        asyncio.get_running_loop().create_task(_notify(execution_id))
    except RuntimeError:
        # No running loop (e.g. a sync context) — send inline in a thread-free
        # best-effort way. Rare; the engine always has a loop.
        try:
            _notify_sync(execution_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[notify] {} inline failed: {}", execution_id[:8], e)


async def _notify(execution_id: str) -> None:
    try:
        await asyncio.to_thread(_notify_sync, execution_id)
    except Exception as e:  # noqa: BLE001 — must never surface into the engine
        logger.warning("[notify] {} failed: {}", execution_id[:8], e)


def _notify_sync(execution_id: str) -> None:
    db = SessionLocal()
    try:
        exc = db.query(Execution).filter_by(id=execution_id).first()
        if not exc or exc.status != "failed":
            return
        if (exc.trigger or "manual") in _SKIP_TRIGGERS:
            return
        channels = db.query(NotificationChannel).filter_by(enabled=True).all()
        if not channels:
            return
        script = db.query(Script).filter_by(id=exc.script_id).first()
        title, body = build_failure_message(exc, script)
        for ch in channels:
            try:
                send_to_channel(ch.type, ch.config or {}, title, body)
                metrics.record_notification(ch.type, ok=True)
                logger.info("[notify] alert sent via {} ({})", ch.type, ch.name)
            except Exception as e:  # noqa: BLE001 — one bad channel can't block others
                metrics.record_notification(ch.type, ok=False)
                logger.warning("[notify] channel {} ({}) failed: {}", ch.name, ch.type, e)
    finally:
        db.close()
