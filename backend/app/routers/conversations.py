import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Conversation, ConversationMessage, Execution, Script
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationMessageOut,
    ConversationSummary,
    ConversationUpdate,
    ConverseConfirmRequest,
    ConverseChatStartRequest,
)
from services.execution_engine import spawn_execution

router = APIRouter()


def _extract_reply(output_data) -> str:
    if output_data is None:
        return ""
    if isinstance(output_data, str):
        return output_data
    if isinstance(output_data, dict):
        for field in ("reply", "message", "response", "result"):
            if field in output_data:
                return str(output_data[field])
    return json.dumps(output_data, ensure_ascii=False)


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ConversationSummary])
def list_conversations(script_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Conversation).order_by(Conversation.updated_at.desc())
    if script_id:
        q = q.filter_by(script_id=script_id)
    return q.all()


@router.post("", response_model=ConversationDetail, status_code=201)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    if not db.query(Script).filter_by(id=body.script_id).first():
        raise HTTPException(404, "Script not found")
    conv = Conversation(
        script_id=body.script_id,
        title=body.title,
        context_turns=body.context_turns,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("/{conv_id}", response_model=ConversationDetail)
def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter_by(id=conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.patch("/{conv_id}", response_model=ConversationSummary)
def update_conversation(conv_id: str, body: ConversationUpdate, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter_by(id=conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if body.title is not None:
        conv.title = body.title
    if body.context_turns is not None:
        conv.context_turns = body.context_turns
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conv_id}", status_code=204)
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter_by(id=conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    db.delete(conv)
    db.commit()


# ── Message CRUD ─────────────────────────────────────────────────────────────

@router.delete("/{conv_id}/messages/{msg_id}", status_code=204)
def delete_message(conv_id: str, msg_id: str, db: Session = Depends(get_db)):
    msg = db.query(ConversationMessage).filter_by(id=msg_id, conversation_id=conv_id).first()
    if not msg:
        raise HTTPException(404, "Message not found")
    db.delete(msg)
    db.commit()


# ── Chat (non-blocking start) ─────────────────────────────────────────────────

@router.post("/{conv_id}/chat")
async def chat_start(conv_id: str, body: ConverseChatStartRequest, db: Session = Depends(get_db)):
    """
    Persist the user message, create an execution, start it non-blocking,
    and immediately return {execution_id, user_msg_id}.

    The caller should:
      1. Open WebSocket to /ws/executions/{execution_id} to receive streaming tokens
      2. On status:completed/failed, call POST /{conv_id}/confirm to persist the reply
    """
    conv = db.query(Conversation).filter_by(id=conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    # Guard against concurrent sends — check if the latest assistant message's
    # execution is still running
    last_msg = (
        db.query(ConversationMessage)
        .filter_by(conversation_id=conv_id, role="assistant")
        .order_by(ConversationMessage.created_at.desc())
        .first()
    )
    if last_msg and last_msg.execution_id:
        running_exc = db.query(Execution).filter_by(
            id=last_msg.execution_id
        ).first()
        if running_exc and running_exc.status in ("pending", "queued", "running"):
            raise HTTPException(409, "A reply is already being generated for this conversation")

    # Persist user message immediately
    user_msg = ConversationMessage(
        conversation_id=conv_id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Build history slice from prior messages
    all_msgs = (
        db.query(ConversationMessage)
        .filter_by(conversation_id=conv_id)
        .order_by(ConversationMessage.created_at)
        .all()
    )
    # Exclude the user message we just saved; take last context_turns pairs
    prior = [m for m in all_msgs[:-1] if not m.error]
    history_slice = prior[-(conv.context_turns * 2):]
    history = [{"role": m.role, "content": m.content} for m in history_slice]

    # Create execution row
    exc = Execution(
        script_id=conv.script_id,
        input_data={"message": body.message, "history": history},
    )
    db.add(exc)
    db.commit()
    db.refresh(exc)

    # Start non-blocking
    spawn_execution(exc.id)

    return {"execution_id": exc.id, "user_msg_id": user_msg.id}


# ── Confirm (persist assistant reply after WS signals completion) ─────────────

@router.post("/{conv_id}/confirm", response_model=ConversationMessageOut)
def confirm_reply(conv_id: str, body: ConverseConfirmRequest, db: Session = Depends(get_db)):
    """
    Called by the frontend after the WebSocket signals execution completion.
    Reads Execution.output_data and persists the assistant ConversationMessage.
    """
    conv = db.query(Conversation).filter_by(id=conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    exc = db.query(Execution).filter_by(id=body.execution_id).first()
    if not exc:
        raise HTTPException(404, "Execution not found")

    if exc.status not in ("completed", "failed", "cancelled"):
        raise HTTPException(409, f"Execution is still {exc.status}")

    if exc.status == "completed":
        content = _extract_reply(exc.output_data)
        error = None
    else:
        content = ""
        error = exc.error or f"Execution {exc.status}"

    assistant_msg = ConversationMessage(
        conversation_id=conv_id,
        role="assistant",
        content=content,
        error=error,
        execution_id=body.execution_id,
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assistant_msg)
    return assistant_msg
