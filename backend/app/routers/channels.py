from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Channel
from app.schemas import (
    ChannelCreate, ChannelUpdate, ChannelOut, ChannelSetDefault,
    ModelListRequest, ModelListResponse,
)

router = APIRouter()


@router.get("", response_model=list[ChannelOut])
def list_channels(db: Session = Depends(get_db)):
    return (
        db.query(Channel)
        .order_by(Channel.priority.desc(), Channel.created_at)
        .all()
    )


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelCreate, db: Session = Depends(get_db)):
    ch = Channel(**body.model_dump())
    db.add(ch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "channel could not be created")
    db.refresh(ch)
    return ch


@router.patch("/{cid}", response_model=ChannelOut)
def update_channel(cid: str, body: ChannelUpdate, db: Session = Depends(get_db)):
    ch = _get_or_404(cid, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(ch, k, v)
    db.commit()
    db.refresh(ch)
    return ch


@router.delete("/{cid}", status_code=204)
def delete_channel(cid: str, db: Session = Depends(get_db)):
    ch = _get_or_404(cid, db)
    db.delete(ch)
    db.commit()


@router.post("/{cid}/set-default", response_model=ChannelOut)
def set_default(cid: str, body: ChannelSetDefault, db: Session = Depends(get_db)):
    """Mark one of this channel's models as the global default (used by
    `get_llm()` with no name). Clears any previous default."""
    ch = _get_or_404(cid, db)
    models = ch.models or []
    model = body.model or (models[0] if models else None)
    if model and model not in models:
        raise HTTPException(400, "model is not served by this channel")
    db.query(Channel).filter(Channel.is_default == True).update(  # noqa: E712
        {"is_default": False, "default_model": None}
    )
    ch.is_default = True
    ch.default_model = model
    db.commit()
    db.refresh(ch)
    return ch


@router.post("/list-models", response_model=ModelListResponse)
def list_provider_models(body: ModelListRequest, db: Session = Depends(get_db)):
    """Fetch available model ids from a provider's API. If api_key is blank,
    reuse a stored key from an existing channel of the same provider."""
    from services.llm_models import list_models
    key = body.api_key
    if not key:
        existing = (
            db.query(Channel)
            .filter(Channel.provider == body.provider, Channel.api_key.isnot(None))
            .first()
        )
        if existing:
            key = existing.api_key
    try:
        return {"models": list_models(body.provider, key, body.base_url), "error": None}
    except Exception as e:  # noqa: BLE001 - surface provider/network errors to the UI
        return {"models": [], "error": f"{type(e).__name__}: {e}"}


def _get_or_404(cid: str, db: Session) -> Channel:
    ch = db.query(Channel).filter_by(id=cid).first()
    if not ch:
        raise HTTPException(404, "channel not found")
    return ch
