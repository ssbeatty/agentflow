from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas import (
    SkillCreate, SkillUpdate, SkillSummary, SkillDetail,
    SkillFileUpsert, SkillFileOut,
)
from services import skill_store

# Skills are stored purely on disk (backend/data/skills/<dir>/), managed by
# services/skill_store.py. The `{skill_id}` path segment is the skill's
# directory name (its stable identity, also what script.skill_ids references).
# Admin gating is applied at include time in app/main.py.
router = APIRouter()


class SkillDirCreate(BaseModel):
    path: str


@router.get("", response_model=list[SkillSummary])
def list_skills():
    return skill_store.list_skills()


@router.post("", response_model=SkillDetail, status_code=201)
def create_skill(body: SkillCreate):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    try:
        skill = skill_store.create_skill(name, body.description or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.enabled is False:
        skill = skill_store.update_skill(skill["id"], enabled=False)
    return skill


@router.get("/{skill_id}", response_model=SkillDetail)
def get_skill(skill_id: str):
    return _get_or_404(skill_id)


@router.patch("/{skill_id}", response_model=SkillDetail)
def update_skill(skill_id: str, body: SkillUpdate):
    _get_or_404(skill_id)
    data = body.model_dump(exclude_none=True)
    if "name" in data and not str(data["name"]).strip():
        raise HTTPException(400, "Name required")
    try:
        return skill_store.update_skill(
            skill_id,
            name=data.get("name"),
            description=data.get("description"),
            enabled=data.get("enabled"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str):
    _get_or_404(skill_id)
    skill_store.delete_skill(skill_id)


# ── File / folder management (mirrors /api/scripts/{id}/files) ─────────────────

@router.put("/{skill_id}/files", response_model=SkillFileOut, status_code=200)
def upsert_file(skill_id: str, body: SkillFileUpsert):
    _get_or_404(skill_id)
    try:
        return skill_store.upsert_file(skill_id, body.filename, body.content, body.is_main)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{skill_id}/files/{filename:path}", status_code=204)
def delete_file(skill_id: str, filename: str):
    _get_or_404(skill_id)
    try:
        skill_store.delete_file(skill_id, filename)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{skill_id}/dirs", status_code=201)
def create_dir(skill_id: str, body: SkillDirCreate):
    """Create an (empty) folder inside a skill — a real on-disk mkdir."""
    _get_or_404(skill_id)
    try:
        skill_store.create_dir(skill_id, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "path": body.path}


@router.delete("/{skill_id}/dirs/{path:path}", status_code=204)
def delete_dir(skill_id: str, path: str):
    """Delete a folder (and everything under it) inside a skill."""
    _get_or_404(skill_id)
    try:
        skill_store.delete_dir(skill_id, path)
    except FileNotFoundError:
        raise HTTPException(404, "Folder not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_404(skill_id: str) -> dict:
    try:
        return skill_store.get_skill(skill_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Skill not found")
