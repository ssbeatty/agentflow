"""
Daily news digest → webhook push   ⭐ flagship example

A complete, genuinely useful agent you can set on a schedule: it researches a
topic on the web, writes a tight digest with sources, and pushes it to your
phone / chat via a webhook. It ties together the pieces AgentFlow gives you —
`get_agent()` + the built-in `web_search` tool, `get_secret()`, `http_post()`,
and cron scheduling — into one "set it and forget it" job.

Setup (3 steps):
  1. Settings → add an LLM channel (any OpenAI-compatible / Anthropic / … provider)
     and mark a default model.
  2. Secrets → add  WEBHOOK_URL = <your push endpoint>. Anything that accepts a
     JSON POST works, e.g.:
       - Bark (iOS):        https://api.day.app/<device_key>
       - Slack / Feishu / DingTalk incoming webhook
       - your own HTTP endpoint
     No secret set? The script still returns the digest — it just skips the push.
  3. Schedule tab → add a cron (e.g. `0 8 * * *`) with input:
       {"topic": "AI agents", "count": 5}

Press ▶ Run once to preview, then let cron drive it every morning.

Input  : {"topic": str, "count": int}     # count = how many items to include
Output : {"topic": str, "digest": str, "pushed": bool}
"""
from agentflow import get_agent, get_secret, http_post, log


def _system_prompt(count: int) -> str:
    return f"""You are a news research assistant.
Use the web_search tool to find the most recent, relevant developments on the
user's topic, then write a tight digest:
- exactly {count} bullet points, most important first
- one sentence each — concrete and specific (names, numbers, dates)
- end each bullet with its source URL in parentheses
Do not pad, editorialize, or repeat. If little is genuinely new, say so briefly."""


def _push(title: str, body: str) -> bool:
    """POST the digest to WEBHOOK_URL as JSON. Returns whether it was sent."""
    url = get_secret("WEBHOOK_URL")
    if not url:
        log("No WEBHOOK_URL secret set — skipping push (digest still returned).",
            level="warning", step="notify")
        return False
    # A generic {title, body} JSON payload most webhooks accept; keeps the script
    # provider-agnostic (Bark/Slack/Feishu/your own all take a JSON POST).
    resp = http_post(url, json={"title": title, "body": body})
    log(f"Pushed digest to webhook (HTTP {resp.status_code}).", step="notify")
    return True


def run(input: dict) -> dict:
    topic = (input.get("topic") or "AI agents").strip()
    count = int(input.get("count") or 5)
    log(f"Researching “{topic}” ({count} items)…", step="research")

    agent = get_agent(system_prompt=_system_prompt(count))
    result = agent.invoke({"messages": [(
        "human",
        f"Give me today's digest on: {topic}. Use up-to-date web results.",
    )]})
    digest = result["messages"][-1].content

    pushed = _push(f"📰 {topic} — daily digest", digest)
    log("Digest ready.", step="done")
    return {"topic": topic, "digest": digest, "pushed": pushed}
