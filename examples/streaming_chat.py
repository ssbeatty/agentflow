"""
Streaming chat — direct LLM, no tools, with reasoning support.

Works with the /converse page out of the box. Tokens appear in real-time as the
LLM generates them.

Reasoning / "Think":
  - The conversation's Think level (set in /converse) arrives as
    input["reasoning"] = "off" | "low" | "medium" | "high" and is passed to
    get_llm(reasoning=…), which maps it to the model's provider-specific knob
    (Claude thinking budget, OpenAI reasoning_effort, gateway enable_thinking…).
  - Reasoning that a model returns separately in
    additional_kwargs["reasoning_content"] (e.g. DeepSeek official API) is
    re-emitted as <think>…</think> so the chat UI renders a collapsible
    "thought process". It is kept OUT of the returned reply, so it is not
    persisted and does not pollute future history.

How to use:
  1. Copy this file's content into a new AgentFlow script (main.py).
  2. Open the script in /converse and pick a Think level to see reasoning.

Input  : {"message": str, "history": [{"role": str, "content": str}], "reasoning": str}
Output : {"reply": str}
"""
from agentflow import token, get_llm


async def run(input: dict) -> dict:
    llm = get_llm(reasoning=input.get("reasoning"))
    history = input.get("history", [])

    messages = (
        [("system", "You are a helpful assistant.")]
        + [(m["role"], m["content"]) for m in history]
        + [("human", input["message"])]
    )

    full_reply = ""
    in_think = False
    async for chunk in llm.astream(messages):
        rc = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
        if rc:
            if not in_think:
                token("<think>")
                in_think = True
            token(rc)
        if chunk.content:
            if in_think:
                token("</think>")
                in_think = False
            token(chunk.content)   # streams to /converse in real-time
            full_reply += chunk.content
    if in_think:
        token("</think>")

    return {"reply": full_reply}
