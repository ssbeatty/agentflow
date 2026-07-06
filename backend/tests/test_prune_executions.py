"""Per-script execution retention (services/execution_engine.py::prune_executions).

Uses the `db` fixture (temp sqlite). Exercises the two invariants documented in
CLAUDE.md: keep the newest `keep` terminal runs, and NEVER delete in-flight ones.
"""
from datetime import datetime, timedelta

from app.models import Execution, Script
from services.execution_engine import prune_executions


def _add_exec(db, script_id, status, age_seconds):
    """Insert an execution with an explicit created_at so ordering is deterministic."""
    e = Execution(
        script_id=script_id,
        status=status,
        created_at=datetime.utcnow() - timedelta(seconds=age_seconds),
    )
    db.add(e)
    db.flush()
    return e


def test_prune_keeps_newest_terminal(db):
    s = Script(name="s")
    db.add(s)
    db.flush()
    # 5 completed runs, decreasing age → the newest 2 should survive keep=2.
    for age in (500, 400, 300, 200, 100):
        _add_exec(db, s.id, "completed", age)
    db.commit()

    removed = prune_executions(db, s.id, keep=2)

    assert removed == 3
    assert db.query(Execution).filter_by(script_id=s.id).count() == 2


def test_prune_never_deletes_inflight(db):
    s = Script(name="s")
    db.add(s)
    db.flush()
    for age in (300, 200, 100):
        _add_exec(db, s.id, "completed", age)
    _add_exec(db, s.id, "running", age_seconds=9999)  # oldest, but in-flight
    db.commit()

    removed = prune_executions(db, s.id, keep=1)

    # 3 terminal, keep 1 → 2 removed; the running one is untouched.
    assert removed == 2
    statuses = [e.status for e in db.query(Execution).filter_by(script_id=s.id)]
    assert "running" in statuses
    assert statuses.count("completed") == 1


def test_prune_unlimited_is_noop(db):
    s = Script(name="s")
    db.add(s)
    db.flush()
    for age in (300, 200, 100):
        _add_exec(db, s.id, "completed", age)
    db.commit()

    assert prune_executions(db, s.id, keep=0) == 0
    assert prune_executions(db, s.id, keep=None) == 0
    assert db.query(Execution).filter_by(script_id=s.id).count() == 3
