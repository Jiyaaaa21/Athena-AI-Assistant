"""
backend/api/goals.py  —  Phase 14: Goal Awareness API

Endpoints:
  GET    /goals              — list all active goals
  POST   /goals              — create a goal
  PUT    /goals/{id}         — update goal
  PATCH  /goals/{id}/progress — update progress
  DELETE /goals/{id}         — delete goal

Goals are factored into every Athena response via context_builder.py.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import Goal
from backend.core.request_context import get_current_user_id

router = APIRouter()


def utcnow():
    return datetime.now(timezone.utc)


class GoalCreate(BaseModel):
    title: str
    description: str | None = None
    timeframe: str = "medium"   # "short" | "medium" | "long"


class GoalUpdate(BaseModel):
    title: str
    description: str | None = None
    timeframe: str = "medium"
    status: str = "active"      # "active" | "completed" | "paused"
    progress: int = 0


class ProgressUpdate(BaseModel):
    progress: int   # 0-100


def _serialize(g: Goal) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "timeframe": g.timeframe,
        "status": g.status,
        "progress": g.progress or 0,
        "createdAt": g.created_at.isoformat() if g.created_at else None,
        "updatedAt": g.updated_at.isoformat() if g.updated_at else None,
    }


@router.get("/goals")
def list_goals():
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        goals = (
            db.query(Goal)
            .filter(Goal.user_id == uid)
            .order_by(Goal.created_at.desc())
            .all()
        )
        return [_serialize(g) for g in goals]
    finally:
        db.close()


@router.post("/goals")
def create_goal(payload: GoalCreate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        goal = Goal(
            user_id=uid,
            title=payload.title,
            description=payload.description,
            timeframe=payload.timeframe,
            status="active",
            progress=0,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return _serialize(goal)
    finally:
        db.close()


@router.put("/goals/{goal_id}")
def update_goal(goal_id: int, payload: GoalUpdate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == uid).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")
        goal.title = payload.title
        goal.description = payload.description
        goal.timeframe = payload.timeframe
        goal.status = payload.status
        goal.progress = payload.progress
        db.commit()
        db.refresh(goal)
        return _serialize(goal)
    finally:
        db.close()


@router.patch("/goals/{goal_id}/progress")
def update_progress(goal_id: int, payload: ProgressUpdate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == uid).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")
        goal.progress = max(0, min(100, payload.progress))
        if goal.progress == 100:
            goal.status = "completed"
        db.commit()
        db.refresh(goal)
        return _serialize(goal)
    finally:
        db.close()


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == uid).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")
        db.delete(goal)
        db.commit()
        return {"ok": True}
    finally:
        db.close()