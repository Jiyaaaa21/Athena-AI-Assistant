"""
backend/tools/email_tool.py  —  Phase 22

Lets Athena actually send an email on the user's behalf (as opposed to
only sending system emails like password resets). Deliberately thin: all
composing/confirmation logic lives in agents/email_agent.py — this tool
only knows how to send once given a fully-formed to/subject/body.
"""
from __future__ import annotations

from backend.core.email import send_email
from backend.core.config import EMAIL_PROVIDER


class EmailTool:

    name = "email"

    description = (
        "Send an email on the user's behalf. Input: 'send:to|subject|body'"
    )

    def run(self, command: str) -> str:
        if not command.startswith("send:"):
            return "Invalid email command."

        payload = command.replace("send:", "", 1).strip()
        parts = payload.split("|", 2)
        if len(parts) != 3:
            return "Invalid email format. Expected to|subject|body."

        to, subject, body = (p.strip() for p in parts)

        if not to or "@" not in to:
            return f"'{to}' doesn't look like a valid email address."

        if EMAIL_PROVIDER == "dev":
            # Dev mode never actually delivers — say so plainly instead of
            # implying a real send happened, so this isn't mistaken for a
            # working integration during local testing.
            ok = send_email(to, subject, body)
            return (
                f"(dev mode — not actually delivered) Logged an email to {to}."
                if ok else f"Failed to log the email to {to}."
            )

        ok = send_email(to, subject, body)
        return f"Email sent to {to}." if ok else f"Failed to send the email to {to}. Check SMTP configuration."
