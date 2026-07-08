"""
Streaming ReAct agent with Obsidian MCP tools.

Tokens stream to the frontend while the agent thinks and calls tools.
Tool calls (e.g. reading notes) appear in the "Agent trace" panel; stream_agent()
streams only the answer, keeping raw tool output out of the reply.

Prerequisites:
  - Configure the Obsidian MCP server in AgentFlow > Tools.
  - Enable that MCP server for this script in the script's right panel.

How to use:
  1. Copy this file's content into a new AgentFlow script (main.py).
  2. Set the entry function to "run".
  3. Enable your Obsidian MCP server for this script.
  4. Open the script in /converse to chat with your notes.

Input  : {"message": str, "history": [{"role": str, "content": str}]}
Output : {"reply": str}
"""
from agentflow import get_agent, stream_agent

SYSTEM_PROMPT = """You are a helpful assistant with access to the user's Obsidian vault.
When asked about notes, always search or read them before answering.
Be concise and cite the note titles you referenced."""


async def run(input: dict) -> dict:
    agent = get_agent(system_prompt=SYSTEM_PROMPT)

    history = [(m["role"], m["content"]) for m in input.get("history", [])]
    messages = history + [("human", input["message"])]

    # stream_agent() streams only the assistant's answer — the MCP tool results
    # (obsidian_search / read note) are dropped from the reply, and the tool calls
    # still render in the /converse "Agent trace" panel via the platform tracer.
    full_reply = await stream_agent(agent, messages)
    return {"reply": full_reply}
