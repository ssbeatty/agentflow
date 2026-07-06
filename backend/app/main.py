import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Windows: asyncio subprocess support requires ProactorEventLoop.
# Some debuggers / tooling install a SelectorEventLoop which breaks
# create_subprocess_exec → NotImplementedError. Force Proactor here.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.logging_config import setup_logging
setup_logging()  # as early as possible, before uvicorn/sqlalchemy touch stdlib logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from app.config import settings
from app.database import engine, SessionLocal
from app.auth_deps import require_admin
from app.routers import (
    scripts, executions, llm_configs, cron_jobs, ws, mcp_servers,
    conversations, files, channels, auth, api_keys, secrets, skills, marketplace,
    search_config, assistant, evals,
)
from services.scheduler import scheduler_service
from services.mcp_gateway import MCPGatewayMiddleware, gateway as mcp_gateway

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is owned entirely by Alembic (see app/migrate.py). On startup we
    # bring the DB up to head — building a fresh DB, adopting+upgrading a
    # pre-Alembic one, or no-op'ing if already current. Fail-fast: a migration
    # error stops startup rather than running behind a broken schema. Works on
    # both sqlite (batch ALTER) and postgres.
    logger.info("Starting AgentFlow backend (env={})", settings.app_env)

    from app.migrate import run_migrations
    run_migrations(engine)

    # Fold any legacy llm_configs rows into the new channels model (idempotent).
    db = SessionLocal()
    try:
        from services.llm_migrate import migrate_llm_configs_to_channels
        n = migrate_llm_configs_to_channels(db)
        if n:
            logger.info("Migrated {} LLM channel(s) from legacy configs", n)
    except Exception:  # never let migration block startup
        logger.exception("LLM channel migration skipped")
    finally:
        db.close()

    # Move any DB-stored skills onto disk + rebind script.skill_ids (idempotent).
    db = SessionLocal()
    try:
        from services.skill_migrate import migrate_skills_to_disk
        n = migrate_skills_to_disk(db)
        if n:
            logger.info("Migrated {} skill(s) from DB to disk", n)
    except Exception:  # never let migration block startup
        logger.exception("Skill disk migration skipped")
    finally:
        db.close()

    # Seed / re-sync the built-in "AI 脚本助手" (internal key + loopback MCP
    # server + assistant script). Idempotent; keeps main.py authoritative.
    db = SessionLocal()
    try:
        from services.assistant_seed import seed_assistant
        seed_assistant(db)
    except Exception:  # never let seeding block startup
        logger.exception("Assistant seed skipped")
    finally:
        db.close()
    scheduler_service.start()
    logger.info("Scheduler started")

    # Warm-worker pool (opt-in via AGENTFLOW_WARM_WORKERS). Eagerly preheat
    # scripts flagged keep_warm so their first run is hot ("provisioned
    # concurrency"). Fire-and-forget so a slow import never blocks startup.
    try:
        from services import worker_pool
        if worker_pool.WARM_WORKERS_ENABLED:
            asyncio.create_task(_preheat_keep_warm())
    except Exception:
        logger.exception("Warm-worker preheat scheduling skipped")

    try:
        # The MCP gateway's StreamableHTTP session manager needs a running task
        # group for the lifetime of the app (stateless mode still requires it).
        async with mcp_gateway.session_manager.run():
            logger.info("AgentFlow backend ready")
            yield
    finally:
        scheduler_service.shutdown()
        try:
            from services import worker_pool
            worker_pool.manager.shutdown_all()
        except Exception:
            pass
        logger.info("AgentFlow backend shut down")


async def _preheat_keep_warm() -> None:
    """Preheat every warm keep_warm script's worker on startup (best-effort)."""
    from app.database import SessionLocal
    from app.models import Script
    from services import worker_pool

    db = SessionLocal()
    try:
        scripts = db.query(Script).filter(
            Script.keep_warm == True, Script.warm == True,  # noqa: E712
        ).all()
        targets = [(s.id, s.entry_function, s.name) for s in scripts]
    except Exception:
        logger.exception("keep_warm preheat query failed")
        return
    finally:
        db.close()

    for sid, entry, name in targets:
        try:
            await worker_pool.manager.acquire(sid, entry, preheat=True)
            logger.info("[worker {}] preheated on startup ({})", sid[:8], name)
        except Exception as e:
            logger.warning("[worker {}] startup preheat failed: {}", sid[:8], e)


app = FastAPI(title="AgentFlow", version="0.1.0", lifespan=lifespan)

_origins = settings.cors_origins_list
_wildcard = "*" in _origins
app.add_middleware(
    CORSMiddleware,
    # CORS spec forbids allow_credentials=True together with "*"; fall back to
    # a regex that echoes any origin so the headers are still well-formed.
    allow_origins=["*"] if _wildcard else _origins,
    allow_origin_regex=".*" if _wildcard else None,
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging + unhandled-exception logging ────────────────────────────
# Static-asset/catch-all noise (frontend export, /health) stays at DEBUG so a
# normal INFO-level deployment doesn't get spammed on every page load.
_QUIET_PREFIXES = ("/_next", "/health")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error: {} {}", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    duration_ms = (time.monotonic() - start) * 1000
    level = "DEBUG" if request.url.path.startswith(_QUIET_PREFIXES) else "INFO"
    logger.log(level, "{} {} -> {} ({:.1f}ms)", request.method, request.url.path, response.status_code, duration_ms)
    return response

# ── Public auth endpoints (login/setup/status) — no admin gate ────────────────
app.include_router(auth.router,        prefix="/api/auth",        tags=["auth"])

# ── Admin-gated management API ────────────────────────────────────────────────
# Every router below requires a logged-in operator. The executions router is the
# exception: it gates per-endpoint internally so POST /api/executions/run can
# accept an external API key instead of an admin session.
_admin = [Depends(require_admin)]
app.include_router(scripts.router,     prefix="/api/scripts",     tags=["scripts"],     dependencies=_admin)
app.include_router(executions.router,  prefix="/api/executions",  tags=["executions"])
app.include_router(llm_configs.router, prefix="/api/llm-configs", tags=["llm-configs"], dependencies=_admin)
app.include_router(channels.router,    prefix="/api/channels",    tags=["channels"],    dependencies=_admin)
app.include_router(cron_jobs.router,   prefix="/api/cron-jobs",   tags=["cron-jobs"],   dependencies=_admin)
app.include_router(ws.router,          prefix="/ws",              tags=["websocket"])
app.include_router(api_keys.router,    prefix="/api/api-keys",    tags=["api-keys"])
app.include_router(mcp_servers.router,    prefix="/api/mcp-servers",    tags=["mcp-servers"],    dependencies=_admin)
app.include_router(conversations.router,  prefix="/api/conversations",  tags=["conversations"],  dependencies=_admin)
app.include_router(files.router,          prefix="/api/files",          tags=["files"],          dependencies=_admin)
app.include_router(secrets.router,        prefix="/api/secrets",        tags=["secrets"],        dependencies=_admin)
app.include_router(skills.router,         prefix="/api/skills",         tags=["skills"],         dependencies=_admin)
app.include_router(marketplace.router,     prefix="/api/marketplace",     tags=["marketplace"],     dependencies=_admin)
app.include_router(search_config.router,   prefix="/api/search-config",   tags=["search-config"],   dependencies=_admin)
app.include_router(assistant.router,        prefix="/api/assistant",        tags=["assistant"],        dependencies=_admin)
app.include_router(evals.router,            prefix="/api/evals",            tags=["evals"],            dependencies=_admin)

# ── MCP gateway (external coding agents: Claude Code, Cursor, …) ─────────────
# Streamable HTTP MCP server for developing scripts remotely, intercepted at
# /mcp before FastAPI routing (a Mount can't match the bare /mcp path). Auth:
# issued API key or admin session Bearer — enforced inside the middleware.
app.add_middleware(MCPGatewayMiddleware)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if not FRONTEND_DIR.is_dir():
        return {"detail": "Frontend not built. Run `npm run build` in /frontend."}
    candidate = (FRONTEND_DIR / full_path).resolve()
    # Prevent path traversal outside FRONTEND_DIR
    if FRONTEND_DIR.resolve() in candidate.parents or candidate == FRONTEND_DIR.resolve():
        if candidate.is_file():
            return FileResponse(candidate)
        index_candidate = candidate / "index.html"
        if index_candidate.is_file():
            return FileResponse(index_candidate)
    return FileResponse(FRONTEND_DIR / "index.html")
