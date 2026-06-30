from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import Reminder
from backend.core.request_context import get_current_user_id

router = APIRouter()


# ---------- Schemas ----------
# Field names mirror src/lib/mock.ts `Reminder`:
# { id, title, dueAt, done, priority? }
# Roadmap addition: category? (optional, additive).

class ReminderCreate(BaseModel):
    title: str
    dueAt: str
    done: bool = False
    priority: str | None = None
    category: str | None = None


class ReminderUpdate(BaseModel):
    """Full edit -- roadmap 'Edit Reminder'. Mirrors ReminderCreate; kept as
    a separate model in case the two need to diverge later (e.g. dueAt
    becoming required-immutable on create only)."""
    title: str
    dueAt: str
    done: bool = False
    priority: str | None = None
    category: str | None = None


class ReminderToggle(BaseModel):
    done: bool


# ---------- Helpers ----------

def best_effort_iso(due_at: str | None, due_time_legacy: str | None) -> str:
    """
    Reminders created via the REST API always have a real ISO due_at
    (the frontend's datetime-local picker guarantees that). Reminders
    created via the /chat tool only have a free-text due_time like
    "Friday", which isn't valid for the frontend's date-fns formatting.
    This makes a best effort to parse that text into a real date, and
    falls back to "tomorrow" rather than crashing the Reminders page.
    """
    if due_at:
        return due_at

    if due_time_legacy:
        try:
            parsed = date_parser.parse(due_time_legacy, fuzzy=True)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        except (ValueError, OverflowError):
            pass

    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def serialize(reminder: Reminder) -> dict:
    due_iso = best_effort_iso(reminder.due_at, reminder.due_time)

    # Roadmap addition: Overdue Status. Derived, not stored -- "overdue"
    # depends on the current time, so persisting it would just go stale.
    # A reminder is overdue only while it's still incomplete; finishing it
    # late shouldn't keep showing a red "Overdue" badge forever.
    overdue = False
    if not reminder.done:
        try:
            due_dt = date_parser.isoparse(due_iso)
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            overdue = due_dt < datetime.now(timezone.utc)
        except (ValueError, OverflowError):
            overdue = False

    return {
        "id": str(reminder.id),
        "title": reminder.title or reminder.content or "",
        "dueAt": due_iso,
        "done": bool(reminder.done),
        "priority": reminder.priority,
        "category": reminder.category,
        "overdue": overdue,
    }


# ---------- Routes ----------

@router.get("/reminders")
def list_reminders():

    db = SessionLocal()

    try:
        reminders = (
            db.query(Reminder)
            .filter(Reminder.user_id == get_current_user_id())
            .order_by(Reminder.id.desc())
            .all()
        )
        return [serialize(r) for r in reminders]

    finally:
        db.close()


@router.post("/reminders")
def create_reminder(payload: ReminderCreate):

    db = SessionLocal()

    try:
        reminder = Reminder(
            title=payload.title,
            content=payload.title,  # keep legacy column populated too
            due_at=payload.dueAt,
            due_time=payload.dueAt,
            done=payload.done,
            priority=payload.priority,
            category=payload.category,
            user_id=get_current_user_id(),
        )

        db.add(reminder)
        db.commit()
        db.refresh(reminder)

        return serialize(reminder)

    finally:
        db.close()


@router.patch("/reminders/{reminder_id}")
def toggle_reminder(reminder_id: str, payload: ReminderToggle):

    db = SessionLocal()

    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == int(reminder_id), Reminder.user_id == get_current_user_id()
        ).first()

        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        reminder.done = payload.done

        db.commit()

        return {"ok": True}

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reminder id")

    finally:
        db.close()


@router.put("/reminders/{reminder_id}")
def update_reminder(reminder_id: str, payload: ReminderUpdate):
    """Roadmap addition: Edit Reminder. Full update of title/dueAt/done/
    priority/category, mirroring how PUT /notes/{id} already works."""

    db = SessionLocal()

    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == int(reminder_id), Reminder.user_id == get_current_user_id()
        ).first()

        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        reminder.title = payload.title
        reminder.content = payload.title
        reminder.due_at = payload.dueAt
        reminder.due_time = payload.dueAt
        reminder.done = payload.done
        reminder.priority = payload.priority
        reminder.category = payload.category

        db.commit()
        db.refresh(reminder)

        return serialize(reminder)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reminder id")

    finally:
        db.close()


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: str):

    db = SessionLocal()

    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == int(reminder_id), Reminder.user_id == get_current_user_id()
        ).first()

        if not reminder:
            raise HTTPException(status_code=404, detail="Reminder not found")

        db.delete(reminder)
        db.commit()

        return {"ok": True}

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reminder id")

    finally:
        db.close()

# ── Phase 16: Due reminder polling endpoint ───────────────────────────────────

@router.get("/reminders/due")
def get_due_reminders():
    """
    Frontend polls this every 30 seconds to get any reminders that fired.
    Returns and clears the queue — so each reminder is delivered once.
    Used by the browser notification system.
    """
    from backend.core.reminder_scheduler import pop_due_reminders
    uid = get_current_user_id()
    if not uid:
        return {"due": []}
    return {"due": pop_due_reminders(uid)}

