# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AgentFlow — a self-hosted platform for writing/running LangGraph/LangChain Python scripts in the browser. FastAPI backend + Next.js frontend (static export, served by FastAPI). Each user script gets its own isolated venv.

## Commands

| Goal | Command |
|---|---|
| Full dev (VS Code) | `F5` — builds frontend then starts backend with debugpy |
| Backend dev (reload) | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Backend prod | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Frontend dev (hot reload, :3000) | `cd frontend && npm run dev` |
| Frontend build (produces `out/` consumed by backend) | `cd frontend && npm run build` |
| Type-check frontend | `cd frontend && npx tsc --noEmit` |
| MCP URL endpoint | `cd backend && uvicorn app.main:app --port 8000` then connect to `http://localhost:8000/mcp/` |
| Python syntax sanity check | `python -c "import ast; ast.parse(open('<path>',encoding='utf-8').read())"` |
| Docker (app + postgres) | `docker compose up -d --build` |
| Docker (sqlite only) | `docker compose up -d app --no-deps` |

There is **no test suite**. Verify changes by running the backend and exercising flows through the UI or `curl`.

## Architecture you must know

### Two Python runtimes — keep them straight

1. **Backend Python** in `backend/.venv` runs FastAPI/SQLAlchemy/APScheduler.
2. **User script Python** in `backend/data/scripts/<id>/.venv` runs whatever the user wrote.

`backend/agentflow/__init__.py` is imported by user scripts, NOT by backend. The runner adds `BACKEND_ROOT` to `sys.path` so user-script venvs can `from agentflow import …` without installing it. Don't add agentflow to `requirements.txt`.

### Subprocess plumbing (the part with sharp edges)

`services/execution_engine.py` and `services/venv_manager.py` deliberately avoid `asyncio.create_subprocess_exec`. Use sync `subprocess.Popen` + background thread + `asyncio.Queue` + `loop.call_soon_threadsafe`. Reasons (do not "fix" them):

- Windows `SelectorEventLoop` (debugpy injects this) raises `NotImplementedError` on `asyncio.subprocess_exec`.
- Pip progress bars emit `\r` (no `\n`) — we hand-split on both.
- `_clean_env()` in `venv_manager.py` strips `PYTHONPATH` / `PYTHONHOME` / `VIRTUAL_ENV` / `PYDEVD_*` / `DEBUGPY_*` / `PYCHARM_*`. **Never replace with `os.environ.copy()`** — debugpy infects user venvs that don't have it installed.
- User-script subprocesses use `CREATE_NEW_PROCESS_GROUP` on Windows so CTRL_C from `uvicorn --reload` doesn't kill them.
- `launch.json` sets `"subProcess": false` because debugpy 2026+ monkey-patches `subprocess.Popen` to inject pydevd into child pythons. Don't re-enable it.

### Runner protocol

`_write_runner()` in `execution_engine.py` generates a tiny `_runner_<execution_id>.py` that wraps the user's entry function. User code communicates with the platform via lines prefixed with `__AGENTFLOW__<json>` on stdout. Anything else is captured as `raw` / `error` log level.

The runner is **fully async** (`asyncio.run(_main())`). `nest_asyncio` is applied at startup so sync `agent.invoke()` can call `asyncio.get_event_loop().run_until_complete()` internally (needed for async MCP tools wrapped by `_ensure_sync()` in `agentflow.get_tools`). Third-party loggers (`mcp`, `httpx`, `openai`, etc.) are silenced to `WARNING` to prevent INFO lines appearing as `[ERR]` in the log panel.

MCP servers are connected via `MultiServerMCPClient` (no async context manager — removed in `langchain-mcp-adapters` 0.1.0; use `client = MultiServerMCPClient(...); tools = await client.get_tools()` instead). Injected tools are stored in `agentflow._injected_tools` before user code runs. Async-only MCP tools (`StructuredTool` with `coroutine` but no `func`) are wrapped by `_ensure_sync()` in `agentflow.get_tools()` so sync `agent.invoke()` works.

### WebSocket with replay buffer

`_WsManager` in `execution_engine.py` buffers every event per `execution_id`. WS clients connecting **after** a run started still get the full history via replay (`connect()` sends buffered then subscribes). Buffers are dropped 5 minutes after the run ends.

### Frontend ↔ Backend routing

Frontend is `output: "export"` (next.config.ts). `backend/app/main.py` has a catch-all that serves `frontend/out/`. Real routes are `/api/*` and `/ws/*`. The previous `frontend/src/app/api/[...path]/route.ts` proxy was removed — don't reintroduce it; the static export can't have route handlers.

When you need `script_id` in the URL, use `?id=...` query (not path segment) — that's the convention `/script` and `/chat` use because static export hates dynamic paths.

### MCP server

`backend/app/mcp_server.py` defines the AgentFlow MCP server. FastAPI mounts it at `/mcp/` when `MCP_ENABLED=true` (`/mcp` redirects there). The intended client entry is URL-based Streamable HTTP: `http://localhost:8000/mcp/`. It exposes high-trust tools that can create/update/delete scripts, manage venvs, execute user code, and read logs, so don't bypass `services.execution_engine`, `services.venv_manager`, or `services.script_files` when changing it.

`MCP_AUTH_TOKEN` is optional. When non-empty, HTTP `/mcp/` requests must send `Authorization: Bearer <token>`.

### Database

- `app/database.py` switches on `DATABASE_URL` (sqlite vs anything else). SQLite gets WAL pragmas + `check_same_thread=False`; everything else gets pool defaults.
- Tables are created via `Base.metadata.create_all` in `lifespan`. **No Alembic / migrations.** When you add a column, run `ALTER TABLE <table> ADD COLUMN <col> <type> DEFAULT <val>` by hand (prefer this over dropping the DB to avoid losing data). `create_all` will not add columns to existing tables.

### Time/timezone

Backend uses naive `datetime.utcnow()` everywhere (stored without TZ). Frontend `formatDate` / `toLocalDate` in `frontend/src/lib/utils.ts` append `Z` to TZ-less strings before parsing. **Don't change one side without the other**, or times will silently shift 8 hours.

## Conventions & contracts

- **User script entry point**: configurable per-script (`script.entry_function`, default `"run"`). Signature: `def run(input: dict) -> Any`. Return value goes into `execution.output_data`.
- **`get_llm()` resolution**: reads `AGENTFLOW_LLM_DEFAULT` env (set when `is_default=True`). `get_llm("name")` normalises name to `AGENTFLOW_LLM_<UPPER_ALNUM_>` — see `_norm()` in both `agentflow/__init__.py` and `execution_engine.py`; **keep them in sync**.
- **Provider mapping** in `agentflow.get_llm`: `anthropic` → `ChatAnthropic`, `ollama` → `ChatOllama`, `deepseek` → `_ChatDeepSeekFixed` (subclass of `ChatDeepSeek` that patches `_get_request_payload` to echo `reasoning_content` back — required for DeepSeek-R1 multi-turn), everything else falls through to `ChatOpenAI` with `base_url`. Default `timeout=60`, `max_retries=1` injected via `extra.setdefault`.
- **Chat page convention**: input is `{message, history: [{role, content}]}`, output is `{reply}` (with fallbacks: `message` / `response` / `result` / stringified). Maintained client-side in `frontend/src/app/chat/page.tsx`.
- **Baseline packages** auto-installed on venv create: see `BASELINE_PACKAGES` in `venv_manager.py`. Currently: `langchain-core`, `langchain-openai`, `langchain-deepseek`, `langgraph`, `httpx`, `ddgs`, `langchain-mcp-adapters`, `nest-asyncio`. Users add more via `requirements.txt`.
- **MCP tool injection is per-script opt-in**: `script.mcp_server_ids` (JSON array of `MCPServerConfig.id`) controls which servers are connected at runtime. Empty = no MCP tools. The `enabled` flag on `MCPServerConfig` is a global availability switch (AND-ed with the per-script selection). Configure in the script's right panel.

## Dev gotchas

- **`--reload` orphans running scripts**: editing backend code reloads uvicorn; running script subprocesses survive (process group detached) but their DB row sticks at `running` and WS dies. When testing scripts, either stop runs first or don't use `--reload`.
- **Frontend dev on :3000 can't hit `/api`**: `next dev` doesn't proxy. For full-stack dev either (a) hit `:8000` (use the static-built frontend), or (b) add a temporary rewrite in `next.config.ts` — but remember `output: "export"` forbids rewrites in production builds.
- **Don't add LangSmith tracing** without thought — `execution_engine` defaults `LANGCHAIN_TRACING_V2=false` / `LANGSMITH_TRACING=false` in sub_env to avoid surprise network calls and slow cold imports.

## Common edit hot-spots

| Task | File(s) |
|---|---|
| New API endpoint | `backend/app/routers/*.py` + register in `app/main.py` |
| Change how user scripts get env / sys.path | `services/execution_engine.py::_write_runner` |
| Change venv tooling (uv/pip) | `services/venv_manager.py` |
| Change MCP tools/resources (AgentFlow's own MCP server) | `backend/app/mcp_server.py` |
| Change user-facing tool API (`get_tools`, `get_agent`, etc.) | `backend/agentflow/__init__.py` |
| Add LLM provider branch | `backend/agentflow/__init__.py::get_llm` |
| Add/remove baseline venv packages | `services/venv_manager.py::BASELINE_PACKAGES` |
| New page in UI | `frontend/src/app/<name>/page.tsx` (link from `app/page.tsx` navbar) |
| Resizable panel | `useResizable` from `frontend/src/components/Splitter.tsx` |
| Log rendering | `frontend/src/components/LogPanel.tsx` (uses `toLocalDate`) |
| Script creation templates | `frontend/src/components/CreateScriptDialog.tsx::TEMPLATES` |
| MCP server CRUD UI | `frontend/src/app/tools/page.tsx` |
