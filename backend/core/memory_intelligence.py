"""
backend/core/memory_intelligence.py  —  Phase 16

Semantic long-term memory for Athena.

After each conversation turn (or in a background pass), the LLM reads
the exchange and extracts structured facts about the user:
  - Goals and aspirations ("preparing for GATE 2027")
  - Preferences ("prefers concise answers", "uses dark mode")
  - Context ("studying in Gurgaon", "works at a startup")
  - Skills/Background ("knows Python", "has a CS degree")

These facts are stored in UserFact table and injected into every LLM
system prompt — giving Athena persistent memory across sessions even
after the 20-message rolling window drops old conversations.

Usage:
  extract_and_store_facts(conversation_text, user_id)  # after each turn
  get_user_facts_prompt(user_id)  # returns formatted facts for LLM injection
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.database.db import SessionLocal
from backend.database.models import UserFact
from backend.core.logger import agent_logger

_MAX_FACTS = 40  # cap per user to keep prompt size manageable


def _utcnow():
    return datetime.now(timezone.utc)


def extract_and_store_facts(
    user_message: str,
    assistant_message: str,
    user_id: int,
) -> list[str]:
    """
    Ask the LLM to extract user facts from this exchange and persist them.
    Called after each chat turn in a background thread (non-blocking).
    Returns list of new facts stored.
    """
    if not user_id or not user_message.strip():
        return []

    try:
        from backend.core.llm import ask_llm_raw
        prompt = (
            f"Analyze this conversation exchange and extract any PERSISTENT facts "
            f"about the USER (not Athena). Only extract facts that would be useful "
            f"to remember across future conversations.\n\n"
            f"User said: {user_message[:500]}\n"
            f"Athena replied: {assistant_message[:300]}\n\n"
            f"Extract facts in these categories:\n"
            f"- goal: long-term aspirations or objectives\n"
            f"- preference: how they like things done\n"
            f"- context: current situation, location, job, study\n"
            f"- skill: things they know or are learning\n\n"
            f"Return ONLY a JSON array of objects, or [] if nothing worth remembering.\n"
            f"Format: [{{\"fact\": \"...\", \"category\": \"goal|preference|context|skill\", \"confidence\": 70-95}}]\n"
            f"Rules:\n"
            f"- Max 3 facts per exchange\n"
            f"- Only facts explicitly stated, not inferred\n"
            f"- Skip trivial facts (\"user said hello\", \"user asked about weather\")\n"
            f"- Return [] if nothing meaningful\n"
            f"Return ONLY the JSON array, no other text."
        )

        raw = ask_llm_raw(prompt).strip()
        # Strip markdown fences if present
        raw = raw.replace("```json", "").replace("```", "").strip()

        facts_data = json.loads(raw)
        if not isinstance(facts_data, list):
            return []

        stored = []
        db = SessionLocal()
        try:
            # Get existing facts to avoid duplicates
            existing = db.query(UserFact).filter(
                UserFact.user_id == user_id,
                UserFact.active == True,
            ).all()
            existing_texts = {f.fact.lower() for f in existing}

            for item in facts_data[:3]:
                fact_text = str(item.get("fact", "")).strip()
                if not fact_text or len(fact_text) < 10:
                    continue

                # Rough dedup: skip if very similar to existing
                if any(
                    _similarity(fact_text.lower(), ex) > 0.7
                    for ex in existing_texts
                ):
                    continue

                # Enforce cap
                if len(existing) + len(stored) >= _MAX_FACTS:
                    # Remove oldest low-confidence fact to make room
                    oldest = min(existing, key=lambda f: f.confidence)
                    oldest.active = False

                db.add(UserFact(
                    user_id=user_id,
                    fact=fact_text,
                    category=item.get("category", "context"),
                    confidence=min(95, max(50, int(item.get("confidence", 75)))),
                    created_at=_utcnow(),
                    updated_at=_utcnow(),
                    active=True,
                ))
                stored.append(fact_text)

            db.commit()
        finally:
            db.close()

        return stored

    except Exception as e:
        agent_logger.debug(f"[MemoryIntelligence] extract failed: {e}")
        return []


def _similarity(a: str, b: str) -> float:
    """Simple word overlap similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


def get_user_facts_prompt(user_id: int) -> str:
    """
    Return a formatted block of user facts for injection into the LLM
    system prompt. Returns empty string if no facts.
    """
    if not user_id:
        return ""

    db = SessionLocal()
    try:
        facts = (
            db.query(UserFact)
            .filter(UserFact.user_id == user_id, UserFact.active == True)
            .order_by(UserFact.confidence.desc(), UserFact.updated_at.desc())
            .limit(20)
            .all()
        )
        if not facts:
            return ""

        by_category: dict[str, list[str]] = {}
        for f in facts:
            cat = f.category or "context"
            by_category.setdefault(cat, []).append(f.fact)

        lines = ["\n\n--- What I know about you (long-term memory) ---"]
        cat_labels = {
            "goal": "Your Goals",
            "preference": "Your Preferences",
            "context": "Your Situation",
            "skill": "Your Skills & Background",
        }
        for cat, label in cat_labels.items():
            if cat in by_category:
                lines.append(f"{label}:")
                for fact in by_category[cat][:6]:
                    lines.append(f"  • {fact}")
        lines.append("--- End of long-term memory ---")
        return "\n".join(lines)

    finally:
        db.close()


def list_user_facts(user_id: int) -> list[dict]:
    """Return all active facts for the memory management UI."""
    db = SessionLocal()
    try:
        facts = (
            db.query(UserFact)
            .filter(UserFact.user_id == user_id, UserFact.active == True)
            .order_by(UserFact.created_at.desc())
            .all()
        )
        return [
            {
                "id": f.id,
                "fact": f.fact,
                "category": f.category,
                "confidence": f.confidence,
                "createdAt": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ]
    finally:
        db.close()


def delete_user_fact(fact_id: int, user_id: int) -> bool:
    """Let user delete a specific memory fact."""
    db = SessionLocal()
    try:
        fact = db.query(UserFact).filter(
            UserFact.id == fact_id,
            UserFact.user_id == user_id,
        ).first()
        if not fact:
            return False
        fact.active = False
        db.commit()
        return True
    finally:
        db.close()
