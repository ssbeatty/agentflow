"""Runs list filtering + cross-run log search (routers/executions.list_executions).

The endpoint takes `db` via Depends, so we call the function directly with the
test session — no HTTP layer needed. Seeds a few executions (+ one log line) and
asserts status / trigger filters and the free-text `q` search that also matches
inside log messages.
"""
from app.models import Execution, ExecutionLog, Script
from app.routers.executions import list_executions


def _seed(db):
    db.add(Script(id="s1", name="S"))
    db.add(Execution(id="run-ok", script_id="s1", status="completed", trigger="manual"))
    db.add(Execution(id="run-bad", script_id="s1", status="failed", trigger="cron",
                     error="ValueError: kaboom happened"))
    db.add(Execution(id="run-cancel", script_id="s1", status="cancelled", trigger="api"))
    # A log line whose message contains a term not present in any execution row,
    # so a match proves the cross-run log search works.
    db.add(ExecutionLog(execution_id="run-ok", level="info", message="fetched widget-42 from api"))
    db.commit()


def _ids(rows):
    return {r.id for r in rows}


def test_filter_by_status(db):
    _seed(db)
    assert _ids(list_executions(status="failed", db=db)) == {"run-bad"}
    assert _ids(list_executions(status="failed,cancelled", db=db)) == {"run-bad", "run-cancel"}


def test_filter_by_trigger(db):
    _seed(db)
    assert _ids(list_executions(trigger="cron", db=db)) == {"run-bad"}
    assert _ids(list_executions(trigger="manual,api", db=db)) == {"run-ok", "run-cancel"}


def test_search_matches_error(db):
    _seed(db)
    assert _ids(list_executions(q="kaboom", db=db)) == {"run-bad"}
    # Case-insensitive.
    assert _ids(list_executions(q="KABOOM", db=db)) == {"run-bad"}


def test_search_matches_run_id(db):
    _seed(db)
    assert _ids(list_executions(q="run-cancel", db=db)) == {"run-cancel"}


def test_search_matches_log_message_cross_run(db):
    # "widget-42" appears only in a LOG line of run-ok, nowhere in the exec rows.
    _seed(db)
    assert _ids(list_executions(q="widget-42", db=db)) == {"run-ok"}


def test_no_filters_returns_all(db):
    _seed(db)
    assert _ids(list_executions(db=db)) == {"run-ok", "run-bad", "run-cancel"}
