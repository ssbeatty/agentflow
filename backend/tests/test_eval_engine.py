"""Eval engine (services/eval_engine.py).

Two layers, mirroring test_usage_stats:
  1. Assertion grading — pure string ops (contains/not_contains/regex/equals) and
     the judge-JSON parser with a fake LLM. No network, no engine.
  2. A full `run_eval` end-to-end: a real one-file script is executed through the
     engine for each case (falling back to the backend python, like
     test_execution_engine_run), then graded. Asserts the pass/fail tally and
     per-case results land on the EvalRun row.
"""
import asyncio
from datetime import datetime, timedelta

import pytest

from app.models import EvalCase, EvalRun, Script, ScriptFile
from services import execution_engine, eval_engine


@pytest.fixture(autouse=True)
def _fast_engine(monkeypatch):
    # Fresh semaphore in this test's loop + short timeout (see execution-engine tests).
    monkeypatch.setattr(execution_engine, "_semaphore", None)
    monkeypatch.setattr(execution_engine, "EXECUTION_TIMEOUT", 90.0)
    monkeypatch.setattr(eval_engine, "CASE_TIMEOUT", 90.0)


# ── layer 1: assertion grading ────────────────────────────────────────────────

def test_string_assertions():
    g = eval_engine._grade_assertion
    assert g({"type": "contains", "value": "7 days"}, "refund in 7 days", None)["passed"]
    assert not g({"type": "contains", "value": "nope"}, "refund in 7 days", None)["passed"]
    assert g({"type": "not_contains", "value": "secret"}, "all public here", None)["passed"]
    assert not g({"type": "not_contains", "value": "secret"}, "the secret is x", None)["passed"]
    assert g({"type": "regex", "value": r"\d{2}:\d{2}"}, "opens 09:00", None)["passed"]
    assert g({"type": "equals", "value": "ok"}, "ok", None)["passed"]
    assert not g({"type": "equals", "value": "ok"}, "okay", None)["passed"]


def test_unknown_assertion_type_does_not_crash():
    r = eval_engine._grade_assertion({"type": "bogus", "value": "x"}, "out", None)
    assert r["passed"] is False and "unknown" in r["detail"]


class _FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, _prompt):
        return type("Msg", (), {"content": self._content})()


def test_judge_passes_above_threshold():
    llm = _FakeLLM('{"score": 9, "reason": "clear and correct"}')
    r = eval_engine._grade_assertion({"type": "judge", "value": "is it clear?", "threshold": 7}, "…", llm)
    assert r["passed"] and r["score"] == 9


def test_judge_fails_below_threshold():
    llm = _FakeLLM('{"score": 3, "reason": "vague"}')
    r = eval_engine._grade_assertion({"type": "judge", "value": "is it clear?", "threshold": 7}, "…", llm)
    assert not r["passed"] and r["score"] == 3


def test_judge_tolerates_non_json_reply():
    # Model rambled instead of returning JSON — we still pull a score out.
    llm = _FakeLLM("I'd rate this a solid 8 out of 10 honestly.")
    r = eval_engine._grade_assertion({"type": "judge", "value": "quality?"}, "…", llm)
    assert r["score"] == 8


# ── layer 2: full run_eval end-to-end ─────────────────────────────────────────

def _seed_script(db):
    script = Script(name="eval-e2e", entry_function="run")
    db.add(script)
    db.flush()
    db.add(ScriptFile(
        script_id=script.id, filename="main.py", is_main=True,
        content=(
            "def run(input):\n"
            "    return {'reply': f\"refund takes 7 days ({input.get('q','')})\"}\n"
        ),
    ))
    return script


def test_run_eval_tallies_pass_and_fail(db):
    script = _seed_script(db)
    passing = EvalCase(
        script_id=script.id, name="pass", input_json='{"q":"hi"}',
        assertions=[{"type": "contains", "value": "7 days"}],
    )
    failing = EvalCase(
        script_id=script.id, name="fail", input_json='{"q":"hi"}',
        assertions=[{"type": "contains", "value": "never-appears-xyz"}],
    )
    run = EvalRun(script_id=script.id, status="running", total=2)
    db.add_all([passing, failing, run])
    db.commit()
    run_id = run.id

    asyncio.run(eval_engine.run_eval(run_id))

    db.expire_all()
    run = db.query(EvalRun).filter_by(id=run_id).first()
    assert run.status == "completed"
    assert run.total == 2
    assert run.passed == 1
    outcomes = {r["name"]: r["passed"] for r in run.results_json}
    assert outcomes == {"pass": True, "fail": False}
    # each case ran a real execution and linked it
    assert all(r["execution_id"] for r in run.results_json)


def test_run_eval_with_judge_case_first_does_not_detach(db):
    # Regression: `needs_judge = any(...)` short-circuits on the first judge case,
    # so cases AFTER it were never row-reloaded and _run_case hit
    # DetachedInstanceError on case.id once the setup session closed. A judge case
    # ordered FIRST + a plain case SECOND reproduces the crash on the old code.
    # No LLM is configured, so the judge assertion just fails gracefully — we only
    # care that the run completes end-to-end without raising.
    script = _seed_script(db)
    judge_case = EvalCase(
        script_id=script.id, name="judge-first", input_json="{}",
        assertions=[{"type": "judge", "value": "is it good?", "threshold": 7}],
        created_at=datetime.utcnow() - timedelta(seconds=10),  # sorts first
    )
    plain_case = EvalCase(
        script_id=script.id, name="plain-second", input_json="{}",
        assertions=[{"type": "contains", "value": "7 days"}],
        created_at=datetime.utcnow(),
    )
    run = EvalRun(script_id=script.id, status="running", total=2)
    db.add_all([judge_case, plain_case, run])
    db.commit()
    run_id = run.id

    asyncio.run(eval_engine.run_eval(run_id))  # must NOT raise DetachedInstanceError

    db.expire_all()
    run = db.query(EvalRun).filter_by(id=run_id).first()
    assert run.status == "completed"  # a crash would leave it "failed"
    assert run.total == 2
    outcomes = {r["name"]: r["passed"] for r in run.results_json}
    # the plain case still ran and passed on "7 days"; the judge case failed
    # gracefully (no LLM) but did not crash the run
    assert outcomes["plain-second"] is True
    assert "judge-first" in outcomes


def test_run_eval_case_with_no_assertions_is_a_smoke_test(db):
    script = _seed_script(db)
    case = EvalCase(script_id=script.id, name="smoke", input_json="{}", assertions=[])
    run = EvalRun(script_id=script.id, status="running", total=1)
    db.add_all([case, run])
    db.commit()
    run_id = run.id

    asyncio.run(eval_engine.run_eval(run_id))

    db.expire_all()
    run = db.query(EvalRun).filter_by(id=run_id).first()
    # no assertions → passes as long as the script ran cleanly
    assert run.status == "completed"
    assert run.passed == 1
