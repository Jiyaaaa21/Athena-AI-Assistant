"""
backend/integrations/google_calendar.py  —  Phase 20

Google Calendar OAuth flow + thin API wrapper. This is what makes
Athena's "calendar" actually be the user's real Google Calendar, not
another internal reminders table — events created here show up in the
user's actual phone/Google Calendar app, and events they already have
show up in Athena.

Uses raw HTTP calls to Google's OAuth2 + Calendar v3 REST endpoints
(via `requests`) rather than the google-api-python-client SDK, to avoid
adding a heavy dependency for what's a handful of well-documented REST
calls.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from backend.core.config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI,
)
from backend.database.db import SessionLocal
from backend.database.models import GoogleCalendarToken
from backend.core.logger import error_logger

_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_CALENDAR_API = "https://www.googleapis.com/calendar/v3"

_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

# In-memory state-token store for CSRF protection during the OAuth dance.
# Short-lived (5 min) and one-use — doesn't need to survive a restart.
_pending_states: dict[str, dict] = {}


def is_configured() -> bool:
    """True once the user has set up a Google OAuth Client ID/Secret."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def build_auth_url(user_id: int) -> str:
    """Returns the URL to redirect the user to for Google consent."""
    state = secrets.token_urlsafe(24)
    _pending_states[state] = {"user_id": user_id, "expires": datetime.utcnow() + timedelta(minutes=5)}

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",     # required to get a refresh_token
        "prompt": "consent",          # forces refresh_token on every connect, not just the first
        "state": state,
    }
    return f"{_AUTH_BASE}?{urlencode(params)}"


def resolve_state(state: str) -> int | None:
    """Validates a state token from the OAuth callback, returns the user_id it was issued for."""
    entry = _pending_states.pop(state, None)
    if not entry:
        return None
    if entry["expires"] < datetime.utcnow():
        return None
    return entry["user_id"]


def exchange_code_for_tokens(code: str) -> dict:
    """Exchange the authorization code for access + refresh tokens."""
    resp = requests.post(_TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_user_email(access_token: str) -> str | None:
    try:
        resp = requests.get(_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("email")
    except Exception:
        return None


def save_tokens(user_id: int, token_response: dict) -> None:
    db = SessionLocal()
    try:
        access_token = token_response["access_token"]
        refresh_token = token_response.get("refresh_token")  # only present on first consent
        expires_in = token_response.get("expires_in", 3600)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        scope = token_response.get("scope", "")
        email = fetch_user_email(access_token)

        row = db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == user_id).first()
        if row:
            row.access_token = access_token
            if refresh_token:  # Google only sends this on first consent — don't clobber with None
                row.refresh_token = refresh_token
            row.token_expiry = expiry
            row.scope = scope
            if email:
                row.google_email = email
        else:
            row = GoogleCalendarToken(
                user_id=user_id, access_token=access_token, refresh_token=refresh_token,
                token_expiry=expiry, scope=scope, google_email=email,
            )
            db.add(row)
        db.commit()
    finally:
        db.close()


def _refresh_access_token(row: GoogleCalendarToken, db) -> str | None:
    """Mint a new access token using the stored refresh_token."""
    if not row.refresh_token:
        return None
    try:
        resp = requests.post(_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": row.refresh_token,
            "grant_type": "refresh_token",
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        row.access_token = data["access_token"]
        row.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        db.commit()
        return row.access_token
    except Exception as e:
        error_logger.error(f"[GoogleCalendar] token refresh failed for user {row.user_id}: {e}")
        return None


def get_valid_access_token(user_id: int) -> str | None:
    """Returns a usable access token, refreshing it first if expired."""
    db = SessionLocal()
    try:
        row = db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == user_id).first()
        if not row:
            return None
        now = datetime.now(timezone.utc)
        expiry = row.token_expiry
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if not expiry or expiry <= now + timedelta(seconds=60):
            return _refresh_access_token(row, db)
        return row.access_token
    finally:
        db.close()


def is_connected(user_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == user_id).first() is not None
    finally:
        db.close()


def get_connection_info(user_id: int) -> dict | None:
    db = SessionLocal()
    try:
        row = db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == user_id).first()
        if not row:
            return None
        return {"connected": True, "email": row.google_email, "connectedAt": row.connected_at.isoformat() if row.connected_at else None}
    finally:
        db.close()


def disconnect(user_id: int) -> bool:
    db = SessionLocal()
    try:
        row = db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == user_id).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


# ── Calendar API operations ───────────────────────────────────────────────────

def list_events(user_id: int, time_min: datetime, time_max: datetime, max_results: int = 20) -> list[dict]:
    """List events in [time_min, time_max] from the user's primary calendar."""
    token = get_valid_access_token(user_id)
    if not token:
        raise RuntimeError("Google Calendar not connected")

    resp = requests.get(
        f"{_CALENDAR_API}/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "timeMin": time_min.astimezone(timezone.utc).isoformat(),
            "timeMax": time_max.astimezone(timezone.utc).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
        },
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        events.append({
            "id": item.get("id"),
            "title": item.get("summary", "(No title)"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "allDay": "date" in start and "dateTime" not in start,
            "location": item.get("location"),
            "description": item.get("description"),
            "htmlLink": item.get("htmlLink"),
        })
    return events


def create_event(
    user_id: int,
    title: str,
    start: datetime,
    end: datetime,
    description: str | None = None,
    location: str | None = None,
) -> dict:
    token = get_valid_access_token(user_id)
    if not token:
        raise RuntimeError("Google Calendar not connected")

    body = {
        "summary": title,
        "start": {"dateTime": start.astimezone(timezone.utc).isoformat()},
        "end": {"dateTime": end.astimezone(timezone.utc).isoformat()},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    resp = requests.post(
        f"{_CALENDAR_API}/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=10,
    )
    resp.raise_for_status()
    item = resp.json()
    return {
        "id": item.get("id"),
        "title": item.get("summary"),
        "start": item.get("start", {}).get("dateTime"),
        "end": item.get("end", {}).get("dateTime"),
        "htmlLink": item.get("htmlLink"),
    }


def delete_event(user_id: int, event_id: str) -> bool:
    token = get_valid_access_token(user_id)
    if not token:
        raise RuntimeError("Google Calendar not connected")
    resp = requests.delete(
        f"{_CALENDAR_API}/calendars/primary/events/{event_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    return resp.status_code in (200, 204, 404)
