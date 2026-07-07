"""
backend/core/user_timezone.py — Phase 35

Shared per-user timezone resolution, used by both agents/reminder_agent.py
(parsing "remind me at 5pm" correctly) and core/context_builder.py
(surfacing the actual current date/time in every conversational
response — see that module for why this was previously missing
entirely, which is what made a plain "what time is it" unanswerable).

Extracted from agents/reminder_agent.py, where this logic was originally
written but didn't really belong architecturally -- core/ modules
needing it would have had to import from agents/, which is backwards
(agents should depend on core, not the other way around).
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.core.logger import agent_logger
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import UserPreference


def get_user_timezone() -> str:
    """
    Phase 16 fix: added diagnostic logging for every fallback path, since
    silent UTC defaulting was the root cause of multiple "wrong reminder
    time" bugs that were invisible in server logs and took many rounds of
    debugging to trace. Now any time this returns "UTC" because the user
    has no saved preference (rather than because they explicitly chose
    UTC), it's logged so the gap is visible immediately instead of only
    showing up as a confusing user-facing symptom.

    Phase 34 fix: even with the above logging, the stored preference
    could still genuinely not have landed yet at the moment a reminder
    was created -- syncTimezoneToBackend() is fire-and-forget and does
    two sequential network round-trips, so a reminder created via chat
    within that window (very plausible right after login) still hit the
    "no preferences row yet" fallback and got permanently created in
    UTC. Now checks the CURRENT request's fresh, race-condition-free
    timezone (sent as the X-Timezone header on every /chat/stream
    request, see api/chat.py) before ever touching the stored
    preference. If that's present, it's used directly -- and
    opportunistically written back to the stored preference too, so
    background jobs with no live request (the proactive engine deciding
    whether it's a reasonable local hour to surface an insight) also
    self-heal without needing their own separate sync path.
    """
    from backend.core.request_context import get_current_request_timezone

    fresh_tz = get_current_request_timezone()
    if fresh_tz:
        _opportunistically_persist_timezone(fresh_tz)
        return fresh_tz

    db = SessionLocal()
    try:
        uid = get_current_user_id()
        if uid is None:
            agent_logger.warning(
                "[user_timezone] get_user_timezone: get_current_user_id() "
                "returned None — falling back to UTC. This means the auth "
                "context did not propagate to this call; times for this "
                "request will be wrong unless the user is actually in UTC."
            )
            return "UTC"

        row = db.query(UserPreference).filter(
            UserPreference.key == "default",
            UserPreference.user_id == uid,
        ).first()

        if row and row.value:
            prefs = json.loads(row.value)
            tz = prefs.get("timezone")
            if tz:
                return tz
            agent_logger.info(
                f"[user_timezone] user {uid} has a preferences row but no "
                f"timezone key set — falling back to UTC. Frontend "
                f"syncTimezoneToBackend() may not have run yet for this user."
            )
            return "UTC"

        agent_logger.info(
            f"[user_timezone] user {uid} has no preferences row at all — "
            f"falling back to UTC. This is expected for a brand-new user "
            f"before their first timezone sync completes."
        )
        return "UTC"
    except Exception as e:
        agent_logger.error(f"[user_timezone] get_user_timezone failed: {e}")
        return "UTC"
    finally:
        db.close()


def _opportunistically_persist_timezone(tz_name: str) -> None:
    """Best-effort write-back of a freshly-known-good timezone into the
    stored preference, so paths that only ever check the stored value
    (background jobs with no live request) benefit too. Never raises --
    this is a nice-to-have, not something that should ever break a
    caller if it fails."""
    uid = get_current_user_id()
    if uid is None:
        return
    db = SessionLocal()
    try:
        row = db.query(UserPreference).filter(
            UserPreference.key == "default",
            UserPreference.user_id == uid,
        ).first()
        prefs = {}
        if row and row.value:
            try:
                prefs = json.loads(row.value)
            except Exception:
                prefs = {}
        if prefs.get("timezone") == tz_name:
            return  # already in sync, nothing to write
        prefs["timezone"] = tz_name
        blob = json.dumps(prefs)
        if row:
            row.value = blob
        else:
            row = UserPreference(key="default", value=blob, user_id=uid)
            db.add(row)
        db.commit()
    except Exception as e:
        agent_logger.warning(f"[user_timezone] opportunistic timezone persist failed (non-fatal): {e}")
    finally:
        db.close()


def local_now_str(tz_name: str) -> str:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        now = datetime.now(tz)
        return now.strftime("%A, %d %B %Y, %I:%M %p %Z")
    except Exception:
        return datetime.utcnow().strftime("%A, %d %B %Y, %I:%M %p UTC")


def to_iso_with_tz(time_str: str, tz_name: str) -> str | None:
    try:
        import zoneinfo
        from dateutil import parser as dp
        tz = zoneinfo.ZoneInfo(tz_name)
        now_local = datetime.now(tz)
        parsed = dp.parse(time_str, default=now_local, fuzzy=True)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        from datetime import timezone as utc_tz
        return parsed.astimezone(utc_tz.utc).isoformat()
    except Exception:
        return None