from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Skill, SkillFile
from app.schemas import (
    SkillCreate, SkillUpdate, SkillSummary, SkillDetail,
    SkillFileUpsert, SkillFileOut,
)
from services.script_files import normalize_script_filename

router = APIRouter()

MAIN_FILE = "SKILL.md"


@router.get("", response_model=list[SkillSummary])
def list_skills(db: Session = Depends(get_db)):
    return db.query(Skill).order_by(Skill.created_at).all()


@router.post("", response_model=SkillDetail, status_code=201)
def create_skill(body: SkillCreate, db: Session = Depends(get_db)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    skill = Skill(name=name, description=body.description, enabled=body.enabled)
    db.add(skill)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Skill name {name!r} already exists")
    # Seed the SKILL.md so the editor opens with a valid Agent Skill scaffold.
    db.add(SkillFile(
        skill_id=skill.id,
        filename=MAIN_FILE,
        content=_default_skill_md(name, body.description),
        is_main=True,
    ))
    db.commit()
    db.refresh(skill)
    return skill


@router.get("/{skill_id}", response_model=SkillDetail)
def get_skill(skill_id: str, db: Session = Depends(get_db)):
    return _get_or_404(skill_id, db)


@router.patch("/{skill_id}", response_model=SkillDetail)
def update_skill(skill_id: str, body: SkillUpdate, db: Session = Depends(get_db)):
    skill = _get_or_404(skill_id, db)
    data = body.model_dump(exclude_none=True)
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(400, "Name required")
    for k, v in data.items():
        setattr(skill, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Skill name already exists")
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str, db: Session = Depends(get_db)):
    skill = _get_or_404(skill_id, db)
    db.delete(skill)
    db.commit()


# ── File management (mirrors /api/scripts/{id}/files) ──────────────────────────

@router.put("/{skill_id}/files", response_model=SkillFileOut, status_code=200)
def upsert_file(skill_id: str, body: SkillFileUpsert, db: Session = Depends(get_db)):
    _get_or_404(skill_id, db)
    try:
        filename = normalize_script_filename(body.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    f = db.query(SkillFile).filter_by(skill_id=skill_id, filename=filename).first()
    if f:
        f.content = body.content
        f.is_main = body.is_main or f.is_main or (filename == MAIN_FILE)
    else:
        f = SkillFile(
            skill_id=skill_id,
            filename=filename,
            content=body.content,
            is_main=body.is_main or (filename == MAIN_FILE),
        )
        db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.delete("/{skill_id}/files/{filename:path}", status_code=204)
def delete_file(skill_id: str, filename: str, db: Session = Depends(get_db)):
    try:
        filename = normalize_script_filename(filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    f = db.query(SkillFile).filter_by(skill_id=skill_id, filename=filename).first()
    if not f:
        raise HTTPException(404, "File not found")
    if f.is_main:
        raise HTTPException(400, "Cannot delete SKILL.md")
    db.delete(f)
    db.commit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_or_404(skill_id: str, db: Session) -> Skill:
    s = db.query(Skill).filter_by(id=skill_id).first()
    if not s:
        raise HTTPException(404, "Skill not found")
    return s


def _default_skill_md(name: str, description: str) -> str:
    desc = description.strip() or "Describe what this skill does and when to use it."
    return f"""---
name: {name}
description: {desc}
---

# {name}

Write the step-by-step instructions the agent should follow when this skill is
active. Reference any supporting files you upload by their filename.

## Examples
- Example usage 1

## Guidelines
- Guideline 1
"""
