"""
Upload arbitrary files that user scripts can read as input.

Endpoints:
    POST   /api/files/upload?script_id=...   multipart "file" → {id, name, size, mime}
    GET    /api/files                        ?script_id=...   list metadata
    GET    /api/files/{file_id}/meta         metadata only
    GET    /api/files/{file_id}              raw bytes (download/preview)
    DELETE /api/files/{file_id}              remove from DB + disk

Files are referenced inside `Execution.input_data` via {"$file": "<file_id>"} markers;
the execution engine resolves and injects them at run time.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UploadedFile, Script
from services import file_storage

router = APIRouter()


class UploadedFileOut(BaseModel):
    id: str
    original_name: str
    mime: Optional[str] = None
    size: int
    script_id: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: UploadedFile) -> "UploadedFileOut":
        return cls(
            id=row.id,
            original_name=row.original_name,
            mime=row.mime,
            size=row.size,
            script_id=row.script_id,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )


@router.post("/upload", response_model=UploadedFileOut, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    script_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if script_id and not db.query(Script).filter_by(id=script_id).first():
        raise HTTPException(status_code=404, detail="script not found")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    row = UploadedFile(
        original_name=file.filename or "unnamed",
        mime=file.content_type,
        size=len(data),
        script_id=script_id,
        storage_path="",  # set after we know the id
    )
    db.add(row)
    db.flush()  # populate row.id

    file_storage.write_blob(row.id, data, row.original_name, row.mime)
    row.storage_path = str(file_storage.blob_path(row.id))
    db.commit()
    db.refresh(row)
    return UploadedFileOut.from_row(row)


@router.get("", response_model=list[UploadedFileOut])
def list_files(script_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(UploadedFile)
    if script_id:
        # include both script-scoped and globally-uploaded files
        q = q.filter((UploadedFile.script_id == script_id) | (UploadedFile.script_id.is_(None)))
    rows = q.order_by(UploadedFile.created_at.desc()).all()
    return [UploadedFileOut.from_row(r) for r in rows]


@router.get("/{file_id}/meta", response_model=UploadedFileOut)
def get_meta(file_id: str, db: Session = Depends(get_db)):
    row = db.query(UploadedFile).filter_by(id=file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    return UploadedFileOut.from_row(row)


@router.get("/{file_id}")
def download_file(file_id: str, db: Session = Depends(get_db)):
    row = db.query(UploadedFile).filter_by(id=file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    bp = file_storage.blob_path(file_id)
    if not bp.is_file():
        raise HTTPException(status_code=404, detail="blob missing on disk")
    return FileResponse(
        bp,
        media_type=row.mime or "application/octet-stream",
        filename=row.original_name,
    )


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    row = db.query(UploadedFile).filter_by(id=file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    db.delete(row)
    db.commit()
    file_storage.delete_blob(file_id)
    return None
