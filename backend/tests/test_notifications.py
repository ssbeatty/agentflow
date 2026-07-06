"""Run-failure notifications (services/notifications.py + schema masking).

Covers the parts worth locking down: secrets never leak in the API shape, the
message is built correctly, provider dispatch works, and the failure notifier
respects the enabled flag + skips eval sub-runs — all without touching the
network (the provider is monkeypatched).
"""
from datetime import datetime

import pytest

from app.models import Execution, NotificationChannel, Script
from app.schemas import NotificationChannelOut
from services import notifications


# ── schema masking ─────────────────────────────────────────────────────────────

def test_out_schema_strips_secrets():
    ch = NotificationChannel(
        id="c1", name="my-email", type="email", enabled=True,
        created_at=datetime(2026, 1, 1),
        config={"smtp_host": "smtp.x.com", "smtp_port": 587,
                "username": "me@x.com", "password": "hunter2",
                "to_addrs": "me@x.com"},
    )
    out = NotificationChannelOut.model_validate(ch).model_dump()

    assert out["has_secret"] is True
    # Non-secret fields survive so the UI can edit them...
    assert out["config_safe"]["smtp_host"] == "smtp.x.com"
    assert out["config_safe"]["username"] == "me@x.com"
    # ...but the password is gone, and no raw `config` field is serialized.
    assert "password" not in out["config_safe"]
    assert "config" not in out


def test_out_schema_has_secret_false_when_unset():
    ch = NotificationChannel(
        id="c2", name="bark", type="bark", enabled=True,
        created_at=datetime(2026, 1, 1),
        config={"server_url": "https://api.day.app"},  # no device_key yet
    )
    out = NotificationChannelOut.model_validate(ch).model_dump()
    assert out["has_secret"] is False
    assert out["config_safe"]["server_url"] == "https://api.day.app"


# ── message ─────────────────────────────────────────────────────────────────────

def test_build_failure_message():
    exc = Execution(
        id="abcd1234efgh", script_id="s1", status="failed",
        error="ValueError: boom", trigger="cron",
        finished_at=datetime(2026, 7, 6, 8, 0, 0),
    )
    script = Script(id="s1", name="Nightly digest")
    title, body = notifications.build_failure_message(exc, script)

    assert "Nightly digest" in title
    assert "cron" in body
    assert "ValueError: boom" in body
    assert "abcd1234" in body  # short run id


# ── provider dispatch ───────────────────────────────────────────────────────────

def test_send_to_channel_unknown_type_raises():
    with pytest.raises(ValueError):
        notifications.send_to_channel("carrier-pigeon", {}, "t", "b")


def test_send_to_channel_dispatches(monkeypatch):
    seen = {}
    monkeypatch.setitem(
        notifications._SENDERS, "bark",
        lambda config, title, body: seen.update(config=config, title=title, body=body),
    )
    notifications.send_to_channel("bark", {"device_key": "k"}, "hi", "there")
    assert seen == {"config": {"device_key": "k"}, "title": "hi", "body": "there"}


def test_send_test_reports_error_without_network():
    # A bark channel with no device_key fails fast (no HTTP call).
    ch = NotificationChannel(id="c", name="b", type="bark", enabled=True, config={})
    ok, error = notifications.send_test(ch)
    assert ok is False
    assert "device_key" in error


# ── failure notifier (DB-backed, provider stubbed) ──────────────────────────────

def _seed(db, *, status="failed", trigger="manual", enabled=True):
    db.add(Script(id="s1", name="S"))
    db.add(Execution(id="e1", script_id="s1", status=status, error="boom", trigger=trigger))
    db.add(NotificationChannel(id="c1", name="ch", type="bark", enabled=enabled,
                               config={"device_key": "k"}))
    db.commit()


def test_notify_sends_for_normal_failure(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "send_to_channel",
                        lambda *a, **k: calls.append(a))
    _seed(db, trigger="manual")
    notifications._notify_sync("e1")
    assert len(calls) == 1


def test_notify_skips_eval_runs(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "send_to_channel",
                        lambda *a, **k: calls.append(a))
    _seed(db, trigger="eval")
    notifications._notify_sync("e1")
    assert calls == []


def test_notify_skips_disabled_channels(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "send_to_channel",
                        lambda *a, **k: calls.append(a))
    _seed(db, trigger="manual", enabled=False)
    notifications._notify_sync("e1")
    assert calls == []


def test_notify_ignores_non_failed(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "send_to_channel",
                        lambda *a, **k: calls.append(a))
    _seed(db, status="completed", trigger="manual")
    notifications._notify_sync("e1")
    assert calls == []


def test_end_to_end_failed_run_pings_channel(db, monkeypatch):
    """Full pipeline: a real failed run through the engine → the fire-and-forget
    task → the thread → _notify_sync → send_to_channel. Deterministic: we drain
    the pending notify task instead of sleeping."""
    import asyncio
    from app.models import Script, ScriptFile, Execution
    from services import execution_engine

    monkeypatch.setattr(execution_engine, "_semaphore", None)
    monkeypatch.setattr(execution_engine, "EXECUTION_TIMEOUT", 90.0)
    sent = []
    monkeypatch.setattr(notifications, "send_to_channel",
                        lambda ch_type, config, title, body: sent.append((ch_type, title)))

    db.add(NotificationChannel(id="c1", name="ch", type="bark", enabled=True,
                               config={"device_key": "k"}))
    script = Script(name="boom", entry_function="run")
    db.add(script)
    db.flush()
    db.add(ScriptFile(script_id=script.id, filename="main.py", is_main=True,
                      content="def run(input):\n    raise RuntimeError('kaboom')\n"))
    exc = Execution(script_id=script.id, status="pending", trigger="manual")
    db.add(exc)
    db.commit()
    eid = exc.id

    async def drive():
        await execution_engine.start_execution(eid)
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(drive())

    db.expire_all()
    assert db.query(Execution).filter_by(id=eid).first().status == "failed"
    assert len(sent) == 1 and sent[0][0] == "bark"
