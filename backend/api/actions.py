"""
backend/api/actions.py  —  Phase 22: Connected Actions API

Endpoints:
  GET    /actions           — list the user's connected actions
  POST   /actions            — register a new one
  PUT    /actions/{id}       — update
  DELETE /actions/{id}       — delete
  POST   /actions/{id}/test  — fire it immediately (bypasses chat confirmation,
                                since clicking "Test" in Settings already IS
                                the confirmation)

Mounted with auth required in main.py, same as goals/projects/etc.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from backend.database.db import SessionLocal
from backend.database.models import UserAction
from backend.core.request_context import get_current_user_id
from backend.core.config import MAX_CONNECTED_ACTIONS_PER_USER
from backend.tools.action_tool import ActionTool

router = APIRouter()
_action_tool = ActionTool()


class ActionCreate(BaseModel):
    name: str
    description: str | None = None
    webhook_url: str
    http_method: str = "POST"
    payload_template: str | None = None

    @field_validator("webhook_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("webhook_url must start with http:// or https://")
        return v

    @field_validator("http_method")
    @classmethod
    def _validate_method(cls, v: str) -> str:
        v = v.upper()
        if v not in ("GET", "POST", "PUT", "PATCH"):
            raise ValueError("http_method must be one of GET, POST, PUT, PATCH")
        return v


class ActionUpdate(ActionCreate):
    enabled: bool = True


def _serialize(a: UserAction) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "webhookUrl": a.webhook_url,
        "httpMethod": a.http_method,
        "payloadTemplate": a.payload_template,
        "enabled": a.enabled,
        "lastTriggeredAt": a.last_triggered_at.isoformat() if a.last_triggered_at else None,
        "createdAt": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/actions")
def list_actions():
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        actions = (
            db.query(UserAction)
            .filter(UserAction.user_id == uid)
            .order_by(UserAction.created_at.desc())
            .all()
        )
        return [_serialize(a) for a in actions]
    finally:
        db.close()


@router.post("/actions")
def create_action(payload: ActionCreate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()

        count = db.query(UserAction).filter(UserAction.user_id == uid).count()
        if count >= MAX_CONNECTED_ACTIONS_PER_USER:
            raise HTTPException(
                status_code=400,
                detail=f"Limit of {MAX_CONNECTED_ACTIONS_PER_USER} connected actions reached.",
            )

        existing = (
            db.query(UserAction)
            .filter(UserAction.user_id == uid, UserAction.name.ilike(payload.name))
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="An action with this name already exists.")

        action = UserAction(
            user_id=uid,
            name=payload.name,
            description=payload.description,
            webhook_url=payload.webhook_url,
            http_method=payload.http_method,
            payload_template=payload.payload_template,
            enabled=True,
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        return _serialize(action)
    finally:
        db.close()


@router.put("/actions/{action_id}")
def update_action(action_id: int, payload: ActionUpdate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        action = db.query(UserAction).filter(UserAction.id == action_id, UserAction.user_id == uid).first()
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")

        action.name = payload.name
        action.description = payload.description
        action.webhook_url = payload.webhook_url
        action.http_method = payload.http_method
        action.payload_template = payload.payload_template
        action.enabled = payload.enabled
        db.commit()
        db.refresh(action)
        return _serialize(action)
    finally:
        db.close()


@router.delete("/actions/{action_id}")
def delete_action(action_id: int):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        action = db.query(UserAction).filter(UserAction.id == action_id, UserAction.user_id == uid).first()
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        db.delete(action)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/actions/{action_id}/test")
def test_action(action_id: int):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        action = db.query(UserAction).filter(UserAction.id == action_id, UserAction.user_id == uid).first()
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        result = _action_tool._trigger(db, action, "")
        return {"result": result}
    finally:
        db.close()
