"""
Uploaded-file storage on local disk.

Layout:
    <UPLOADS_DIR>/<file_id>/blob          # raw bytes
    <UPLOADS_DIR>/<file_id>/meta.json     # {original_name, mime, size}

UPLOADS_DIR defaults to BACKEND_ROOT/data/uploads.
"""
import json
import shutil
from pathlib import Path

from app.config import DATA_DIR

UPLOADS_DIR: Path = DATA_DIR.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _entry_dir(file_id: str) -> Path:
    return UPLOADS_DIR / file_id


def blob_path(file_id: str) -> Path:
    return _entry_dir(file_id) / "blob"


def meta_path(file_id: str) -> Path:
    return _entry_dir(file_id) / "meta.json"


def write_blob(file_id: str, data: bytes, original_name: str, mime: str | None) -> int:
    d = _entry_dir(file_id)
    d.mkdir(parents=True, exist_ok=True)
    bp = blob_path(file_id)
    bp.write_bytes(data)
    meta_path(file_id).write_text(
        json.dumps({"original_name": original_name, "mime": mime or "", "size": len(data)}),
        encoding="utf-8",
    )
    return len(data)


def delete_blob(file_id: str) -> None:
    d = _entry_dir(file_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
