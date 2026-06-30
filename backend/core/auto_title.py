"""
backend/core/auto_title.py  —  Phase 16

Auto-generates meaningful conversation titles after the first exchange.
Previously all conversations were titled "New Conversation" permanently.

Called from api/chat.py after the first assistant response in a new
conversation. Runs in a background thread (non-blocking).
"""

from __future__ import annotations

from backend.core.logger import agent_logger


def generate_title(user_message: str, assistant_message: str) -> str:
    """
    Generate a short, descriptive conversation title (max 8 words).
    Falls back to a truncated user message if LLM fails.
    """
    try:
        from backend.core.llm import ask_llm_raw
        prompt = (
            f"Generate a short, descriptive title for this conversation (max 6 words).\n"
            f"User: {user_message[:200]}\n"
            f"Assistant: {assistant_message[:200]}\n\n"
            f"Rules:\n"
            f"- 3-6 words maximum\n"
            f"- Capture the main topic specifically\n"
            f"- No quotes, no punctuation at end\n"
            f"- Examples: 'GATE 2027 Preparation Plan', 'Python Learning Roadmap',\n"
            f"  'Grocery Shopping List', 'Agentic AI Basics'\n"
            f"Return ONLY the title, nothing else."
        )
        title = ask_llm_raw(prompt).strip().strip('"').strip("'")
        # Cap at 60 chars
        if len(title) > 60:
            title = title[:57] + "..."
        return title if title else _fallback_title(user_message)
    except Exception as e:
        agent_logger.debug(f"[AutoTitle] failed: {e}")
        return _fallback_title(user_message)


def _fallback_title(user_message: str) -> str:
    """Truncate user message as fallback title."""
    clean = user_message.strip()
    if len(clean) > 50:
        clean = clean[:47] + "..."
    return clean or "Conversation"


def auto_title_conversation(conv_id: int, user_message: str, assistant_message: str):
    """
    Update conversation title in background thread.
    Only runs when title is still the default "New Conversation".
    """
    try:
        from backend.database.db import SessionLocal
        from backend.database.models import Conversation

        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
            if not conv:
                return
            # Only auto-title if still the default
            if conv.title and conv.title not in ("New Conversation", ""):
                return
            title = generate_title(user_message, assistant_message)
            conv.title = title
            db.commit()
            agent_logger.info(f"[AutoTitle] conv {conv_id} → '{title}'")
        finally:
            db.close()
    except Exception as e:
        agent_logger.error(f"[AutoTitle] conv {conv_id} error: {e}")
