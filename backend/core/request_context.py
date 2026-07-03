"""
Phase 12 addition: per-request "current user" context.

Why this exists
----------------
Athena's chat pipeline (api/chat.py -> agents/agent.py -> tools/*.py ->
core/memory_service.py / rag/*) is a long, synchronous-looking call chain
of module-level functions with fixed signatures (e.g. `BaseTool.run(self,
input_data)` takes only a string -- it has no way to receive a user id).
Rewriting every signature in that chain to thread a `user_id` parameter
through would touch ~15 files and risk breaking the existing, working
tool-routing behaviour that Phase 11/12 explicitly must not regress.

Instead, the FastAPI auth dependency (auth/dependencies.py) sets the
authenticated user's id into this contextvar at the very start of every
protected request. Every service-layer function that needs to scope a
query to "the current user" (memory_service, vector_store, tools/*) reads
it back via `get_current_user_id()`. New REST endpoints (notes, reminders,
documents, ...) use the exact same helper for consistency, even though
most of them could also take an explicit `current_user` dependency -- using
one mechanism everywhere keeps the isolation guarantee uniform and easy to
audit.

Why a contextvar (not a global) is safe here
---------------------------------------------
`contextvars.ContextVar` is asyncio-task-local: each incoming request that
FastAPI/Starlette handles gets its own `Context`, so concurrent requests
from different users never see each other's value, even though the
variable looks "global" at the module level. `asyncio.to_thread` (used by
the SSE streaming chat endpoint) explicitly copies the current context
into the worker thread, so the value still flows correctly through the
`await asyncio.to_thread(...)` calls in api/chat.py.
"""

from __future__ import annotations

import contextvars
from typing import Optional

_current_user_id: "contextvars.ContextVar[Optional[int]]" = contextvars.ContextVar(
    "current_user_id", default=None
)

# Phase 34 addition: see set_current_request_timezone()'s docstring below
# for why this exists alongside the separately-persisted timezone
# preference (core/preferences.py) rather than replacing it.
_current_request_timezone: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "current_request_timezone", default=None
)


def set_current_user_id(user_id: Optional[int]) -> None:
    _current_user_id.set(user_id)


def get_current_user_id() -> Optional[int]:
    """
    Returns the authenticated user's id for the current request, or None
    if called outside of a request (e.g. a script) or before the auth
    dependency has run.
    """
    return _current_user_id.get()


def set_current_request_timezone(tz_name: Optional[str]) -> None:
    """
    Phase 34 fix: reminder times were occasionally created in UTC for
    users whose browser-detected timezone (Asia/Kolkata, etc.) had been
    correctly synced to their UserPreference row -- but not yet, at the
    exact moment a reminder got created. That sync
    (lib/api.ts's syncTimezoneToBackend()) is fire-and-forget and does
    two sequential network round-trips; a reminder created via chat
    within that window (very plausible right after login, especially
    after a Render free-tier cold start) landed before the sync did,
    and agents/reminder_agent.py's _get_user_timezone() correctly-but-
    unhelpfully fell back to UTC, permanently baking in the wrong time.

    Rather than try to make the sync land faster or block on it (which
    only narrows the race, doesn't close it), the frontend now sends its
    current IANA timezone on the request that actually matters (see
    api/chat.py's chat_stream, reading the X-Timezone header) --
    computed fresh at send time, not dependent on any prior sync having
    completed. This has no race condition to lose: the browser tells the
    backend its own timezone on the very request that needs it.

    The separately-persisted preference isn't redundant, though -- it's
    still what background jobs without a live request use (e.g.
    core/proactive_engine.py deciding whether it's a reasonable local
    hour to surface an insight). _get_user_timezone() checks this
    per-request value first and falls back to the stored preference,
    which this also opportunistically keeps in sync (see reminder_agent.py).
    """
    _current_request_timezone.set(tz_name)


def get_current_request_timezone() -> Optional[str]:
    return _current_request_timezone.get()


def require_current_user_id() -> int:
    """
    Same as get_current_user_id(), but raises instead of silently
    returning None. Use this in service-layer code where proceeding
    without a user id would mean writing/reading unscoped (potentially
    cross-user) data -- better to fail loudly.
    """
    user_id = _current_user_id.get()
    if user_id is None:
        raise RuntimeError(
            "No authenticated user in the current request context. "
            "This usually means a protected route's auth dependency "
            "didn't run before this code executed."
        )
    return user_id