"""
Artifacts demo — exercises every rich-rendering channel.

Open the script's "Artifacts" tab after running to see:
  - markdown()  → headings, lists, code blocks, GFM tables, links
                  + embedded ```mermaid``` fences auto-render as diagrams
  - table()     → list[dict] and list[list] forms
  - image()     → external URL, local file (from an uploaded {"$file"}), raw bytes
  - html()      → sandboxed iframe with inline styles
  - mermaid()   → flowchart / sequence / state / class / ER / gantt etc.

How to use:
  1. Create a new AgentFlow script and paste this whole file into main.py.
  2. Optional: upload any small image in the Files panel; the script will use it.
     If you don't upload anything, the script falls back to a generated PNG and
     a public placeholder URL.
  3. Run — switch to the Artifacts tab to see all renderings.

Input shape (all optional):
  {
    "title":      "Custom dashboard title",
    "uploaded":   {"$file": "<file_id>"}    // any image you upload
  }
"""
from agentflow import log, markdown, image, table, html, mermaid, paths, AgentFlowFile


# A 1×1 transparent PNG so the demo always has bytes to render
# even if the user doesn't pip-install pillow / matplotlib.
TINY_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C63F8FFFF3F0005FE02FE2C8E1B6E0000000049454E44AE426082"
)


MARKDOWN_SAMPLE = """
## Today's metrics

> Pulled from `agentflow.markdown()`. Supports **GFM** — tables, task lists, code blocks.

### Throughput

| Region | RPS | p99 (ms) |
|--------|----:|---------:|
| us-east  | 1,240 | 87 |
| us-west  | 1,108 | 92 |
| eu-west  |   902 | 105 |

### TODO

- [x] migrate the worker pool
- [x] backfill the new index
- [ ] run the canary deploy
- [ ] flip the feature flag

### Sample code

```python
from agentflow import get_agent

agent = get_agent(system_prompt="You are concise.")
result = agent.invoke({"messages": [("user", "Hello!")]})
```

Learn more in the [docs](/docs).
"""


HTML_SAMPLE = """
<div style="
  font-family: -apple-system, system-ui, sans-serif;
  padding: 16px;
  background: linear-gradient(135deg,#1e3a8a 0%,#7e22ce 100%);
  color: white;
  border-radius: 8px;
">
  <div style="font-size:11px;opacity:0.7;letter-spacing:.1em">SYSTEM STATUS</div>
  <div style="font-size:28px;font-weight:600;margin-top:4px">All systems operational</div>
  <div style="display:flex;gap:24px;margin-top:16px">
    <div><div style="font-size:24px;font-weight:600">99.98%</div><div style="font-size:11px;opacity:0.7">uptime · 30d</div></div>
    <div><div style="font-size:24px;font-weight:600">142ms</div><div style="font-size:11px;opacity:0.7">p50 latency</div></div>
    <div><div style="font-size:24px;font-weight:600">0</div><div style="font-size:11px;opacity:0.7">open incidents</div></div>
  </div>
</div>
"""


def run(input: dict) -> dict:
    log("Starting artifacts demo", data={"keys": list(input.keys())})

    title = input.get("title") or "AgentFlow Artifacts Demo"

    # ── 1. Markdown: cover headings, GFM table, task list, code, link
    markdown(f"# {title}\n\nThis page is generated entirely from `agentflow.*` calls.\n", title="header")
    markdown(MARKDOWN_SAMPLE, title="full markdown sample")

    # ── 2. Table from list[dict] (columns auto-inferred, insertion order preserved)
    table(
        [
            {"name": "alice", "team": "platform", "commits": 47, "active": True},
            {"name": "bob",   "team": "platform", "commits": 31, "active": True},
            {"name": "carol", "team": "infra",    "commits": 92, "active": False},
            {"name": "dan",   "team": "infra",    "commits": 18, "active": True},
        ],
        title="contributors (list[dict])",
    )

    # ── 3. Table from list[list] with explicit columns
    table(
        rows=[
            [2026, 1, 1248, 87],
            [2026, 2, 1402, 91],
            [2026, 3, 1571, 95],
            [2026, 4, 1689, 98],
        ],
        columns=["year", "month", "events", "p99_ms"],
        title="time series (list[list])",
    )

    # ── 4. Image from URL (no bytes leave AgentFlow; the browser fetches directly)
    image(
        "https://placehold.co/600x200/3b82f6/white/png?text=External+image+via+URL",
        alt="external placeholder",
        title="image() — URL",
    )

    # ── 5. Image from raw bytes (saved into runs/<exec_id>/_artifacts/ and served back)
    image(TINY_PNG, mime="image/png", alt="1×1 transparent pixel", title="image() — raw bytes")

    # ── 6. Image from an uploaded file (only when user supplies {"$file": "..."})
    uploaded = input.get("uploaded")
    if isinstance(uploaded, AgentFlowFile):
        image(uploaded.path, alt=uploaded.name, title=f"image() — uploaded ({uploaded.name})")
        log("rendered uploaded image", data={"name": uploaded.name, "size": uploaded.size, "mime": uploaded.mime})
    else:
        markdown(
            "_Tip: upload any image in the **Files** panel, then add "
            "`\"uploaded\": {\"$file\": \"<id>\"}` to the input JSON to see it rendered here._",
            title="upload to see more",
        )

    # ── 7. Image from a local file we just wrote into the per-run cwd
    local_png = paths.run_dir / "generated.png"
    local_png.write_bytes(TINY_PNG)
    image(local_png, alt="written to run_dir", title="image() — local path")

    # ── 8. HTML (sandboxed iframe; no scripts, inline styles only)
    html(HTML_SAMPLE, title="html() — dashboard widget")

    # ── 9. Mermaid flowchart via explicit emitter
    mermaid(
        """flowchart LR
    Client[Browser] --> LB[Load balancer]
    LB --> A1[App #1]
    LB --> A2[App #2]
    A1 --> DB[(Postgres)]
    A2 --> DB
    A1 --> Cache[(Redis)]
    A2 --> Cache
""",
        title="mermaid() — flowchart",
    )

    # ── 10. Mermaid sequence diagram
    mermaid(
        """sequenceDiagram
    autonumber
    participant U as User
    participant API as API gateway
    participant W as Worker
    participant Q as Queue
    U->>API: POST /jobs
    API->>Q: enqueue
    API-->>U: 202 Accepted
    Q-->>W: pop job
    W->>W: process
    W-->>API: result
""",
        title="mermaid() — sequence",
    )

    # ── 11. Markdown that EMBEDS a mermaid code fence (renderer auto-detects it)
    markdown(
        "## State machine in a markdown block\n\n"
        "The renderer auto-detects ` ```mermaid ` fences inside `markdown()`:\n\n"
        "```mermaid\n"
        "stateDiagram-v2\n"
        "    [*] --> Idle\n"
        "    Idle --> Running: start\n"
        "    Running --> Done: finish\n"
        "    Running --> Failed: error\n"
        "    Failed --> Idle: retry\n"
        "    Done --> [*]\n"
        "```\n\n"
        "So you can mix prose, headings, and diagrams in one card.",
        title="markdown + embedded mermaid",
    )

    # ── 12. One more markdown to bookend
    base_count = 11  # md(2) + table(2) + image(3) + html(1) + mermaid(2) + md-with-mermaid(1)
    total = base_count + (1 if isinstance(uploaded, AgentFlowFile) else 0)
    markdown(
        "## ✅ Done\n\n"
        f"Rendered **{total}** artifact cards above.\n\n"
        "All five artifact types are working: "
        "`markdown()`, `table()`, `image()`, `html()`, `mermaid()`.",
        title="summary",
    )

    log("demo finished")
    return {
        "rendered": {
            "markdown": 5,
            "table": 2,
            "image": 3 if not isinstance(uploaded, AgentFlowFile) else 4,
            "html": 1,
            "mermaid": 2,
        },
        "uploaded_used": isinstance(uploaded, AgentFlowFile),
    }
