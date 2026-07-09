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
from services import conversation_threads

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
        reasoning_effort=body.reasoning_effort or "off",
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
    if body.reasoning_effort is not None:
        conv.reasoning_effort = body.reasoning_effort
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conv_id}", status_code=204)
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter_by(id=conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    # Reclaim this conversation's LangGraph thread from workspace/threads.db so
    # its checkpoints don't linger after the visible messages are gone (a deleted
    # conversation is never resumed). Best-effort; runs before the row is gone so
    # we still have script_id. See services/conversation_threads.py.
    conversation_threads.reset_thread(conv.script_id, conv_id)
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

    # ── Conversation threading anchor ─────────────────────────────────────────
    # The conversation is a durable LangGraph thread (thread_id == conv id). We
    # pass the thread id + an anchor checkpoint so a threaded agent resumes the
    # thread (and rolls back correctly if a later turn was deleted): the anchor is
    # the head checkpoint recorded on the most recent SURVIVING assistant turn.
    # No surviving anchor → wipe any stale thread so a fresh one starts. A
    # non-threaded chat script simply ignores thread_id and keeps using `history`.
    last_assistant = next(
        (m for m in reversed(prior) if m.role == "assistant"), None
    )
    anchor = last_assistant.checkpoint_id if last_assistant else None
    if not anchor:
        conversation_threads.reset_thread(conv.script_id, conv_id)

    # Create execution row. Thread the conversation's reasoning level into the
    # input so the script can pass it to get_llm(reasoning=input.get("reasoning")).
    exc = Execution(
        script_id=conv.script_id,
        input_data={
            "message": body.message,
            "history": history,
            "reasoning": conv.reasoning_effort or "off",
            "thread_id": conv_id,
            "checkpoint_id": anchor,
        },
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

    # The chain-of-thought is streamed over the WS only (not in output_data), so the
    # frontend hands it back here to persist for reload. Stored separately from
    # `content` so it never enters the model history built by chat_start.
    reasoning = (body.reasoning or "").strip() or None if exc.status == "completed" else None

    # Record the thread's head checkpoint after this turn (if the script ran as a
    # threaded agent → workspace/threads.db exists). The next turn anchors here;
    # deleting this turn later makes the previous message's checkpoint the anchor
    # (rollback). Best-effort: None for a non-threaded conversation.
    checkpoint_id = (
        conversation_threads.read_head_checkpoint(conv.script_id, conv_id)
        if exc.status == "completed"
        else None
    )

    assistant_msg = ConversationMessage(
        conversation_id=conv_id,
        role="assistant",
        content=content,
        reasoning=reasoning,
        error=error,
        execution_id=body.execution_id,
        checkpoint_id=checkpoint_id,
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assistant_msg)
    return assistant_msg
