"""Connection-pool sizing guards the concurrent-`/run` deadlock fix.

A burst of concurrent synchronous `POST /executions/run?wait=true` requests each
hold DB connections for the whole run (the auth dependency queries the DB, and the
engine holds its own session while draining the subprocess). With the SQLAlchemy
default sqlite pool (5 + 10 overflow = 15) the ~10th concurrent run exhausted it,
and because the run endpoints do *synchronous* SQLAlchemy work on the event loop, a
blocked pool checkout froze the loop → the subprocess-drain callbacks
(`loop.call_soon_threadsafe`) starved → runs never finished → their connections
never freed → **permanent deadlock** (reproduced live at exactly 10 concurrent
runs; all hung indefinitely). The pool must stay generously sized so a realistic
concurrent-request burst never blocks a checkout on the loop.
"""
from sqlalchemy import text

from app.database import engine, IS_SQLITE


def test_pool_capacity_is_generous():
    pool = engine.pool
    size = pool.size()
    overflow = getattr(pool, "_max_overflow", 0)
    capacity = size + overflow
    assert capacity >= 50, (
        f"connection pool too small ({size}+{overflow}={capacity}); a burst of "
        f"concurrent synchronous /run requests can exhaust it and a blocked "
        f"checkout on the event loop deadlocks the drain (see app/database.py)"
    )


def test_sqlite_busy_timeout_pragma_is_set():
    if not IS_SQLITE:
        import pytest
        pytest.skip("sqlite-only pragma")
    with engine.connect() as conn:
        val = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert val and val >= 1000, (
        f"busy_timeout should be set so a momentary writer collision backs off "
        f"instead of erroring a run (got {val})"
    )
