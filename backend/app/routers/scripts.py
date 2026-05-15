from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Script, ScriptFile
from app.schemas import ScriptCreate, ScriptUpdate, ScriptDetail, ScriptSummary, ScriptFileUpsert, ScriptFileOut
from services.venv_manager import venv_exists, stream_create_venv, stream_install

router = APIRouter()


@router.get("", response_model=list[ScriptSummary])
def list_scripts(db: Session = Depends(get_db)):
    return db.query(Script).order_by(Script.updated_at.desc()).all()


@router.post("", response_model=ScriptDetail, status_code=201)
def create_script(body: ScriptCreate, db: Session = Depends(get_db)):
    script = Script(**body.model_dump())
    db.add(script)
    db.flush()
    # create default main.py
    main_file = ScriptFile(
        script_id=script.id,
        filename="main.py",
        content=_default_main(body.entry_function),
        is_main=True,
    )
    db.add(main_file)
    db.commit()
    db.refresh(script)
    return script


@router.get("/{script_id}", response_model=ScriptDetail)
def get_script(script_id: str, db: Session = Depends(get_db)):
    script = _get_or_404(script_id, db)
    return script


@router.patch("/{script_id}", response_model=ScriptDetail)
def update_script(script_id: str, body: ScriptUpdate, db: Session = Depends(get_db)):
    script = _get_or_404(script_id, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(script, k, v)
    db.commit()
    db.refresh(script)
    return script


@router.delete("/{script_id}", status_code=204)
def delete_script(script_id: str, db: Session = Depends(get_db)):
    script = _get_or_404(script_id, db)
    db.delete(script)
    db.commit()


# ── File management ────────────────────────────────────────────────────────────

@router.put("/{script_id}/files", response_model=ScriptFileOut, status_code=200)
def upsert_file(script_id: str, body: ScriptFileUpsert, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    f = db.query(ScriptFile).filter_by(script_id=script_id, filename=body.filename).first()
    if f:
        f.content = body.content
        f.is_main = body.is_main
    else:
        f = ScriptFile(script_id=script_id, **body.model_dump())
        db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.delete("/{script_id}/files/{filename}", status_code=204)
def delete_file(script_id: str, filename: str, db: Session = Depends(get_db)):
    f = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
    if not f:
        raise HTTPException(404, "File not found")
    if f.is_main:
        raise HTTPException(400, "Cannot delete main file")
    db.delete(f)
    db.commit()


# ── Venv & install (streamed) ──────────────────────────────────────────────────

@router.post("/{script_id}/venv")
async def create_venv(script_id: str, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)

    async def gen():
        async for line in stream_create_venv(script_id):
            yield line + "\n"

    return StreamingResponse(gen(), media_type="text/plain")


@router.post("/{script_id}/install")
async def install_deps(script_id: str, db: Session = Depends(get_db)):
    script = _get_or_404(script_id, db)
    if not venv_exists(script_id):
        raise HTTPException(400, "Create venv first")

    async def gen():
        async for line in stream_install(script_id, script.requirements or ""):
            yield line + "\n"

    return StreamingResponse(gen(), media_type="text/plain")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(script_id: str, db: Session) -> Script:
    s = db.query(Script).filter_by(id=script_id).first()
    if not s:
        raise HTTPException(404, "Script not found")
    return s


def _default_main(entry_fn: str) -> str:
    return f"""from agentflow import log, get_llm


def {entry_fn}(input: dict) -> dict:
    log("Script started", data=input)
    # Your LangGraph logic here
    return {{"result": "ok"}}
"""
