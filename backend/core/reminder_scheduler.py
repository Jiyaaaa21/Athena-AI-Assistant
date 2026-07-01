"""
backend/core/reminder_scheduler.py  —  Phase 16

Reminder firing engine. Previously reminders were saved with due_at
timestamps but nothing ever checked them — they sat in the DB forever.

This module:
1. Runs a background thread that polls every 60 seconds
2. Finds reminders where due_at <= now AND not done AND not already fired
3. Marks them as fired in ReminderFired table
4. Pushes them to an in-memory queue that the frontend polls via SSE

Frontend polls GET /reminders/due every 30 seconds and shows browser
notifications for any pending items.

Start with: start_scheduler() called from main.py on_startup.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from collections import defaultdict

from backend.core.logger import agent_logger

# Per-user queues of due reminders waiting to be delivered to the frontend
_due_queues: dict[int, list[dict]] = defaultdict(list)
_lock = threading.Lock()
_running = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check_reminders():
    """Poll DB for due reminders and push to per-user queues."""
    try:
        from backend.database.db import SessionLocal
        from backend.database.models import Reminder, ReminderFired
        from dateutil import parser as dp

        db = SessionLocal()
        try:
            now = _utcnow()
            # Find undone reminders with a due_at set
            reminders = (
                db.query(Reminder)
                .filter(
                    Reminder.done == False,
                    Reminder.due_at != None,
                )
                .all()
            )

            already_fired = {
                row.reminder_id
                for row in db.query(ReminderFired).all()
            }

            fired_count = 0
            for r in reminders:
                if r.id in already_fired:
                    continue
                try:
                    due = dp.parse(r.due_at)
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    if due <= now:
                        # Fire it
                        uid = r.user_id
                        title = r.title or r.content or "Reminder"
                        if uid:
                            with _lock:
                                _due_queues[uid].append({
                                    "id": r.id,
                                    "title": title,
                                    "due_time": r.due_time or "",
                                    "priority": r.priority or "med",
                                })
                            # Phase 21: also fire a real OS-level push, so
                            # the reminder still reaches the person if
                            # Athena isn't open in any tab -- the
                            # in-memory queue above only helps while a
                            # tab is open polling GET /reminders/due.
                            #
                            # Phase 23: `urgent=True` for high/urgent
                            # priority reminders -- flows through to
                            # public/sw.js as requireInteraction, so a
                            # genuinely important one stays on screen
                            # until dismissed instead of auto-hiding
                            # after a few seconds like a routine reminder.
                            try:
                                from backend.core.push_notifications import send_push_to_user
                                send_push_to_user(
                                    uid,
                                    title="Reminder",
                                    body=title,
                                    url="/reminders",
                                    urgent=(r.priority or "").lower() in ("high", "urgent"),
                                )
                            except Exception as push_err:
                                # Never let a push failure block marking
                                # the reminder as fired -- the in-app
                                # queue above is the source of truth.
                                agent_logger.error(f"[Scheduler] push send failed: {push_err}")
                        # Mark as fired
                        db.add(ReminderFired(reminder_id=r.id, fired_at=_utcnow()))
                        fired_count += 1
                except Exception:
                    continue

            if fired_count:
                db.commit()
                agent_logger.info(f"[Scheduler] Fired {fired_count} reminder(s)")

        finally:
            db.close()

    except Exception as e:
        agent_logger.error(f"[Scheduler] check_reminders error: {e}")


def _scheduler_loop():
    global _running
    agent_logger.info("[Scheduler] Reminder scheduler started (60s interval)")
    while _running:
        _check_reminders()
        # Sleep in short increments so shutdown is responsive
        for _ in range(60):
            if not _running:
                break
            time.sleep(1)
    agent_logger.info("[Scheduler] Reminder scheduler stopped")


def start_scheduler():
    """Call from main.py on_startup. Idempotent."""
    global _running
    if _running:
        return
    _running = True
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="reminder-scheduler")
    t.start()


def stop_scheduler():
    """Call on shutdown if needed."""
    global _running
    _running = False


def pop_due_reminders(user_id: int) -> list[dict]:
    """
    Called by GET /reminders/due. Returns and clears the queue for this user.
    Frontend polls this every 30 seconds and shows notifications.
    """
    with _lock:
        items = _due_queues.pop(user_id, [])
    return items


def peek_due_reminders(user_id: int) -> list[dict]:
    """Non-destructive peek (for debugging)."""
    with _lock:
        return list(_due_queues.get(user_id, []))