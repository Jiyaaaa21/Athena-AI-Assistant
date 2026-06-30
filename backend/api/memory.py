"""
Memory API — Phase 6: Memory OS

All existing endpoints are preserved unchanged.
New endpoints added (all additive):
  PUT  /memory/{id}          → edit content/category of a single entry
  GET  /memory/timeline      → messages grouped into Today/This Week/This Month/Older
  GET  /memory/topics        → inferred recurring topics + entity clusters
  GET  /memory/preferences   → personalization layer: top topics, active hours,
                               workflow patterns, personalized suggestions

Importance scoring (deterministic, no randomness):
  Score 0-10 based on content length, personal/preference keywords, role.
  Levels: low (0-2), medium (3-5), high (6-8), critical (9-10).
  "Critical" is new in Phase 6 — triggered by name/identity statements +
  long content, e.g. "My name is X and I work at Y as a Z".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import re

from backend.core.memory_service import (
    get_history_with_ids,
    delete_message,
    update_message_content,
)

router = APIRouter()


# ── Importance + category helpers ────────────────────────────────────────────

_PERSONAL_KW = {
    "i am", "i'm", "my name", "i live", "i work", "my job",
    "my role", "i am a", "i'm a", "my company", "my team",
}
_PREF_KW = {
    "i like", "i love", "i prefer", "i enjoy", "i hate",
    "i dislike", "favourite", "favorite", "always", "never",
}
_WORK_KW = {
    "project", "deadline", "meeting", "client", "report",
    "sprint", "task", "ticket", "jira", "github",
}
_LEARNING_KW = {
    "learn", "study", "course", "book", "tutorial",
    "lecture", "exam", "practice", "skill",
}
_PROJECTS_KW = {
    "building", "working on", "developing", "shipping", "launching",
    "coding", "designing", "athena", "roadmap",
}
_CRITICAL_KW = {
    "my name is", "i am a ", "i work at", "my job is", "i'm a ",
    "i'm the", "i am the",
}

_CATEGORY_MAP = [
    ("Personal",     _PERSONAL_KW),
    ("Preferences",  _PREF_KW),
    ("Projects",     _PROJECTS_KW),
    ("Work",         _WORK_KW),
    ("Learning",     _LEARNING_KW),
]

ALL_CATEGORIES = ["Personal", "Preferences", "Projects", "Work", "Learning", "Conversations", "Documents", "Reminders", "Notes"]


def _score(content: str, role: str) -> int:
    lo = content.lower()
    score = 0

    words = len(lo.split())
    if words >= 40:
        score += 4
    elif words >= 20:
        score += 3
    elif words >= 10:
        score += 2
    elif words >= 4:
        score += 1

    for kw in _CRITICAL_KW:
        if kw in lo:
            score += 4
            break

    for kw in _PERSONAL_KW | _PREF_KW:
        if kw in lo:
            score += 2
            break

    for kw in _WORK_KW | _LEARNING_KW | _PROJECTS_KW:
        if kw in lo:
            score += 1
            break

    if role == "user":
        score += 1

    return min(score, 10)


def _importance_label(raw: int) -> str:
    if raw >= 9:
        return "critical"
    if raw >= 6:
        return "high"
    if raw >= 3:
        return "medium"
    return "low"


def _infer_category(content: str, role: str) -> str:
    lo = content.lower()
    for cat, kws in _CATEGORY_MAP:
        for kw in kws:
            if kw in lo:
                return cat
    return "Conversations"


def _enrich(m: dict) -> dict:
    raw_score = _score(m["content"], m["role"])
    return {
        **m,
        "category": _infer_category(m["content"], m["role"]),
        "importance": _importance_label(raw_score),
        "importance_score": raw_score,
    }


# ── Timeline bucketing ────────────────────────────────────────────────────────

def _bucket_label(created_at: str | None, now: datetime) -> str:
    if not created_at:
        return "Older"
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "Older"

    diff = now - dt
    if diff.days == 0:
        return "Today"
    if diff.days <= 7:
        return "This Week"
    if diff.days <= 30:
        return "This Month"
    return "Older"


# ── Topic extraction ─────────────────────────────────────────────────────────

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "i", "you", "it",
    "that", "this", "not", "no", "my", "your", "we", "they", "he", "she",
    "what", "how", "when", "where", "why", "who", "which", "so", "if",
    "then", "about", "just", "up", "out", "there", "use", "also", "want",
    "need", "like", "get", "into", "than", "me", "am", "any", "some",
    "make", "more", "its", "s", "re", "ve", "t", "ll", "d",
}

def _extract_topics(user_messages: list[dict], top_n: int = 12) -> list[dict]:
    """Return top recurring noun phrases / keywords from user messages."""
    bigram_counts: Counter = Counter()
    word_counts: Counter = Counter()

    for m in user_messages:
        text = re.sub(r"[^\w\s]", " ", m["content"].lower())
        words = [w for w in text.split() if w not in _STOP_WORDS and len(w) > 3]

        for w in words:
            word_counts[w] += 1

        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            bigram_counts[bigram] += 1

    # Prefer bigrams (more descriptive) then unigrams
    results = []
    seen: set[str] = set()

    for phrase, count in bigram_counts.most_common(top_n):
        if count >= 2:
            results.append({"topic": phrase, "count": count, "type": "phrase"})
            for w in phrase.split():
                seen.add(w)

    for word, count in word_counts.most_common(top_n):
        if word not in seen and count >= 2 and len(results) < top_n:
            results.append({"topic": word, "count": count, "type": "keyword"})

    return sorted(results, key=lambda x: -x["count"])[:top_n]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/memory")
def memory():
    messages = get_history_with_ids()
    return {"messages": [_enrich(m) for m in messages]}


@router.get("/memory/stats")
def memory_stats():
    messages = get_history_with_ids()

    if not messages:
        return {
            "total": 0,
            "by_category": {},
            "by_importance": {"low": 0, "medium": 0, "high": 0, "critical": 0},
            "by_role": {"user": 0, "assistant": 0},
            "oldest": None,
            "newest": None,
            "most_active_category": None,
        }

    enriched = [_enrich(m) for m in messages]
    by_cat: dict[str, int] = {}
    by_imp: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    by_role: dict[str, int] = {"user": 0, "assistant": 0}

    for m in enriched:
        by_cat[m["category"]] = by_cat.get(m["category"], 0) + 1
        key = m["importance"]
        by_imp[key] = by_imp.get(key, 0) + 1
        role_key = m["role"] if m["role"] in by_role else "assistant"
        by_role[role_key] += 1

    most_active = max(by_cat, key=lambda k: by_cat[k]) if by_cat else None
    dates = [m["createdAt"] for m in messages if m.get("createdAt")]
    oldest = min(dates) if dates else None
    newest = max(dates) if dates else None

    return {
        "total": len(enriched),
        "by_category": by_cat,
        "by_importance": by_imp,
        "by_role": by_role,
        "oldest": oldest,
        "newest": newest,
        "most_active_category": most_active,
    }


@router.get("/memory/search")
def memory_search(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    importance: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
):
    messages = get_history_with_ids()
    enriched = [_enrich(m) for m in messages]
    results = enriched

    if q:
        lo = q.lower()
        results = [m for m in results if lo in m["content"].lower()]
    if category:
        results = [m for m in results if m["category"].lower() == category.lower()]
    if importance:
        results = [m for m in results if m["importance"] == importance.lower()]
    if role:
        results = [m for m in results if m["role"] == role.lower()]
    if date_from:
        results = [m for m in results if m.get("createdAt") and m["createdAt"] >= date_from]
    if date_to:
        results = [m for m in results if m.get("createdAt") and m["createdAt"] <= date_to]

    return {"messages": results, "total": len(results)}


@router.get("/memory/timeline")
def memory_timeline():
    """Return memories grouped into Today / This Week / This Month / Older."""
    messages = get_history_with_ids()
    enriched = [_enrich(m) for m in messages]
    now = datetime.now(timezone.utc)

    bucket_order = ["Today", "This Week", "This Month", "Older"]
    buckets: dict[str, list] = {b: [] for b in bucket_order}

    for m in reversed(enriched):  # newest first within each group
        label = _bucket_label(m.get("createdAt"), now)
        buckets[label].append(m)

    return {
        "timeline": [
            {"period": label, "entries": buckets[label], "count": len(buckets[label])}
            for label in bucket_order
            if buckets[label]
        ]
    }


@router.get("/memory/topics")
def memory_topics():
    """Infer recurring topics and entities from user messages."""
    messages = get_history_with_ids()
    user_msgs = [m for m in messages if m["role"] == "user"]

    if not user_msgs:
        return {"topics": [], "total_analyzed": 0}

    topics = _extract_topics(user_msgs, top_n=15)
    return {"topics": topics, "total_analyzed": len(user_msgs)}


@router.get("/memory/preferences")
def memory_preferences():
    """
    Personalization layer — derives insights from actual conversation data.
    Returns: top topics, active hours, most used categories, workflow patterns,
    and personalized suggestions.
    """
    messages = get_history_with_ids()
    enriched = [_enrich(m) for m in messages]
    user_msgs = [m for m in enriched if m["role"] == "user"]
    now = datetime.now(timezone.utc)

    # ── Top categories ────────────────────────────────────────────────────
    cat_counts: Counter = Counter()
    for m in user_msgs:
        cat_counts[m["category"]] += 1
    top_categories = [
        {"category": cat, "count": cnt, "pct": round(cnt / max(len(user_msgs), 1) * 100, 1)}
        for cat, cnt in cat_counts.most_common(5)
    ]

    # ── Active hours (hour of day from timestamps) ────────────────────────
    hour_counts = [0] * 24
    for m in user_msgs:
        if m.get("createdAt"):
            try:
                dt = datetime.fromisoformat(m["createdAt"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hour_counts[dt.hour] += 1
            except (ValueError, TypeError):
                pass
    peak_hour = hour_counts.index(max(hour_counts)) if any(hour_counts) else None
    active_hours = [{"hour": h, "count": c} for h, c in enumerate(hour_counts)]

    # ── Frequently discussed topics ───────────────────────────────────────
    topics = _extract_topics(user_msgs, top_n=8)

    # ── Most active days ──────────────────────────────────────────────────
    day_counts: Counter = Counter()
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for m in user_msgs:
        if m.get("createdAt"):
            try:
                dt = datetime.fromisoformat(m["createdAt"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                day_counts[dt.weekday()] += 1
            except (ValueError, TypeError):
                pass
    most_active_days = [
        {"day": day_names[wd], "count": cnt}
        for wd, cnt in sorted(day_counts.items(), key=lambda x: -x[1])[:3]
    ]

    # ── Personalized suggestions (derived from real data) ─────────────────
    suggestions = []

    # Suggestion: based on high-importance memories
    high_imp = [m for m in enriched if m["importance"] in ("high", "critical")]
    if high_imp:
        latest = sorted(high_imp, key=lambda m: m.get("createdAt") or "", reverse=True)[:1][0]
        suggestions.append({
            "type": "memory",
            "title": "Review important memory",
            "detail": latest["content"][:80] + ("…" if len(latest["content"]) > 80 else ""),
            "icon": "brain",
        })

    # Suggestion: based on recurring topics
    if topics:
        top_topic = topics[0]["topic"]
        suggestions.append({
            "type": "topic",
            "title": f"Frequently discussed: {top_topic}",
            "detail": f"Mentioned {topics[0]['count']} times in your conversations.",
            "icon": "trending-up",
        })

    # Suggestion: based on peak hour
    if peak_hour is not None and max(hour_counts) > 0:
        ampm = "AM" if peak_hour < 12 else "PM"
        h12 = peak_hour % 12 or 12
        suggestions.append({
            "type": "pattern",
            "title": "Peak activity window",
            "detail": f"You're most active around {h12}:00 {ampm}.",
            "icon": "clock",
        })

    # Suggestion: based on most active category
    if top_categories:
        tc = top_categories[0]
        suggestions.append({
            "type": "pattern",
            "title": f"Top focus area: {tc['category']}",
            "detail": f"{tc['count']} conversations tagged to this category ({tc['pct']}%).",
            "icon": "folder",
        })

    return {
        "top_categories": top_categories,
        "active_hours": active_hours,
        "peak_hour": peak_hour,
        "most_active_days": most_active_days,
        "frequently_discussed_topics": topics,
        "suggestions": suggestions[:4],
        "total_user_messages": len(user_msgs),
    }


# ── Edit memory entry ─────────────────────────────────────────────────────────

class MemoryEdit(BaseModel):
    content: str


@router.put("/memory/{message_id}")
def edit_memory(message_id: int, body: MemoryEdit):
    """Phase 6: edit the content of a stored memory entry."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    ok = update_message_content(message_id, body.content.strip())
    if not ok:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    # Return the enriched entry
    messages = get_history_with_ids()
    for m in messages:
        if m["id"] == message_id:
            return _enrich(m)
    raise HTTPException(status_code=404, detail="Memory entry not found after update")


@router.delete("/memory/{message_id}")
def forget(message_id: int):
    ok = delete_message(message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"ok": True}