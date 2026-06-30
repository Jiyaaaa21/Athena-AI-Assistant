"""
backend/api/assistant.py  —  Phase 14: Smart Assistant Action Router

POST /assistant/action

When the user says something like "save this for later", "remind me tomorrow",
or "what project am I working on?", Athena decides the right action and
executes it automatically — no manual module navigation needed.

This is the "chat as the primary interface" layer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.llm import ask_llm_raw
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import Note, Reminder, Goal

router = APIRouter()


class ActionRequest(BaseModel):
    message: str          # The user's raw message
    context: str = ""     # Optional surrounding conversation context


class ActionResult(BaseModel):
    action: str           # What Athena decided to do
    result: dict          # The outcome
    reply: str            # Human-friendly response to show the user


def _classify_action(message: str, context: str) -> dict:
    """
    Ask the LLM to classify the user's intent into a structured action.
    Returns a dict with: action, params
    """
    prompt = f"""You are Athena's action classifier. Given a user message, determine what action to take.

User message: "{message}"
{f'Recent context: {context}' if context else ''}

Choose exactly ONE action from this list and respond in valid JSON only:
- save_note: user wants to save text as a note. params: {{"title": str, "body": str}}
- save_reminder: user wants a reminder. params: {{"title": str, "due": str (natural language)}}
- save_goal: user wants to track a goal. params: {{"title": str, "timeframe": "short"|"medium"|"long"}}
- recall_goals: user wants to see their goals. params: {{}}
- recall_reminders: user wants to see their reminders. params: {{}}
- recall_notes: user wants to see their notes. params: {{}}
- create_project: user wants to start a project. params: {{"name": str}}
- chat: no specific action needed, just conversation. params: {{}}

Response format (JSON only, no markdown):
{{"action": "action_name", "params": {{...}}, "confidence": 0-100}}"""

    try:
        raw = ask_llm_raw(prompt).strip()
        # Strip markdown fences if present
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {"action": "chat", "params": {}, "confidence": 50}


@router.post("/assistant/action")
def smart_action(payload: ActionRequest):
    """
    Classify and execute a smart action from natural language.
    Returns what was done + a friendly reply for the chat interface.
    """
    uid = get_current_user_id()
    classified = _classify_action(payload.message, payload.context)
    action = classified.get("action", "chat")
    params = classified.get("params", {})

    db = SessionLocal()
    try:
        # ── Save Note ───────────────────────────────────────────────────────
        if action == "save_note":
            title = params.get("title") or payload.message[:60]
            body = params.get("body") or payload.message
            note = Note(
                user_id=uid,
                title=title,
                content=body,
                pinned=False,
            )
            db.add(note)
            db.commit()
            db.refresh(note)
            # Invalidate context cache so next LLM call sees new note
            try:
                from backend.core.llm import invalidate_context_cache
                invalidate_context_cache()
            except Exception:
                pass
            return {
                "action": "save_note",
                "result": {"id": note.id, "title": title},
                "reply": f"✅ I've saved that as a note: **{title}**",
            }

        # ── Save Reminder ────────────────────────────────────────────────────
        elif action == "save_reminder":
            title = params.get("title") or payload.message[:100]
            due_str = params.get("due", "tomorrow")
            # Try to parse due date
            try:
                from dateutil import parser as dp
                due_dt = dp.parse(due_str, fuzzy=True)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                due_iso = due_dt.isoformat()
            except Exception:
                due_iso = due_str

            reminder = Reminder(
                user_id=uid,
                title=title,
                content=title,
                due_at=due_iso,
                due_time=due_str,
                done=False,
            )
            db.add(reminder)
            db.commit()
            db.refresh(reminder)
            return {
                "action": "save_reminder",
                "result": {"id": reminder.id, "title": title, "due": due_iso},
                "reply": f"⏰ Reminder set: **{title}** — due {due_str}",
            }

        # ── Save Goal ────────────────────────────────────────────────────────
        elif action == "save_goal":
            title = params.get("title") or payload.message[:100]
            timeframe = params.get("timeframe", "medium")
            goal = Goal(
                user_id=uid,
                title=title,
                timeframe=timeframe,
                status="active",
                progress=0,
            )
            db.add(goal)
            db.commit()
            db.refresh(goal)
            return {
                "action": "save_goal",
                "result": {"id": goal.id, "title": title, "timeframe": timeframe},
                "reply": f"🎯 Goal tracked: **{title}** ({timeframe}-term)",
            }

        # ── Recall Goals ─────────────────────────────────────────────────────
        elif action == "recall_goals":
            goals = (
                db.query(Goal)
                .filter(Goal.user_id == uid, Goal.status == "active")
                .order_by(Goal.created_at.desc())
                .limit(10)
                .all()
            )
            if not goals:
                return {
                    "action": "recall_goals",
                    "result": {"goals": []},
                    "reply": "You haven't set any goals yet. Want to add one?",
                }
            lines = "\n".join(f"• [{g.timeframe}] {g.title} ({g.progress or 0}%)" for g in goals)
            return {
                "action": "recall_goals",
                "result": {"goals": [{"id": g.id, "title": g.title, "timeframe": g.timeframe} for g in goals]},
                "reply": f"🎯 Your active goals:\n{lines}",
            }

        # ── Recall Reminders ─────────────────────────────────────────────────
        elif action == "recall_reminders":
            reminders = (
                db.query(Reminder)
                .filter(Reminder.user_id == uid, Reminder.done == False)
                .order_by(Reminder.id.desc())
                .limit(10)
                .all()
            )
            if not reminders:
                return {
                    "action": "recall_reminders",
                    "result": {"reminders": []},
                    "reply": "No pending reminders! You're all caught up.",
                }
            lines = "\n".join(f"• {r.title or r.content}" for r in reminders)
            return {
                "action": "recall_reminders",
                "result": {"count": len(reminders)},
                "reply": f"⏰ Your pending reminders:\n{lines}",
            }

        # ── Recall Notes ─────────────────────────────────────────────────────
        elif action == "recall_notes":
            notes = (
                db.query(Note)
                .filter(Note.user_id == uid)
                .order_by(Note.id.desc())
                .limit(10)
                .all()
            )
            if not notes:
                return {
                    "action": "recall_notes",
                    "result": {"notes": []},
                    "reply": "No notes saved yet. Want me to save something?",
                }
            lines = "\n".join(f"• {n.title or (n.content or '')[:60]}" for n in notes)
            return {
                "action": "recall_notes",
                "result": {"count": len(notes)},
                "reply": f"📝 Your recent notes:\n{lines}",
            }

        # ── Create Project ────────────────────────────────────────────────────
        elif action == "create_project":
            from backend.database.models import Project
            name = params.get("name") or payload.message[:80]
            project = Project(user_id=uid, name=name, status="active")
            db.add(project)
            db.commit()
            db.refresh(project)
            return {
                "action": "create_project",
                "result": {"id": project.id, "name": name},
                "reply": f"📁 Project created: **{name}**. I'll group related notes, reminders, and documents under it.",
            }

        # ── Default: chat ─────────────────────────────────────────────────────
        else:
            return {
                "action": "chat",
                "result": {},
                "reply": "",  # Frontend should fall back to normal chat stream
            }

    finally:
        db.close()