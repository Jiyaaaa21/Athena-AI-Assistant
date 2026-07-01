"""
backend/core/push_vapid.py  —  Phase 21

VAPID (Voluntary Application Server Identification, RFC 8292) is how this
backend identifies itself to browser push services (Google's FCM endpoint
for Chrome, Mozilla's autopush for Firefox, etc.) without needing a
separate API key per browser vendor. It's a single EC (P-256) keypair:

  - The PRIVATE key signs every push message this server sends, proving
    to the push service that it's really Athena's backend sending it.
  - The PUBLIC key is handed to the browser when the user subscribes
    (`PushManager.subscribe({ applicationServerKey: ... })`); the browser
    embeds it in the subscription, so the push service can verify that
    only pushes signed by the matching private key are allowed to reach
    that specific subscription.

Both keys must stay stable across server restarts — regenerating them
would silently invalidate every subscription already stored in the
`push_subscriptions` table (they'd start failing with 401/403 from the
push service, and the frontend would have no way to know why). So the
private key is generated once and persisted to disk; every subsequent
startup loads the same key instead of minting a new one.

Usage:
    from backend.core.push_vapid import ensure_vapid_keys, get_vapid_public_key, get_vapid

    ensure_vapid_keys()  # call once, from main.py on_startup
    get_vapid_public_key()  # -> base64url string for the frontend
    get_vapid()  # -> py_vapid.Vapid instance, passed to pywebpush.webpush()
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from py_vapid import Vapid

from backend.core.config import VAPID_CLAIM_EMAIL
from backend.core.logger import agent_logger

_VAPID_DIR = "data/vapid"
_PRIVATE_KEY_PATH = os.path.join(_VAPID_DIR, "private_key.pem")

_vapid_instance: Optional[Vapid] = None
_public_key_b64: Optional[str] = None


def ensure_vapid_keys() -> None:
    """
    Call once from main.py's on_startup. Idempotent and safe to call
    multiple times — loads the existing keypair from disk if present,
    otherwise generates and persists a new one.
    """
    global _vapid_instance, _public_key_b64

    os.makedirs(_VAPID_DIR, exist_ok=True)

    # Vapid.from_file() already does "load if exists, else generate +
    # save" internally — no need to duplicate that branching here.
    vapid = Vapid.from_file(_PRIVATE_KEY_PATH)

    _vapid_instance = vapid
    _public_key_b64 = _encode_public_key(vapid)

    agent_logger.info(
        "[Push] VAPID keys ready (claim=%s)", VAPID_CLAIM_EMAIL
    )


def _encode_public_key(vapid: Vapid) -> str:
    """
    Encode the EC public key as the raw 65-byte uncompressed point,
    base64url without padding — the exact format the browser's
    `PushManager.subscribe({ applicationServerKey })` expects.
    """
    from cryptography.hazmat.primitives import serialization

    raw = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


def get_vapid() -> Optional[Vapid]:
    """Returns the loaded Vapid instance, or None if ensure_vapid_keys()
    hasn't run yet (or failed)."""
    return _vapid_instance


def get_vapid_public_key() -> Optional[str]:
    """Returns the base64url-encoded public key for the frontend, or
    None if VAPID isn't set up yet."""
    return _public_key_b64


def is_configured() -> bool:
    return _vapid_instance is not None
