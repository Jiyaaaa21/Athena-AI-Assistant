"""
memory_service.py — Phase 6 addition: update_message_content()
Phase 12 addition: every function is now scoped to the current
authenticated user (see core/request_context.py) so two users' chat
memories never mix. All existing function signatures are unchanged --
callers (agent.py, llm.py, api/memory.py, api/chat.py) needed zero edits.

PHASE 15 FIX: get_history() now has a hard cap (last 20 messages) so it
never overflows the LLM context window. Also added
seed_from_conversation() so loading a saved Conversation properly
pre-populates the in-memory history used by the LLM — previously the
two tables were disconnected and switching conversations reset context.
"""
from backend.database.db import SessionLocal
from backend.database.models import Message, ConversationMessage, Conversation
from backend.core.request_context import get_current_user_id

# Hard cap on how many messages we feed to the LLM. Keeps token usage
# predictable. Increase if you're on a higher-TPM plan.
_HISTORY_CAP = 20


def add_message(role, content):
    db = SessionLocal()
    try:
        message = Message(
            role=role,
            content=content,
            user_id=get_current_user_id(),
        )
        db.add(message)
        db.commit()
    finally:
        db.close()


def get_history():
    db = SessionLocal()
    try:
        messages = (
            db.query(Message)
            .filter(Message.user_id == get_current_user_id())
            .order_by(Message.id.desc())
            .limit(_HISTORY_CAP)
            .all()
        )
        # Reverse so oldest-first (correct chronological order for LLM)
        messages = list(reversed(messages))
        return [{"role": msg.role, "content": msg.content} for msg in messages]
    finally:
        db.close()


def get_history_with_ids():
    db = SessionLocal()
    try:
        messages = (
            db.query(Message)
            .filter(Message.user_id == get_current_user_id())
            .order_by(Message.id)
            .all()
        )
        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "createdAt": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ]
    finally:
        db.close()


def seed_from_conversation(conv_id: int):
    """
    PHASE 15 FIX: Load a saved Conversation's messages into the global
    Message table (memory) for the current user so the LLM has context
    when the user resumes that conversation.

    This bridges the gap between ConversationMessage (UI-layer storage)
    and Message (LLM-context storage), which were previously disconnected.
    Call this when a user selects a conversation from the sidebar.

    Strategy: clear current memory, write last 20 messages from conv.
    """
    uid = get_current_user_id()
    if not uid:
        return

    db = SessionLocal()
    try:
        # Verify ownership
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id,
            Conversation.user_id == uid,
        ).first()
        if not conv:
            return

        # Fetch last 20 messages from this conversation
        msgs = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conv_id)
            .order_by(ConversationMessage.id.desc())
            .limit(_HISTORY_CAP)
            .all()
        )
        msgs = list(reversed(msgs))  # oldest first

        if not msgs:
            return

        # Clear existing memory for this user
        db.query(Message).filter(Message.user_id == uid).delete()

        # Write conversation messages into memory
        for m in msgs:
            db.add(Message(
                role=m.role,
                content=m.content or "",
                user_id=uid,
            ))

        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def delete_message(message_id: int) -> bool:
    db = SessionLocal()
    try:
        message = (
            db.query(Message)
            .filter(Message.id == message_id, Message.user_id == get_current_user_id())
            .first()
        )
        if not message:
            return False
        db.delete(message)
        db.commit()
        return True
    finally:
        db.close()


def update_message_content(message_id: int, content: str) -> bool:
    """Phase 6 addition: edit the content of an existing memory entry."""
    db = SessionLocal()
    try:
        message = (
            db.query(Message)
            .filter(Message.id == message_id, Message.user_id == get_current_user_id())
            .first()
        )
        if not message:
            return False
        message.content = content
        db.commit()
        return True
    finally:
        db.close()


def clear_memory():
    db = SessionLocal()
    try:
        db.query(Message).filter(Message.user_id == get_current_user_id()).delete()
        db.commit()
    finally:
        db.close()
