"""Endpoints backing the in-browser **AI 脚本助手** panel.

The panel drives the assistant entirely through existing primitives — it starts
a run with `POST /api/executions` against the assistant script id and streams it
over `/ws/executions/{id}` (same as any run), so the only thing it needs from
here is *which* script that is (plus whether its venv is ready).
"""
import importlib.util

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from services.assistant_seed import get_assistant_script_id

router = APIRouter()


@router.get("/info")
def assistant_info(db: Session = Depends(get_db)):
    """Return the built-in assistant script id + whether the backend can run it.

    The assistant is PLATFORM code: it runs on the *backend* python and reuses
    the platform's langchain deps (requirements.txt) — there is no per-script
    venv to set up. So "ready" means the langgraph stack is importable in the
    backend process (it is in the Docker image; in a dev checkout it requires
    `pip install -r requirements.txt` once). Seeds the assistant on demand."""
    script_id = get_assistant_script_id(db)
    ready = importlib.util.find_spec("langgraph") is not None
    return {"script_id": script_id, "venv_ready": ready}
