"""
backend/core/context_builder.py  —  Phase 14: Rich Context Assembly

Builds a structured context snapshot of the current user's world:
  - Active goals
  - Pending / upcoming reminders
  - Recent notes
  - Active projects
  - Conversation topics from last 7 days
  - Frequently discussed subjects

This context is injected into every LLM call so Athena can give
personalized, proactive, goal-aware responses instead of generic ones.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.database.db import SessionLocal
from backend.database.models import (
    Goal, Project, Reminder, Note, Message, Conversation,
)
from backend.core.request_context import get_current_user_id


def _aware(dt: datetime) -> datetime:
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt or datetime.now(timezone.utc)


def build_user_context() -> dict:
    """
    Returns a dict with all context sections. Returns safe empty values
    if the user has no data yet.
    """
    try:
        uid = get_current_user_id()
    except Exception:
        return {}

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        # ── Active Goals ──────────────────────────────────────────────────
        goals = (
            db.query(Goal)
            .filter(Goal.user_id == uid, Goal.status == "active")
            .order_by(Goal.created_at.desc())
            .limit(10)
            .all()
        )
        goals_summary = [
            f"[{g.timeframe.upper()}] {g.title}" + (f" — {g.description}" if g.description else "")
            for g in goals
        ]

        # ── Active Projects ───────────────────────────────────────────────
        projects = (
            db.query(Project)
            .filter(Project.user_id == uid, Project.status == "active")
            .order_by(Project.updated_at.desc())
            .limit(5)
            .all()
        )
        projects_summary = [p.name for p in projects]

        # ── Pending / Upcoming Reminders ──────────────────────────────────
        reminders = (
            db.query(Reminder)
            .filter(Reminder.user_id == uid, Reminder.done == False)
            .order_by(Reminder.id.desc())
            .limit(10)
            .all()
        )
        pending_reminders = []
        overdue_reminders = []
        for r in reminders:
            title = r.title or r.content or ""
            if not title:
                continue
            due_str = r.due_at or r.due_time or ""
            try:
                from dateutil import parser as dp
                due_dt = _aware(dp.parse(due_str, fuzzy=True)) if due_str else None
                if due_dt and due_dt < now:
                    overdue_reminders.append(title)
                else:
                    pending_reminders.append(
                        f"{title}" + (f" (due {due_str})" if due_str else "")
                    )
            except Exception:
                pending_reminders.append(title)

        # ── Recent Notes (titles only) ────────────────────────────────────
        notes = (
            db.query(Note)
            .filter(Note.user_id == uid)
            .order_by(Note.id.desc())
            .limit(5)
            .all()
        )
        recent_notes = [n.title or (n.content or "")[:60] for n in notes if n.title or n.content]

        # ── Recent Conversation Topics ────────────────────────────────────
        recent_msgs = (
            db.query(Message)
            .filter(
                Message.user_id == uid,
                Message.role == "user",
            )
            .order_by(Message.created_at.desc().nullslast())
            .limit(20)
            .all()
        )
        # Simple topic extraction: take first 80 chars of each message
        recent_topics = list({
            (m.content or "")[:80].strip()
            for m in recent_msgs
            if m.content and len(m.content.strip()) > 10
        })[:5]

        return {
            "goals": goals_summary,
            "projects": projects_summary,
            "pending_reminders": pending_reminders,
            "overdue_reminders": overdue_reminders,
            "recent_notes": recent_notes,
            "recent_topics": recent_topics,
        }

    except Exception:
        return {}
    finally:
        db.close()


def format_context_for_prompt(ctx: dict) -> str:
    """
    Converts the context dict into a formatted string block to inject into
    the system prompt or agent prompts.
    """
    if not ctx:
        return ""

    lines = ["\n\n--- ATHENA CONTEXT (use to personalize your response) ---"]

    if ctx.get("goals"):
        lines.append("\nUSER'S ACTIVE GOALS:")
        for g in ctx["goals"]:
            lines.append(f"  • {g}")

    if ctx.get("projects"):
        lines.append("\nACTIVE PROJECTS:")
        for p in ctx["projects"]:
            lines.append(f"  • {p}")

    if ctx.get("overdue_reminders"):
        lines.append("\nOVERDUE REMINDERS (mention proactively if relevant):")
        for r in ctx["overdue_reminders"]:
            lines.append(f"  ⚠ {r}")

    if ctx.get("pending_reminders"):
        lines.append("\nUPCOMING REMINDERS:")
        for r in ctx["pending_reminders"][:5]:
            lines.append(f"  • {r}")

    if ctx.get("recent_notes"):
        lines.append("\nRECENT NOTES:")
        for n in ctx["recent_notes"]:
            lines.append(f"  • {n}")

    if ctx.get("recent_topics"):
        lines.append("\nRECENT CONVERSATION TOPICS:")
        for t in ctx["recent_topics"]:
            lines.append(f"  • {t}")

    lines.append("\n--- END CONTEXT ---\n")
    return "\n".join(lines)