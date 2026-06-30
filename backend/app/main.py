import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows: asyncio subprocess support requires ProactorEventLoop.
# Some debuggers / tooling install a SelectorEventLoop which breaks
# create_subprocess_exec → NotImplementedError. Force Proactor here.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.database import engine, Base, SessionLocal
from app.auth_deps import require_admin
from app.routers import (
    scripts, executions, llm_configs, cron_jobs, ws, mcp_servers,
    conversations, files, channels, auth, api_keys,
)
from services.scheduler import scheduler_service

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Fold any legacy llm_configs rows into the new channels model (idempotent).
    db = SessionLocal()
    try:
        from services.llm_migrate import migrate_llm_configs_to_channels
        n = migrate_llm_configs_to_channels(db)
        if n:
            print(f"[agentflow] migrated {n} LLM channel(s) from legacy configs")
    except Exception as exc:  # never let migration block startup
        print(f"[agentflow] LLM channel migration skipped: {exc}")
    finally:
        db.close()
    scheduler_service.start()
    try:
        yield
    finally:
        scheduler_service.shutdown()


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
