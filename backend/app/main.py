from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.routers import scripts, executions, llm_configs, cron_jobs, ws
from services.scheduler import scheduler_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler_service.start()
    yield
    scheduler_service.shutdown()


app = FastAPI(title="OpenGraph", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scripts.router,     prefix="/api/scripts",     tags=["scripts"])
app.include_router(executions.router,  prefix="/api/executions",  tags=["executions"])
app.include_router(llm_configs.router, prefix="/api/llm-configs", tags=["llm-configs"])
app.include_router(cron_jobs.router,   prefix="/api/cron-jobs",   tags=["cron-jobs"])
app.include_router(ws.router,          prefix="/ws",              tags=["websocket"])


@app.get("/health")
def health():
    return {"status": "ok"}
