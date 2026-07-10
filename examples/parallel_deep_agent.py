"""
Parallel sub-agents the deepagents way — the LLM decides the fan-out.

Where parallel_gather_orchestrator.py splits the work in CODE, this hands one
deep agent a `task` tool + a named subagent and lets the MODEL launch it — in
parallel, when it emits several `task` calls in a single turn (deepagents' task
tool runs those concurrently on the async path). Zero orchestration code:
get_deep_agent(subagents=[...]) is the whole thing, and you also get deepagents'
planning + filesystem + skills for free.

Trade-off vs. the gather version:
  + Least code; the model adapts the decomposition to each question.
  - Parallelism is EMERGENT: it only overlaps if your model emits parallel tool
    calls (Claude / GPT-4o class do; some OpenAI-compatible gateways / local
    models don't — then you still get isolated-context subagents, but they run
    sequentially, with no wall-clock speedup).

How to SEE whether it actually parallelized:
  Open the run's Flow / "Agent trace" panel and look at the `task` calls — if
  two or more start at overlapping timestamps, they ran in parallel. If they run
  strictly one-after-another, your model isn't emitting parallel tool calls; use
  parallel_gather_orchestrator.py for guaranteed parallelism.

Note: each subagent gets an ISOLATED context window (it only sees the task
description you delegate, not the whole conversation) and returns just its final
message — the Anthropic "isolate context, compress the result back up" pattern,
handled by deepagents for free.

How to use:
  1. Configure an LLM channel in Settings.
  2. Copy this file into a new AgentFlow script (main.py); entry function "run".
  3. Ask a breadth-first question in /converse, e.g. "compare the pros/cons of
     Postgres, MySQL and SQLite for a small self-hosted app" — independent
     angles the orchestrator can research in parallel.

Input  : {"message": str, "history": [...], "reasoning": str}
Output : {"reply": str}
"""
from agentflow import get_deep_agent, get_tools, stream_agent

ORCHESTRATOR_PROMPT = """You are a research orchestrator with a `task` tool and a
`researcher` subagent. When the question has several INDEPENDENT parts, launch
one `task` per part **in a single turn** (multiple task calls in one message) so
they run in parallel — do not call them one at a time. Then synthesize the
subagents' results into one clear final answer. For a trivial question, just
answer directly without spawning subagents."""

RESEARCHER_PROMPT = """You research the ONE sub-question you are given, using
web_search / web_fetch for current or specific facts, and return a tight,
sourced summary of just that sub-question. The orchestrator only sees your final
message — put the complete answer there."""


async def run(input: dict) -> dict:
    message = input.get("message") or input.get("text") or ""
    if not message:
        return {"reply": 'No "message" in input. Try a breadth-first question.'}

    agent = get_deep_agent(
        system_prompt=ORCHESTRATOR_PROMPT,
        tools=get_tools(),                       # main + subagents inherit web_search/web_fetch
        reasoning=input.get("reasoning"),
        stream_reasoning=True,
        subagents=[
            {
                "name": "researcher",
                "description": "Researches ONE focused, independent sub-question "
                               "and returns a concise, sourced summary. Launch "
                               "several in parallel for a multi-part question.",
                "system_prompt": RESEARCHER_PROMPT,
                # no "model" / "tools" → inherits the orchestrator's model + tools
            },
        ],
    )
    reply = await stream_agent(agent, [("human", message)])
    return {"reply": reply}
