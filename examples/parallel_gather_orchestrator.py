"""
Parallel orchestrator-worker fan-out (asyncio.gather) — CODE-directed parallelism.

The canonical "多个 agent 并行工作" pattern, done the deterministic way: a cheap
planner splits the question into independent sub-questions, N worker agents
research them **in parallel** (asyncio.gather over get_agent().ainvoke), and a
final synthesizer merges the findings into one answer.

Why this shape (vs. letting one deep agent decide — see parallel_deep_agent.py):
  - TRUE parallelism regardless of the model — it never depends on the model
    emitting parallel tool calls; asyncio.gather overlaps the workers' network
    I/O on the runner's single event loop (the runner is asyncio.run + nest_asyncio).
  - Deterministic + testable: you control how the work is split and merged.
  - Cheap, isolated workers.

The two AgentFlow-specific rules this file demonstrates — both REQUIRED for
correct parallel agents on this platform:
  1. Workers use get_agent(checkpointer=False). Otherwise, in a /converse chat
     run, every worker auto-attaches the SAME conversation thread and they
     corrupt each other's state by writing to it concurrently.
  2. Workers run with plain .ainvoke (no token()/stream). Only the final
     synthesizer uses stream_agent(), so parallel workers never interleave
     half-sentences into one chat bubble.

It logs a timing line so you can SEE the value: parallel wall-clock vs. the
serial sum, and the resulting speedup. Watch it in the run's Logs / Flow panel.

How to use:
  1. Configure an LLM channel in Settings (get_agent needs a default LLM).
  2. Copy this file into a new AgentFlow script (main.py); entry function "run".
  3. Run it with a breadth-first input, e.g.
     {"message": "对比 Postgres、MySQL、SQLite 做自托管小应用的优劣"} — it splits
     cleanly into parallel angles. Or chat via /converse.

Input  : {"message": str, "history": [...], "reasoning": str}
Output : {"reply": str, "subtasks": [str], "speedup": float}
"""
import asyncio
import json
import time

from agentflow import get_agent, get_llm, stream_agent, log

MAX_WORKERS = 4

PLANNER_PROMPT = """You split a user's question into at most {n} INDEPENDENT
sub-questions that can be researched in parallel with no dependency on each
other. Return ONLY a JSON array of strings, nothing else. If the question is
simple and not worth splitting, return a single-element array."""

WORKER_PROMPT = """You research ONE focused sub-question. Use web_search /
web_fetch if you need current or specific facts. Return a tight, concrete
summary of just this sub-question — no preamble, no restating the question."""

SYNTH_PROMPT = """You synthesize several parallel research results into one
coherent, well-structured answer to the user's original question. Merge
overlaps, resolve contradictions, and keep it concise."""


def _parse_subtasks(text: str, fallback: str) -> list[str]:
    """Best-effort pull a JSON array of strings out of the planner's reply."""
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        arr = json.loads(text[start:end])
        subs = [str(s).strip() for s in arr if str(s).strip()]
        if subs:
            return subs[:MAX_WORKERS]
    except Exception:
        pass
    return [fallback]


async def _plan(question: str) -> list[str]:
    llm = get_llm()
    if llm is None:
        return [question]
    try:
        resp = await llm.ainvoke(
            [("system", PLANNER_PROMPT.format(n=MAX_WORKERS)), ("human", question)]
        )
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _parse_subtasks(content, question)
    except Exception as e:
        log(f"planner failed ({e}); running the question as a single task", step="plan")
        return [question]


async def _worker(idx: int, subtask: str) -> tuple[float, str]:
    # checkpointer=False → a stateless worker that never touches the conversation
    # thread, so many of these are safe to run concurrently. No streaming here.
    agent = get_agent(system_prompt=WORKER_PROMPT, checkpointer=False)
    t0 = time.perf_counter()
    result = await agent.ainvoke({"messages": [("user", subtask)]})
    dt = time.perf_counter() - t0
    msgs = result.get("messages") if isinstance(result, dict) else None
    text = msgs[-1].content if msgs else ""
    log(f"worker #{idx + 1} finished in {dt:.1f}s", step=f"worker-{idx + 1}",
        data={"subtask": subtask})
    return dt, text


async def run(input: dict) -> dict:
    question = input.get("message") or input.get("text") or ""
    if not question:
        return {"reply": 'No "message" in input. Try {"message": "compare X vs Y vs Z"}.'}

    subtasks = await _plan(question)
    log(f"planned {len(subtasks)} parallel sub-question(s)", step="plan", data=subtasks)

    # ── the fan-out: all workers run concurrently ─────────────────────────────
    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[_worker(i, s) for i, s in enumerate(subtasks)],
        return_exceptions=True,   # one worker failing must not sink the rest
    )
    wall = time.perf_counter() - t0

    findings: list[tuple[int, str]] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            log(f"worker #{i + 1} errored: {r}", level="error", step=f"worker-{i + 1}")
        else:
            findings.append((i, r[1]))
    serial = sum(r[0] for r in results if not isinstance(r, Exception))
    speedup = round(serial / wall, 1) if wall > 0 else 1.0
    log(f"PARALLEL wall={wall:.1f}s  vs  serial≈{serial:.1f}s  →  {speedup}x speedup",
        step="timing")

    if not findings:
        return {"reply": "All parallel workers failed — see the error logs above.",
                "subtasks": subtasks, "speedup": speedup}

    # ── synthesize: the ONLY agent that streams to the chat UI ────────────────
    synth = get_agent(system_prompt=SYNTH_PROMPT,
                      reasoning=input.get("reasoning"), stream_reasoning=True)
    joined = "\n\n".join(
        f"## sub-question {i + 1}: {subtasks[i]}\n{text}" for i, text in findings
    )
    prompt = (f"Original question:\n{question}\n\n"
              f"Parallel research results:\n{joined}\n\n"
              f"Synthesize these into one complete answer to the original question.")
    reply = await stream_agent(synth, [("human", prompt)])
    return {"reply": reply, "subtasks": subtasks, "speedup": speedup}
