"""
backend/api/user_memory.py  —  Phase 16

API endpoints for the semantic long-term memory (UserFact) system.
The Memory page now shows two sections:
  1. Conversation history (existing GET /memory)
  2. What Athena knows about you (new GET /memory/facts)
"""
from fastapi import APIRouter, HTTPException
from backend.core.memory_intelligence import list_user_facts, delete_user_fact
from backend.core.request_context import get_current_user_id

router = APIRouter()


@router.get("/memory/facts")
def get_user_facts():
    """Return all semantic facts Athena has learned about this user."""
    uid = get_current_user_id()
    if not uid:
        return {"facts": []}
    return {"facts": list_user_facts(uid)}


@router.delete("/memory/facts/{fact_id}")
def delete_fact(fact_id: int):
    """Let user remove a specific memory fact (forget it)."""
    uid = get_current_user_id()
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    ok = delete_user_fact(fact_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"deleted": fact_id}


@router.delete("/memory/facts")
def clear_all_facts():
    """Wipe all semantic facts for this user."""
    from backend.database.db import SessionLocal
    from backend.database.models import UserFact
    uid = get_current_user_id()
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = SessionLocal()
    try:
        db.query(UserFact).filter(
            UserFact.user_id == uid
        ).update({"active": False})
        db.commit()
        return {"cleared": True}
    finally:
        db.close()
