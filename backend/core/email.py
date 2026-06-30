"""
Phase 11 addition: pluggable "send an email" abstraction.

Today only EMAIL_PROVIDER=dev (the default) is implemented: it never makes
a network call, just logs the message and returns the content so the
caller (auth/service.py) can decide whether to also hand the raw token
back in the API response for local testing.

Wiring up a real provider later means:
  1. Add a branch in `send_email()` below for "smtp" | "sendgrid" | "resend"
     that actually calls the provider's API/SMTP using
     EMAIL_FROM_ADDRESS + whatever provider-specific env vars you add to
     core/config.py.
  2. Set EMAIL_PROVIDER to that value.
No caller of `send_email()` needs to change.
"""

from __future__ import annotations

from backend.core.config import EMAIL_PROVIDER, EMAIL_FROM_ADDRESS
from backend.core.logger import agent_logger as logger


def send_email(to: str, subject: str, body: str) -> bool:
    """
    Returns True if the email was handed off successfully (or, in dev mode,
    "successfully logged"). Never raises -- a misconfigured email provider
    should never crash the request that triggered it (e.g. signup).
    """
    if EMAIL_PROVIDER == "dev":
        logger.info(
            "[email:dev] from=%s to=%s subject=%r\n%s",
            EMAIL_FROM_ADDRESS,
            to,
            subject,
            body,
        )
        return True

    # Placeholder for real providers. Intentionally raises so a
    # misconfigured EMAIL_PROVIDER value fails loudly at send-time instead
    # of silently pretending to have sent an email.
    raise NotImplementedError(
        f"EMAIL_PROVIDER={EMAIL_PROVIDER!r} is not implemented yet. "
        "Add an SMTP/SendGrid/Resend integration in core/email.py, or set "
        "EMAIL_PROVIDER=dev to log instead of sending."
    )


def send_password_reset_email(to: str, reset_url: str, raw_token: str) -> None:
    subject = "Reset your Athena password"
    body = (
        f"We received a request to reset your Athena password.\n\n"
        f"Reset link: {reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n"
        f"This link expires shortly.\n"
    )
    send_email(to, subject, body)
