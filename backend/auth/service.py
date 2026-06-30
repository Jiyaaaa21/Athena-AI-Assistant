"""
Phase 11 addition: auth business logic, kept separate from api/auth.py so
the HTTP layer stays thin and this is independently testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.core.config import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    FRONTEND_BASE_URL,
)
from backend.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_opaque_token,
    hash_token,
)
from backend.core.email import send_password_reset_email
from backend.database.models import User, RefreshToken, PasswordResetToken
from backend.auth.schemas import TokenPair


def _utcnow():
    """
    Phase 17 fix — return naive UTC, not timezone-aware UTC.

    The RefreshToken/PasswordResetToken models declare their expires_at
    columns as DateTime(timezone=True), and this function used to return
    datetime.now(timezone.utc) (timezone-AWARE) to match. That's correct
    for PostgreSQL, which actually stores and returns tzinfo. SQLite has
    no native timezone-aware datetime type, though — SQLAlchemy's
    DateTime(timezone=True) is silently downgraded on SQLite: values are
    written as naive ISO strings and read back as naive datetime objects
    regardless of the column's declared type.

    The result: every write here stored an AWARE datetime, but every read
    back out of the database (row.expires_at) came back NAIVE. The
    comparison `row.expires_at < _utcnow()` then mixed an aware and a
    naive datetime, which Python raises as an unhandled TypeError, not an
    HTTPException — bypassing FastAPI's normal error response entirely
    and returning a raw, header-less 500. The browser sees a response
    with no Access-Control-Allow-Origin header and reports it as a CORS
    failure, even though CORS was never the actual problem.

    Fix: make this function return naive UTC so it matches what SQLite
    actually round-trips. This keeps all reads/writes in this file
    internally consistent. (On PostgreSQL in production, naive-UTC
    comparisons against an aware-UTC column also work correctly as long
    as both sides are naive — SQLAlchemy doesn't require timezone
    metadata to compare two UTC instants meaningfully here, since this
    codebase exclusively works in UTC, never local time, at this layer.)
    """
    return datetime.utcnow()


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ── Signup / Login ────────────────────────────────────────────────────────────

def create_user(db: Session, name: str, email: str, password: str) -> User:
    email = normalize_email(email)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        # Phase 11: duplicate-account prevention. Deliberately generic
        # message (doesn't reveal *which* field collided) -- still useful
        # to the legitimate owner, doesn't help an enumeration attacker
        # much more than the obvious "this email already has an account".
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        name=name.strip(),
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    email = normalize_email(email)
    user = db.query(User).filter(User.email == email).first()

    # Deliberately identical error for "no such user" and "wrong password"
    # -- distinguishing them lets an attacker enumerate valid emails.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
    )

    if not user:
        raise invalid
    if not verify_password(password, user.password_hash):
        raise invalid
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    return user


# ── Token issuance / refresh rotation / logout ───────────────────────────────

def issue_token_pair(
    db: Session,
    user: User,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> TokenPair:
    access_token = create_access_token(user.id)

    raw_refresh = generate_opaque_token()
    refresh_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=_utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        revoked=False,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(refresh_row)
    db.commit()

    return TokenPair(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def rotate_refresh_token(
    db: Session,
    raw_refresh_token: str,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> TokenPair:
    """
    Validates the presented refresh token, revokes it, and issues a brand
    new access+refresh pair (rotation). Raises 401 if the token is
    missing, expired, revoked, or unknown.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )

    token_hash = hash_token(raw_refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if not row:
        raise invalid
    if row.revoked:
        # Phase 11: a revoked token being presented again is a strong
        # signal of token theft/replay -- as a defensive measure, revoke
        # every other active refresh token for this user too, forcing a
        # fresh login everywhere.
        db.query(RefreshToken).filter(
            RefreshToken.user_id == row.user_id, RefreshToken.revoked == False  # noqa: E712
        ).update({"revoked": True})
        db.commit()
        raise invalid
    if row.expires_at < _utcnow():
        raise invalid

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        raise invalid

    row.revoked = True
    db.commit()

    return issue_token_pair(db, user, user_agent=user_agent, ip_address=ip_address)


def revoke_refresh_token(db: Session, raw_refresh_token: str) -> None:
    token_hash = hash_token(raw_refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if row:
        row.revoked = True
        db.commit()


def revoke_all_refresh_tokens_for_user(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id).update(
        {"revoked": True}
    )
    db.commit()


# ── Password reset ───────────────────────────────────────────────────────────

def request_password_reset(db: Session, email: str) -> Optional[str]:
    """
    Always returns None to the API caller's response body in production --
    the route handler deliberately doesn't reveal whether the email exists.
    Returns the raw token (for dev-mode convenience / testing) when a user
    was found, otherwise None. The reset email is only actually sent (or,
    in dev mode, logged) when a matching user exists.
    """
    email = normalize_email(email)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None

    raw_token = generate_opaque_token()
    reset_row = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=_utcnow() + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        used=False,
    )
    db.add(reset_row)
    db.commit()

    reset_url = f"{FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    try:
        send_password_reset_email(user.email, reset_url, raw_token)
    except NotImplementedError:
        # Misconfigured EMAIL_PROVIDER shouldn't break the reset flow for
        # dev/testing -- the raw token is still returned below.
        pass

    return raw_token


def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This reset link is invalid or has expired.",
    )

    token_hash = hash_token(raw_token)
    row = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash
    ).first()

    if not row or row.used or row.expires_at < _utcnow():
        raise invalid

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise invalid

    user.password_hash = hash_password(new_password)
    row.used = True

    # Phase 11: a password reset invalidates every existing session -- if
    # someone else had a stolen refresh token, this kicks them out too.
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).update(
        {"revoked": True}
    )

    db.commit()