from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LLMConfig
from app.schemas import LLMConfigCreate, LLMConfigUpdate, LLMConfigOut

router = APIRouter()


@router.get("", response_model=list[LLMConfigOut])
def list_configs(db: Session = Depends(get_db)):
    return db.query(LLMConfig).order_by(LLMConfig.created_at).all()


@router.post("", response_model=LLMConfigOut, status_code=201)
def create_config(body: LLMConfigCreate, db: Session = Depends(get_db)):
    if body.is_default:
        _clear_default(db)
    cfg = LLMConfig(**body.model_dump())
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.patch("/{cfg_id}", response_model=LLMConfigOut)
def update_config(cfg_id: str, body: LLMConfigUpdate, db: Session = Depends(get_db)):
    cfg = _get_or_404(cfg_id, db)
    data = body.model_dump(exclude_none=True)
    if data.get("is_default"):
        _clear_default(db)
    for k, v in data.items():
        setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.delete("/{cfg_id}", status_code=204)
def delete_config(cfg_id: str, db: Session = Depends(get_db)):
    cfg = _get_or_404(cfg_id, db)
    db.delete(cfg)
    db.commit()


@router.post("/{cfg_id}/set-default", response_model=LLMConfigOut)
def set_default(cfg_id: str, db: Session = Depends(get_db)):
    cfg = _get_or_404(cfg_id, db)
    _clear_default(db)
    cfg.is_default = True
    db.commit()
    db.refresh(cfg)
    return cfg


def _get_or_404(cfg_id: str, db: Session) -> LLMConfig:
    c = db.query(LLMConfig).filter_by(id=cfg_id).first()
    if not c:
        raise HTTPException(404, "LLM config not found")
    return c


def _clear_default(db: Session) -> None:
    db.query(LLMConfig).filter_by(is_default=True).update({"is_default": False})
    db.flush()
