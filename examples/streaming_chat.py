"""
Streaming chat — direct LLM, no tools, with reasoning support.

Works with the /converse page out of the box. Tokens appear in real-time as the
LLM generates them.

Reasoning / "Think":
  - The conversation's Think level (set in /converse) arrives as
    input["reasoning"] = "off" | "low" | "medium" | "high" and is passed to
    get_llm(reasoning=…), which maps it to the model's provider-specific knob
    (Claude thinking budget, OpenAI reasoning_effort, gateway enable_thinking…).
  - `stream_reasoning=True` makes the PLATFORM surface the model's chain-of-thought
    (DeepSeek `reasoning_content`, Claude thinking blocks, …) in the chat UI as a
    collapsible "thought process" — kept out of the returned reply automatically.
    Your loop stays trivial: no <think> tags, no reasoning_content branch. This
    is the whole point — think handling is not the script's job to get right.

How to use:
  1. Copy this file's content into a new AgentFlow script (main.py).
  2. Open the script in /converse and pick a Think level to see reasoning.

Input  : {"message": str, "history": [{"role": str, "content": str}], "reasoning": str}
Output : {"reply": str}
"""
from agentflow import token, get_llm


async def run(input: dict) -> dict:
    llm = get_llm(reasoning=input.get("reasoning"), stream_reasoning=True)
    history = input.get("history", [])

    messages = (
        [("system", "You are a helpful assistant.")]
        + [(m["role"], m["content"]) for m in history]
        + [("human", input["message"])]
    )

    full_reply = ""
    async for chunk in llm.astream(messages):
        # Only the answer — the platform streams the <think> reasoning block for us.
        text = chunk.content if isinstance(chunk.content, str) else "".join(
            c.get("text", "") for c in chunk.content if isinstance(c, dict))
        if text:
            token(text)          # streams to /converse in real-time
            full_reply += text

    return {"reply": full_reply}
