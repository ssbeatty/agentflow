"""One-time data migration: move skills from the DB (`skills` / `skill_files`
tables) onto disk (backend/data/skills/<dir>/, see services/skill_store.py) and
rewrite every `script.skill_ids` binding from the old DB id to the new dir name.

Runs on startup (from the FastAPI lifespan). Idempotent and safe:
  - a skill already materialized on disk (sidecar `migrated_from_id` matches) is
    skipped but still contributes to the id→dir map so bindings are rewritten;
  - the legacy `skills` / `skill_files` rows are left in place (read-only) as a
    rollback backup — nothing else reads them once migrated.
"""
from __future__ import annotations


def migrate_skills_to_disk(db) -> int:
    """Returns the number of skills newly written to disk (0 if none)."""
    from app.models import Skill, Script
    from services import skill_store

    try:
        skills = db.query(Skill).all()
    except Exception:
        # legacy table may not exist on a brand-new database — nothing to do.
        return 0
    if not skills:
        return 0

    id_map: dict[str, str] = {}   # old DB id -> new dir name
    migrated = 0
    for sk in skills:
        existing = skill_store.find_by_migrated_id(sk.id)
        if existing:
            id_map[sk.id] = existing
            continue
        files = [
            {"filename": f.filename, "content": f.content or "", "is_main": bool(f.is_main)}
            for f in sk.files
        ]
        dir_name = skill_store.create_from_files(
            sk.name, sk.description or "", files,
            source=(sk.source or "manual"),
            migrated_from_id=sk.id,
            enabled=bool(sk.enabled),
        )
        id_map[sk.id] = dir_name
        migrated += 1

    # Rewrite script bindings id -> dir (runs even if migrated == 0, to recover
    # from a prior run that materialized skills but died before rebinding).
    changed = False
    for s in db.query(Script).all():
        ids = s.skill_ids or []
        if not ids:
            continue
        new = [id_map.get(x, x) for x in ids]
        if new != ids:
            s.skill_ids = new
            changed = True
    if changed:
        db.commit()

    return migrated
