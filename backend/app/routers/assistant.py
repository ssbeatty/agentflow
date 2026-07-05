"""Endpoints backing the in-browser **AI 脚本助手** panel.

The panel drives the assistant entirely through existing primitives — it starts
a run with `POST /api/executions` against the assistant script id and streams it
over `/ws/executions/{id}` (same as any run), so the only thing it needs from
here is *which* script that is (plus whether its venv is ready).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from services.assistant_seed import get_assistant_script_id
from services.venv_manager import venv_exists

router = APIRouter()


@router.get("/info")
def assistant_info(db: Session = Depends(get_db)):
    """Return the built-in assistant script id + whether its venv is set up.
    Seeds the assistant on demand if it doesn't exist yet."""
    script_id = get_assistant_script_id(db)
    return {"script_id": script_id, "venv_ready": venv_exists(script_id)}
