"""
Streaming ReAct agent chat — built-in tools, no setup required.

This is the `get_agent()` counterpart to `streaming_chat.py` (which drives the LLM
directly). Use this when you want the model to **use tools** while chatting — it
gets the built-in `web_search` / `web_fetch` out of the box, so it can look things
up mid-conversation. Works with the /converse page as-is; no MCP server or skill
to configure (see `streaming_agent_obsidian.py` / `skill_agent.py` for those).

Why `stream_agent()` (not a hand-rolled `agent.astream(...)` loop):
  - It streams **only the assistant's answer** to /converse token-by-token — a
    tool's raw output (search results, fetched page text) never leaks into the reply.
  - The tool calls still render live in the /converse "Agent trace" panel via the
    platform tracer.
  - It returns the full answer string, so `run()` stays a two-liner.

Reasoning / "Think":
  - The conversation's Think level (set in /converse) arrives as
    input["reasoning"] = "off" | "low" | "medium" | "high" and is forwarded to
    get_agent(reasoning=…), mapped to the model's provider-specific knob.
  - `stream_reasoning=True` makes the PLATFORM surface the model's chain-of-thought
    as a collapsible "thought process" in the chat UI — kept out of the reply
    automatically, so this script has zero <think> logic.

How to use:
  1. Configure an LLM channel in Settings (get_agent needs a default LLM).
  2. Copy this file's content into a new AgentFlow script (main.py); entry "run".
  3. Open the script in /converse and chat — ask something current (e.g.
     "what happened in the news today?") to watch it search, then pick a Think
     level to see the reasoning block.

Input  : {"message": str, "history": [{"role": str, "content": str}], "reasoning": str}
Output : {"reply": str}
"""
from agentflow import get_agent, stream_agent

SYSTEM_PROMPT = """You are a helpful assistant. You can search the web
(web_search) and read pages (web_fetch) when the question needs current or
specific facts — use them, then cite what you relied on. For plain conversation,
just answer directly without calling a tool."""


async def run(input: dict) -> dict:
    # get_agent() pre-loads the built-in tools (web_search / web_fetch). Pass
    # reasoning + stream_reasoning so the platform handles the <think> block for us.
    agent = get_agent(
        system_prompt=SYSTEM_PROMPT,
        reasoning=input.get("reasoning"),
        stream_reasoning=True,
    )

    # In /converse the agent is threaded (state persists across turns under the
    # conversation id), so send only the new message — the checkpointer supplies
    # prior turns and multi-turn memory just works.
    # Streams only the answer to /converse; tool calls render in the Agent trace.
    full_reply = await stream_agent(agent, [("human", input["message"])])
    return {"reply": full_reply}
