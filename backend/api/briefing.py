"""
backend/api/briefing.py  —  Phase 14: Daily Briefing API

GET /briefing  — returns a personalized daily briefing generated from:
  - Pending / overdue reminders
  - Active goals
  - Recent unfinished conversations
  - Recent notes
  - Active projects
  - A proactive suggestion from the LLM

This powers the "Good Morning" assistant-first home screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.database.db import SessionLocal
from backend.database.models import (
    Goal, Reminder, Note, Conversation, Project, Message,
)
from backend.core.request_context import get_current_user_id
from backend.core.llm import ask_llm_raw
from backend.core.rate_limit import chat_rate_limiter_minute, chat_rate_limiter_daily, require_budget

router = APIRouter()


def _aware(dt: datetime) -> datetime:
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt or datetime.now(timezone.utc)


@router.get("/briefing")
def get_briefing():
    """
    Returns a structured daily briefing payload.
    The frontend uses this to render the assistant-first home screen.
    """
    # Phase 29: this calls ask_llm_raw() on every single request -- no
    # caching, no dedup per day -- and the UI has a one-click refresh
    # button (RefreshCw icon on the home screen) with no cooldown of its
    # own. Shares the same budget as /chat/stream since it draws on the
    # same underlying keys.
    uid_for_limit = get_current_user_id()
    require_budget(
        chat_rate_limiter_minute, chat_rate_limiter_daily,
        str(uid_for_limit) if uid_for_limit is not None else "unknown",
        minute_detail="Briefing was just refreshed — please wait a moment before refreshing again.",
        daily_detail="You've hit today's usage limit for this shared deployment. It resets in 24 hours.",
    )

    db = SessionLocal()
    try:
        uid = get_current_user_id()
        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)
        week_ago = now - timedelta(days=7)

        # ── Reminders ─────────────────────────────────────────────────────
        all_reminders = (
            db.query(Reminder)
            .filter(Reminder.user_id == uid, Reminder.done == False)
            .order_by(Reminder.id.desc())
            .limit(20)
            .all()
        )
        overdue = []
        upcoming = []
        for r in all_reminders:
            title = r.title or r.content or ""
            if not title:
                continue
            due_str = r.due_at or r.due_time or ""
            try:
                from dateutil import parser as dp
                due_dt = _aware(dp.parse(due_str, fuzzy=True)) if due_str else None
                if due_dt and due_dt < now:
                    overdue.append({"id": r.id, "title": title, "dueAt": due_str})
                else:
                    upcoming.append({"id": r.id, "title": title, "dueAt": due_str})
            except Exception:
                upcoming.append({"id": r.id, "title": title, "dueAt": due_str})

        # ── Goals ─────────────────────────────────────────────────────────
        goals = (
            db.query(Goal)
            .filter(Goal.user_id == uid, Goal.status == "active")
            .order_by(Goal.created_at.desc())
            .limit(5)
            .all()
        )
        goals_data = [
            {"id": g.id, "title": g.title, "timeframe": g.timeframe, "progress": g.progress or 0}
            for g in goals
        ]

        # ── Recent conversations (last 48h) ────────────────────────────────
        recent_convs = (
            db.query(Conversation)
            .filter(
                Conversation.user_id == uid,
                Conversation.updated_at >= two_days_ago,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(3)
            .all()
        )
        convs_data = [
            {"id": c.id, "title": c.title, "updatedAt": c.updated_at.isoformat() if c.updated_at else None}
            for c in recent_convs
        ]

        # ── Active projects ────────────────────────────────────────────────
        projects = (
            db.query(Project)
            .filter(Project.user_id == uid, Project.status == "active")
            .order_by(Project.updated_at.desc())
            .limit(3)
            .all()
        )
        projects_data = [{"id": p.id, "name": p.name} for p in projects]

        # ── Recent notes ───────────────────────────────────────────────────
        recent_notes = (
            db.query(Note)
            .filter(Note.user_id == uid)
            .order_by(Note.id.desc())
            .limit(3)
            .all()
        )
        notes_data = [
            {"id": n.id, "title": n.title or (n.content or "")[:60]}
            for n in recent_notes
        ]

        # ── Proactive suggestion (LLM) ─────────────────────────────────────
        suggestion = _generate_suggestion(
            overdue=overdue,
            upcoming=upcoming,
            goals=goals_data,
            convs=convs_data,
            projects=projects_data,
        )

        # ── Hour-based greeting ────────────────────────────────────────────
        hour = now.hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        return {
            "greeting": greeting,
            "timestamp": now.isoformat(),
            "overdue_reminders": overdue,
            "upcoming_reminders": upcoming[:5],
            "goals": goals_data,
            "recent_conversations": convs_data,
            "active_projects": projects_data,
            "recent_notes": notes_data,
            "suggestion": suggestion,
            "summary": {
                "overdue_count": len(overdue),
                "upcoming_count": len(upcoming),
                "goals_count": len(goals_data),
                "open_conversations": len(convs_data),
            },
        }

    finally:
        db.close()


def _generate_suggestion(
    overdue: list,
    upcoming: list,
    goals: list,
    convs: list,
    projects: list,
) -> str:
    """Ask the LLM for a single proactive suggestion based on the briefing data."""
    try:
        parts = []
        if overdue:
            titles = ", ".join(r["title"] for r in overdue[:3])
            parts.append(f"Overdue reminders: {titles}")
        if upcoming:
            titles = ", ".join(r["title"] for r in upcoming[:3])
            parts.append(f"Upcoming reminders: {titles}")
        if goals:
            titles = ", ".join(g["title"] for g in goals[:3])
            parts.append(f"Active goals: {titles}")
        if convs:
            titles = ", ".join(c["title"] for c in convs[:2])
            parts.append(f"Recent conversations: {titles}")
        if projects:
            names = ", ".join(p["name"] for p in projects[:2])
            parts.append(f"Active projects: {names}")

        if not parts:
            return "You're all caught up! What would you like to work on today?"

        context = "\n".join(parts)
        prompt = (
            f"You are Athena. Based on the user's current state, write ONE short, "
            f"helpful, proactive suggestion (2 sentences max). Be specific and action-oriented.\n\n"
            f"User's current state:\n{context}\n\n"
            f"Suggestion:"
        )
        return ask_llm_raw(prompt).strip()
    except Exception:
        return "Ready to help you have a productive day. What's on your mind?"