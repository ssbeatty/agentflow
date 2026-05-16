"""
Streaming ReAct agent with Obsidian MCP tools.

Tokens stream to the frontend while the agent thinks and calls tools.
Tool calls (e.g. reading notes) appear as log events in the log strip.

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
from agentflow import token, get_agent, log

SYSTEM_PROMPT = """You are a helpful assistant with access to the user's Obsidian vault.
When asked about notes, always search or read them before answering.
Be concise and cite the note titles you referenced."""


async def run(input: dict) -> dict:
    agent = get_agent(system_prompt=SYSTEM_PROMPT)

    history = [(m["role"], m["content"]) for m in input.get("history", [])]
    messages = history + [("human", input["message"])]

    full_reply = ""
    async for event in agent.astream_events({"messages": messages}, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            # LLM is generating a token
            content = event["data"]["chunk"].content
            if content:
                token(content)
                full_reply += content

        elif kind == "on_tool_start":
            # Agent is calling a tool (e.g. obsidian_search)
            log(f"Using tool: {event['name']}", step="tool")

        elif kind == "on_tool_end":
            # Optionally log tool result summary
            pass

    return {"reply": full_reply}
