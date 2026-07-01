import json

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Script, ScriptFile, ScriptRevision, ScriptInputPreset
from app.schemas import (
    ScriptCreate, ScriptUpdate, ScriptDetail, ScriptSummary, ScriptFileUpsert, ScriptFileOut,
    RevisionCreate, RevisionLabelUpdate, RevisionSummaryOut, RevisionDetailOut,
    RevisionFileOut, ForkRevisionRequest,
    InputPresetCreate, InputPresetUpdate, InputPresetOut,
)
from services.venv_manager import (
    venv_exists, stream_create_venv, stream_install, delete_venv,
    list_installed_packages,
)
from services.script_files import normalize_script_filename

MAX_REVISIONS = 50

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
    try:
        filename = normalize_script_filename(body.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    f = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
    if f:
        f.content = body.content
        f.is_main = body.is_main
    else:
        payload = body.model_dump()
        payload["filename"] = filename
        f = ScriptFile(script_id=script_id, **payload)
        db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.delete("/{script_id}/files/{filename:path}", status_code=204)
def delete_file(script_id: str, filename: str, db: Session = Depends(get_db)):
    try:
        filename = normalize_script_filename(filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    f = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
    if not f:
        raise HTTPException(404, "File not found")
    if f.is_main:
        raise HTTPException(400, "Cannot delete main file")
    db.delete(f)
    db.commit()


# ── Venv & install (streamed) ──────────────────────────────────────────────────

@router.post("/{script_id}/venv")
async def create_venv(script_id: str, force: bool = False, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)

    async def gen():
        async for line in stream_create_venv(script_id, force=force):
            yield line + "\n"

    return StreamingResponse(gen(), media_type="text/plain")


@router.delete("/{script_id}/venv", status_code=200)
def remove_venv(script_id: str, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    removed = delete_venv(script_id)
    return {"removed": removed}


@router.get("/{script_id}/venv", status_code=200)
def venv_status(script_id: str, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    return {"exists": venv_exists(script_id)}


@router.get("/{script_id}/packages", status_code=200)
def list_packages(script_id: str, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    pkgs, error = list_installed_packages(script_id)
    return {"packages": pkgs, "error": error}


# ── Static Python validation ───────────────────────────────────────────────────

class _LintRequest(BaseModel):
    source: str
    filename: str = "main.py"


@router.post("/{script_id}/lint", status_code=200)
def lint(script_id: str, body: _LintRequest, db: Session = Depends(get_db)):
    """Static syntax check via ast.parse. Cheap, no venv required."""
    import ast
    script = _get_or_404(script_id, db)
    issues: list[dict] = []
    try:
        ast.parse(body.source, filename=body.filename)
    except SyntaxError as e:
        issues.append({
            "line": e.lineno or 1,
            "col": e.offset or 1,
            "end_line": e.end_lineno or e.lineno or 1,
            "end_col": e.end_offset or (e.offset or 1) + 1,
            "message": e.msg or "syntax error",
            "severity": "error",
        })

    # also check that the entry function exists
    if not issues:
        try:
            tree = ast.parse(body.source)
            names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            if script.entry_function not in names:
                issues.append({
                    "line": 1, "col": 1, "end_line": 1, "end_col": 1,
                    "message": f"entry function `{script.entry_function}` not defined in this file",
                    "severity": "warning",
                })
        except Exception:
            pass

    return {"issues": issues}


@router.post("/{script_id}/install")
async def install_deps(script_id: str, db: Session = Depends(get_db)):
    script = _get_or_404(script_id, db)
    if not venv_exists(script_id):
        raise HTTPException(400, "Create venv first")

    async def gen():
        async for line in stream_install(script_id, script.requirements or ""):
            yield line + "\n"

    return StreamingResponse(gen(), media_type="text/plain")


# ── Revisions ─────────────────────────────────────────────────────────────────

@router.post("/{script_id}/revisions", response_model=RevisionSummaryOut, status_code=201)
def create_revision(script_id: str, body: RevisionCreate, db: Session = Depends(get_db)):
    rev = _snapshot(script_id, body.label, db)
    return rev


@router.get("/{script_id}/revisions", response_model=list[RevisionSummaryOut])
def list_revisions(script_id: str, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    return (
        db.query(ScriptRevision)
        .filter_by(script_id=script_id)
        .order_by(ScriptRevision.revision_number.desc())
        .all()
    )


@router.get("/{script_id}/revisions/{rev_id}", response_model=RevisionDetailOut)
def get_revision(script_id: str, rev_id: str, db: Session = Depends(get_db)):
    rev = _get_rev_or_404(rev_id, script_id, db)
    return _rev_detail(rev)


@router.patch("/{script_id}/revisions/{rev_id}", response_model=RevisionSummaryOut)
def update_revision_label(script_id: str, rev_id: str, body: RevisionLabelUpdate, db: Session = Depends(get_db)):
    rev = _get_rev_or_404(rev_id, script_id, db)
    rev.label = body.label
    db.commit()
    db.refresh(rev)
    return rev


@router.delete("/{script_id}/revisions/{rev_id}", status_code=204)
def delete_revision(script_id: str, rev_id: str, db: Session = Depends(get_db)):
    rev = _get_rev_or_404(rev_id, script_id, db)
    db.delete(rev)
    db.commit()


@router.post("/{script_id}/revisions/{rev_id}/fork", response_model=ScriptDetail, status_code=201)
def fork_revision(script_id: str, rev_id: str, body: ForkRevisionRequest, db: Session = Depends(get_db)):
    rev = _get_rev_or_404(rev_id, script_id, db)
    files = json.loads(rev.files_snapshot or "[]")

    new_script = Script(
        name=body.name,
        description=f"Forked from \"{rev.name}\" (revision #{rev.revision_number})",
        entry_function=rev.entry_function,
        requirements=rev.requirements,
    )
    db.add(new_script)
    db.flush()

    for f in files:
        db.add(ScriptFile(
            script_id=new_script.id,
            filename=f["filename"],
            content=f["content"],
            is_main=f.get("is_main", False),
        ))

    db.commit()
    db.refresh(new_script)
    return new_script


# ── Input presets ─────────────────────────────────────────────────────────────

@router.get("/{script_id}/presets", response_model=list[InputPresetOut])
def list_presets(script_id: str, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    return (
        db.query(ScriptInputPreset)
        .filter_by(script_id=script_id)
        .order_by(ScriptInputPreset.created_at)
        .all()
    )


@router.post("/{script_id}/presets", response_model=InputPresetOut, status_code=201)
def create_preset(script_id: str, body: InputPresetCreate, db: Session = Depends(get_db)):
    _get_or_404(script_id, db)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    _validate_json(body.input_json)
    p = ScriptInputPreset(script_id=script_id, name=name, input_json=body.input_json)
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Preset named {name!r} already exists")
    db.refresh(p)
    return p


@router.patch("/{script_id}/presets/{preset_id}", response_model=InputPresetOut)
def update_preset(script_id: str, preset_id: str, body: InputPresetUpdate, db: Session = Depends(get_db)):
    p = _get_preset_or_404(preset_id, script_id, db)
    data = body.model_dump(exclude_none=True)
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(400, "Name required")
    if "input_json" in data:
        _validate_json(data["input_json"])
    for k, v in data.items():
        setattr(p, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Preset with this name already exists")
    db.refresh(p)
    return p


@router.delete("/{script_id}/presets/{preset_id}", status_code=204)
def delete_preset(script_id: str, preset_id: str, db: Session = Depends(get_db)):
    p = _get_preset_or_404(preset_id, script_id, db)
    db.delete(p)
    db.commit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(script_id: str, db: Session) -> Script:
    s = db.query(Script).filter_by(id=script_id).first()
    if not s:
        raise HTTPException(404, "Script not found")
    return s


def _get_rev_or_404(rev_id: str, script_id: str, db: Session) -> ScriptRevision:
    r = db.query(ScriptRevision).filter_by(id=rev_id, script_id=script_id).first()
    if not r:
        raise HTTPException(404, "Revision not found")
    return r


def _get_preset_or_404(preset_id: str, script_id: str, db: Session) -> ScriptInputPreset:
    p = db.query(ScriptInputPreset).filter_by(id=preset_id, script_id=script_id).first()
    if not p:
        raise HTTPException(404, "Preset not found")
    return p


def _validate_json(text: str) -> None:
    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e.msg}")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "Input JSON must be an object")


def _rev_detail(rev: ScriptRevision) -> RevisionDetailOut:
    files = [RevisionFileOut(**f) for f in json.loads(rev.files_snapshot or "[]")]
    return RevisionDetailOut(
        id=rev.id,
        script_id=rev.script_id,
        revision_number=rev.revision_number,
        label=rev.label,
        name=rev.name,
        entry_function=rev.entry_function,
        requirements=rev.requirements,
        created_at=rev.created_at,
        files=files,
    )


def _snapshot(script_id: str, label: str, db: Session) -> ScriptRevision:
    script = _get_or_404(script_id, db)
    max_num = db.query(func.max(ScriptRevision.revision_number)).filter_by(script_id=script_id).scalar() or 0

    files_data = [
        {"filename": f.filename, "content": f.content, "is_main": f.is_main}
        for f in script.files
    ]
    rev = ScriptRevision(
        script_id=script_id,
        revision_number=max_num + 1,
        label=label,
        name=script.name,
        entry_function=script.entry_function,
        requirements=script.requirements or "",
        files_snapshot=json.dumps(files_data),
    )
    db.add(rev)
    db.flush()

    # Prune oldest beyond limit
    all_revs = (
        db.query(ScriptRevision)
        .filter_by(script_id=script_id)
        .order_by(ScriptRevision.revision_number.asc())
        .all()
    )
    for old in all_revs[: max(0, len(all_revs) - MAX_REVISIONS)]:
        db.delete(old)

    db.commit()
    db.refresh(rev)
    return rev


def _default_main(entry_fn: str) -> str:
    return f"""from agentflow import log, get_llm


def {entry_fn}(input: dict) -> dict:
    log("Script started", data=input)
    # Your LangGraph logic here
    return {{"result": "ok"}}
"""
