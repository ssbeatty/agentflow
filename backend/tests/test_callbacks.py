"""Completion webhooks (services/callbacks.py).

Locks the parts worth guarding: the payload shape external callers depend on,
the "no callback_url → no HTTP" gate, a successful POST, and the retry-then-give-up
path — all without touching the network (httpx.post is monkeypatched).
"""
from datetime import datetime

from app.models import Execution, Script
from services import callbacks


class _FakeResp:
    def __init__(self, status_code=200, raise_exc=None):
        self.status_code = status_code
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise


# ── payload ─────────────────────────────────────────────────────────────────────

def test_build_payload_shape():
    exc = Execution(
        id="abcd1234", script_id="s1", status="completed", trigger="api",
        output_data={"reply": "hi"}, error=None, retry_count=0, total_tokens=42,
        started_at=datetime(2026, 7, 6, 8, 0, 0),
        finished_at=datetime(2026, 7, 6, 8, 0, 5),
    )
    p = callbacks.build_payload(exc)
    assert p["id"] == "abcd1234"
    assert p["script_id"] == "s1"
    assert p["status"] == "completed"
    assert p["trigger"] == "api"
    assert p["output_data"] == {"reply": "hi"}
    assert p["total_tokens"] == 42
    assert p["started_at"] == "2026-07-06T08:00:00"
    assert p["finished_at"] == "2026-07-06T08:00:05"


# ── delivery gate + POST ─────────────────────────────────────────────────────────

def _seed(db, *, callback_url, status="completed"):
    db.add(Script(id="s1", name="S"))
    db.add(Execution(id="e1", script_id="s1", status=status,
                     output_data={"ok": True}, callback_url=callback_url))
    db.commit()


def test_deliver_skips_without_callback_url(db, monkeypatch):
    posts = []
    monkeypatch.setattr(callbacks.httpx, "post", lambda *a, **k: posts.append(a))
    _seed(db, callback_url=None)
    callbacks._deliver_sync("e1")
    assert posts == []


def test_deliver_posts_result(db, monkeypatch):
    seen = {}
    def fake_post(url, json=None, timeout=None):
        seen.update(url=url, json=json)
        return _FakeResp(200)
    monkeypatch.setattr(callbacks.httpx, "post", fake_post)
    _seed(db, callback_url="https://hooks.example.com/run-done")
    callbacks._deliver_sync("e1")
    assert seen["url"] == "https://hooks.example.com/run-done"
    assert seen["json"]["id"] == "e1"
    assert seen["json"]["status"] == "completed"
    assert seen["json"]["output_data"] == {"ok": True}


def test_deliver_retries_then_gives_up(db, monkeypatch):
    attempts = {"n": 0}
    def boom(*a, **k):
        attempts["n"] += 1
        raise RuntimeError("connection refused")
    monkeypatch.setattr(callbacks.httpx, "post", boom)
    monkeypatch.setattr(callbacks.time, "sleep", lambda *_: None)  # no real backoff
    _seed(db, callback_url="https://down.example.com/hook")
    # Must not raise — best-effort — but should have tried _MAX_ATTEMPTS times.
    callbacks._deliver_sync("e1")
    assert attempts["n"] == callbacks._MAX_ATTEMPTS
