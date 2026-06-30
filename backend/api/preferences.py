"""
User Preferences API — Phase 4.5 addition.

Endpoints:
  GET  /preferences        → current preferences (defaults if unset)
  PUT  /preferences        → upsert all preferences

Stored in a single JSON blob in the `user_preferences` table (one row, key="default").
This avoids schema changes for each new preference field.
"""

from __future__ import annotations

import json
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from backend.database.db import SessionLocal
from backend.database.models import UserPreference
from backend.core.request_context import get_current_user_id

router = APIRouter()

_DEFAULT_PREFS = {
    "theme": "system",            # "light" | "dark" | "system"
    "notifications": True,
    "default_search_behavior": "web",   # "web" | "documents" | "both"
    "compact_view": False,
    "show_timestamps": True,
    # Phase 14: timezone for correct reminder time resolution
    # Accepts any IANA tz string e.g. "Asia/Kolkata", "America/New_York"
    "timezone": "UTC",
    # feature toggles
    "feature_voice": True,
    "feature_memory": True,
    "feature_analytics": True,
    "feature_experimental": False,
}

_KEY = "default"


def _get_prefs(db) -> dict:
    row = db.query(UserPreference).filter(
        UserPreference.key == _KEY, UserPreference.user_id == get_current_user_id()
    ).first()
    if not row:
        return dict(_DEFAULT_PREFS)
    try:
        stored = json.loads(row.value)
        # Merge with defaults so new keys always appear
        return {**_DEFAULT_PREFS, **stored}
    except Exception:
        return dict(_DEFAULT_PREFS)


def _set_prefs(db, prefs: dict):
    row = db.query(UserPreference).filter(
        UserPreference.key == _KEY, UserPreference.user_id == get_current_user_id()
    ).first()
    blob = json.dumps(prefs)
    if row:
        row.value = blob
    else:
        row = UserPreference(key=_KEY, value=blob, user_id=get_current_user_id())
        db.add(row)
    db.commit()


class PrefsIn(BaseModel):
    theme: Optional[str] = None
    notifications: Optional[bool] = None
    default_search_behavior: Optional[str] = None
    compact_view: Optional[bool] = None
    show_timestamps: Optional[bool] = None
    # Phase 14: user's IANA timezone (e.g. "Asia/Kolkata", "America/New_York")
    timezone: Optional[str] = None
    feature_voice: Optional[bool] = None
    feature_memory: Optional[bool] = None
    feature_analytics: Optional[bool] = None
    feature_experimental: Optional[bool] = None


@router.get("/preferences")
def get_preferences():
    db = SessionLocal()
    try:
        return _get_prefs(db)
    finally:
        db.close()


@router.put("/preferences")
def update_preferences(body: PrefsIn):
    db = SessionLocal()
    try:
        current = _get_prefs(db)
        updates = body.model_dump(exclude_none=True)
        current.update(updates)
        _set_prefs(db, current)
        return current
    finally:
        db.close()