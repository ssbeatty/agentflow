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
| Python syntax sanity check | `python -c "import ast; ast.parse(open('<path>',encoding='utf-8').read())"` |
| Docker (app + postgres) | `docker compose pull && docker compose up -d` (pulls `ghcr.io/ssbeatty/agentflow:latest`) |
| Docker (sqlite only) | `DATABASE_URL=sqlite:////app/backend/data/agentflow.db docker compose up -d app --no-deps` |
| Docker (build from source) | `docker build -t agentflow:local . && AGENTFLOW_IMAGE=agentflow:local docker compose up -d` |
| Docker HTTPS (Traefik + Let's Encrypt) | set `DOMAIN`/`SSL_EMAIL` in `.env`, then `docker compose -f docker-compose.traefik.yml up -d` |

There is **no test suite**. Verify changes by running the backend and exercising flows through the UI or `curl`.

**CI**: `.github/workflows/docker.yml` builds the image with Buildx (`context: .`, default `Dockerfile`) and pushes to GHCR on push to `main` (→ `main` + `latest`) and on `v*` tags (→ semver tags + `latest`). `docker-compose.yml` pulls that image by default; override the tag/source with the `AGENTFLOW_IMAGE` env var. There is no CI lint/test step — keep `tsc`/`next build` green locally before pushing.

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

When you need `script_id` in the URL, use `?id=...` query (not path segment) — that's the convention `/script` and `/converse` use because static export hates dynamic paths.

### External MCP tool injection

AgentFlow can connect to external MCP servers configured in the Tools UI. `script.mcp_server_ids` selects which enabled `MCPServerConfig` records are connected for a run. The runner builds `AGENTFLOW_MCP_CONFIGS`, creates a `MultiServerMCPClient`, injects tools into `agentflow._injected_tools`, and scripts access them through `get_tools()` / `get_agent()`.

The per-server connection dict is built by **one** helper — `services/mcp_config.py::build_connection(srv, db)` — used by both the runtime injector (`execution_engine`) and the "test connection" probe, so a probe reflects exactly what a run will see.

#### Test connection / tool listing (probe)

`POST /api/mcp-servers/{id}/probe` connects to a single server and returns `{ok, tools:[{name,title,description,input_schema}], error, needs_auth}`. It runs in the **backend** process via the raw `mcp` SDK (`services/mcp_probe.py`), inside a dedicated thread with a fresh `ProactorEventLoop` so `stdio` subprocess transport works regardless of the loop debugpy installs. The MCP client SDK (`mcp`) + `httpx` are backend deps now (`requirements.txt`); `langchain-mcp-adapters` stays a per-script venv baseline. The Tools UI exposes this as a per-server **Test** button that opens a dialog listing the tools + their JSON schemas.

#### OAuth 2.0 for remote MCP servers

Servers like Todoist / Fastmail sit behind OAuth — a static `Authorization` header won't do. Because scripts run headless in subprocesses (no browser), the **backend** owns the flow (`services/mcp_oauth.py`):

- `MCPServerConfig.auth_type` = `none` | `oauth2`. `oauth_config` (JSON) caches discovered + manual endpoints and client creds; `oauth_token` (JSON) holds the live grant. **Neither is ever serialized to the frontend** — `MCPServerOut` only exposes `auth_type`, a computed `oauth_connected`, and `oauth_scope`.
- `GET .../oauth/authorize-url` discovers the auth server (RFC 9728 → RFC 8414 / OIDC), dynamically registers a client if needed (RFC 7591), generates PKCE, and returns a URL the UI opens in a popup. The `redirect_uri` is built from `settings.public_base_url` if set, else `request.base_url`. **Behind a reverse proxy you must set `PUBLIC_BASE_URL=https://host`** — otherwise the redirect_uri is the proxy's internal http URL and providers reject it at the registration step (400). The Docker image runs uvicorn with `--proxy-headers` so a proxy that sends `X-Forwarded-Proto` also fixes the scheme; `docker-compose.traefik.yml` sets `PUBLIC_BASE_URL` from `$DOMAIN`.
- `GET .../oauth/callback` exchanges the code for tokens and renders a self-closing page that `postMessage`s `{source:"agentflow-oauth", ok}` back to the opener (Tools page listens and reloads).
- `POST .../oauth/disconnect` clears the token.
- At run time `build_connection()` calls `ensure_access_token()` (refresh-if-expired) and folds the bearer into `headers["Authorization"]`, so the subprocess only ever sees a static header — no token objects crossing the `AGENTFLOW_MCP_CONFIGS` JSON boundary.
- `PATCH /api/mcp-servers/{id}` **shallow-merges** `oauth_config` so editing e.g. scope in the UI doesn't wipe the discovered endpoints / client_id.

### External secrets (credentials for user scripts)

Scripts must not hard-code API keys / tokens / webhook URLs. The `Secret` model (`secrets` table: `key`, `value`, `description`) holds them, managed via `routers/secrets.py` (admin-gated CRUD) and the `/secrets` page. Mirrors the channel/OAuth "secret never crosses to the frontend" contract:

- `SecretOut` reads `value` only to derive a computed `has_value` + masked `preview` (`Field(exclude=True)`); the raw value is **never serialized**. `SecretCreate.key` is constrained to `^[A-Za-z_][A-Za-z0-9_]*$` so the env-var mapping is unambiguous; the router also rejects keys that collide once upper-cased.
- At run time `execution_engine` loads all secrets and builds `AGENTFLOW_SECRET_<NORM(key)>` env vars (+ `AGENTFLOW_SECRET_NAMES`). These go into **`sub_env` only** — deliberately **not** passed to `_write_runner()`, so secret values are never baked into the on-disk `_runner.py` (unlike `llm_envs`, which currently are). The diagnostic log prints secret **keys**, never values.
- Scripts read them via `agentflow.get_secret("<key>")` (case-insensitive, non-alnum → `_`, same `_norm` as `get_llm`) / `list_secrets()`. Global by design — single-admin model, every script sees every secret (no per-script opt-in like `mcp_server_ids`).
- **At rest the value is plaintext in the DB** — consistent with `channels.api_key` and `oauth_token`; the DB lives on the protected data volume and is never exposed via the API. Encryption-at-rest would need a non-stdlib cipher (breaks `security.py`'s stdlib-only rule), so it's intentionally out of scope.

### Database

- `app/database.py` switches on `DATABASE_URL` (sqlite vs anything else). SQLite gets WAL pragmas + `check_same_thread=False`; everything else gets pool defaults.
- Tables are initially created via `Base.metadata.create_all` in `lifespan` (handles brand-new databases). `create_all` **will not add columns to existing tables**.
- **Migrations auto-apply on startup.** The `lifespan` runs `create_all`, then `app/db_migrate.py::run_startup_migrations(engine, fresh_db=…)`. `fresh_db` is detected **before** `create_all` (is the `scripts` table absent?):
  - **fresh DB** → every `V*.sql` is *baselined* (recorded in `schema_migrations`, **not executed**), because `create_all` already built the latest schema; re-running their `ALTER ... ADD COLUMN` would error. This also sidesteps SQLite-dialect SQL (`DATETIME`) in the `CREATE TABLE`s failing on Postgres.
  - **existing DB** → pending `V*.sql` are executed in order (create_all made any brand-new *tables*, so `CREATE TABLE IF NOT EXISTS` no-ops and only incremental `ALTER`/`CREATE INDEX` run). Fail-fast: a migration error stops startup.
  So a plain `docker compose pull && up -d` (or `F5`) self-migrates — **no manual `apply.py` step needed on deploy.**
- Schema changes are tracked in `backend/migrations/V<N>__<description>.sql` files. The migration logic lives in `app/db_migrate.py`; `migrations/apply.py` is a thin CLI wrapper over it for inspection / out-of-band runs:
  ```
  cd backend && python migrations/apply.py            # apply pending (rarely needed — startup does this)
  cd backend && python migrations/apply.py --status   # list applied/pending
  cd backend && python migrations/apply.py --dry-run  # preview without applying
  ```
  Applied versions are recorded in the `schema_migrations` table.
- **When adding a column**: write a new `V<N+1>__<description>.sql` with an `ALTER TABLE` statement (keep it idempotent-friendly: new *tables* use `CREATE TABLE IF NOT EXISTS` since `create_all` may have made them), add the matching `Column` to the model, then just restart — startup applies it. Do not drop the DB.

### Skills (reusable agent instructions + files)

A **Skill** is an [Agent Skill](https://github.com/anthropics/skills): a folder with a `SKILL.md` (YAML frontmatter `name`/`description` + markdown instructions) plus any supporting files. Skills are **global** like MCP servers (`skills` + `skill_files` tables, mirroring `scripts`/`script_files` — content lives in the DB, written to disk at run time). A script opts in via `script.skill_ids` (JSON array, AND-ed with the skill's global `enabled` flag), exactly like `mcp_server_ids`.

- **Management**: `routers/skills.py` (admin-gated CRUD + file upsert/delete, reuses `normalize_script_filename` — which already permits nested `a/b.md` paths). Creating a skill seeds a starter `SKILL.md` (`is_main=True`). The Tools page (`/tools`) lists skills; editing opens a dedicated editor page `/skill?id=…` that **reuses `FileTree` + `ScriptEditor` (Monaco)** and the same in-list upload flow as the script editor. `FileTree` renders a **collapsible folder tree** and supports **folder-preserving upload** (`webkitdirectory` picker + drag-dropped folders via `webkitGetAsEntry`, which drop the top folder name so its contents map to the skill root). Pass `showRequirements={false}` for skills so the script-only `requirements.txt` row is hidden.
- **Runtime — two ways to consume skills** (both use the same `run_dir/skills/<safe-name>/` materialization + `AGENTFLOW_SKILLS` manifest `[{name, description, dir, main}]`; `AGENTFLOW_RUN_DIR` points at the run dir):
  - `get_agent()` (default, lightweight, progressive disclosure à la deepagents): folds each skill's **name+description into the system prompt** and adds a built-in **`read_skill(name)`** tool that returns a skill's full `SKILL.md`. Built on `create_react_agent`; the agent can only read SKILL.md (supporting files reachable from script code via `skill_path`). No extra dependency.
  - `get_deep_agent()` (opt-in): builds a **deepagents** Deep Agent (`create_deep_agent`) whose `FilesystemBackend(root_dir=run_dir)` mounts `skills/`, so the agent browses+reads **every** skill file itself (SKILL.md + supporting files + nested folders) plus gets planning/sub-agents. Accepts a LangChain model instance (from `get_llm()`), so all channels work. Param names vary across deepagents versions, so it introspects `create_deep_agent`'s signature (`system_prompt` vs `instructions`, whether `backend`/`skills`/`tools` are supported). Needs the `deepagents` baseline package.
- Scripts can also read skills directly via `list_skills()` / `get_skill(name)` / `skill_path(name)`.
- Skill **install-from-repo** is intentionally out of scope for now (manual management only); `Skill.source` is reserved for it.

### Authentication & API keys

The whole management UI/API sits behind a **single admin login**; external systems call the run endpoint with **issued API keys**. There is no multi-user model — auth is a gate, not tenancy.

- **Crypto lives in one place**: `app/security.py` (stdlib only — no new deps). PBKDF2-SHA256 password hashing; admin sessions are stateless HMAC-signed `<payload>.<sig>` tokens (JWT-ish); API keys are random `af_…` tokens of which only the SHA-256 hash is stored. The signing secret comes from `SECRET_KEY` or is generated once into `data/.secret_key` (persisted via the data volume).
- **Dependencies** are in `app/auth_deps.py`: `require_admin` (session cookie **or** `Authorization: Bearer <token>`) and `require_api_key_or_admin` (admin session **or** `X-API-Key` / `Authorization: Bearer af_…`). `current_subject()` is the non-raising variant for `/auth/status`.
- **Session transport is a cookie** (`af_session`, httpOnly, SameSite=Lax, `Secure` when `COOKIE_SECURE=true`). Cookies auto-attach to `fetch`, `<img>`/file downloads **and the WebSocket handshake** on the same origin — that's why `<img>` artifacts and `/ws/*` work without manual token plumbing. WS handlers validate the cookie via `_ws_authenticated()` and close with code `4401` if invalid.
- **Wiring (`app/main.py`)**: `/api/auth/*` is public; every management router is included with `dependencies=[Depends(require_admin)]`. The **executions router is the exception** — it gates per-endpoint so `POST /api/executions/run` can use `require_api_key_or_admin` while the rest require admin. `/health` and the frontend catch-all stay public so the login page can load.
- **Routers**: `routers/auth.py` (status/setup/login/logout/change-password/me) and `routers/api_keys.py` (list / create-once / revoke). `setup` only works when no admin exists yet (first-run).
- **Frontend gate**: `components/AuthGate.tsx` wraps the app in `layout.tsx`; it calls `/api/auth/status` on every navigation and routes to `/setup` (no admin), `/login` (not authed), or through. Protected pages don't mount until authorized. `lib/api.ts::req()` bounces to `/login` on a 401 (except for `/auth/*` calls). Pages: `app/login`, `app/setup`, `app/security` (account + API key management).
- **External API usage**: `curl -X POST http://host/api/executions/run -H "X-API-Key: af_…" -H "Content-Type: application/json" -d '{"script_id":"…","input_data":{…}}'` — blocks until the script finishes and returns `{id,status,output_data,error,…}`.

### Time/timezone

Backend uses naive `datetime.utcnow()` everywhere (stored without TZ). Frontend `formatDate` / `toLocalDate` in `frontend/src/lib/utils.ts` append `Z` to TZ-less strings before parsing. **Don't change one side without the other**, or times will silently shift 8 hours.

## Conventions & contracts

- **User script entry point**: configurable per-script (`script.entry_function`, default `"run"`). Signature: `def run(input: dict) -> Any`. Return value goes into `execution.output_data`.
- **`get_llm()` resolution (channels)**: LLMs are configured as **channels** (NewAPI-style: one provider endpoint + key serving a list of models) in the `channels` table. `get_llm("<model-id>")` resolves a **model id** to `AGENTFLOW_LLM_<UPPER_ALNUM_>`; `get_llm()` reads `AGENTFLOW_LLM_DEFAULT`. `execution_engine` builds these envs by ranking enabled channels (`priority` desc, ties → earliest `created_at`) and picking, per model id, the winning channel's creds — so a model served by several channels uses the highest-priority one. The default is whichever channel set `is_default` + `default_model`. `_norm()` lives in both `agentflow/__init__.py` and `execution_engine.py` — **keep them in sync**. The legacy `llm_configs` table is auto-folded into channels on startup (`services/llm_migrate.py`, idempotent) and otherwise unused; the `/api/llm-configs` router is legacy.
- **Provider mapping** in `agentflow.get_llm`: `anthropic` → `ChatAnthropic`, `ollama` → `ChatOllama`, `deepseek` → `_ChatDeepSeekFixed` (subclass of `ChatDeepSeek` that patches `_get_request_payload` to echo `reasoning_content` back — required for DeepSeek-R1 multi-turn), everything else falls through to `ChatOpenAI` with `base_url`. Default `timeout=60`, `max_retries=1` injected via `extra.setdefault`.
- **Chat page convention**: input is `{message, history: [{role, content}]}`, output is `{reply}` (with fallbacks: `message` / `response` / `result` / stringified). Maintained client-side in `frontend/src/app/converse/page.tsx` (Open-WebUI-style: collapsible searchable sidebar, flat full-width assistant messages, hover copy/delete, stop-generation, scroll-to-bottom). The chat page also consumes `trace` WS events and renders agent internals via `AgentNarrative` — one **collapsed-by-default** "Agent 过程" block above each assistant answer that expands to the readable story of the turn: the agent's intermediate text returns rendered as markdown, each tool call as a card with args/result/status (chronological, from `buildRows`). The last LLM turn's text is excluded (`excludeLastLlmText`) since the authoritative `content` renders it as the final answer. The shared markdown renderer is `components/Markdown.tsx`. On reload it re-hydrates from the run's `_trace` logs. (`AgentTraceInline.tsx` is the older compact-timeline view, no longer wired into the chat.) The tracer (`agentflow/_tracer.py`) is global, so any `get_agent()` / LangGraph run is traced automatically — a plain `run()` that isn't a LangGraph node won't show node steps, but its tool/LLM calls still do.
- **Baseline packages** auto-installed on venv create: see `BASELINE_PACKAGES` in `venv_manager.py`. Currently: `langchain-core`, `langchain-openai`, `langchain-deepseek`, `langgraph`, `httpx`, `ddgs`, `langchain-mcp-adapters`, `nest-asyncio`, `deepagents` (powers `get_deep_agent()`). Users add more via `requirements.txt`.
- **MCP tool injection is per-script opt-in**: `script.mcp_server_ids` (JSON array of `MCPServerConfig.id`) controls which servers are connected at runtime. Empty = no MCP tools. The `enabled` flag on `MCPServerConfig` is a global availability switch (AND-ed with the per-script selection). Configure in the script's right panel.
- **Secrets & convenience helpers (`agentflow`)**: `get_secret("KEY")` / `list_secrets()` read externally-managed credentials (see *External secrets* above) — keys are case-insensitive (`_norm`, same as `get_llm`). `http_get` / `http_post` / `http_request` are **provider-agnostic** thin `httpx` wrappers (default timeout / follow-redirects / raise-for-status) returning the `httpx.Response` — they kill request boilerplate without locking the platform to any specific service. Add reusable cross-script helpers here rather than re-implementing them in each script; **keep them generic** — no per-vendor logic (e.g. Bark/Slack/Todoist) belongs in the core SDK.

## Dev gotchas

- **`--reload` orphans running scripts**: editing backend code reloads uvicorn; running script subprocesses survive (process group detached) but their DB row sticks at `running` and WS dies. When testing scripts, either stop runs first or don't use `--reload`.
- **Frontend dev on :3000 can't hit `/api`**: `next dev` doesn't proxy. For full-stack dev either (a) hit `:8000` (use the static-built frontend), or (b) add a temporary rewrite in `next.config.ts` — but remember `output: "export"` forbids rewrites in production builds.
- **Don't add LangSmith tracing** without thought — `execution_engine` defaults `LANGCHAIN_TRACING_V2=false` / `LANGSMITH_TRACING=false` in sub_env to avoid surprise network calls and slow cold imports.

## Common edit hot-spots

| Task | File(s) |
|---|---|
| Add/modify DB columns | `backend/migrations/V<N>__<desc>.sql` + model `Column`, then restart (startup auto-migrates; `python migrations/apply.py` for manual/out-of-band) |
| Migration runner (startup auto-apply + CLI share this) | `backend/app/db_migrate.py` (wired in `app/main.py` lifespan; CLI wrapper `migrations/apply.py`) |
| New API endpoint | `backend/app/routers/*.py` + register in `app/main.py` |
| Change how user scripts get env / sys.path | `services/execution_engine.py::_write_runner` |
| Change venv tooling (uv/pip) | `services/venv_manager.py` |
| Change user-facing tool API (`get_tools`, `get_agent`, etc.) | `backend/agentflow/__init__.py` |
| Add LLM provider branch | `backend/agentflow/__init__.py::get_llm` |
| Add/remove baseline venv packages | `services/venv_manager.py::BASELINE_PACKAGES` |
| New page in UI | `frontend/src/app/<name>/page.tsx` (link from `app/page.tsx` navbar) |
| Resizable panel | `useResizable` from `frontend/src/components/Splitter.tsx` |
| Log rendering | `frontend/src/components/LogPanel.tsx` (uses `toLocalDate`) |
| Script creation templates | `frontend/src/components/CreateScriptDialog.tsx::TEMPLATES` |
| External MCP server CRUD UI | `frontend/src/app/tools/page.tsx` |
| MCP connection probe / tool listing | `services/mcp_probe.py` + `routers/mcp_servers.py::probe_server_endpoint` |
| MCP OAuth flow (discovery/DCR/PKCE/refresh) | `services/mcp_oauth.py` + `routers/mcp_servers.py` oauth endpoints |
| MCP per-server connection dict (runtime + probe) | `services/mcp_config.py::build_connection` |
| LLM channels CRUD / priority / default | `backend/app/routers/channels.py` + `app/models.py::Channel` |
| LLM model auto-fetch (Settings "Load models") | `services/llm_models.py` + `routers/channels.py::list_provider_models` |
| LLM Settings UI (channel cards, model multi-select, default) | `frontend/src/app/settings/page.tsx` |
| Legacy llm_configs → channels migration | `services/llm_migrate.py` (runs in `app/main.py` lifespan) |
| Chat page agent process (collapsible: text + tool cards) | `frontend/src/components/AgentNarrative.tsx` + shared `components/Markdown.tsx` |
| Auth crypto (passwords / session tokens / API keys) | `backend/app/security.py` (stdlib only) |
| Auth dependencies (require_admin / api-key) | `backend/app/auth_deps.py` |
| Auth & API-key endpoints | `backend/app/routers/auth.py` + `routers/api_keys.py` |
| Gate a router behind admin login | `app/main.py` include_router `dependencies=[Depends(require_admin)]` |
| Frontend login wall / login / setup / security pages | `frontend/src/components/AuthGate.tsx` + `app/login` + `app/setup` + `app/security` |
| Secret store (model / schema / CRUD) | `app/models.py::Secret` + `schemas.py` (`Secret*`) + `routers/secrets.py` + `V8__secrets.sql` |
| Secret injection into user scripts | `services/execution_engine.py` (`secret_envs` → `sub_env`) |
| Script-facing secret / HTTP helpers | `backend/agentflow/__init__.py::get_secret` / `list_secrets` / `http_get` / `http_post` |
| Secrets management UI | `frontend/src/app/secrets/page.tsx` (+ navbar link in `app/page.tsx`) |
| Skill store (model / schema / CRUD) | `app/models.py::Skill`/`SkillFile` + `schemas.py` (`Skill*`) + `routers/skills.py` + `V9__skills.sql` |
| Skill materialization + manifest into runs | `services/execution_engine.py` (`AGENTFLOW_SKILLS`, `_safe_skill_dirname`) |
| Script-facing skill API + `read_skill` tool | `backend/agentflow/__init__.py::list_skills`/`get_skill`/`_make_skill_tool` (wired in `get_agent`) |
| Deep-agent skill loading (deepagents FilesystemBackend) | `backend/agentflow/__init__.py::get_deep_agent`/`_skills_root` (needs `deepagents` baseline pkg) |
| Skills list + create | `frontend/src/app/tools/page.tsx` (Skills section) |
| Skill editor (FileTree + Monaco + upload) | `frontend/src/app/skill/page.tsx` |
| Bind skills to a script | `frontend/src/app/script/page.tsx` (`selectedSkillIds`) + `script.skill_ids` |
