"""Disk-backed Skill storage.

A **Skill** is an Agent Skill: a folder with a ``SKILL.md`` (YAML frontmatter
``name``/``description`` + markdown instructions) plus any supporting files.

Unlike scripts (whose file contents live in the DB), skills are stored **purely
on disk** under ``backend/data/skills/<dir>/``:

  backend/data/skills/
    my-skill/
      SKILL.md            # is_main; name+description in frontmatter
      references/…        # arbitrary supporting files / nested folders
      .agentflow.json     # our sidecar: {enabled, source, installed_at, upstream}

The **directory name is the skill's stable identity** (used in ``script.skill_ids``
and in the ``/api/skills/{id}`` routes). Display name/description come from the
SKILL.md frontmatter; AgentFlow-specific state (enabled flag, install provenance)
lives in the ``.agentflow.json`` sidecar so the rest of the folder stays a clean,
portable Agent Skill (installable from / exportable to the marketplace as-is).

This module is the single place that touches the skills directory; the router,
the runtime materializer (execution_engine) and the marketplace all go through it.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from app.config import DATA_DIR
from services.script_files import normalize_script_filename

# data/skills sits next to data/scripts (DATA_DIR) — both under backend/data.
SKILLS_ROOT: Path = DATA_DIR.parent / "skills"

MAIN_FILE = "SKILL.md"
SIDECAR = ".agentflow.json"
_TEXT_MAX = 512 * 1024  # editor content cap (bytes)

_DIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ── paths & identity ──────────────────────────────────────────────────────────

def skills_root() -> Path:
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    return SKILLS_ROOT


def _valid_dirname(name: str) -> str:
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", "..") or not _DIR_RE.match(name):
        raise ValueError(f"invalid skill id {name!r}")
    return name


def skill_dir(dir_name: str) -> Path:
    """Resolve a skill's directory, guarding against path escapes."""
    d = _valid_dirname(dir_name)
    root = skills_root().resolve()
    target = (root / d).resolve()
    if target.parent != root:
        raise ValueError("skill id escapes skills root")
    return target


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-.")
    return slug or "skill"


def _unique_dir(slug: str) -> str:
    root = skills_root()
    cand, i = slug, 2
    while (root / cand).exists():
        cand = f"{slug}-{i}"
        i += 1
    return cand


def _safe_path(d: Path, rel: str) -> Path:
    root = d.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("path escapes skill directory")
    return target


# ── frontmatter (minimal, dependency-free) ────────────────────────────────────

def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _quote(v: str) -> str:
    v = (v or "").replace("\n", " ").strip()
    if v == "" or v[0] in "!&*[]{}>|%@`\"'#" or ": " in v or v.endswith(":") or "#" in v:
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (meta, body). meta holds top-level ``key: scalar`` pairs only."""
    meta: dict = {}
    body = text or ""
    lines = body.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            for ln in lines[1:end]:
                s = ln.strip()
                if not s or s.startswith("#") or ":" not in ln:
                    continue
                # top-level keys only (no leading indent → part of a nested block)
                if ln[:1] in (" ", "\t"):
                    continue
                k, _, v = ln.partition(":")
                meta[k.strip()] = _unquote(v.strip())
            body = "\n".join(lines[end + 1:])
            body = body[1:] if body.startswith("\n") else body
    return meta, body


def set_frontmatter(text: str, name: str, description: str) -> str:
    """Rewrite the SKILL.md frontmatter's name/description, preserving the body
    and any other frontmatter keys."""
    meta, body = parse_frontmatter(text)
    meta["name"] = name
    meta["description"] = description
    order = ["name", "description"] + [k for k in meta if k not in ("name", "description")]
    out = ["---"] + [f"{k}: {_quote(str(meta[k]))}" for k in order] + ["---"]
    fm = "\n".join(out)
    return f"{fm}\n\n{body.lstrip(chr(10))}" if body.strip() else fm + "\n"


def default_skill_md(name: str, description: str) -> str:
    desc = (description or "").strip() or "Describe what this skill does and when to use it."
    return f"""---
name: {name}
description: {_quote(desc) if (':' in desc or '#' in desc) else desc}
---

# {name}

Write the step-by-step instructions the agent should follow when this skill is
active. Reference any supporting files you upload by their filename.

## Examples
- Example usage 1

## Guidelines
- Guideline 1
"""


# ── sidecar ───────────────────────────────────────────────────────────────────

def read_sidecar(d: Path) -> dict:
    p = d / SIDECAR
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def write_sidecar(d: Path, data: dict) -> None:
    (d / SIDECAR).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ── file reads ────────────────────────────────────────────────────────────────

def _is_hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in Path(rel).parts)


def _iter_files(d: Path):
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(d).as_posix()
        if _is_hidden(rel):  # sidecar + any dotfile/dotdir (e.g. .git, .claude-plugin)
            continue
        yield rel, p


def _iter_dirs(d: Path):
    for p in sorted(d.rglob("*")):
        if not p.is_dir():
            continue
        rel = p.relative_to(d).as_posix()
        if _is_hidden(rel):
            continue
        yield rel


def _read_text(p: Path) -> str:
    try:
        raw = p.read_bytes()
    except Exception:
        return ""
    if len(raw) > _TEXT_MAX:
        return f"<file too large to display in editor: {len(raw)} bytes>"
    if b"\x00" in raw:
        return f"<binary file: {len(raw)} bytes — edit on disk>"
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary file: {len(raw)} bytes — edit on disk>"


def _latest_mtime(d: Path) -> float:
    mt = d.stat().st_mtime
    for _, p in _iter_files(d):
        try:
            mt = max(mt, p.stat().st_mtime)
        except OSError:
            pass
    return mt


# ── summaries / detail (shapes match schemas.SkillSummary / SkillDetail) ───────

def _summary(d: Path) -> dict:
    main = d / MAIN_FILE
    meta = parse_frontmatter(main.read_text(encoding="utf-8", errors="replace"))[0] if main.is_file() else {}
    side = read_sidecar(d)
    st = d.stat()
    return {
        "id": d.name,
        "name": (meta.get("name") or d.name).strip() or d.name,
        "description": (meta.get("description") or "").strip(),
        "enabled": bool(side.get("enabled", True)),
        "source": side.get("source", "manual"),
        "created_at": datetime.utcfromtimestamp(st.st_ctime),
        "updated_at": datetime.utcfromtimestamp(_latest_mtime(d)),
    }


def _is_skill_dir(d: Path) -> bool:
    return d.is_dir() and not d.name.startswith(".") and (d / MAIN_FILE).is_file()


def list_skills() -> list[dict]:
    out = []
    for d in sorted(skills_root().iterdir()):
        if _is_skill_dir(d):
            try:
                out.append(_summary(d))
            except Exception:
                continue
    return out


def get_skill(dir_name: str) -> dict:
    d = skill_dir(dir_name)
    if not _is_skill_dir(d):
        raise FileNotFoundError(dir_name)
    summ = _summary(d)
    files = []
    for rel, p in _iter_files(d):
        files.append({
            "id": f"{dir_name}:{rel}",
            "skill_id": dir_name,
            "filename": rel,
            "content": _read_text(p),
            "is_main": rel == MAIN_FILE,
            "updated_at": datetime.utcfromtimestamp(p.stat().st_mtime),
        })
    summ["files"] = files
    summ["dirs"] = list(_iter_dirs(d))
    return summ


def exists(dir_name: str) -> bool:
    try:
        return _is_skill_dir(skill_dir(dir_name))
    except ValueError:
        return False


# ── mutations ─────────────────────────────────────────────────────────────────

def create_skill(name: str, description: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    dir_name = _unique_dir(slugify(name))
    d = skill_dir(dir_name)
    d.mkdir(parents=True, exist_ok=False)
    (d / MAIN_FILE).write_text(default_skill_md(name, description), encoding="utf-8")
    write_sidecar(d, {"enabled": True, "source": "manual", "installed_at": _now_iso()})
    return get_skill(dir_name)


def create_from_files(name: str, description: str, files: list[dict], *,
                      source: str = "manual", migrated_from_id: str | None = None,
                      enabled: bool = True, upstream: str = "") -> str:
    """Create a skill folder from an in-memory list of ``{filename, content,
    is_main}`` (used by the DB→disk migration). Ensures a SKILL.md exists whose
    frontmatter reflects the given name/description. Returns the new dir name."""
    dir_name = _unique_dir(slugify(name or "skill"))
    d = skill_dir(dir_name)
    d.mkdir(parents=True, exist_ok=False)
    for f in files or []:
        try:
            rel = normalize_script_filename(f.get("filename", ""))
        except ValueError:
            continue
        if _is_hidden(rel):
            continue
        target = _safe_path(d, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.get("content") or "", encoding="utf-8")
    main = d / MAIN_FILE
    text = main.read_text(encoding="utf-8", errors="replace") if main.is_file() else ""
    main.write_text(set_frontmatter(text, (name or dir_name).strip() or dir_name,
                                    (description or "").strip()), encoding="utf-8")
    side = {"enabled": enabled, "source": source, "installed_at": _now_iso()}
    if migrated_from_id:
        side["migrated_from_id"] = migrated_from_id
    if upstream:
        side["upstream"] = upstream
    write_sidecar(d, side)
    return dir_name


def update_skill(dir_name: str, *, name=None, description=None, enabled=None) -> dict:
    d = skill_dir(dir_name)
    if not _is_skill_dir(d):
        raise FileNotFoundError(dir_name)
    if name is not None or description is not None:
        main = d / MAIN_FILE
        text = main.read_text(encoding="utf-8", errors="replace") if main.is_file() else ""
        meta = parse_frontmatter(text)[0]
        new_name = (name if name is not None else meta.get("name") or dir_name).strip() or dir_name
        new_desc = description if description is not None else (meta.get("description") or "")
        main.write_text(set_frontmatter(text, new_name, new_desc), encoding="utf-8")
    if enabled is not None:
        side = read_sidecar(d)
        side["enabled"] = bool(enabled)
        write_sidecar(d, side)
    return get_skill(dir_name)


def delete_skill(dir_name: str) -> None:
    d = skill_dir(dir_name)
    if d.is_dir():
        shutil.rmtree(d)


def upsert_file(dir_name: str, filename: str, content: str = "", is_main: bool = False) -> dict:
    d = skill_dir(dir_name)
    if not _is_skill_dir(d):
        raise FileNotFoundError(dir_name)
    rel = normalize_script_filename(filename)
    if _is_hidden(rel):
        raise ValueError("filename conflicts with AgentFlow skill metadata")
    target = _safe_path(d, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content or "", encoding="utf-8")
    return {
        "id": f"{dir_name}:{rel}",
        "skill_id": dir_name,
        "filename": rel,
        "content": content or "",
        "is_main": rel == MAIN_FILE,
        "updated_at": datetime.utcfromtimestamp(target.stat().st_mtime),
    }


def delete_file(dir_name: str, filename: str) -> None:
    d = skill_dir(dir_name)
    rel = normalize_script_filename(filename)
    if rel == MAIN_FILE:
        raise ValueError("cannot delete SKILL.md")
    target = _safe_path(d, rel)
    if not target.is_file():
        raise FileNotFoundError(rel)
    target.unlink()
    _prune_empty(target.parent, d)


def create_dir(dir_name: str, relpath: str) -> None:
    d = skill_dir(dir_name)
    if not _is_skill_dir(d):
        raise FileNotFoundError(dir_name)
    rel = normalize_script_filename(relpath)
    if _is_hidden(rel):
        raise ValueError("folder name conflicts with AgentFlow skill metadata")
    _safe_path(d, rel).mkdir(parents=True, exist_ok=True)


def delete_dir(dir_name: str, relpath: str) -> None:
    """Delete a folder and everything under it inside a skill. The skill root and
    its metadata are protected; SKILL.md lives at the root so it's never inside a
    deletable subfolder."""
    d = skill_dir(dir_name)
    if not _is_skill_dir(d):
        raise FileNotFoundError(dir_name)
    rel = normalize_script_filename(relpath)
    if _is_hidden(rel):
        raise ValueError("cannot delete AgentFlow skill metadata")
    target = _safe_path(d, rel)
    if target.resolve() == d.resolve():
        raise ValueError("cannot delete the skill root")
    if not target.is_dir():
        raise FileNotFoundError(rel)
    shutil.rmtree(target)
    _prune_empty(target.parent, d)


def _prune_empty(start: Path, stop: Path) -> None:
    """Remove now-empty parent dirs up to (but not including) the skill root."""
    cur = start.resolve()
    stop = stop.resolve()
    while cur != stop and stop in cur.parents:
        try:
            next(cur.iterdir())
            return  # not empty
        except StopIteration:
            parent = cur.parent
            cur.rmdir()
            cur = parent
        except OSError:
            return


# ── import (used by marketplace install + DB→disk migration) ──────────────────

def import_skill_dir(src: Path, *, source: str, upstream: str = "",
                     slug: str | None = None, migrated_from_id: str | None = None,
                     enabled: bool = True) -> str:
    """Copy an on-disk skill folder (must contain SKILL.md at its root) into the
    skills store under a fresh unique dir, writing our sidecar. Returns the dir."""
    if not (src / MAIN_FILE).is_file():
        raise ValueError("source folder has no SKILL.md at its root")
    meta = parse_frontmatter((src / MAIN_FILE).read_text(encoding="utf-8", errors="replace"))[0]
    base = slug or slugify(meta.get("name") or src.name)
    dir_name = _unique_dir(base)
    dest = skill_dir(dir_name)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(SIDECAR, ".git", "__pycache__"))
    side = {"enabled": enabled, "source": source, "installed_at": _now_iso()}
    if upstream:
        side["upstream"] = upstream
    if migrated_from_id:
        side["migrated_from_id"] = migrated_from_id
    write_sidecar(dest, side)
    return dir_name


def find_by_upstream(upstream: str) -> str | None:
    for d in skills_root().iterdir():
        if _is_skill_dir(d) and read_sidecar(d).get("upstream") == upstream:
            return d.name
    return None


def find_by_migrated_id(old_id: str) -> str | None:
    for d in skills_root().iterdir():
        if _is_skill_dir(d) and read_sidecar(d).get("migrated_from_id") == old_id:
            return d.name
    return None


# ── runtime manifest (used by execution_engine) ───────────────────────────────

def manifest_entry(dir_name: str) -> dict | None:
    """Return {dir(Path), name, description, main} for an *enabled* skill, else None."""
    try:
        d = skill_dir(dir_name)
    except ValueError:
        return None
    if not _is_skill_dir(d):
        return None
    if not read_sidecar(d).get("enabled", True):
        return None
    meta = parse_frontmatter((d / MAIN_FILE).read_text(encoding="utf-8", errors="replace"))[0]
    return {
        "dir": d,
        "name": (meta.get("name") or dir_name).strip() or dir_name,
        "description": (meta.get("description") or "").strip(),
        "main": MAIN_FILE,
    }
