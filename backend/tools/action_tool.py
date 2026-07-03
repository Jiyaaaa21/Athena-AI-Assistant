"""
backend/tools/action_tool.py  —  Phase 22

Generic "connected action" trigger. Rather than writing a bespoke
integration for every third-party service a user might want (Slack,
Home Assistant, IFTTT, Zapier/Make, n8n, ...), the user registers a named
outbound webhook once in Settings (see api/actions.py + UserAction model),
and Athena can trigger any of them from natural language: "run my
'lights on' action", "post this to Slack".

Safety:
  - Only webhooks the user has registered themselves are ever called —
    Athena cannot invent a URL to hit.
  - SSRF guard: refuses to POST to loopback/private/link-local addresses
    unless ALLOW_LOCAL_ACTION_WEBHOOKS=true (dev convenience only).
  - Hard timeout so a slow/unresponsive webhook can't hang a chat turn.
  - `enabled=False` actions are skipped even if matched by name, so a user
    can pause an action without deleting it.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from urllib.parse import urlparse

import requests

from backend.core.config import (
    ALLOW_LOCAL_ACTION_WEBHOOKS,
    ACTION_WEBHOOK_TIMEOUT_SECONDS,
)
from backend.core.logger import agent_logger, error_logger
from backend.core.rate_limit import action_rate_limiter_minute, action_rate_limiter_daily, require_budget
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import UserAction
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)


def _is_blocked_host(hostname: str) -> bool:
    """True if hostname resolves to a loopback/private/link-local address."""
    if ALLOW_LOCAL_ACTION_WEBHOOKS:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Can't resolve — let the actual request fail with a clear error
        # rather than silently blocking on a DNS hiccup.
        return False

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


class ActionTool:

    name = "action"

    description = (
        "Trigger a user-registered webhook (a 'connected action'). "
        "Input: 'list' or 'run:<action name>|<json payload or empty>'"
    )

    def run(self, command: str) -> str:
        db = SessionLocal()
        user_id = get_current_user_id()
        try:
            if command == "list":
                actions = (
                    db.query(UserAction)
                    .filter(UserAction.user_id == user_id, UserAction.enabled == True)  # noqa: E712
                    .all()
                )
                if not actions:
                    return "No connected actions are set up yet."
                return "\n".join(
                    f"- {a.name}" + (f": {a.description}" if a.description else "")
                    for a in actions
                )

            if command.startswith("run:"):
                payload_str = command.replace("run:", "", 1).strip()
                if "|" in payload_str:
                    action_name, extra_json = payload_str.split("|", 1)
                else:
                    action_name, extra_json = payload_str, ""
                action_name = action_name.strip()
                extra_json = extra_json.strip()

                action = (
                    db.query(UserAction)
                    .filter(
                        UserAction.user_id == user_id,
                        UserAction.name.ilike(action_name),
                    )
                    .first()
                )
                if not action:
                    return f"No connected action named '{action_name}' found."
                if not action.enabled:
                    return f"The '{action_name}' action is currently disabled."

                return self._trigger(db, action, extra_json)

            return "Invalid action command."
        finally:
            db.close()

    def _trigger(self, db, action: UserAction, extra_json: str) -> str:
        # Phase 32: checked here rather than duplicated in both callers
        # (api/actions.py's /test endpoint and this class's own run()
        # for the chat-triggered "run:" path) -- both funnel through this
        # one method, so this is the single place that actually needs it.
        try:
            require_budget(
                action_rate_limiter_minute, action_rate_limiter_daily,
                str(action.user_id),
                minute_detail="Too many action triggers in a short time -- please wait a moment.",
                daily_detail="Today's connected-action trigger limit has been reached.",
            )
        except Exception as e:
            return f"'{action.name}' was not triggered: {e}"

        parsed = urlparse(action.webhook_url)
        if parsed.scheme not in ("http", "https"):
            return f"'{action.name}' has an invalid webhook URL."
        if not parsed.hostname:
            return f"'{action.name}' has an invalid webhook URL."
        if _is_blocked_host(parsed.hostname):
            error_logger.warning(
                "[action_tool] blocked webhook to private/loopback host "
                "for action_id=%s host=%s", action.id, parsed.hostname,
            )
            return (
                f"'{action.name}' points at a local/private address, which "
                f"is blocked for safety. Set ALLOW_LOCAL_ACTION_WEBHOOKS=true "
                f"if this is intentional (local dev only)."
            )

        # Build the JSON body: template + extra fields override, or raw
        # extra_json if there's no template at all.
        body: dict | None = None
        if action.payload_template:
            try:
                body = json.loads(action.payload_template)
            except json.JSONDecodeError:
                body = None
        if extra_json:
            try:
                extra = json.loads(extra_json)
                if isinstance(extra, dict):
                    body = {**(body or {}), **extra}
            except json.JSONDecodeError:
                pass  # ignore malformed extra payload, fall back to template/None

        method = (action.http_method or "POST").upper()

        try:
            resp = requests.request(
                method,
                action.webhook_url,
                json=body if body is not None else None,
                timeout=ACTION_WEBHOOK_TIMEOUT_SECONDS,
            )
            action.last_triggered_at = _utcnow()
            db.commit()

            agent_logger.info(
                "[action_tool] triggered action_id=%s name=%r status=%s",
                action.id, action.name, resp.status_code,
            )

            if resp.ok:
                return f"Triggered '{action.name}' successfully."
            return f"'{action.name}' responded with status {resp.status_code}."

        except requests.RequestException as exc:
            error_logger.error(
                "[action_tool] request failed action_id=%s: %s", action.id, exc,
            )
            return f"Failed to trigger '{action.name}': {exc}"