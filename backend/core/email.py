"""
Phase 11 addition: pluggable "send an email" abstraction.
Phase 22 addition: real SMTP provider, wired up for two callers —
password resets (existing) and the new EmailAgent/EmailTool, which lets
Athena compose and send an email on the user's behalf from chat.

EMAIL_PROVIDER=dev (default) never makes a network call: it just logs the
message and returns True so local dev / tests never need real credentials.

EMAIL_PROVIDER=smtp sends for real over smtplib using EMAIL_FROM_ADDRESS +
SMTP_HOST/PORT/USERNAME/PASSWORD/USE_TLS from core/config.py. This covers
Gmail, Outlook, and any other standard SMTP provider (SendGrid/Resend also
expose SMTP endpoints, so this one branch covers all of them without an
extra SDK dependency) — no caller of `send_email()` needs to change.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from backend.core.config import (
    EMAIL_PROVIDER,
    EMAIL_FROM_ADDRESS,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SMTP_USE_TLS,
)
from backend.core.logger import agent_logger as logger, error_logger


def send_email(to: str, subject: str, body: str) -> bool:
    """
    Returns True if the email was handed off successfully (or, in dev mode,
    "successfully logged"). Never raises -- a misconfigured email provider
    should never crash the request that triggered it (e.g. signup, or a
    chat turn where the user asked Athena to send an email). Callers that
    need to know *why* a send failed should check the logs; the boolean
    keeps every call site (auth flow, EmailTool) simple.
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

    if EMAIL_PROVIDER == "smtp":
        return _send_via_smtp(to, subject, body)

    error_logger.error(
        "[email] EMAIL_PROVIDER=%r is not implemented. Set EMAIL_PROVIDER=dev "
        "to log instead of sending, or =smtp with SMTP_HOST/PORT/USERNAME/"
        "PASSWORD configured.",
        EMAIL_PROVIDER,
    )
    return False


def _send_via_smtp(to: str, subject: str, body: str) -> bool:
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        error_logger.error(
            "[email:smtp] EMAIL_PROVIDER=smtp but SMTP_HOST/SMTP_USERNAME/"
            "SMTP_PASSWORD are not fully configured — refusing to attempt "
            "a send. Set these in .env (see core/config.py)."
        )
        return False

    msg = EmailMessage()
    msg["From"] = EMAIL_FROM_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        if SMTP_USE_TLS:
            # STARTTLS on the plain port (587 for most providers, incl. Gmail)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls(context=context)
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # Implicit TLS (465) — no STARTTLS handshake needed
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

        logger.info("[email:smtp] sent to=%s subject=%r", to, subject)
        return True

    except Exception as exc:
        error_logger.error("[email:smtp] send failed to=%s: %s", to, exc)
        return False


def send_password_reset_email(to: str, reset_url: str, raw_token: str) -> None:
    subject = "Reset your Athena password"
    body = (
        f"We received a request to reset your Athena password.\n\n"
        f"Reset link: {reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n"
        f"This link expires shortly.\n"
    )
    send_email(to, subject, body)
