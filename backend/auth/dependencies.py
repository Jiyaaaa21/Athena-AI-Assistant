"""
Phase 11 addition: FastAPI dependencies for authenticating requests.

`get_current_user` is the single entry point every protected route (or
router, via `app.include_router(..., dependencies=[Depends(get_current_user)])`
in main.py) relies on. Besides returning the User row, it also calls
`set_current_user_id()` so every legacy service-layer function further down
the call stack (memory_service, vector_store, tools/*) is automatically
scoped to the right user -- see core/request_context.py for why.

Phase 16 fix — async, not sync:
-----------------------------------
This function MUST be `async def`, not `def`. FastAPI runs synchronous
dependency callables inside a worker thread (via Starlette's
`run_in_threadpool` / anyio `to_thread.run_sync`) to avoid blocking the
event loop on potentially slow sync code. Critically, that thread-pool
call does NOT copy contextvars changes back to the caller's context --
exactly the same class of bug as `loop.run_in_executor()` not propagating
context to worker threads, except one level higher in the stack, inside
FastAPI's own internals, and far less obvious because it never raises or
logs anything.

The practical symptom: `set_current_user_id(user.id)` appeared to run
successfully (no errors, `user` was returned correctly, `Depends()`
resolved fine) -- but `get_current_user_id()` read back `None` everywhere
downstream, INCLUDING in the *same* request's route handler body and any
code reached from it (services, the streaming response generator, agents
run via run_in_executor, etc.). This silently broke per-user scoping in
many places at once: the reminder agent's timezone lookup always fell
back to the UTC default (causing wildly wrong "due in X hours" times
regardless of the user's actual saved timezone), RAG's document lookup
intermittently saw no documents for the user, and likely other
`get_current_user_id()` call sites inherited the same gap.

Making the dependency `async def` keeps it on the *same* coroutine/task
as the route handler -- no thread hop, so the contextvars `Context.set()`
call made inside it is visible everywhere else in that request, including
inside `loop.run_in_executor()` workers when the caller explicitly does
`captured_context.run(...)` (see api/chat.py's `_stream_generator`).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.core.security import decode_access_token, TokenError
from backend.core.request_context import set_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import User

# `tokenUrl` only matters for the interactive /docs "Authorize" button; the
# real client (the React frontend) just sends `Authorization: Bearer <token>`
# directly and never hits this URL.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    token: str | None = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise credentials_exception

    # Synchronous DB query is fine here -- this function itself stays
    # `async def` so it runs on the request's own task/context, not a
    # separate worker thread. The query call below is a quick local
    # SQLite/Postgres round-trip via SQLAlchemy's sync API, which does
    # not need its own thread offload to avoid meaningfully blocking
    # the loop for a single-row lookup.
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    set_current_user_id(user.id)
    return user


async def get_current_user_optional(
    token: str | None = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """
    Same as get_current_user, but returns None instead of raising when no
    (or an invalid) token is present. Not used by any protected route
    today, but kept available for future public-but-personalized endpoints.
    """
    if not token:
        return None
    try:
        return await get_current_user(token=token, db=db)
    except HTTPException:
        return None
