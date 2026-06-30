"""
backend/api/calendar.py  —  Phase 20

Routes for connecting Google Calendar and reading/creating real events.

Note: /calendar/connect and /calendar/oauth/callback are deliberately on
the PUBLIC router (no JWT dependency) for /callback specifically — Google
redirects the browser here directly with no Authorization header, so we
identify the user via the CSRF state token instead (see resolve_state).
/connect itself DOES require auth (it's the user clicking "Connect" from
within the app), so it stays on the protected router.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.core.config import FRONTEND_BASE_URL
from backend.core.request_context import get_current_user_id
from backend.integrations import google_calendar as gcal

router = APIRouter()                 # protected (auth required)
public_router = APIRouter()          # public (Google's redirect lands here)


@router.get("/calendar/status")
def calendar_status():
    uid = get_current_user_id()
    if not gcal.is_configured():
        return {"configured": False, "connected": False}
    info = gcal.get_connection_info(uid)
    return {"configured": True, "connected": info is not None, **(info or {})}


@router.post("/calendar/connect")
def calendar_connect():
    """Returns the Google consent URL for the frontend to redirect to."""
    if not gcal.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google Calendar isn't configured on this server yet. "
                   "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env — "
                   "see backend/core/config.py for setup steps.",
        )
    uid = get_current_user_id()
    return {"authUrl": gcal.build_auth_url(uid)}


@router.delete("/calendar/disconnect")
def calendar_disconnect():
    uid = get_current_user_id()
    ok = gcal.disconnect(uid)
    if not ok:
        raise HTTPException(status_code=404, detail="No calendar connection found")
    return {"disconnected": True}


@public_router.get("/calendar/oauth/callback")
def calendar_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """
    Google redirects here after the user approves/denies access. No JWT
    on this request — Google doesn't send one — so the user is identified
    via the CSRF state token issued in /calendar/connect.
    """
    if error:
        return RedirectResponse(f"{FRONTEND_BASE_URL}/settings?calendar_error={error}")

    if not code or not state:
        return RedirectResponse(f"{FRONTEND_BASE_URL}/settings?calendar_error=missing_code")

    user_id = gcal.resolve_state(state)
    if not user_id:
        return RedirectResponse(f"{FRONTEND_BASE_URL}/settings?calendar_error=invalid_state")

    try:
        tokens = gcal.exchange_code_for_tokens(code)
        gcal.save_tokens(user_id, tokens)
    except Exception:
        return RedirectResponse(f"{FRONTEND_BASE_URL}/settings?calendar_error=token_exchange_failed")

    return RedirectResponse(f"{FRONTEND_BASE_URL}/settings?calendar_connected=1")


# ── Event read/write ────────────────────────────────────────────────────────

class CreateEventIn(BaseModel):
    title: str
    start: str   # ISO datetime
    end: str     # ISO datetime
    description: str | None = None
    location: str | None = None


@router.get("/calendar/events")
def get_events(days_ahead: int = 7):
    uid = get_current_user_id()
    if not gcal.is_connected(uid):
        raise HTTPException(status_code=409, detail="Google Calendar not connected")
    now = datetime.now(timezone.utc)
    try:
        events = gcal.list_events(uid, now, now + timedelta(days=days_ahead))
        return {"events": events}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch calendar events: {e}")


@router.post("/calendar/events")
def post_event(body: CreateEventIn):
    uid = get_current_user_id()
    if not gcal.is_connected(uid):
        raise HTTPException(status_code=409, detail="Google Calendar not connected")
    try:
        from dateutil import parser as dp
        start_dt = dp.isoparse(body.start)
        end_dt = dp.isoparse(body.end)
        event = gcal.create_event(uid, body.title, start_dt, end_dt, body.description, body.location)
        return event
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create calendar event: {e}")


@router.delete("/calendar/events/{event_id}")
def remove_event(event_id: str):
    uid = get_current_user_id()
    if not gcal.is_connected(uid):
        raise HTTPException(status_code=409, detail="Google Calendar not connected")
    try:
        ok = gcal.delete_event(uid, event_id)
        return {"deleted": ok}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete calendar event: {e}")
