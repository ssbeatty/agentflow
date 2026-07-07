"""Asynchronous, best-effort reclamation of a deleted script's on-disk folder.

Deleting a script must free its ``data/scripts/<id>/`` folder — the per-script
``.venv`` alone is hundreds of MB. Doing the ``rmtree`` inline made
``DELETE /api/scripts/{id}`` slow (seconds, dominated by the venv). Instead the
folder is reclaimed **off the request path** (a FastAPI ``BackgroundTask``), so
the endpoint returns as soon as the DB row + in-flight runs are gone and the UI
updates immediately.

The fallback: :func:`sweep_orphan_script_dirs` runs on startup and ``rmtree``s
any directory under ``DATA_DIR`` that has no live ``Script`` row — catching a
background delete that never finished (process killed mid-``rmtree``, or a
Windows file lock that left a partial folder). **Live scripts — including the
built-in AI assistant — are protected because they still have a DB row** (the
assistant is seeded before the sweep runs). Only ``<script_id>`` folders live
directly under ``DATA_DIR`` (skills / uploads / logs / the DB all live one level
up under ``data/``), so a dir there with no matching row is unambiguously an
orphan.
"""
from __future__ import annotations

import shutil

from loguru import logger

from app.config import DATA_DIR


def delete_script_dir(script_id: str) -> None:
    """``rmtree`` ``data/scripts/<id>/``. Best-effort — ``ignore_errors`` so a
    lingering Windows file handle can't fail the delete; the startup sweep
    retries later. Meant to run as a background task (off the request path)."""
    target = DATA_DIR / script_id
    if not target.exists():
        return
    shutil.rmtree(target, ignore_errors=True)
    if target.exists():
        # A file lock (e.g. a lingering venv python on Windows) blocked part of
        # the tree. Leave it — the next startup sweep will retry it as an orphan.
        logger.warning(
            "[script {}] on-disk folder not fully removed (file lock?); "
            "will retry on next startup sweep", script_id,
        )
    else:
        logger.info("[script {}] on-disk folder reclaimed", script_id)


def sweep_orphan_script_dirs(db) -> int:
    """Fallback cleanup: remove any ``data/scripts/<dir>`` whose name is not a
    live ``Script`` id — i.e. an incomplete background delete (or a partial
    folder a Windows lock left behind). Returns the count removed.

    Never deletes a live script's folder — including the built-in AI assistant,
    which always has a ``Script`` row. Skips dot-dirs and stray files."""
    from app.models import Script

    try:
        live_ids = {sid for (sid,) in db.query(Script.id).all()}
    except Exception:
        logger.exception("orphan script-dir sweep skipped (could not list scripts)")
        return 0

    try:
        entries = list(DATA_DIR.iterdir())
    except OSError:
        return 0

    removed = 0
    for entry in entries:
        name = entry.name
        if name.startswith(".") or not entry.is_dir():
            continue
        if name in live_ids:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
        logger.info("Reclaimed orphaned script folder: {}", name)
    return removed
