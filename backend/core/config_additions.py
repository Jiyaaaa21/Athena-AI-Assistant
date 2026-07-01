# ── APPEND THIS BLOCK TO THE END OF backend/core/config.py ──────────────────

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
