import asyncio
import contextlib
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows: asyncio subprocess support requires ProactorEventLoop.
# Some debuggers / tooling install a SelectorEventLoop which breaks
# create_subprocess_exec → NotImplementedError. Force Proactor here.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app.config import settings
from app.database import engine, Base
from app.routers import scripts, executions, llm_configs, cron_jobs, ws
from services.scheduler import scheduler_service

agentflow_mcp = None
if settings.mcp_enabled:
    from app.mcp_server import mcp as agentflow_mcp

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler_service.start()
    try:
        async with contextlib.AsyncExitStack() as stack:
            if agentflow_mcp is not None:
                await stack.enter_async_context(agentflow_mcp.session_manager.run())
            yield
    finally:
        scheduler_service.shutdown()


app = FastAPI(title="OpenGraph", version="0.1.0", lifespan=lifespan)

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
    expose_headers=["Mcp-Session-Id"],
)


@app.middleware("http")
async def require_mcp_token(request: Request, call_next):
    if (
        settings.mcp_auth_token
        and request.url.path.startswith("/mcp")
        and request.method != "OPTIONS"
    ):
        expected = f"Bearer {settings.mcp_auth_token}"
        if request.headers.get("authorization") != expected:
            return JSONResponse({"detail": "Unauthorized MCP request"}, status_code=401)
    return await call_next(request)

app.include_router(scripts.router,     prefix="/api/scripts",     tags=["scripts"])
app.include_router(executions.router,  prefix="/api/executions",  tags=["executions"])
app.include_router(llm_configs.router, prefix="/api/llm-configs", tags=["llm-configs"])
app.include_router(cron_jobs.router,   prefix="/api/cron-jobs",   tags=["cron-jobs"])
app.include_router(ws.router,          prefix="/ws",              tags=["websocket"])

if agentflow_mcp is not None:
    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def mcp_redirect(request: Request):
        return RedirectResponse(str(request.url.replace(path="/mcp/")), status_code=307)

    app.mount("/mcp", agentflow_mcp.streamable_http_app())


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
