"""
API key issuance (admin only).

  GET    /api/api-keys        list issued keys (metadata only, never the secret)
  POST   /api/api-keys        issue a new key — returns the plaintext key ONCE
  DELETE /api/api-keys/{id}   revoke + remove a key

Keys authenticate external callers of POST /api/executions/run via the
`X-API-Key` header (or `Authorization: Bearer af_…`). Only the SHA-256 hash is
persisted, so a lost key cannot be recovered — issue a new one.
"""
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyOut, ApiKeyCreated
from app.auth_deps import require_admin
from app.security import generate_api_key

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db)):
    return db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_key(body: ApiKeyCreate, db: Session = Depends(get_db)):
    full, prefix, key_hash = generate_api_key()
    rec = ApiKey(name=(body.name or "API Key").strip(), prefix=prefix, key_hash=key_hash)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info("API key issued: {} (prefix={})", rec.id, prefix)
    out = ApiKeyOut.model_validate(rec).model_dump()
    return ApiKeyCreated(**out, key=full)


@router.delete("/{key_id}", status_code=204)
def delete_key(key_id: str, db: Session = Depends(get_db)):
    rec = db.query(ApiKey).filter_by(id=key_id).first()
    if not rec:
        raise HTTPException(404, "API key not found")
    db.delete(rec)
    db.commit()
    logger.info("API key revoked: {} (prefix={})", key_id, rec.prefix)
