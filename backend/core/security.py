"""
Phase 11 addition: password hashing + JWT helpers.

Uses `bcrypt` directly (already a pinned dependency in requirements.txt)
rather than pulling in passlib -- passlib's bcrypt backend has had repeated
compatibility issues with bcrypt>=4.x, and we don't need passlib's
multi-algorithm abstraction since bcrypt is the only hashing scheme Athena
will ever need for this.
"""

from __future__ import annotations

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from backend.core.config import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

# bcrypt only uses the first 72 bytes of the input; anything beyond that is
# silently ignored by the C extension, but recent bcrypt releases raise a
# hard error instead. Truncate explicitly (after UTF-8 encoding) so very
# long pasted passwords don't 500 the signup endpoint.
_BCRYPT_MAX_BYTES = 72


def _prepare_password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    return encoded[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(_prepare_password_bytes(password), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            _prepare_password_bytes(password), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        # Malformed hash on the row (shouldn't happen) -- fail closed.
        return False


# ── JWT access tokens ─────────────────────────────────────────────────────────
# Stateless, short-lived. Carries just enough to identify + re-authorize the
# user on every request without a DB lookup per request.

def create_access_token(user_id: int, extra_claims: Optional[dict] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": secrets.token_urlsafe(8),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


class TokenError(Exception):
    """Raised for any invalid/expired/malformed JWT."""


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid access token") from exc

    if payload.get("type") != "access":
        raise TokenError("Token is not an access token")

    return payload


# ── Refresh tokens & password-reset tokens ───────────────────────────────────
# These are opaque random strings (NOT JWTs). Only a SHA-256 hash is ever
# stored in the DB, so a leaked database dump can't be used to forge valid
# tokens, and revocation is a simple row update (unlike a stateless JWT,
# which can't be revoked before it naturally expires).

def generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
