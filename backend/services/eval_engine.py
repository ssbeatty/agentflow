"""Eval / regression engine.

Runs a script's whole eval dataset and grades each case, turning "did my change
make the agent better or worse?" into a pass/fail number.

Design — reuse, don't reinvent:
  - Each case is executed through the **real** execution engine (`spawn_execution`),
    so it exercises the exact same venv / LLM / tracer path a normal run does, and
    every case run is a first-class Execution row (with token usage tracked). The
    eval layer only orchestrates + grades; it never re-implements running a script.
  - Assertions are graded here in the backend. String assertions
    (contains/not_contains/regex/equals) are pure. The `judge` assertion builds an
    LLM from the default channel (the backend has the langchain stack — same as the
    built-in assistant) and asks it to score the output 0–10 against a criterion.

A run is kicked off as a background asyncio task; the frontend polls the EvalRun
row for status/results (same pattern as executions).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta

from loguru import logger

from app.database import SessionLocal
from app.models import Execution, EvalCase, EvalRun, Channel
from services.execution_engine import spawn_execution, stop_execution

# Wall-clock cap for a single case's script run (seconds).
CASE_TIMEOUT = float(os.getenv("AGENTFLOW_EVAL_CASE_TIMEOUT", "300"))
DEFAULT_JUDGE_THRESHOLD = 7
# How many cases to run at once. Each case is a real subprocess run (cold-imports
# the langchain stack), so running them concurrently is the cheap win over strict
# sequential — bounded so an eval doesn't flood the box / starve other runs. The
# per-case subprocesses are also still gated by the engine's global concurrency
# semaphore (AGENTFLOW_MAX_CONCURRENT).
EVAL_CONCURRENCY = max(1, int(os.getenv("AGENTFLOW_EVAL_CONCURRENCY", "4")))

# Keep strong refs to in-flight eval tasks so they aren't GC'd mid-run.
_eval_tasks: set[asyncio.Task] = set()


# ── judge LLM (default channel, built in the backend) ─────────────────────────

def _default_llm_blob(db) -> dict | None:
    """The default channel's creds, in the same shape execution_engine bakes into
    AGENTFLOW_LLM_DEFAULT. Returns None if no default model is configured."""
    channels = db.query(Channel).filter(Channel.enabled == True).all()  # noqa: E712
    ranked = sorted(channels, key=lambda c: (-(c.priority or 0), c.created_at or datetime.min))
    chosen: dict[str, Channel] = {}
    for ch in ranked:
        for model in (ch.models or []):
            chosen.setdefault(model, ch)
    default_model = next((c.default_model for c in channels if c.is_default and c.default_model), None)
    if not (default_model and default_model in chosen):
        return None
    ch = chosen[default_model]
    return {
        "name": default_model, "provider": ch.provider, "model": default_model,
        "api_key": ch.api_key, "base_url": ch.base_url, "extra_config": ch.extra_config or {},
    }


def _build_judge_llm(db):
    """Build a langchain chat model from the default channel for LLM-as-judge.

    Reuses `agentflow.get_llm` (no provider logic duplicated) by transiently
    setting AGENTFLOW_LLM_DEFAULT in the backend process — the default channel is
    global, so the value is stable even under concurrency. Returns (llm, model)
    or (None, None) if unavailable."""
    blob = _default_llm_blob(db)
    if not blob:
        return None, None
    prev = os.environ.get("AGENTFLOW_LLM_DEFAULT")
    os.environ["AGENTFLOW_LLM_DEFAULT"] = json.dumps(blob)
    try:
        import agentflow
        return agentflow.get_llm(), blob.get("model")
    except Exception as e:  # pragma: no cover - depends on installed provider libs
        logger.warning("[eval] judge LLM build failed: {}", e)
        return None, None
    finally:
        if prev is None:
            os.environ.pop("AGENTFLOW_LLM_DEFAULT", None)
        else:
            os.environ["AGENTFLOW_LLM_DEFAULT"] = prev


# ── assertion grading ─────────────────────────────────────────────────────────

def _stringify(output) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except Exception:
        return str(output)


_JUDGE_PROMPT = (
    "You are grading an AI agent's output against a single criterion.\n"
    "Score how well the output satisfies the criterion from 0 (fails completely) "
    "to 10 (fully satisfies).\n\n"
    "CRITERION:\n{criterion}\n\n"
    "AGENT OUTPUT:\n{output}\n\n"
    'Reply with ONLY a JSON object: {{"score": <integer 0-10>, "reason": "<one short sentence>"}}'
)


def _run_judge(llm, criterion: str, output_str: str) -> tuple[int, str]:
    """Ask the judge LLM to score the output. Returns (score, reason). Resilient
    to non-JSON replies (pulls the first integer out as a fallback)."""
    prompt = _JUDGE_PROMPT.format(criterion=criterion, output=output_str[:8000])
    resp = llm.invoke(prompt)
    text = getattr(resp, "content", None) or str(resp)
    if isinstance(text, list):  # some providers return content blocks
        text = " ".join(str(getattr(b, "text", b)) for b in text)
    try:
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        score = int(data.get("score"))
        reason = str(data.get("reason", ""))[:300]
        return max(0, min(10, score)), reason
    except Exception:
        m = re.search(r"\b(10|[0-9])\b", text)
        return (int(m.group(1)) if m else 0), text.strip()[:300]


def _grade_assertion(a: dict, output_str: str, judge_llm) -> dict:
    """Grade one assertion against the output. Returns
    {type, value, passed, detail}."""
    t = (a.get("type") or "").strip()
    value = a.get("value") or ""
    res = {"type": t, "value": value, "passed": False, "detail": ""}
    try:
        if t == "contains":
            res["passed"] = value in output_str
            res["detail"] = "found" if res["passed"] else "substring not found"
        elif t == "not_contains":
            res["passed"] = value not in output_str
            res["detail"] = "absent" if res["passed"] else "forbidden substring present"
        elif t == "equals":
            res["passed"] = output_str.strip() == value.strip()
            res["detail"] = "exact match" if res["passed"] else "not equal"
        elif t == "regex":
            res["passed"] = re.search(value, output_str) is not None
            res["detail"] = "matched" if res["passed"] else "no match"
        elif t == "judge":
            if judge_llm is None:
                res["detail"] = "no default LLM configured for judge"
            else:
                threshold = a.get("threshold") or DEFAULT_JUDGE_THRESHOLD
                score, reason = _run_judge(judge_llm, value, output_str)
                res["passed"] = score >= threshold
                res["score"] = score
                res["threshold"] = threshold
                res["detail"] = f"{score}/10 (≥{threshold}) — {reason}"
        else:
            res["detail"] = f"unknown assertion type: {t}"
    except Exception as e:
        res["detail"] = f"assertion error: {e}"
    return res


# ── run orchestration ─────────────────────────────────────────────────────────

async def _run_case(case: dict, judge_llm) -> dict:
    """Execute one case through the real engine and grade its assertions.

    `case` is a plain dict (id/name/script_id/input_json/assertions) extracted
    from the ORM BEFORE the caller's session closed — never a live EvalCase, so
    there is no detached-instance lazy-load across the long await below."""
    entry = {
        "case_id": case["id"],
        "name": case["name"],
        "passed": False,
        "output": None,
        "error": None,
        "execution_id": None,
        "assertions": [],
    }
    try:
        input_data = json.loads(case["input_json"] or "{}")
        if not isinstance(input_data, dict):
            raise ValueError("input must be a JSON object")
    except Exception as e:
        entry["error"] = f"invalid input JSON: {e}"
        return entry

    # Create + run a real Execution for this case.
    db = SessionLocal()
    try:
        exc = Execution(script_id=case["script_id"], input_data=input_data)
        db.add(exc)
        db.commit()
        db.refresh(exc)
        execution_id = exc.id
    finally:
        db.close()
    entry["execution_id"] = execution_id

    task = spawn_execution(execution_id)
    try:
        await asyncio.wait_for(task, timeout=CASE_TIMEOUT)
    except asyncio.TimeoutError:
        await stop_execution(execution_id)
        entry["error"] = f"case timed out after {CASE_TIMEOUT:.0f}s"
        return entry
    except Exception as e:  # pragma: no cover
        entry["error"] = f"execution error: {e}"
        return entry

    db = SessionLocal()
    try:
        final = db.query(Execution).filter_by(id=execution_id).first()
        output = final.output_data if final else None
        run_error = final.error if final else None
        status = final.status if final else "failed"
    finally:
        db.close()

    entry["output"] = output
    if status != "completed":
        entry["error"] = run_error or f"run {status}"
        return entry

    output_str = _stringify(output)
    assertions = case["assertions"] or []
    # Grade off the event loop: a judge assertion does a blocking llm.invoke(),
    # which would serialize concurrent cases (and block the WS) if run inline.
    graded = await asyncio.to_thread(
        lambda: [_grade_assertion(a if isinstance(a, dict) else {}, output_str, judge_llm) for a in assertions]
    )
    entry["assertions"] = graded
    # A case passes if it ran cleanly AND every assertion passed. A case with no
    # assertions passes as long as the run completed (a smoke test).
    entry["passed"] = all(g["passed"] for g in graded)
    return entry


async def run_eval(eval_run_id: str) -> None:
    """Execute all cases for an EvalRun and persist the results. Runs as a
    background task; failures are captured onto the row, never raised."""
    db = SessionLocal()
    try:
        run = db.query(EvalRun).filter_by(id=eval_run_id).first()
        if not run:
            return
        script_id = run.script_id
        cases = db.query(EvalCase).filter_by(script_id=script_id).order_by(EvalCase.created_at).all()
        # Extract each case into a plain dict WHILE the session is open — the run
        # loop below awaits per-case executions with the session closed, so a live
        # ORM instance would raise DetachedInstanceError on attribute access.
        cases_data = [
            {"id": c.id, "name": c.name, "script_id": c.script_id,
             "input_json": c.input_json, "assertions": list(c.assertions or [])}
            for c in cases
        ]
        run.total = len(cases_data)
        db.commit()
        needs_judge = any(
            (a or {}).get("type") == "judge"
            for cd in cases_data for a in cd["assertions"]
        )
        judge_llm, judge_model = (_build_judge_llm(db) if needs_judge else (None, None))
        if judge_model:
            run.judge_model = judge_model
            db.commit()
    except Exception as e:
        logger.exception("[eval] run {} setup failed", eval_run_id)
        _fail_run(eval_run_id, str(e))
        db.close()
        return
    finally:
        db.close()

    # Run cases with bounded concurrency (preserves order). A per-case crash is
    # captured as a failed result rather than sinking the whole run.
    sem = asyncio.Semaphore(EVAL_CONCURRENCY)

    async def _guarded(case: dict) -> dict:
        async with sem:
            try:
                return await _run_case(case, judge_llm)
            except Exception as e:  # pragma: no cover - _run_case already guards
                logger.exception("[eval] case {} crashed", case.get("id"))
                return {"case_id": case.get("id"), "name": case.get("name"), "passed": False,
                        "output": None, "error": f"case error: {e}", "execution_id": None,
                        "assertions": []}

    try:
        results = list(await asyncio.gather(*[_guarded(c) for c in cases_data]))
    except Exception as e:
        logger.exception("[eval] run {} crashed", eval_run_id)
        _fail_run(eval_run_id, str(e), [])
        return

    passed = sum(1 for r in results if r["passed"])
    db = SessionLocal()
    try:
        run = db.query(EvalRun).filter_by(id=eval_run_id).first()
        if run:
            run.results_json = results
            run.passed = passed
            run.total = len(results)
            run.status = "completed"
            run.finished_at = datetime.utcnow()
            db.commit()
        logger.info("[eval] run {} done: {}/{} passed", eval_run_id, passed, len(results))
    finally:
        db.close()


def _fail_run(eval_run_id: str, error: str, results: list | None = None) -> None:
    db = SessionLocal()
    try:
        run = db.query(EvalRun).filter_by(id=eval_run_id).first()
        if run:
            run.status = "failed"
            run.error = error
            if results is not None:
                run.results_json = results
                run.passed = sum(1 for r in results if r.get("passed"))
            run.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def start_eval_run(eval_run_id: str) -> asyncio.Task:
    """Schedule a background eval run on the running event loop. Must be called
    from async context (the running loop) — `asyncio.create_task` needs it, and
    unlike `get_event_loop()` it never fabricates a loop in a threadpool thread
    (which is why a sync route handler calling this used to 500). Mirrors
    execution_engine.spawn_execution."""
    task = asyncio.create_task(run_eval(eval_run_id))
    _eval_tasks.add(task)
    task.add_done_callback(_eval_tasks.discard)
    return task
