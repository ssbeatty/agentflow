"""
Streaming chat — direct LLM, no tools.

Works with the /converse page out of the box.
Tokens appear in real-time as the LLM generates them.

How to use:
  1. Copy this file's content into a new AgentFlow script (main.py).
  2. Open the script in /converse to chat with persistent history.

Input  : {"message": str, "history": [{"role": str, "content": str}]}
Output : {"reply": str}
"""
from agentflow import token, get_llm


async def run(input: dict) -> dict:
    llm = get_llm()
    history = input.get("history", [])

    messages = (
        [("system", "You are a helpful assistant.")]
        + [(m["role"], m["content"]) for m in history]
        + [("human", input["message"])]
    )

    full_reply = ""
    async for chunk in llm.astream(messages):
        if chunk.content:
            token(chunk.content)   # streams to /converse in real-time
            full_reply += chunk.content

    return {"reply": full_reply}
