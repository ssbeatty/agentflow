from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Secret
from app.schemas import SecretCreate, SecretUpdate, SecretOut

router = APIRouter()


def _env_key(key: str) -> str:
    """How get_secret() will look this up: upper-cased (keys are already
    constrained to [A-Za-z_][A-Za-z0-9_]* by the schema)."""
    return (key or "").upper()


@router.get("", response_model=list[SecretOut])
def list_secrets(db: Session = Depends(get_db)):
    return db.query(Secret).order_by(Secret.key).all()


@router.post("", response_model=SecretOut, status_code=201)
def create_secret(body: SecretCreate, db: Session = Depends(get_db)):
    target = _env_key(body.key)
    # Reject keys that collide once normalized (e.g. "BarkKey" vs "barkkey").
    for existing in db.query(Secret).all():
        if _env_key(existing.key) == target:
            raise HTTPException(409, f"a secret resolving to {target!r} already exists")
    s = Secret(key=body.key, value=body.value, description=body.description)
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "secret key already exists")
    db.refresh(s)
    return s


@router.patch("/{sid}", response_model=SecretOut)
def update_secret(sid: str, body: SecretUpdate, db: Session = Depends(get_db)):
    s = _get_or_404(sid, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{sid}", status_code=204)
def delete_secret(sid: str, db: Session = Depends(get_db)):
    s = _get_or_404(sid, db)
    db.delete(s)
    db.commit()


def _get_or_404(sid: str, db: Session) -> Secret:
    s = db.query(Secret).filter_by(id=sid).first()
    if not s:
        raise HTTPException(404, "secret not found")
    return s
