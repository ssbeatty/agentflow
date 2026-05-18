"""
Chat-driven artifacts demo (for /converse).

The reply streams character-by-character (typewriter via token()), and
artifact cards render below the bubble depending on keywords in your
message. No LLM required — purely deterministic keyword routing so you
can verify every channel by hand.

How to test in /converse:

    type:           you'll see:
    --------------  -------------------------------------------------
    hi              greeting only, no artifacts
    show image      2 images (external URL + raw PNG bytes)
    show table      a sales table
    markdown        a styled weekly-report markdown card
    html            a gradient dashboard HTML card (sandboxed iframe)
    image + table   combine: both renderers fire
    all             one of every kind in a single turn
    anything else   reply explains what triggers exist

Chinese aliases also work: 图/图片, 表/表格, 报告, 卡片, 全部

Input  : {"message": str, "history": [...]}   ← /converse convention
Output : {"reply": str}
"""
import time
from agentflow import token, log, markdown, image, table, html


# A 1×1 transparent PNG so the "raw bytes" image always renders without deps.
TINY_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C63F8FFFF3F0005FE02FE2C8E1B6E0000000049454E44AE426082"
)


def stream(text: str, delay: float = 0.02) -> str:
    """Emit text via token() with a small delay so the typewriter is visible
    in the chat. Returns the full text for use as the final reply."""
    for ch in text:
        token(ch)
        time.sleep(delay)
    return text


# ── Artifact emitters (one per kind) ──────────────────────────────────────────

def emit_image() -> None:
    image(
        "https://placehold.co/420x140/10b981/white/png?text=image()+via+URL",
        alt="placeholder",
        title="image — URL",
    )
    image(TINY_PNG, mime="image/png", alt="1×1 pixel", title="image — raw bytes")


def emit_table() -> None:
    table(
        [
            {"product": "Widget A", "qty": 120, "revenue": 2400},
            {"product": "Widget B", "qty":  85, "revenue": 1700},
            {"product": "Widget C", "qty":  42, "revenue":  840},
        ],
        title="sample sales",
    )


def emit_markdown() -> None:
    markdown(
        "# Weekly report\n\n"
        "## Highlights\n"
        "- Revenue **+12%** WoW\n"
        "- p99 latency **142 ms** (target: 200 ms ✅)\n"
        "- 0 incidents\n\n"
        "## Action items\n"
        "- [x] migrate worker pool\n"
        "- [x] backfill new index\n"
        "- [ ] canary deploy\n"
        "- [ ] flip feature flag\n",
        title="weekly report",
    )


def emit_html() -> None:
    html(
        "<div style=\"padding:16px;"
        "background:linear-gradient(135deg,#1e3a8a 0%,#7e22ce 100%);"
        "color:white;border-radius:8px;font-family:-apple-system,system-ui,sans-serif\">"
        "<div style=\"font-size:11px;opacity:0.7;letter-spacing:.1em\">SYSTEM STATUS</div>"
        "<div style=\"font-size:24px;font-weight:600;margin-top:4px\">All systems operational</div>"
        "<div style=\"display:flex;gap:24px;margin-top:12px;font-size:11px\">"
        "<div><b style=\"font-size:18px\">99.98%</b><br>uptime · 30d</div>"
        "<div><b style=\"font-size:18px\">142ms</b><br>p50 latency</div>"
        "<div><b style=\"font-size:18px\">0</b><br>open incidents</div>"
        "</div></div>",
        title="dashboard widget",
    )


# ── Routing ───────────────────────────────────────────────────────────────────

# (keyword aliases, label, emitter)
TRIGGERS = [
    (("image", "img", "picture", "pic", "图", "图片"),  "an image set",     emit_image),
    (("table", "data", "表", "表格"),                    "a table",          emit_table),
    (("markdown", "report", "报告"),                     "a markdown card",  emit_markdown),
    (("html", "dashboard", "card", "卡片"),              "an html card",     emit_html),
]


def _matches(msg: str, words) -> bool:
    return any(w in msg for w in words)


def run(input: dict) -> dict:
    msg = (input.get("message") or "").strip()
    msg_lower = msg.lower()
    log("user said", data={"message": msg})

    if not msg or msg_lower in {"hi", "hello", "hey", "你好", "嗨"}:
        return {"reply": stream(
            "Hey! Type a keyword to trigger an artifact: "
            "image, table, markdown, html, or all. "
            "Chinese works too: 图 / 表 / 报告 / 卡片 / 全部."
        )}

    # "all" / "全部" → fire every emitter
    if "all" in msg_lower or "全部" in msg or "everything" in msg_lower:
        for _, _, fn in TRIGGERS:
            fn()
        return {"reply": stream(
            "Here you go — one of every artifact kind rendered above. "
            "Refresh the page or open History to verify the artifacts persist."
        )}

    # otherwise, fire each trigger whose keyword appears
    fired = []
    for words, label, fn in TRIGGERS:
        if _matches(msg_lower, words):
            fn()
            fired.append(label)

    if not fired:
        return {"reply": stream(
            f"No trigger keywords detected in “{msg}”. "
            "Try one of: image, table, markdown, html, or all "
            "(图 / 表 / 报告 / 卡片 / 全部)."
        )}

    if len(fired) == 1:
        summary = fired[0]
    elif len(fired) == 2:
        summary = f"{fired[0]} and {fired[1]}"
    else:
        summary = ", ".join(fired[:-1]) + f", and {fired[-1]}"

    return {"reply": stream(f"Rendered {summary} above. What else?")}
