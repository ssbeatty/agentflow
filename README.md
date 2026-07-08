<div align="center">

# AgentFlow

**Write LangGraph / LangChain agents in your browser. Run them as a service.**

[![CI](https://github.com/ssbeatty/agentflow/actions/workflows/test.yml/badge.svg)](https://github.com/ssbeatty/agentflow/actions/workflows/test.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-ssbeatty%2Fagentflow-blue?logo=docker)](https://github.com/ssbeatty/agentflow/pkgs/container/agentflow)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

English | [简体中文](README.zh-CN.md)

</div>

AgentFlow is a **self-hosted home for your agent code**. You write a plain Python `run(input)` function — real code, real `pip` dependencies, real stack traces — and one Docker image turns it into an operable service: isolated per-script venvs, live logs and agent traces, a chat UI, cron scheduling, an HTTP API with webhooks, per-run token accounting, regression evals, and MCP in both directions.

No per-node metering. No seat fees. No lock-in. `docker compose up` and it's yours.

<p align="center">
  <img src="docs/images/dashboard.png" alt="AgentFlow dashboard" width="900">
</p>

---

## Why AgentFlow?

**Visual flow builders hit a ceiling.** Drag-and-drop platforms are great for the first 80% — then the canvas turns to spaghetti, the sandboxed "code node" won't import the library you need, and the error says `Node execution failed`. In AgentFlow the script *is* the product: multi-file Python projects, any dependency via `requirements.txt` in an isolated venv, full tracebacks persisted to the run log, and an automatic revision snapshot on every save.

**LangGraph is a library, not a service.** It gives you a graph — not a scheduler, a run API, a logs UI, secrets, or evals. Hosted agent platforms fill that gap with per-node metering and enterprise contracts. AgentFlow fills it with a single free container on your own machine.

**Your coding agent can drive it.** AgentFlow exposes an MCP endpoint, so Claude Code / Cursor can connect and create, edit, run, debug, and eval scripts remotely — *develop with your coding agent, run on AgentFlow*. Flow-builder JSON is opaque to coding agents; Python is their native tongue.

---

## Features

| | |
|---|---|
| 🐍 **Browser IDE** | Monaco editor, multi-file scripts, Python lint on save, drag-and-drop upload |
| 📦 **Isolated venvs** | One environment per script, langchain / langgraph stack preinstalled, `uv`-accelerated |
| 🔌 **Any LLM** | OpenAI / Anthropic / DeepSeek / Ollama / any OpenAI-compatible gateway — configure once, `get_llm()` anywhere |
| ▶️ **Run & observe** | Live WebSocket logs (with replay), agent trace view of every LLM turn and tool call, Output / Flow / Artifacts panels, full run history |
| 📊 **Cost visibility** | Token usage recorded per run, 7-day trend and top-spending scripts on the dashboard, Prometheus `/metrics` |
| 🧪 **Evals & regression** | Per-script test datasets (contains / regex / LLM-as-judge assertions), pass-rate deltas vs the previous run, pinned to script revisions |
| 💬 **Built-in chat UI** | Any script becomes a streaming chat app — markdown, collapsible reasoning, tool-call trace, embeddable |
| 🔧 **MCP & 🧩 Agent Skills** | Consume external MCP servers (with OAuth), install [Agent Skills](https://github.com/anthropics/skills) from a built-in marketplace, opt in per script |
| ⏰ **Scheduling** | Cron triggers with timezone control, saved input presets |
| 🌐 **HTTP API + webhooks** | Sync `POST /run`, or async `wait=false` with a completion callback; poll by execution id — all via issued API keys |
| 🔔 **Failure alerts** | PushPlus / Bark / email when a scheduled run dies at 3am |
| 🤖 **AI in the loop** | Built-in script assistant writes and edits scripts with diff review + one-click revert; outward MCP gateway for Claude Code / Cursor |
| 🔐 **Auth** | Single-admin login for the console, hashed API keys for machines |
| 🗄️ **Any database** | SQLite (zero-dep default) / Postgres / MySQL — switch with one env var, schema migrates itself |

---

## Quickstart (5 minutes)

### Option 1 · Docker (recommended)

Pull the CI-built image `ghcr.io/ssbeatty/agentflow:latest`:

```bash
cp .env.example .env      # set POSTGRES_PASSWORD, or go SQLite-only (below)
docker compose pull
docker compose up -d
```

Open <http://localhost:8000> → the first visit walks you through **creating the admin account** — and you're in.

<p align="center">
  <img src="docs/images/setup.png" alt="First-run setup — create the admin account" width="440">
</p>

> **Even lighter?** Skip Postgres and use the embedded SQLite:
> ```bash
> DATABASE_URL=sqlite:////app/backend/data/agentflow.db docker compose up -d app --no-deps
> ```
> **Pin a version / build from source?**
> ```bash
> AGENTFLOW_IMAGE=ghcr.io/ssbeatty/agentflow:v1.2.3 docker compose up -d
> docker build -t agentflow:local . && AGENTFLOW_IMAGE=agentflow:local docker compose up -d
> ```

### Option 2 · HTTPS with automatic certificates (Traefik)

The easiest public deployment: Traefik terminates TLS, fetches Let's Encrypt certificates, and redirects `80 → 443`.

**Prerequisites**: a domain with an A record pointing at the host, ports `80`/`443` open.

Create `.env` with **just two lines**:

```env
DOMAIN=agentflow.example.com
SSL_EMAIL=you@example.com
```

Then:

```bash
docker compose -f docker-compose.traefik.yml up -d
```

Open `https://your-domain`, create the admin account, done. Traefik wiring sets `PUBLIC_BASE_URL` / `COOKIE_SECURE` / `CORS_ORIGINS` for you, so login cookies and MCP OAuth work over HTTPS out of the box.

> 🔒 **For real production** also set `SECRET_KEY=<random string>` (sessions survive restarts/replicas) and a strong `POSTGRES_PASSWORD`.
> 🧭 **Using your own reverse proxy** (Nginx / Caddy)? Set `PUBLIC_BASE_URL=https://your-domain` yourself, or MCP OAuth callbacks will be built from the internal http address and rejected.

### Option 3 · Local development

Needs Python 3.12+ and Node 20+:

```bash
# backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# in another terminal — frontend dev server (hot reload, :3000)
cd frontend
npm install
npm run dev
```

> VS Code users: just press `F5` — it builds the frontend and starts the backend with debugpy attached.

---

## A tour of the UI

<table>
  <tr>
    <td width="50%">
      <b>① Write scripts</b> — start from a template: ReAct agent / streaming chat / deep agent / LangGraph loop…<br>
      <img src="docs/images/new-script.png" alt="New script dialog with templates">
    </td>
    <td width="50%">
      <b>② Edit & run</b> — Monaco editor, config panel on the right, Logs / Output / Flow tabs below.<br>
      <img src="docs/images/editor.png" alt="Script editor">
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>③ Chat with your agent</b> — pick a script and talk to it; markdown rendering, collapsible reasoning.<br>
      <img src="docs/images/chat.png" alt="Built-in chat page">
    </td>
    <td width="50%">
      <b>④ Connect LLMs</b> — one channel = one provider endpoint + a set of models, picked by priority.<br>
      <img src="docs/images/settings.png" alt="LLM channel settings">
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>⑤ Tools & skills</b> — built-in web search, external MCP servers, installable Agent Skills.<br>
      <img src="docs/images/tools.png" alt="Tools / MCP / Skills">
    </td>
    <td width="50%">
      <b>⑥ External API</b> — call scripts over HTTP, or let Claude Code / Cursor develop through MCP.<br>
      <img src="docs/images/api-docs.png" alt="API reference page">
    </td>
  </tr>
</table>

---

## Your first script

Click **New Script** → pick a template (or blank) → what you edit is just a `run(input)` function:

```python
from agentflow import log, get_llm

def run(input: dict) -> dict:
    msg = input.get("message", "hello")
    log("received", data={"msg": msg}, step="recv")

    llm = get_llm()                 # default model of the default channel
    if llm is None:
        return {"reply": "No LLM configured yet — add a channel in Settings."}

    resp = llm.invoke(f"Repeat this in uppercase: {msg}")
    return {"reply": resp.content}
```

Hit **Create venv** in the right panel (installs the baseline stack), then **Run**. Logs and the return value stream into the bottom panels live.

> The entry point defaults to `run` with signature `def run(input: dict) -> Any`; the return value becomes the execution's output. Both are configurable per script.

### An agent with tools

`get_agent()` returns a ReAct agent pre-wired with the built-in tools (web search / fetch) plus whatever MCP servers and skills you've enabled for the script:

```python
from agentflow import get_agent

def run(input: dict) -> dict:
    agent = get_agent(system_prompt="You are a research assistant. Use web_search and cite sources.")
    result = agent.invoke({"messages": [("human", input["question"])]})
    return {"answer": result["messages"][-1].content}
```

### A LangGraph example

```python
from typing import TypedDict
from agentflow import get_llm
from langgraph.graph import StateGraph, END

class State(TypedDict):
    count: int

def tick(s): return {"count": s["count"] + 1}
def cond(s): return "loop" if s["count"] < 3 else "done"

def build():
    g = StateGraph(State)
    g.add_node("tick", tick)
    g.set_entry_point("tick")
    g.add_conditional_edges("tick", cond, {"loop": "tick", "done": END})
    return g.compile()

def run(input):
    return build().invoke({"count": 0})
```

The SDK in one breath: `log()` for structured logs, `get_llm()` / `get_agent()` / `get_deep_agent()` for models and agents, `get_tools()` for the tool list, `get_secret()` for credentials, `web_search()` / `web_fetch()` for the internet, `markdown()` / `table()` / `image()` to render rich cards in chat, and a module-level `INPUT_SCHEMA` to give `run()` a typed, validated input with an auto-generated form. The full reference lives on the in-app `/docs` page.

---

## Develop with Claude Code, run on AgentFlow

AgentFlow serves its own MCP endpoint. Point a coding agent at it and the whole write → run → debug → eval loop happens remotely — the agent creates scripts, edits files (with lint feedback), builds venvs, runs executions, reads tracebacks, and adds graded eval cases:

```bash
claude mcp add --transport http agentflow http://localhost:8000/mcp --header "X-API-Key: af_…"
```

There's also a companion [Agent Skill](https://github.com/anthropics/skills) that teaches the agent AgentFlow's scripting conventions — download it from `GET /mcp/skill` or let the agent call the `get_scripting_guide` tool. And if you'd rather stay in the browser: the built-in AI assistant writes and edits scripts for you, with per-file diff review and one-click revert.

---

## Connect an LLM

Go to **Settings → Add channel**. A *channel* is one provider endpoint (key + base_url) serving a set of models; scripts fetch models by id with `get_llm("<model-id>")`, or `get_llm()` for the default. If several channels serve the same model, the highest-priority one wins.

| Provider | `provider` | `base_url` example |
|---|---|---|
| OpenAI | `openai` | *(leave empty)* |
| Anthropic | `anthropic` | — |
| DeepSeek | `openai` | `https://api.deepseek.com/v1` |
| Moonshot / Kimi | `openai` | `https://api.moonshot.cn/v1` |
| Zhipu / GLM | `openai` | `https://open.bigmodel.cn/api/paas/v4` |
| Ollama | `ollama` | `http://localhost:11434` |

Most gateways speak the OpenAI-compatible protocol — pick `openai` and fill in `base_url` (`anthropic` / `ollama` have dedicated integrations). The ⭐-starred model on a channel card is what `get_llm()` returns by default.

---

## Auth & the external API

The entire console (all pages + `/api/*` management endpoints) sits behind the **admin login**. The first visit routes to admin creation; passwords are PBKDF2-hashed, sessions ride an httpOnly cookie. Change the password / issue API keys under 🛡️ **Security** in the navbar.

**Call a script from an external system** — API key, no login:

```bash
curl -X POST 'http://localhost:8000/api/executions/run?timeout=120' \
  -H 'X-API-Key: af_xxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{"script_id":"<script UUID>","input_data":{"message":"hi"}}'
# blocks until the run finishes, returns {id,status,output_data,error,...}
```

Copy `script_id` from the 📋 button in the editor header. API keys are shown **once**; only a hash is stored — if you lose one, issue a new one.

**Long task? Don't hold the connection — submit async + webhook.** Add `wait=false` to get the execution `id` back immediately; pass a `callback_url` and the final result is `POST`ed to you on any terminal state (success or failure):

```bash
curl -X POST 'http://localhost:8000/api/executions/run?wait=false' \
  -H 'X-API-Key: af_xxxxxxxx' -H 'Content-Type: application/json' \
  -d '{"script_id":"<UUID>","input_data":{...},"callback_url":"https://your-service/hook"}'
# returns immediately: {"id":"...","status":"queued",...}
```

You can also poll `GET /api/executions/{id}` with the same key. The callback body is `{id,script_id,status,output_data,error,started_at,finished_at,retry_count,total_tokens}`; delivery is best-effort (a few retries, never affects the run itself).

> For HTTPS deployments set `COOKIE_SECURE=true`; for multi-replica setups set an explicit `SECRET_KEY` (otherwise sessions won't be shared across replicas).

---

## Database

One env var, no code changes:

```bash
DATABASE_URL=sqlite:///./data/agentflow.db                              # SQLite (default, zero deps)
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname           # Postgres
DATABASE_URL=mysql+pymysql://user:pass@host/dbname                      # MySQL (uncomment pymysql in requirements)
```

The schema is owned by **Alembic** and auto-migrates on startup (`upgrade head`, sqlite and postgres alike). Old databases — even partially-migrated ones — are healed and adopted automatically.

---

## Configuration reference

Set via environment variables / `.env`:

| key | default | what it does |
|---|---|---|
| `DATABASE_URL` | local sqlite file | SQLAlchemy URL |
| `DATA_DIR` | `./data/scripts` | where per-script venvs live |
| `CORS_ORIGINS` | `*` | comma-separated allowed origins, or `*` |
| `APP_PORT` | `8000` | docker-compose only |
| `SECRET_KEY` | generated into `data/.secret_key` | signs login cookies; set explicitly for multi-replica |
| `SESSION_TTL_HOURS` | `168` | login session lifetime (hours) |
| `COOKIE_SECURE` | `false` | set `true` behind HTTPS |
| `PUBLIC_BASE_URL` | *(request URL)* | **required behind a non-Traefik reverse proxy**, e.g. `https://your-domain`; used for MCP OAuth callbacks |
| `DOMAIN` / `SSL_EMAIL` | — | `docker-compose.traefik.yml` only: domain + Let's Encrypt email |
| `POSTGRES_PASSWORD` | `agentflow` | change it when using Postgres |
| `SCHEDULER_TIMEZONE` | *(host local zone)* | IANA name (e.g. `Asia/Shanghai`) that cron expressions are interpreted in |
| `AGENTFLOW_MAX_CONCURRENT` | `5` | max concurrently running executions |
| `AGENTFLOW_WARM_WORKERS` | off | opt-in warm worker pool — keeps a per-script interpreter alive so repeat runs skip the cold import |
| `AGENTFLOW_METRICS_PUBLIC` / `AGENTFLOW_METRICS_TOKEN` | off | open up `GET /metrics` for a trusted-network Prometheus, or give it a dedicated scrape token |
| `LOG_LEVEL` | `INFO` | backend operational log level |

---

## Architecture at a glance

```
┌─────────────────────────────────────────────┐
│  Next.js frontend (static export,           │
│  served by FastAPI)                         │
│  dashboard · editor · chat · tools · docs   │
└───────────────────┬─────────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼─────────────────────────┐
│  FastAPI (uvicorn)                          │
│  scripts / executions / channels / cron /   │
│  mcp-servers / skills / ws log streams …    │
└───────┬──────────────────┬──────────────────┘
        │                  │
   ┌────▼─────┐      ┌─────▼──────────────────┐
   │ Database │      │ subprocess.Popen        │
   │ (SQL*)   │      │ per-script .venv python │
   └──────────┘      │ + thread queue → live WS│
                     └─────────────────────────┘
```

- Every run forks a python subprocess inside the script's own venv — dependency isolation by construction
- Subprocess stdout / structured events flow through a background thread → asyncio queue → WebSocket, live
- Restarting the backend doesn't kill running scripts (detached process groups)

Deeper internals — the two-Python-runtimes split, subprocess plumbing, migration strategy — are documented in [`CLAUDE.md`](CLAUDE.md) at the repo root.

---

## FAQ

**Venv creation is slow?** The image ships `uv` and prefers it over pip (~10× faster); without uv it falls back to `python -m venv` + `pip`.

**`NotImplementedError: subprocess` on Windows?** Already routed around — the engine uses sync `subprocess.Popen` + thread queues instead of asyncio subprocesses. You shouldn't hit this.

**Edited backend code and a run is stuck at `running`?** Dev-mode `--reload` restarts the backend; the subprocess survives but its DB row may stay `running`. Don't use `--reload` while testing scripts, or hit Stop in the UI first.

**Slow networks?** Slow pip → set `PIP_INDEX_URL` to a nearby mirror on the container. Slow LLM calls → add `{"timeout": 120}` to the channel's `extra_config`.

---

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15 / React 19 / TailwindCSS 4 / shadcn-style UI / Monaco Editor |
| Backend | FastAPI / SQLAlchemy 2 / Alembic / APScheduler / pydantic-settings |
| Agent SDK | LangChain / LangGraph / deepagents / langchain-mcp-adapters |
| Packaging | uv (pip fallback) |
| Database | SQLite / Postgres / MySQL |

---

## Honest limits & roadmap

AgentFlow is built for **single-machine, single-admin / small-team self-hosting** — one person or one group, one box, all their agent scripts gathered in one operable place. To keep the "write a `run()` function and it's live" simplicity, some dimensions are *deliberately* not built heavy. Here is the honest map of where the edges are, so you can judge the fit yourself.

### Known limitations

| Dimension | Today | Why / impact |
|---|---|---|
| **Horizontal scaling** | Single-machine by design: execution is a local `subprocess.Popen`, venvs live on local disk, concurrency is an in-process semaphore; cron (APScheduler), the warm worker pool, and WS replay buffers are all in-process. | **Scales up (bigger box), not out.** Multiple replicas would double-fire cron and can't share load. Clustering needs the execution layer split into workers + an external queue (see roadmap). |
| **Isolation strength** | The main-path sandbox (rlimits + bubblewrap) is **defense-in-depth, best-effort**: POSIX-only, and it degrades silently to no isolation on Windows or where the kernel blocks unprivileged namespaces. Network and env vars are deliberately *not* isolated (scripts need their own keys and the internet). | Stops "one script OOMs the host / reads another script's files" — but it is **not a hard multi-tenant boundary** and doesn't replace containers / gVisor / a VM per run. Pair it with the single-admin trust model. |
| **Trust model** | Single admin + issued API keys. No multi-user, RBAC, or tenancy. Secrets are global — every script can read every secret. | Right for "me / my small team"; wrong for running mutually-untrusted tenants on one instance. |
| **Secrets at rest** | `Secret.value`, channel `api_key`s, and OAuth tokens are **plaintext in the DB** (stdlib-only crypto constraint; the data volume is the protection boundary). | No at-rest encryption / KMS / Vault. A leaked database is a leaked keyring. |
| **Quotas & rate limits** | API keys have no rate limits, token budgets, or per-script scopes (one key gets full script CRUD + run via `/mcp`). Runs are bounded only by wall-clock timeout + memory rlimit. | A runaway script can burn API budget; a leaked key has a wide blast radius. |
| **Observability depth** | Per-run token usage, structured logs, loguru ops log, failure notification channels, and a Prometheus `/metrics` endpoint are built in — but there's **no distributed tracing / OTel export** and no fine-grained alerting rules. | Plenty for single-box self-checks; wiring into an existing tracing stack needs your own exporter. |
| **Disk / venvs** | One full venv per script (hundreds of MB), no shared base layer; baseline upgrades don't retrofit existing venvs; disk is reclaimed only on delete / retention pruning. | Disk grows with script count; cold starts re-import the whole langchain stack (the opt-in warm worker pool eliminates this from run #2). |
| **Frontend tests** | The backend has a pytest regression suite; **the frontend has no automated tests**, and static export means no server routes/middleware. | UI regressions are caught by hand. |

### Roadmap

Grouped by whether the architecture has to move. High-value, low-cost first — issues and votes welcome.

**Near-term · incremental (no architecture change)**

- [x] **Async external API** — `/run?wait=false` returns the execution id immediately + optional `callback_url` completion webhook ✅
- [x] **Metrics export** — Prometheus `GET /metrics`: runs, latency, tokens, failure rates, queue depth ✅
- [ ] **API-key scopes & quotas** — per-key script allowlists / rate limits / token budgets; separately toggleable `/mcp` write access
- [ ] **Secret encryption at rest** — optional `ENCRYPTION_KEY` to encrypt secrets / channel keys / OAuth tokens before they hit the DB
- [ ] **Script export / import** — zip bundles (files + requirements + input schema + eval cases) for backup, sharing, and Git-friendly workflows
- [ ] **Venv slimming** — shared baseline layer / cache to cut disk and cold-start cost

**Long-term · architectural**

- [ ] **Horizontal scaling** — split execution into standalone workers + an external queue (Redis / Celery-style), distributed-lock scheduling, WS replay in Redis
- [ ] **Harder isolation** — container / gVisor / microVM per run, optional per-script network egress policies
- [ ] **Multi-user / RBAC** — from single-admin gate to teams + roles + per-user scripts + audit log
- [ ] **Frontend tests** — Playwright e2e for the critical flows

**Explicit non-goals** (positioning, not neglect)

- **No Airflow / Dify-scale DAG orchestration** — the mental model stays "one `run()` function, running"
- **No standalone pip package for the `agentflow` SDK** — it's injected via `sys.path` by the runner and versions with the platform on purpose
- **No hard network isolation on the main execution path** — scripts legitimately need their LLMs, MCP servers, and your own APIs

---

## License

[MIT](LICENSE)
