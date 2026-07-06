import asyncio

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NotificationChannel
from app.schemas import (
    NotificationChannelCreate, NotificationChannelUpdate, NotificationChannelOut,
    _NOTIFY_SECRET_KEYS,
)
from services import notifications

router = APIRouter()


def _get_or_404(cid: str, db: Session) -> NotificationChannel:
    ch = db.query(NotificationChannel).filter_by(id=cid).first()
    if not ch:
        raise HTTPException(404, "notification channel not found")
    return ch


@router.get("", response_model=list[NotificationChannelOut])
def list_channels(db: Session = Depends(get_db)):
    return db.query(NotificationChannel).order_by(NotificationChannel.created_at).all()


@router.post("", response_model=NotificationChannelOut, status_code=201)
def create_channel(body: NotificationChannelCreate, db: Session = Depends(get_db)):
    ch = NotificationChannel(
        name=body.name, type=body.type, enabled=body.enabled,
        config=body.config or {},
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    logger.info("Notification channel created: {} ({}/{})", ch.id, ch.type, ch.name)
    return ch


@router.patch("/{cid}", response_model=NotificationChannelOut)
def update_channel(cid: str, body: NotificationChannelUpdate, db: Session = Depends(get_db)):
    ch = _get_or_404(cid, db)
    if body.name is not None:
        ch.name = body.name
    if body.enabled is not None:
        ch.enabled = body.enabled
    if body.config is not None:
        merged = dict(body.config)
        old = ch.config or {}
        # The UI never re-sends stored secrets, so a blank/missing secret sub-key
        # means "keep the existing one" rather than "clear it".
        for k in _NOTIFY_SECRET_KEYS:
            if not merged.get(k) and old.get(k):
                merged[k] = old[k]
        ch.config = merged
    db.commit()
    db.refresh(ch)
    logger.info("Notification channel updated: {} ({})", cid, ch.name)
    return ch


@router.delete("/{cid}", status_code=204)
def delete_channel(cid: str, db: Session = Depends(get_db)):
    ch = _get_or_404(cid, db)
    db.delete(ch)
    db.commit()
    logger.info("Notification channel deleted: {} ({})", cid, ch.name)


@router.post("/{cid}/test")
async def test_channel(cid: str, db: Session = Depends(get_db)):
    """Send a canned test message through the channel's stored config."""
    ch = _get_or_404(cid, db)
    ok, error = await asyncio.to_thread(notifications.send_test, ch)
    if ok:
        logger.info("Notification channel test OK: {} ({})", cid, ch.name)
    else:
        logger.warning("Notification channel test failed: {} ({}): {}", cid, ch.name, error)
    return {"ok": ok, "error": error}
