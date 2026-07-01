"""
backend/api/push.py  —  Phase 21

Endpoints for the Web Push subscription lifecycle:

  GET    /push/vapid-public-key   (public — no JWT)  the browser needs
                                    this BEFORE the user is necessarily
                                    doing anything auth-gated, to call
                                    PushManager.subscribe()
  POST   /push/subscribe          save/refresh a device's subscription
  DELETE /push/unsubscribe        remove a device's subscription
  GET    /push/status             is VAPID configured + how many devices
                                    does this user have subscribed
  POST   /push/test               send a real test push to all of the
                                    current user's devices

Mirrors the calendar.py split: `router` (JWT-protected, mounted with
`dependencies=[Depends(get_current_user)]` in main.py) and
`public_router` (mounted unprotected) for the one endpoint that has to
be reachable before subscribing.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import PushSubscription
from backend.core.request_context import get_current_user_id
from backend.core.push_vapid import get_vapid_public_key, is_configured
from backend.core.push_notifications import send_push_to_user

router = APIRouter()
public_router = APIRouter()


class SubscriptionKeysIn(BaseModel):
    p256dh: str
    auth: str


class SubscribeIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeysIn
    user_agent: str | None = None


@public_router.get("/push/vapid-public-key")
def vapid_public_key():
    """
    Public by necessity: the browser calls this to get the
    applicationServerKey for PushManager.subscribe() as part of the
    permission-request flow, which happens from the Settings page
    regardless of whether that particular fetch race lands before or
    after the auth-wait guard in lib/api.ts resolves.
    """
    key = get_vapid_public_key()
    if not key:
        raise HTTPException(status_code=503, detail="Push notifications are not configured on this server yet")
    return {"publicKey": key}


@router.post("/push/subscribe")
def subscribe(body: SubscribeIn):
    uid = get_current_user_id()
    if not is_configured():
        raise HTTPException(status_code=503, detail="Push notifications are not configured on this server yet")

    db = SessionLocal()
    try:
        existing = (
            db.query(PushSubscription)
            .filter(PushSubscription.endpoint == body.endpoint)
            .first()
        )
        if existing:
            # Same browser/device re-subscribing (e.g. keys rotated) --
            # reassign to whichever account is currently logged in on it
            # and refresh the keys rather than creating a duplicate row.
            existing.user_id = uid
            existing.p256dh = body.keys.p256dh
            existing.auth = body.keys.auth
            existing.user_agent = body.user_agent
        else:
            db.add(PushSubscription(
                user_id=uid,
                endpoint=body.endpoint,
                p256dh=body.keys.p256dh,
                auth=body.keys.auth,
                user_agent=body.user_agent,
            ))
        db.commit()
        return {"subscribed": True}
    finally:
        db.close()


@router.delete("/push/unsubscribe")
def unsubscribe(endpoint: str):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        deleted = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id == uid, PushSubscription.endpoint == endpoint)
            .delete()
        )
        db.commit()
        return {"unsubscribed": bool(deleted)}
    finally:
        db.close()


@router.get("/push/status")
def push_status():
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        count = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id == uid)
            .count()
        )
        return {"configured": is_configured(), "deviceCount": count}
    finally:
        db.close()


@router.post("/push/test")
def push_test():
    uid = get_current_user_id()
    if not is_configured():
        raise HTTPException(status_code=503, detail="Push notifications are not configured on this server yet")
    sent = send_push_to_user(
        uid,
        title="Athena",
        body="Push notifications are working. You'll get these even when the tab is closed.",
        url="/",
        urgent=True,
    )
    if sent == 0:
        raise HTTPException(status_code=404, detail="No active push subscriptions found for this account")
    return {"sent": sent}