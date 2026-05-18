"""
Chat-driven artifacts demo with LLM tool-calling (for /converse).

The LLM decides which artifact tool to call based on natural language,
then its text reply streams character-by-character (typewriter).

This is the AI version. The deterministic keyword version is
examples/chat_artifacts.py — use that to test the channel itself
without depending on an LLM provider.

Requires:
  - A default LLM configured in Settings → LLM Configs.
  - The model must support tool calling. Good picks: GPT-4o-mini,
    Claude 3.5 Haiku, DeepSeek-V3-Chat. DeepSeek-R1 will NOT tool-call.

How to test in /converse — just talk naturally:
  "show me a sample sales table"
  "render a markdown weekly status report"
  "draw a dashboard card showing uptime"
  "find me a cat picture"
  "give me a table AND a brief summary"
  "hi"                  ← regular chat works, no tools triggered

Input  : {"message": str, "history": [...]}
Output : {"reply": str}
"""
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage

from agentflow import (
    token, log, get_agent, get_llm,
    markdown as _markdown,
    image as _image,
    table as _table,
    html as _html,
)


# ── Tools: each one calls the matching artifact emitter ──────────────────────
#
# Tools return a short confirmation string so the LLM knows the call landed —
# the actual rendering side-effect happens in the platform.

@tool
def show_markdown(content: str, title: str = "") -> str:
    """Render a markdown card in the chat. Use for prose, lists, GFM tables, code blocks, links."""
    _markdown(content, title=title or None)
    return f"rendered markdown ({len(content)} chars)"


@tool
def show_table(rows: list[dict], title: str = "") -> str:
    """Render a data table. `rows` must be a list of dicts; keys form the columns.

    Example: show_table([{"name":"alice","score":92},{"name":"bob","score":81}], title="scores")
    """
    _table(rows, title=title or None)
    return f"rendered table ({len(rows)} rows)"


@tool
def show_image(url: str, alt: str = "", title: str = "") -> str:
    """Render an image from a public http(s) URL.

    If you don't have a real URL, use https://placehold.co/<w>x<h>/<bg>/<fg>/png?text=...
    """
    _image(url, alt=alt, title=title or None)
    return "rendered image"


@tool
def show_html(html_snippet: str, title: str = "") -> str:
    """Render an HTML snippet in a sandboxed iframe.

    Inline CSS only — scripts are blocked. Good for styled cards, dashboards,
    custom layouts. Keep it self-contained (no external assets).
    """
    _html(html_snippet, title=title or None)
    return "rendered html"


TOOLS = [show_markdown, show_table, show_image, show_html]


SYSTEM_PROMPT = """You are a chat assistant that can render rich artifacts.

Available rendering tools:
  - show_markdown(content, title)
  - show_table(rows, title)         # rows is list of dicts
  - show_image(url, alt, title)     # URL must be public
  - show_html(html_snippet, title)  # sandboxed iframe, inline CSS only

Rules:
  - If the user asks to see / show / draw / render / display / visualise
    something, call the matching tool.
  - Then ALWAYS also write a short text reply (1-2 sentences) explaining
    what you rendered. The text streams as a typewriter alongside the card.
  - When the user is just exploring ("show me a table"), invent plausible
    sample data — 3-5 rows for tables, a realistic snippet for HTML.
  - Don't call the same tool twice in a turn unless explicitly asked.
  - For pure conversation ("hi", "how are you"), don't call tools at all.

Examples:
  User: "show me a sales table"
    → show_table([{"product":"Widget A","qty":120,"revenue":2400}, ...], title="sales")
    → "Here's a sample sales table."

  User: "render a status dashboard"
    → show_html('<div style="...">...</div>', title="status")
    → "Here's a dashboard card."
"""


async def run(input: dict) -> dict:
    user_msg = (input.get("message") or "").strip()
    history = input.get("history") or []

    if get_llm() is None:
        msg = "⚠️ No default LLM configured. Add one in Settings → LLM Configs."
        token(msg)
        return {"reply": msg}

    log("turn start", data={"user": user_msg, "history_turns": len(history)})

    agent = get_agent(system_prompt=SYSTEM_PROMPT, tools=TOOLS)

    # /converse passes prior turns in input.history — convert to LangChain messages.
    msgs = []
    for m in history:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            msgs.append(HumanMessage(content))
        elif role == "assistant" and content:
            msgs.append(AIMessage(content))
    msgs.append(HumanMessage(user_msg))

    full_text = ""
    async for chunk, meta in agent.astream(
        {"messages": msgs},
        stream_mode="messages",
    ):
        # Skip token streams from tool nodes — only the agent's own LLM step
        # should appear in the chat bubble.
        if meta.get("langgraph_node") != "agent":
            continue
        text = getattr(chunk, "content", None)
        if text and isinstance(text, str):
            token(text)
            full_text += text

    log("turn done", data={"reply_chars": len(full_text)})
    return {"reply": full_text}
