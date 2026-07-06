"""LLM token-usage accounting (Tier-1 cost observability).

Two layers:
  1. `agentflow._tracer._extract_usage` — normalizes token counts across the
     provider shapes we actually see (langchain `usage_metadata`, OpenAI
     `llm_output.token_usage`, Anthropic `llm_output.usage`). Pure, no deps.
  2. `routers/executions.get_usage_stats` — aggregates persisted per-run tokens
     into the dashboard payload (overall totals, zero-filled daily trend,
     per-script breakdown). Uses the `db` fixture (temp sqlite).
"""
from datetime import datetime, timedelta

from app.models import Execution, Script
from app.routers.executions import get_usage_stats
from agentflow._tracer import _extract_usage, _accumulate_usage, get_usage_totals, _usage_totals


# ── layer 1: provider-shape normalization ────────────────────────────────────

class _Msg:
    def __init__(self, um):
        self.usage_metadata = um


class _Gen:
    def __init__(self, um=None):
        self.message = _Msg(um) if um is not None else None


class _Resp:
    def __init__(self, gens=None, llm_output=None):
        self.generations = gens
        self.llm_output = llm_output


def test_extract_usage_from_usage_metadata():
    # langchain-standard field (ChatOpenAI / ChatAnthropic new)
    r = _Resp(gens=[[_Gen({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})]])
    assert _extract_usage(r) == (10, 5, 15)


def test_extract_usage_from_openai_llm_output():
    r = _Resp(gens=[[_Gen()]], llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})
    assert _extract_usage(r) == (7, 3, 10)


def test_extract_usage_from_anthropic_usage_without_total():
    # input/output only → total is derived
    r = _Resp(gens=[[_Gen()]], llm_output={"usage": {"input_tokens": 4, "output_tokens": 6}})
    assert _extract_usage(r) == (4, 6, 10)


def test_extract_usage_absent_is_zero():
    assert _extract_usage(_Resp(gens=[[_Gen()]])) == (0, 0, 0)
    assert _extract_usage(_Resp()) == (0, 0, 0)


def test_accumulate_usage_counts_calls_and_sums():
    # reset the module-global accumulator (single process, tests share it)
    _usage_totals.update(prompt_tokens=0, completion_tokens=0, total_tokens=0, llm_calls=0)
    _accumulate_usage(_Resp(gens=[[_Gen({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})]]))
    _accumulate_usage(_Resp(gens=[[_Gen()]], llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}))
    # a call with no usage still bumps llm_calls (a round-trip happened)
    _accumulate_usage(_Resp(gens=[[_Gen()]]))
    assert get_usage_totals() == {"prompt_tokens": 17, "completion_tokens": 8, "total_tokens": 25, "llm_calls": 3}


# ── layer 2: dashboard aggregation ───────────────────────────────────────────

def _add_run(db, script_id, total, prompt=0, completion=0, calls=1, age_days=0):
    e = Execution(
        script_id=script_id,
        status="completed",
        total_tokens=total,
        prompt_tokens=prompt,
        completion_tokens=completion,
        llm_calls=calls,
        created_at=datetime.utcnow() - timedelta(days=age_days),
    )
    db.add(e)
    db.flush()
    return e


def test_usage_stats_totals_and_breakdown(db):
    a = Script(name="alpha")
    b = Script(name="beta")
    db.add_all([a, b])
    db.flush()
    _add_run(db, a.id, total=100, prompt=60, completion=40, calls=2, age_days=0)
    _add_run(db, a.id, total=50, prompt=30, completion=20, calls=1, age_days=1)
    _add_run(db, b.id, total=300, prompt=200, completion=100, calls=3, age_days=2)
    db.commit()

    out = get_usage_stats(days=7, db=db)

    assert out["total_tokens"] == 450
    assert out["prompt_tokens"] == 290
    assert out["completion_tokens"] == 160
    assert out["llm_calls"] == 6
    assert out["runs"] == 3
    # daily trend is zero-filled to exactly `days` entries, oldest→newest
    assert len(out["daily"]) == 7
    assert sum(d["total_tokens"] for d in out["daily"]) == 450
    # breakdown sorted by spend, beta (300) ahead of alpha (150)
    assert [s["name"] for s in out["by_script"]] == ["beta", "alpha"]
    assert out["by_script"][0]["total_tokens"] == 300


def test_usage_stats_excludes_runs_outside_window(db):
    s = Script(name="s")
    db.add(s)
    db.flush()
    _add_run(db, s.id, total=100, age_days=1)     # inside 7d
    _add_run(db, s.id, total=999, age_days=30)    # outside 7d
    db.commit()

    out = get_usage_stats(days=7, db=db)

    assert out["total_tokens"] == 100
    assert out["runs"] == 1
