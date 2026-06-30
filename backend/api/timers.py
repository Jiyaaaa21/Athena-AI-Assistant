"""
backend/api/timers.py  —  Phase 18

Timers: short-duration countdown timers with an audible alarm, the
classic "set a timer for 10 minutes" voice command. Distinct from
Reminders, which are scheduled-datetime, silent-notification style.

The frontend owns the actual countdown display and alarm sound playback
(it ticks down locally using ends_at, no need to poll constantly) — this
API just persists timer state so it survives a page refresh and so
multiple tabs/devices could theoretically stay in sync.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import Timer
from backend.core.request_context import get_current_user_id

router = APIRouter()


def _serialize(t: Timer) -> dict:
    return {
        "id": t.id,
        "label": t.label,
        "durationSeconds": t.duration_seconds,
        "endsAt": t.ends_at.isoformat() if t.ends_at else None,
        "status": t.status,
        "remainingSecondsAtPause": t.remaining_seconds_at_pause,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
    }


class CreateTimerIn(BaseModel):
    duration_seconds: int
    label: str | None = None


@router.get("/timers")
def list_timers():
    """Active (running/paused) timers for the current user."""
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        timers = (
            db.query(Timer)
            .filter(Timer.user_id == uid, Timer.status.in_(["running", "paused"]))
            .order_by(Timer.created_at.desc())
            .all()
        )
        return {"timers": [_serialize(t) for t in timers]}
    finally:
        db.close()


@router.post("/timers")
def create_timer(body: CreateTimerIn):
    if body.duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="duration_seconds must be positive")
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        timer = Timer(
            user_id=uid,
            label=body.label,
            duration_seconds=body.duration_seconds,
            ends_at=now + timedelta(seconds=body.duration_seconds),
            status="running",
        )
        db.add(timer)
        db.commit()
        db.refresh(timer)
        return _serialize(timer)
    finally:
        db.close()


@router.post("/timers/{timer_id}/pause")
def pause_timer(timer_id: int):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        t = db.query(Timer).filter(Timer.id == timer_id, Timer.user_id == uid).first()
        if not t or t.status != "running":
            raise HTTPException(status_code=404, detail="Running timer not found")
        remaining = (t.ends_at - datetime.utcnow()).total_seconds()
        t.remaining_seconds_at_pause = max(0, int(remaining))
        t.status = "paused"
        db.commit()
        db.refresh(t)
        return _serialize(t)
    finally:
        db.close()


@router.post("/timers/{timer_id}/resume")
def resume_timer(timer_id: int):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        t = db.query(Timer).filter(Timer.id == timer_id, Timer.user_id == uid).first()
        if not t or t.status != "paused":
            raise HTTPException(status_code=404, detail="Paused timer not found")
        remaining = t.remaining_seconds_at_pause or 0
        t.ends_at = datetime.utcnow() + timedelta(seconds=remaining)
        t.remaining_seconds_at_pause = None
        t.status = "running"
        db.commit()
        db.refresh(t)
        return _serialize(t)
    finally:
        db.close()


@router.delete("/timers/{timer_id}")
def cancel_timer(timer_id: int):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        t = db.query(Timer).filter(Timer.id == timer_id, Timer.user_id == uid).first()
        if not t:
            raise HTTPException(status_code=404, detail="Timer not found")
        t.status = "cancelled"
        db.commit()
        return {"cancelled": timer_id}
    finally:
        db.close()


@router.post("/timers/{timer_id}/finish")
def mark_timer_finished(timer_id: int):
    """Called by the frontend once the countdown actually hits zero and
    the alarm has played, so the timer stops showing as 'active'."""
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        t = db.query(Timer).filter(Timer.id == timer_id, Timer.user_id == uid).first()
        if not t:
            raise HTTPException(status_code=404, detail="Timer not found")
        t.status = "finished"
        db.commit()
        return {"finished": timer_id}
    finally:
        db.close()
