from dotenv import load_dotenv
import os
import secrets

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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
