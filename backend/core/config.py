from dotenv import load_dotenv
import os
import secrets
 
load_dotenv()
 
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Phase 26 addition: free fallback LLM provider, used only when Groq fails
# (rate limit / token quota exhausted / outage) — see core/llm.py. Get a
# free key with no credit card at https://aistudio.google.com/apikey.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GNEWS_API_KEY = os.getenv(
    "GNEWS_API_KEY"
)
 
# Phase 2 addition: the frontend now calls this API cross-origin (the Vite
# dev server and the FastAPI server run on different ports/hosts), and
# nothing in the original backend configured CORS, so every request from
# the browser would have been blocked. Comma-separated list of allowed
# origins, e.g. "http://localhost:5173,https://athena.yourdomain.com".
# Defaults to "*" (open) for local development convenience.
#
# Phase 11 note: browsers reject `Access-Control-Allow-Credentials: true`
# combined with a wildcard origin. Auth here relies on an Authorization
# header (not cookies), so this isn't a hard requirement -- but if
# ALLOWED_ORIGINS is ever narrowed to real origins, allow_credentials can
# safely be turned on in main.py without any change here.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
 
# Phase 8 addition: nothing previously bounded upload size or page count,
# so a very large PDF could hang the embedding step for a long time or
# exhaust memory. Configurable via env vars; sane defaults otherwise.
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25"))
MAX_UPLOAD_PAGES = int(os.getenv("MAX_UPLOAD_PAGES", "500"))
 
# ── Phase 11/12 addition: Database ───────────────────────────────────────────
# Postgres-ready: the entire app talks to SQLAlchemy, never to sqlite3
# directly, so moving to Postgres later is just:
#   1. set DATABASE_URL=postgresql+psycopg2://user:pass@host/dbname
#   2. `alembic upgrade head`
# No application code changes required.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///athena.db")
 
# ── Phase 11 addition: JWT Authentication ────────────────────────────────────
# IMPORTANT: JWT_SECRET_KEY MUST be set via env var in any real deployment.
# The random fallback below means tokens stop validating across restarts
# (every user gets logged out) if it's left unset -- that's intentional:
# it's a loud, safe failure mode rather than silently shipping a fixed
# well-known secret baked into source control.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(64)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
 
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30")
)
 
# ── Phase 11 addition: Avatars ────────────────────────────────────────────────
AVATAR_UPLOAD_DIR = os.getenv("AVATAR_UPLOAD_DIR", "data/avatars")
MAX_AVATAR_SIZE_MB = int(os.getenv("MAX_AVATAR_SIZE_MB", "5"))
 
# ── Phase 11 addition: Email provider (pluggable, stubbed for now) ──────────
# When unset, password-reset "emails" are just logged + the raw token is
# returned in the API response (dev-mode only -- see core/email.py). Set
# EMAIL_PROVIDER to "smtp" | "sendgrid" | "resend" and fill in the matching
# env vars once a provider is wired up; no other code needs to change.
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "dev")
EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "no-reply@athena.local")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
 
# ── Phase 20 addition: Google Calendar OAuth ─────────────────────────────────
# Required for real calendar integration (read/create events). The user
# must create an OAuth 2.0 Client ID in Google Cloud Console:
#   1. console.cloud.google.com → APIs & Services → Credentials
#   2. Create OAuth client ID → Web application
#   3. Authorized redirect URI: http://localhost:8000/calendar/oauth/callback
#      (swap host/port for your real backend URL in production)
#   4. Enable the "Google Calendar API" under APIs & Services → Library
#   5. Copy the Client ID and Client Secret into your .env as shown below
#
# Without these set, the calendar feature simply stays disabled (the
# "Connect Google Calendar" button in Settings shows a setup notice
# instead of erroring) — nothing else breaks.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/calendar/oauth/callback"
)
 
# ── Phase 21 addition: PWA push notifications (Web Push / VAPID) ────────────
# No console setup needed here, unlike Google Calendar -- the VAPID
# keypair is generated automatically on first run (see
# core/push_vapid.py) and persisted to data/vapid/private_key.pem.
#
# VAPID_CLAIM_EMAIL is the one required piece of config: RFC 8292 requires
# every VAPID-signed push to carry a "sub" claim identifying who's sending
# it (an operator contact, so a push service like FCM can reach out if
# this server starts misbehaving/spamming). It doesn't need to be a real
# inbox for local dev, but should be a real address before this ever
# talks to a real push service in production.
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "mailto:admin@athena.local")
 
# ── Phase 22 addition: SMTP (real email sending) ─────────────────────────────
# Only read when EMAIL_PROVIDER=smtp (see core/email.py). Works with Gmail
# (use an App Password, not your normal password), Outlook, or any SMTP
# relay. SMTP_USE_TLS=true means STARTTLS on the given port (587 is the
# normal choice); set it to false for implicit-TLS providers on port 465.
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
 
# ── Phase 22 addition: Connected Actions (generic outbound webhooks) ────────
# Lets a user register their own webhooks (Zapier, Make.com, IFTTT, Home
# Assistant, Slack incoming webhook, n8n, ...) in Settings, then trigger
# them from chat ("run my 'lights on' action") without Athena needing a
# bespoke integration written for every possible third-party service.
#
# SSRF guard: by default the action tool refuses to POST to a private/
# loopback address (127.0.0.1, 10.x, 192.168.x, etc.) since a malicious or
# buggy webhook URL pointed inward could otherwise be used to probe the
# server's own network. Set ALLOW_LOCAL_ACTION_WEBHOOKS=true only for local
# dev if you're intentionally testing against something like a local n8n
# or Home Assistant instance.
ALLOW_LOCAL_ACTION_WEBHOOKS = os.getenv(
    "ALLOW_LOCAL_ACTION_WEBHOOKS", "false"
).lower() in ("1", "true", "yes")
ACTION_WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("ACTION_WEBHOOK_TIMEOUT_SECONDS", "10"))
MAX_CONNECTED_ACTIONS_PER_USER = int(os.getenv("MAX_CONNECTED_ACTIONS_PER_USER", "20"))
 
# ── Phase 23 addition: Proactive Intelligence engine ─────────────────────────
# Background loop (core/proactive_engine.py) that periodically looks at each
# user's own context (goals, overdue reminders, upcoming calendar events,
# recent conversation) and decides -- via an LLM call -- whether there's
# something worth surfacing unprompted, then delivers it as a push
# notification (core/push_notifications.py) and a persisted ProactiveInsight
# row the frontend can show as a dismissible feed.
#
# PROACTIVE_INTERVAL_SECONDS: how often the background loop wakes up and
# re-evaluates every user. 900s (15 min) by default -- frequent enough to
# feel responsive to an upcoming calendar event, infrequent enough not to
# hammer the Groq API once there are many users.
#
# PROACTIVE_MIN_GAP_MINUTES: per-user cooldown. Even if the engine wakes up
# every 15 minutes, it won't generate a second insight for the same user
# until this many minutes have passed since their last one -- the whole
# point is occasional, relevant nudges, not a notification every cycle.
PROACTIVE_ENABLED = os.getenv("PROACTIVE_ENABLED", "true").lower() in ("1", "true", "yes")
PROACTIVE_INTERVAL_SECONDS = int(os.getenv("PROACTIVE_INTERVAL_SECONDS", "900"))
PROACTIVE_MIN_GAP_MINUTES = int(os.getenv("PROACTIVE_MIN_GAP_MINUTES", "120"))