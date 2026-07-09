"""Backend-side helpers for a conversation's durable LangGraph thread.

A /converse conversation is a LangGraph thread (thread_id == conversation id)
persisted by the user-script subprocess into ``workspace/threads.db`` via the
async ``AsyncSqliteSaver`` (see ``agentflow`` SDK). The backend never *runs* the
agent, but it needs two cheap, read-mostly operations on that same file to drive
rollback:

* ``read_head_checkpoint`` — after a turn finishes, record the thread's head
  checkpoint id onto the assistant message, so a later turn can anchor there.
* ``reset_thread`` — wipe a thread when a conversation has no surviving turn to
  anchor to (all deleted / pre-threading), so a fresh thread starts cleanly.

Both use the *sync* ``SqliteSaver`` over the same file (same on-disk schema as the
async saver) — no event loop needed in the request handler. Everything is
best-effort: a missing file / package / lock never raises into the request, it
just degrades (returns ``None`` / no-ops), mirroring the SDK's degrade rule.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from loguru import logger


def _threads_db_path(script_id: str) -> Optional[Path]:
    try:
        from services.venv_manager import get_script_dir  # lazy: avoid import cycle
        return get_script_dir(script_id) / "workspace" / "threads.db"
    except Exception:
        return None


def _open_saver(script_id: str, *, must_exist: bool):
    """Return a sync ``SqliteSaver`` over the script's threads.db, or ``None``.

    ``must_exist=True`` short-circuits to ``None`` when the file doesn't exist
    yet (a non-threaded conversation never created one) so we don't materialize
    an empty db just to read from it."""
    path = _threads_db_path(script_id)
    if path is None:
        return None
    if must_exist and not path.exists():
        return None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except Exception:
        return None
    try:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=5000")
        return SqliteSaver(conn), conn
    except Exception:
        return None


def read_head_checkpoint(script_id: str, thread_id: str) -> Optional[str]:
    """The head checkpoint id of the conversation's thread, or ``None``.

    Called right after a chat turn finishes to stamp the assistant message.
    ``None`` when the run wasn't a threaded agent (no threads.db) or on any
    error — the caller stores ``None`` and the anchor logic treats it as a fresh
    thread."""
    opened = _open_saver(script_id, must_exist=True)
    if opened is None:
        return None
    saver, conn = opened
    try:
        tup = saver.get_tuple({"configurable": {"thread_id": str(thread_id)}})
        if tup is None:
            return None
        return (tup.config or {}).get("configurable", {}).get("checkpoint_id")
    except Exception as e:
        logger.debug(f"read_head_checkpoint failed for {thread_id}: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def reset_thread(script_id: str, thread_id: str) -> None:
    """Delete a conversation's thread so the next turn starts fresh. No-op when
    there's no threads.db yet. Best-effort."""
    opened = _open_saver(script_id, must_exist=True)
    if opened is None:
        return
    saver, conn = opened
    try:
        saver.delete_thread(str(thread_id))
    except Exception as e:
        logger.debug(f"reset_thread failed for {thread_id}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
