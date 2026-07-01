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

**cwd & where the user's files live**: the subprocess runs with `cwd = run_dir` (`script_dir/runs/<execution_id>/`, per-execution & isolated). The user's own files (from `script.files`) are written to **both** `script_dir` (for `import`/venv/persistence — the runner adds `script_dir` to `sys.path` and imports `main.py` from there) **and** `run_dir` (so intuitive relative reads like `open("data.txt")` just work against the cwd). run_dir is ephemeral per run, so anything the script writes stays out of the source tree; runtime files (`_runner.py`/`_input.json`/`skills/`) are written after the user files and win on any name clash. Paths are also exposed via env: `AGENTFLOW_RUN_DIR` (cwd), `AGENTFLOW_WORKSPACE_DIR` (persistent shared `script_dir/workspace`), `AGENTFLOW_SCRIPT_DIR`.

The runner is **fully async** (`asyncio.run(_main())`). `nest_asyncio` is applied at startup so sync `agent.invoke()` can call `asyncio.get_event_loop().run_until_complete()` internally (needed for async MCP tools wrapped by `_ensure_sync()` in `agentflow.get_tools`). Third-party loggers (`mcp`, `httpx`, `openai`, etc.) are silenced to `WARNING` to prevent INFO lines appearing as `[ERR]` in the log panel.

MCP servers are connected via `MultiServerMCPClient` (no async context manager — removed in `langchain-mcp-adapters` 0.1.0; use `client = MultiServerMCPClient(...); tools = await client.get_tools()` instead). Injected tools are stored in `agentflow._injected_tools` before user code runs. Async-only MCP tools (`StructuredTool` with `coroutine` but no `func`) are wrapped by `_ensure_sync()` in `agentflow.get_tools()` so sync `agent.invoke()` works.

### WebSocket with replay buffer

`_WsManager` in `execution_engine.py` buffers every event per `execution_id`. WS clients connecting **after** a run started still get the full history via replay (`connect()` sends buffered then subscribes). Buffers are dropped 5 minutes after the run ends.

### Execution records: error persistence & retention

Two easy traps in `execution_engine.py`, both fixed — keep them fixed:

- **Persist failures as logs, not just `execution.error`.** When a user script crashes, the runner emits a structured `{"type":"error", traceback}` event. The `_drain` loop now **also** writes it as an `ExecutionLog` (level `error`, step `error`) and pushes a `log` WS event — otherwise the crash would only land in `execution.error` (shown as a transient toast) and be **invisible in the Logs/Output/Flow panels**, especially on reload. If the process exits non-zero but emitted *no* error (e.g. `sys.exit()`, SIGKILL/OOM, native crash), the engine **synthesizes** an error from the exit code so a failed run is never blank. `_mark_failed()` likewise persists a log.
- **Per-script execution retention.** `Script.max_executions` (default 50, `0` = unlimited; Alembic revision `0002`) caps how many execution *rows* a script keeps. `prune_executions(db, script_id, keep)` deletes the oldest **terminal** runs beyond `keep` (never in-flight ones) + their run dirs; it runs at the end of every run and on a `PATCH /scripts/{id}` that lowers the value. This is distinct from `_prune_old_runs(keep=20)`, which caps run *directories* on disk. Manual management: `DELETE /api/executions/{id}` (409 if the run is still in-flight — stop it first) and `DELETE /api/executions?script_id=…` (clears all terminal records + dirs). Both wired into the script page's **Runs** tab (per-row trash + "Clear"), with the cap configurable in the Config panel ("Kept Executions").

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

- `app/database.py` switches on `DATABASE_URL` (sqlite vs anything else). SQLite gets WAL pragmas + `check_same_thread=False`; everything else gets pool defaults. **Both sqlite (local/single-host) and postgres (docker) are first-class and must keep working.**
- **Schema is owned entirely by Alembic** (`backend/alembic/`, driven by `backend/alembic.ini`). There is **no more `create_all` and no hand-rolled `V*.sql`/`schema_migrations` runner** — that system was fragile (a drifted `schema_migrations` row re-ran an old `ALTER ADD COLUMN` and crashed startup with `DuplicateColumn`) and was removed. `env.py` reads the DB URL straight from `app.database` (single source of truth; also avoids configparser `%`-interpolation issues with postgres passwords) and sets `render_as_batch=True` on sqlite so `ALTER`s work there — **the same revision files run on sqlite and postgres**.
- **Migrations auto-apply on startup**, so `docker compose pull && up -d` (or `F5`) self-migrates. `lifespan` calls `app/migrate.py::run_migrations(engine)`, which inspects the DB and picks one path (fail-fast: an error stops startup):
  - **`alembic_version` present** → `alembic upgrade head`.
  - **no `alembic_version` but `scripts` present** → a **pre-Alembic** deployment of *unknown / possibly partial* schema (old AgentFlow DBs used a fragile runner that could crash mid-way, leaving later columns/tables missing — e.g. a DB that died on migration `V1` never got `skills`, `scripts.skill_ids`, etc.). We do **not** assume it matches any revision. Instead `_heal_schema_to_models(engine)` **reconciles it to the ORM models**: `create_all` builds missing *tables*, then each missing *column* is added **nullable + backfilled to the model default** (`col.type.compile(dialect)` for the type; a nullable ADD can't fail on a populated table; the backfill fixes API-required fields like `skill_ids`/`mcp_server_ids`/`max_executions` that must not be NULL). Then `command.stamp("head")`. **This heals ANY partial state** and is the real fix for a drifted cloud DB — do not revert it to a naive `stamp("0001")` (that assumed a full baseline the crashed DB didn't have).
  - **empty DB** → `upgrade head` builds everything.
- **Revisions** live in `backend/alembic/versions/`. `0001_baseline_schema` is the full schema **as a complete pre-retention deployment has it** (i.e. *without* later-added columns — do not add new columns to it). `0002_add_max_executions` adds `scripts.max_executions` with a **plain `op.add_column`** (not `batch_alter_table` — a pure add needs no sqlite table-recreate) and an **idempotent guard** (skips the ADD if the column already exists, since a DB that got it via the interim legacy migration `V11` would otherwise hit "duplicate column"). Fresh/`alembic_version`-tracked DBs run these revisions; pre-Alembic DBs are healed to models + stamped `head` (revisions not replayed). **Write additive column migrations the same defensive way** (plain add_column + inspector guard).
- **When adding a column/table**: add the `Column`/model, then `cd backend && alembic revision --autogenerate -m "<desc>"`, review the generated file (autogenerate diffs models↔DB; `compare_type=True`), add a data backfill (`op.execute("UPDATE …")`) if the new column is non-optional in the API schema, then just restart — startup runs `upgrade head`. Give a column a `server_default` (mirrored on the model `Column`) so existing rows populate on ADD and autogenerate sees no drift. Use `op.batch_alter_table(...)` for column changes so sqlite works too. Do not drop the DB, and do not edit an already-shipped revision — add a new one.
- To author/inspect out of band: `cd backend && alembic history`, `alembic current`, `alembic upgrade head`, `alembic upgrade head --sql` (preview DDL, e.g. `DATABASE_URL=postgresql+psycopg2://… alembic upgrade head --sql` to eyeball the postgres SQL without a live DB).

### Skills (reusable agent instructions + files)

A **Skill** is an [Agent Skill](https://github.com/anthropics/skills): a folder with a `SKILL.md` (YAML frontmatter `name`/`description` + markdown instructions) plus any supporting files. Skills are **global** like MCP servers, and stored **purely on disk** under `backend/data/skills/<dir>/` (all of `backend/data/` is gitignored) — *not* in the DB. This differs from scripts (whose files live in `script_files` rows): skills can bundle many/large files and marketplace install = drop a folder, so disk is the natural home. A script opts in via `script.skill_ids` (JSON array of skill **directory names**, AND-ed with each skill's `enabled` flag), exactly like `mcp_server_ids`.

- **On-disk layout & store**: `services/skill_store.py` is the *single* module that touches the skills dir. Each skill: `<dir>/SKILL.md` (`is_main`) + supporting files/nested folders + a `.agentflow.json` **sidecar** = `{enabled, source, installed_at, upstream, migrated_from_id}`. The **directory name is the stable identity** (used in `skill_ids` and `/api/skills/{id}` routes). Display **name/description come from the SKILL.md frontmatter** (parsed by a tiny dependency-free parser — no PyYAML); AgentFlow-specific state lives only in the sidecar, so the rest of the folder stays a clean, portable Agent Skill. `skill_store` exposes `list_skills`/`get_skill`(returns `files` **and** `dirs`, incl. empty ones)/`create_skill`/`update_skill`(rewrites frontmatter for name/desc, sidecar for enabled)/`delete_skill`/`upsert_file`/`delete_file`/`create_dir`/`delete_dir`(rmtree a subfolder; skill root + `.agentflow.*` metadata protected)/`import_skill_dir`/`create_from_files`/`manifest_entry`. Path safety reuses `normalize_script_filename` (permits nested `a/b.md`).
- **Management**: `routers/skills.py` is a thin wrapper over `skill_store` (admin-gated; `{skill_id}` = dir name). Response shapes are unchanged (`SkillDetail` now also carries `dirs: list[str]`), so the frontend is untouched apart from folder support. New `POST /skills/{id}/dirs {path}` makes a **real on-disk folder** and `DELETE /skills/{id}/dirs/{path}` removes one — `FileTree`'s "New folder" now persists empty dirs (via `onNewFolder`/`emptyDirs` props) and dir rows/context-menu offer **Delete folder** (via `onDeleteDir`). Scripts have no dir endpoint: they still chain folder→first-file, and `onDeleteDir` there just deletes every file under the (virtual) prefix so the folder vanishes from the tree. The Tools page (`/tools`) lists skills; editing opens `/skill?id=…` reusing `FileTree` + `ScriptEditor` (Monaco). `FileTree` still supports collapsible tree + folder-preserving upload (`webkitdirectory` / `webkitGetAsEntry`). Pass `showRequirements={false}` for skills.
- **DB→disk migration**: `services/skill_migrate.py::migrate_skills_to_disk(db)` runs in the `app/main.py` lifespan (after `run_migrations`, mirroring `llm_migrate`). It writes any legacy `skills`/`skill_files` rows to disk (sidecar `migrated_from_id`) and rewrites every `script.skill_ids` entry from the old DB id → new dir name. Idempotent; legacy rows are **kept** (read-only rollback backup). The `Skill`/`SkillFile` models stay defined but are read *only* by this migration.
- **Runtime — two ways to consume skills** (`execution_engine` **copies** each enabled bound skill's folder `backend/data/skills/<dir>/` → `run_dir/skills/<safe>/` via `shutil.copytree`, so both agent modes see skills under `run_dir` and can't mutate the stored copy; then builds the `AGENTFLOW_SKILLS` manifest `[{name, description, dir, main}]`; `AGENTFLOW_RUN_DIR` points at the run dir):
  - `get_agent()` (default, lightweight, progressive disclosure à la deepagents): folds each skill's **name+description into the system prompt** and adds a built-in **`read_skill(name)`** tool that returns a skill's full `SKILL.md`. Built on `create_react_agent`; the agent can only read SKILL.md (supporting files reachable from script code via `skill_path`). No extra dependency.
  - `get_deep_agent()` (opt-in): builds a **deepagents** Deep Agent (`create_deep_agent`) whose `FilesystemBackend(root_dir=run_dir, virtual_mode=True)` mounts `skills/` at the **virtual** source `"/skills"`, so the agent browses+reads **every** skill file itself plus gets planning/sub-agents. **`virtual_mode=True` is mandatory on Windows** — deepagents' path validator rejects drive-letter absolute paths (`D:\…\SKILL.md`), so a non-virtual backend crashes the instant the skills loader hands the agent a skill-file path (`Windows absolute paths are not supported`). Virtual POSIX paths (`/skills/…`) behave identically on every OS. It **also** gets the same `read_skill` tool as `get_agent()` (a plain file-read of SKILL.md) as a reliable, cross-platform **unified entry point** regardless of backend quirks. Accepts a LangChain model instance (from `get_llm()`); introspects `create_deep_agent`'s signature across versions. Needs the `deepagents` baseline package.
  - The agentflow SDK skill functions (`list_skills`/`get_skill`/`skill_path`/`_make_skill_tool`/`_skills_root`) were **unchanged** — they already read from the `AGENTFLOW_SKILLS` manifest + `run_dir/skills` on disk.
- Scripts can also read skills directly via `list_skills()` / `get_skill(name)` / `skill_path(name)`.

#### Skill marketplace (browse + install from official + community)

`routers/marketplace.py` (admin-gated, `/api/marketplace`) lets an admin browse and one-click install skills. **Key insight: both sources are GitHub-backed** (registries only *discover*; files always live on GitHub), so there is one install engine:

- `services/marketplace.py` — the GitHub engine: `parse_github_ref` (owner/repo, `@ref`, tree/blob URLs, subpaths), `fetch_repo` (downloads a repo **tarball** once to `backend/data/marketplace/cache/`, extracts with stdlib `tarfile` + a path-traversal guard — one request per source refresh, so we stay under GitHub rate limits), `scan_skills` (finds every `SKILL.md`), `install_skill` (copies the folder into the store via `skill_store.import_skill_dir`, sidecar `upstream` = `owner/repo[@ref]#subpath` for the installed-flag/idempotency), `official_catalog` (browses `anthropics/skills`). Optional `GITHUB_TOKEN`/`GH_TOKEN` env raises the rate limit.
- `services/marketplace_registry.py` — **two** community search providers (discovery only; both return `githubUrl` per result → install flows through the GitHub engine above):
  - **SkillsMP** (`search`): `GET https://skillsmp.com/api/v1/skills/search`, anonymous works (50/day), optional `SKILLSMP_API_KEY` Bearer raises it (→500/day), surfaces `X-RateLimit-Daily-Remaining`.
  - **skills.sh** (Vercel Labs, `search_skillsh` + `skillsh_token`): `GET https://skills.sh/api/v1/skills/search` **requires a bearer token** (`SKILLS_SH_TOKEN` or `VERCEL_OIDC_TOKEN`) — anonymous requests 401, so without a token `search_skillsh` short-circuits to `{auth_required: true}` (no network call) and the UI shows a hint. Results map `source`→`githubUrl` (only GitHub-backed skills are kept).
- Endpoints: `GET /official?refresh=`, `GET /registry/search?q=&page=&sort=&provider=skillsmp|skillssh` (a needs-auth registry returns `{auth_required:true, skills:[]}` instead of erroring), `POST /install {owner?,repo?,ref?,subpath?,githubUrl?}` (a multi-skill repo returns `{needs_choice, skills:[…]}` for the caller to pick a `subpath`), `GET /sources` (returns `official` + a `registries[]` array).
- Frontend: `components/SkillMarketplaceDialog.tsx` (three tabs: Official anthropics/skills · Community SkillsMP · Community skills.sh; cards with ⭐ + Install, `needs_choice` picker; native-`overflow-y-auto` scroll inside a `flex`-bounded `DialogContent`), opened from a **"Browse Marketplace"** button in the `/tools` Skills section; installs reload the skill list.
- **Out of scope** (noted, not built): auto-installing a skill's own Python deps or executing bundled skill scripts (no per-skill venv); a custom-GitHub-sources management screen (the engine accepts any `githubUrl`, but there's no sources-list CRUD UI).

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
- **Chat page convention**: input is `{message, history: [{role, content}]}`, output is `{reply}` (with fallbacks: `message` / `response` / `result` / stringified). Maintained client-side in `frontend/src/app/converse/page.tsx` (Open-WebUI-style: collapsible searchable sidebar, flat full-width assistant messages, hover copy/delete, stop-generation, scroll-to-bottom). The chat page also consumes `trace` WS events and renders agent internals via `AgentNarrative` — one **collapsed-by-default** "Agent trace" block above each assistant answer that expands to the readable story of the turn: the agent's intermediate text returns rendered as markdown, each tool call as a card with args/result/status (chronological, from `buildRows`). The last LLM turn's text is excluded (`excludeLastLlmText`) since the authoritative `content` renders it as the final answer. The shared markdown renderer is `components/Markdown.tsx`. On reload it re-hydrates from the run's `_trace` logs. (`AgentTraceInline.tsx` is the older compact-timeline view, no longer wired into the chat.) The tracer (`agentflow/_tracer.py`) is global, so any `get_agent()` / LangGraph run is traced automatically — a plain `run()` that isn't a LangGraph node won't show node steps, but its tool/LLM calls still do.
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
| Add/modify DB columns | model `Column` + `cd backend && alembic revision --autogenerate -m "…"` (review + add backfill), then restart (startup runs `upgrade head`) |
| Migration runner (startup auto-apply + reconcile) | `backend/app/migrate.py::run_migrations` (wired in `app/main.py` lifespan); revisions in `backend/alembic/versions/`; config `backend/alembic.ini` + `backend/alembic/env.py` |
| New API endpoint | `backend/app/routers/*.py` + register in `app/main.py` |
| Change how user scripts get env / sys.path | `services/execution_engine.py::_write_runner` |
| Change venv tooling (uv/pip) | `services/venv_manager.py` |
| Change user-facing tool API (`get_tools`, `get_agent`, etc.) | `backend/agentflow/__init__.py` |
| Add LLM provider branch | `backend/agentflow/__init__.py::get_llm` |
| Add/remove baseline venv packages | `services/venv_manager.py::BASELINE_PACKAGES` |
| New page in UI | `frontend/src/app/<name>/page.tsx` (link from `app/page.tsx` navbar) |
| Resizable panel | `useResizable` from `frontend/src/components/Splitter.tsx` |
| Log rendering | `frontend/src/components/LogPanel.tsx` (uses `toLocalDate`) |
| Execution error persistence (crash → Logs panel) | `services/execution_engine.py` (`_drain` `error` branch, silent-exit synth, `_mark_failed`) |
| Execution-record retention (cap + auto-prune) | `services/execution_engine.py::prune_executions` + `Script.max_executions` (Alembic `0002`) + `routers/scripts.py` PATCH |
| Delete / clear execution records | `routers/executions.py` (`DELETE /{id}`, `DELETE ?script_id=`) + `RunsTab` in `frontend/src/app/script/page.tsx` |
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
| Skill disk store (CRUD / frontmatter / sidecar) | `backend/services/skill_store.py` (schemas in `schemas.py::Skill*`; `routers/skills.py` wraps it) |
| Skill DB→disk migration (+ rebind skill_ids) | `backend/services/skill_migrate.py` (wired in `app/main.py` lifespan) |
| Skill materialization (copytree) + manifest into runs | `services/execution_engine.py` (`AGENTFLOW_SKILLS`, `_safe_skill_dirname`, `shutil.copytree`) |
| Script-facing skill API + `read_skill` tool | `backend/agentflow/__init__.py::list_skills`/`get_skill`/`_make_skill_tool` (wired in `get_agent`) |
| Deep-agent skill loading (deepagents FilesystemBackend, **virtual_mode** for Windows) | `backend/agentflow/__init__.py::get_deep_agent` (needs `deepagents` baseline pkg) |
| Skill marketplace (GitHub engine / registry / router) | `backend/services/marketplace.py` + `marketplace_registry.py` + `routers/marketplace.py` |
| Skill marketplace UI | `frontend/src/components/SkillMarketplaceDialog.tsx` (opened from `app/tools/page.tsx`) |
| Skills list + create | `frontend/src/app/tools/page.tsx` (Skills section) |
| Skill editor (FileTree + Monaco + upload + folders) | `frontend/src/app/skill/page.tsx` + `components/FileTree.tsx` (`onNewFolder`/`emptyDirs`/`onDeleteDir`) |
| Delete a folder (skill = disk rmtree; script = delete files under prefix) | `skill_store.delete_dir` + `routers/skills.py` `DELETE …/dirs/{path}` + `FileTree`'s `onDeleteDir` (wired in both editor pages) |
| Bind skills to a script | `frontend/src/app/script/page.tsx` (`selectedSkillIds`) + `script.skill_ids` (holds dir names) |
