from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from backend.api.chat import router as chat_router
from backend.api.memory import router as memory_router
from backend.api.admin import router as admin_router
from backend.api.upload import router as upload_router
from backend.api.documents import router as documents_router, public_router as documents_public_router
from backend.api.notes import router as notes_router
from backend.api.reminders import router as reminders_router
from backend.api.news import router as news_router
from backend.api.weather import router as weather_router
from backend.api.analytics import router as analytics_router
# Phase 4.5 additions
from backend.api.preferences import router as preferences_router
from backend.api.health import router as health_router
# Phase 7 addition
from backend.api.search import router as search_router
# Phase 8 addition
from backend.api.conversations import router as conversations_router, public_router as conversations_public_router
# Phase 9 addition
from backend.api.voice import router as voice_router
# Phase 11 additions: Authentication + User Profiles
from backend.api.auth import router as auth_router
from backend.api.profile import router as profile_router
# Phase 16 additions: Memory Intelligence + Scheduler
from backend.api.user_memory import router as user_memory_router
from backend.api.timers import router as timers_router
from backend.api.routines import router as routines_router
from backend.api.calendar import router as calendar_router, public_router as calendar_public_router
from backend.api.push import router as push_router, public_router as push_public_router
from backend.api.goals import router as goals_router
from backend.api.projects import router as projects_router
from backend.api.briefing import router as briefing_router
from backend.api.assistant import router as assistant_router
from backend.api.proactive import router as proactive_router

from backend.core.config import ALLOWED_ORIGINS
from backend.database.migrate import run_migrations
from backend.auth.dependencies import get_current_user

app = FastAPI(title="Athena")

# Phase 2 addition: the frontend (Vite dev server / deployed static site)
# calls this API from a different origin, and nothing previously configured
# CORS, so every browser request would have been blocked silently. See
# core/config.py — ALLOWED_ORIGINS is configurable via the ALLOWED_ORIGINS
# env var and defaults to "*" for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Phase 17 fix: guarantee CORS headers even on unhandled exceptions ────────
#
# An unhandled exception raised inside a route handler (e.g. a TypeError
# from comparing a naive and timezone-aware datetime — see the
# auth/service.py fix in this same change) can produce a raw 500 response
# that never passes back through CORSMiddleware's response-wrapping logic
# the way a normal HTTPException does. The browser then reports this as
# a CORS failure ("No Access-Control-Allow-Origin header"), which sent
# debugging entirely in the wrong direction — the actual bug was a Python
# TypeError three layers down, not a CORS misconfiguration at all.
#
# This handler catches anything that reaches it unhandled, logs the real
# exception so it's diagnosable, and manually attaches the same CORS
# headers the middleware would have added — so future bugs in route
# handlers surface as "500 Internal Server Error" with the real error
# detail, not as a misleading CORS error that sends debugging down the
# wrong path.
from fastapi import Request
from fastapi.responses import JSONResponse
from backend.core.logger import error_logger
import traceback


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    error_logger.error(
        "Unhandled exception on %s %s: %s\n%s",
        request.method, request.url.path, exc, traceback.format_exc(),
    )

    origin = request.headers.get("origin")
    headers = {}
    if origin and (ALLOWED_ORIGINS == ["*"] or origin in ALLOWED_ORIGINS):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "false"

    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
        headers=headers,
    )


@app.on_event("startup")
def on_startup():
    import os
    os.makedirs("data/avatars", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    run_migrations()
    # Phase 21: Generate (or load persisted) VAPID keypair for Web Push.
    # Runs before the reminder scheduler below, since it now calls
    # send_push_to_user() on every fired reminder -- send_push_to_user()
    # itself degrades gracefully (returns 0, logs a warning) if VAPID
    # somehow isn't ready, but there's no reason to race it.
    from backend.core.push_vapid import ensure_vapid_keys
    ensure_vapid_keys()
    # Phase 16: Start reminder firing scheduler
    from backend.core.reminder_scheduler import start_scheduler
    start_scheduler()
    # Phase 23: Start the proactive-intelligence engine (periodically
    # evaluates each user's context and, occasionally, pushes an
    # unprompted insight -- see core/proactive_engine.py). Started after
    # the reminder scheduler for no strict reason other than reading
    # top-to-bottom as "reactive stuff first, proactive stuff second".
    from backend.core.proactive_engine import start_engine
    start_engine()


# ── Phase 11/12: route protection ────────────────────────────────────────────
# Every router below that touches user-owned data is mounted with
# `dependencies=[Depends(get_current_user)]`. This:
#   1. Returns 401 for any request without a valid access token, and
#   2. Sets the per-request "current user" context (core/request_context.py)
#      that the legacy chat/tool/memory/RAG call chains read from, so this
#      one line is what makes multi-user isolation apply to those existing
#      endpoints without editing their internals.
#
# `auth_router` (signup/login/refresh/...) and `health_router` are
# intentionally NOT protected -- you need to be able to log in before you
# have a token. `profile_router` is also mounted unprotected at the router
# level because one of its routes (avatar image serving) is meant to be
# fetchable like a plain image URL; every other route in that router
# declares `Depends(get_current_user)` itself.

_auth_required = [Depends(get_current_user)]

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(health_router)
# Public token-download endpoints (no JWT — token IS the auth)
app.include_router(conversations_public_router)

app.include_router(chat_router, dependencies=_auth_required)
app.include_router(memory_router, dependencies=_auth_required)
app.include_router(admin_router, dependencies=_auth_required)
app.include_router(upload_router, dependencies=_auth_required)
app.include_router(documents_router, dependencies=_auth_required)
# Phase 25 fix: public token-authenticated file serving for the document
# preview iframe — an <iframe src="..."> can't send an Authorization
# header, so this route deliberately carries no JWT dependency; the
# short-lived token in the URL is the auth (see api/documents.py).
app.include_router(documents_public_router)
app.include_router(notes_router, dependencies=_auth_required)
app.include_router(reminders_router, dependencies=_auth_required)
app.include_router(news_router, dependencies=_auth_required)
app.include_router(weather_router, dependencies=_auth_required)
app.include_router(analytics_router, dependencies=_auth_required)
# Phase 4.5 additions
app.include_router(preferences_router, dependencies=_auth_required)
# Phase 7 addition
app.include_router(search_router, dependencies=_auth_required)
# Phase 8 addition
app.include_router(conversations_router, dependencies=_auth_required)
# Phase 9 addition
app.include_router(voice_router, dependencies=_auth_required)
# Phase 14 additions: Assistant Transformation
app.include_router(goals_router, dependencies=_auth_required)
app.include_router(projects_router, dependencies=_auth_required)
app.include_router(briefing_router, dependencies=_auth_required)
app.include_router(assistant_router, dependencies=_auth_required)
app.include_router(proactive_router, dependencies=_auth_required)
app.include_router(user_memory_router, dependencies=_auth_required)
app.include_router(timers_router, dependencies=_auth_required)
app.include_router(routines_router, dependencies=_auth_required)
app.include_router(calendar_router, dependencies=_auth_required)
app.include_router(calendar_public_router)  # OAuth callback — no JWT, Google redirects here directly
app.include_router(push_router, dependencies=_auth_required)
app.include_router(push_public_router)  # vapid-public-key — no JWT, needed before subscribe flow


@app.get("/")
def home():
    return {
        "message": "Athena is running"
    }