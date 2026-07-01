"""
backend/core/push_notifications.py  —  Phase 21

Sends real OS-level push notifications (the kind that show up even when
the browser tab is closed) via the Web Push protocol, using the VAPID
keypair from core/push_vapid.py.

This is what lets a reminder fire while the person isn't looking at
Athena at all — the previous "browser notification" implementation
(Phase 16, use-reminder-notifications.ts) only worked while the tab was
open and polling; this fires an actual push through the browser vendor's
push service (FCM for Chrome, autopush for Firefox, etc.) to the
device's push subscription, which the service worker (public/sw.js)
receives and turns into a system notification even if Athena isn't
open in any tab.

send_push_to_user() is the single entry point every caller (the
reminder scheduler, the /push/test endpoint, future proactive-intelligence
features) should use — it handles the fan-out across a user's multiple
subscriptions (they may have Athena open on a phone AND a laptop) and
prunes subscriptions the push service reports as permanently dead.
"""
from __future__ import annotations

import json
from typing import Optional

from pywebpush import webpush, WebPushException

from backend.core.config import VAPID_CLAIM_EMAIL
from backend.core.push_vapid import get_vapid
from backend.core.logger import agent_logger


def send_push_to_user(
    user_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
    url: str = "/",
    urgent: bool = False,
) -> int:
    """
    Sends a push notification to every device the given user has
    subscribed on. Returns the number of subscriptions it successfully
    pushed to (0 if VAPID isn't configured, the user has no
    subscriptions, or every send failed).

    Dead subscriptions (the push service returns 404/410 — the browser
    unsubscribed, cleared data, or the endpoint expired) are deleted from
    the database automatically so future sends don't keep retrying them.

    `urgent` (Phase 23 addition): flows straight into the push payload as
    `"urgent": true/false`. public/sw.js reads this to decide whether the
    notification should stick around until the person actually dismisses
    it (`requireInteraction`) instead of auto-hiding after a few seconds --
    reserved for things like an overdue high-priority reminder or a
    meeting starting imminently, not every gentle proactive nudge.
    """
    vapid = get_vapid()
    if vapid is None:
        agent_logger.warning("[Push] send_push_to_user called before VAPID keys were initialized")
        return 0

    # Local imports to avoid a circular import at module load time
    # (database/models.py doesn't depend on core/, but core/ modules are
    # imported very early via main.py -> keeping this lazy is cheap
    # insurance against import-order surprises).
    from backend.database.db import SessionLocal
    from backend.database.models import PushSubscription

    db = SessionLocal()
    try:
        subs = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id == user_id)
            .all()
        )
        if not subs:
            return 0

        payload = json.dumps({
            "title": title,
            "body": body,
            "url": url,
            "urgent": urgent,
            **(data or {}),
        })


        sent = 0
        dead_ids = []

        for sub in subs:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=vapid,
                    vapid_claims={"sub": VAPID_CLAIM_EMAIL},
                    ttl=60,
                )
                sent += 1
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):
                    # Subscription is permanently gone — clean it up.
                    dead_ids.append(sub.id)
                else:
                    agent_logger.error(f"[Push] send failed (status={status}): {e}")

        if dead_ids:
            db.query(PushSubscription).filter(PushSubscription.id.in_(dead_ids)).delete(
                synchronize_session=False
            )
            db.commit()
            agent_logger.info(f"[Push] pruned {len(dead_ids)} dead subscription(s)")

        return sent
    finally:
        db.close()