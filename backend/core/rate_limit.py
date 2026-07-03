"""
backend/core/rate_limit.py — Phase 29

Two independent problems this addresses:

1. GROQ_API_KEY, GEMINI_API_KEY, and TAVILY_API_KEY are single keys shared
   across every user of this deployment, all on free tiers with real caps.
   Nothing previously stopped one user (a runaway script, a confused loop
   in some future automation, or just someone leaning on Enter) from
   sending a burst of chat messages large enough to exhaust that shared
   budget for everyone else, with zero visibility into who did it.

2. /auth/login, /auth/signup, /auth/forgot-password, and
   /auth/reset-password had no rate limiting at all -- straightforwardly
   brute-forceable.

This is a simple in-memory sliding-window limiter, not a full library
like slowapi -- deliberately, to avoid a new dependency for something
this small. It relies on the app running as a single worker process
(WEB_CONCURRENCY=1 / --workers 1), which is already a hard requirement
here for the reminder scheduler and proactive engine (see main.py) --
so this fits the same constraint the app already has, not a new one.

If this app ever legitimately needs >1 worker, this in-memory store (and
the OAuth CSRF state store in integrations/google_calendar.py) would both
need to move to something shared across processes (e.g. the database, or
Redis) -- noted here so that migration isn't a surprise later.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from backend.core.logger import error_logger


class RateLimiter:
    """Sliding-window limiter: at most `max_calls` within any trailing
    `window_seconds` window, per key (e.g. a user_id or an IP address)."""

    def __init__(self, max_calls: int, window_seconds: int, name: str):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.name = name
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Records this call and returns True if it's allowed, False if
        the key is currently over the limit (the over-limit call is NOT
        recorded, so it doesn't extend the window further)."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.max_calls:
                return False
            hits.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            return max(0, self.max_calls - len(hits))

    def check_or_raise(self, key: str, detail: str | None = None):
        """Convenience for route handlers: raises HTTPException(429) if
        the key is over the limit, otherwise returns normally."""
        if not self.check(key):
            error_logger.warning(
                f"[rate_limit] '{self.name}' tripped for key={key!r} "
                f"(limit: {self.max_calls} per {self.window_seconds}s)"
            )
            raise HTTPException(
                status_code=429,
                detail=detail or (
                    f"Rate limit exceeded ({self.max_calls} requests per "
                    f"{self.window_seconds}s). Please slow down and try again shortly."
                ),
            )


def require_budget(
    minute_limiter: RateLimiter,
    daily_limiter: RateLimiter,
    key: str,
    minute_detail: str,
    daily_detail: str,
):
    """
    Checks a request against both a per-minute and a per-day limiter for
    the same key, raising a 429 with an appropriately worded message for
    whichever one actually trips. Used by every route that consumes one
    of the shared free-tier API budgets (chat/LLM text, voice, uploads).
    """
    minute_limiter.check_or_raise(key, detail=minute_detail)
    daily_limiter.check_or_raise(key, detail=daily_detail)


# ── Chat/LLM-text: protects the shared free-tier Groq/Gemini/Tavily budget ───
#
# Applied across EVERY endpoint that ultimately calls a chat-completion
# LLM, not just /chat/stream -- GET /chat (a separate non-streaming
# endpoint with the same underlying cost), /briefing (a single ask_llm_raw
# call per request -- and there's a one-click refresh button for it in the
# UI with no cooldown of its own), /routines/{id}/run (executes routine
# steps through the SAME orchestrator /chat/stream uses, just via a
# completely different endpoint), and /assistant/action (a classification
# call before it even decides what to do). All of these draw on the exact
# same shared keys, so they share the exact same two budgets -- a user
# can't work around the chat limit by hammering the briefing-refresh
# button or a routine instead.
#
# Per-user, two windows: a short one to stop a rapid-fire burst, and a
# daily one to stop a single user from eating the whole day's shared
# quota even at a "reasonable" pace. Both are generous for genuine human
# use -- these exist to catch scripts/loops/abuse, not to throttle normal
# use of the app.
chat_rate_limiter_minute = RateLimiter(max_calls=20, window_seconds=60, name="chat_per_minute")
chat_rate_limiter_daily = RateLimiter(max_calls=300, window_seconds=86400, name="chat_per_day")

# ── Voice: protects Groq Whisper / the Hugging Face Whisper fallback ─────────
#
# A distinct resource from chat completions (different models, and for
# Groq specifically, a different per-model quota bucket), so it gets its
# own budget rather than sharing the chat one -- otherwise a burst of
# voice notes would eat into someone's text-chat budget for the day too.
voice_rate_limiter_minute = RateLimiter(max_calls=15, window_seconds=60, name="voice_per_minute")
voice_rate_limiter_daily = RateLimiter(max_calls=150, window_seconds=86400, name="voice_per_day")

# ── Document upload: protects the Hugging Face embeddings API ────────────────
#
# Also a distinct shared resource (HF_TOKEN), separate budget for the
# same reason as voice above.
upload_rate_limiter_minute = RateLimiter(max_calls=10, window_seconds=60, name="upload_per_minute")
upload_rate_limiter_daily = RateLimiter(max_calls=50, window_seconds=86400, name="upload_per_day")

# ── Document search: also HF embeddings (query embedding, not upload) ────────
#
# Same underlying resource as upload above, but deliberately a separate,
# more generous limiter rather than sharing the upload one. The frontend
# debounces search input (400ms), but a focused search session still
# legitimately fires several queries a minute as someone refines their
# search terms -- the tight upload limit (uploading a file is a rare,
# deliberate action) would frustrate normal search use. Still bounded
# against a scripted/automated abuse loop.
search_rate_limiter_minute = RateLimiter(max_calls=30, window_seconds=60, name="search_per_minute")
search_rate_limiter_daily = RateLimiter(max_calls=300, window_seconds=86400, name="search_per_day")

# ── Auth: protects against brute-forcing, keyed by IP since there's no
# authenticated user yet at this point ────────────────────────────────────────
auth_rate_limiter = RateLimiter(max_calls=10, window_seconds=60, name="auth_per_minute")