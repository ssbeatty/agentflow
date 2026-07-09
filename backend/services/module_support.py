"""Reusable code modules for user scripts.

A **module** is a `Script` with `kind="module"`: importable Python code (a
package) that other scripts opt into via `script.module_ids` — exactly like
skills (`skill_ids`) / MCP servers (`mcp_server_ids`), *not* global. A module has
NO venv and is never run. At run time the engine materializes each bound module's
files into the REFERENCING script's `script_dir/modules/<package>/` and puts
`script_dir/modules` on `sys.path`, so the script can `from <package> import …`.
The module's own `requirements` are merged into the referencing script's venv
install (see `effective_requirements`) — deps land where the importing code runs.

Everything module-related lives here so the runtime seam (execution_engine +
worker_pool), the install sites, and the invalidation fan-out share one
implementation and never drift.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Script
from services.script_files import script_file_path

# Bound module files are copied under this subdir of the referencing script's dir;
# `script_dir/modules` is added to sys.path so `import <package>` resolves.
MODULES_SUBDIR = "modules"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize_package_name(name: str) -> str:
    """Best-effort slug of a display name into a valid Python package identifier
    (used as the default `module_package` when the author didn't set one)."""
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", (name or "").strip()).strip("_").lower()
    if not slug:
        return "module"
    if slug[0].isdigit():
        slug = "mod_" + slug
    return slug


def is_valid_package_name(name: str) -> bool:
    return bool(name) and bool(_IDENTIFIER.match(name))


def module_package_of(module: Script) -> str:
    """The importable package name for a module (explicit, else slug of name)."""
    return module.module_package or normalize_package_name(module.name)


def bound_modules(db: Session, script: Script) -> list[Script]:
    """The kind='module' Scripts this script binds via `module_ids`, in order.
    Silently drops ids that don't exist / aren't modules (mirrors skills)."""
    ids = list(getattr(script, "module_ids", None) or [])
    if not ids:
        return []
    rows = {
        m.id: m
        for m in db.query(Script)
        .filter(Script.id.in_(ids), Script.kind == "module")
        .all()
    }
    return [rows[i] for i in ids if i in rows]


def effective_requirements(db: Session, script: Script) -> str:
    """The script's own requirements plus every bound module's requirements,
    line-deduped case-insensitively (first occurrence wins, order preserved).

    This is what gets installed into the REFERENCING script's venv, so a module's
    dependencies are importable by the code that imports the module. Comments and
    blank lines are dropped (only spec lines matter for `pip install -r`)."""
    lines: list[str] = []
    seen: set[str] = set()
    blocks = [script.requirements or ""] + [m.requirements or "" for m in bound_modules(db, script)]
    for block in blocks:
        for ln in block.splitlines():
            spec = ln.strip()
            if not spec or spec.startswith("#"):
                continue
            key = spec.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(spec)
    return "\n".join(lines)


def materialize_modules(db: Session, script: Script, script_dir: Path) -> list[dict]:
    """Copy each bound module's files into `script_dir/modules/<package>/` so the
    referencing script can `import <package>`. Mirrors the engine's script-file
    materialization: skip-if-content-identical (so concurrent runs don't truncate
    a file mid-import) and ensure an `__init__.py` (so the dir is an importable
    package even if the author didn't add one). Returns a manifest for diagnostics.
    Best-effort per module — a bad package name is skipped, never raises."""
    manifest: list[dict] = []
    mods = bound_modules(db, script)
    if not mods:
        return manifest
    modules_root = script_dir / MODULES_SUBDIR
    for m in mods:
        pkg = module_package_of(m)
        if not is_valid_package_name(pkg):
            continue
        pkg_dir = modules_root / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)
        has_init = False
        for f in m.files:
            if f.filename == "__init__.py":
                has_init = True
            try:
                target = script_file_path(pkg_dir, f.filename)
            except ValueError:
                continue  # skip names that would escape the package dir
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if target.exists() and target.read_text(encoding="utf-8") == f.content:
                    continue
            except (OSError, UnicodeDecodeError):
                pass
            target.write_text(f.content, encoding="utf-8")
        if not has_init:
            init = pkg_dir / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
        manifest.append({
            "name": m.name,
            "package": pkg,
            "dir": str(pkg_dir),
            "files": [f.filename for f in m.files],
        })
    return manifest


def write_script_files(script: Script, script_dir: Path) -> None:
    """Write a script's own files into `script_dir` (skip-if-identical), so a warm
    worker booting straight from `script_dir` (preheat, before any run) finds
    main.py + helpers. The one-shot engine path materializes these itself; this
    covers the eager-preheat paths that boot a worker without a preceding run."""
    for f in script.files:
        try:
            target = script_file_path(script_dir, f.filename)
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if target.exists() and target.read_text(encoding="utf-8") == f.content:
                continue
        except (OSError, UnicodeDecodeError):
            pass
        target.write_text(f.content, encoding="utf-8")


def prepare_worker_dir(db: Session, script: Script, script_dir: Path) -> list[dict]:
    """Materialize a script's own files + its bound modules into `script_dir`
    before a warm worker boots from it (preheat paths). Returns the module
    manifest."""
    write_script_files(script, script_dir)
    return materialize_modules(db, script, script_dir)


def dependent_script_ids(db: Session, module_id: str) -> list[str]:
    """Every Script whose `module_ids` includes this module — the set whose warm
    worker / cached schema goes stale when the module's code changes. Scanned live
    (scripts are few, admin-scale); a JSON-contains filter isn't portable across
    sqlite + postgres, so we filter in Python."""
    out: list[str] = []
    for s in db.query(Script).all():
        if module_id in (s.module_ids or []):
            out.append(s.id)
    return out
