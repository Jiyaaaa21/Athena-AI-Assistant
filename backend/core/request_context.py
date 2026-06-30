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


def set_current_user_id(user_id: Optional[int]) -> None:
    _current_user_id.set(user_id)


def get_current_user_id() -> Optional[int]:
    """
    Returns the authenticated user's id for the current request, or None
    if called outside of a request (e.g. a script) or before the auth
    dependency has run.
    """
    return _current_user_id.get()


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
