"""
Phase 11 — Authentication API

  POST /auth/signup            — create account, returns tokens (auto-login)
  POST /auth/login              — email+password -> access + refresh tokens
  POST /auth/logout              — revoke a refresh token (client also drops
                                    its stored tokens)
  POST /auth/refresh             — rotate a refresh token for a new pair
  POST /auth/forgot-password     — request a reset token (always 200, never
                                    reveals whether the email exists)
  POST /auth/reset-password      — consume a reset token, set new password
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.core.config import EMAIL_PROVIDER
from backend.auth.dependencies import get_db
from backend.auth.schemas import (
    SignupRequest,
    LoginRequest,
    RefreshRequest,
    LogoutRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    AuthResponse,
    TokenPair,
    UserOut,
)
from backend.auth import service
from backend.api.profile import serialize_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    user = service.create_user(db, payload.name, payload.email, payload.password)
    tokens = service.issue_token_pair(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return AuthResponse(user=serialize_user(user), tokens=tokens)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = service.authenticate_user(db, payload.email, payload.password)
    tokens = service.issue_token_pair(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return AuthResponse(user=serialize_user(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    return service.rotate_refresh_token(
        db,
        payload.refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


@router.post("/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    service.revoke_refresh_token(db, payload.refresh_token)
    return {"ok": True}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    raw_token = service.request_password_reset(db, payload.email)

    response: dict = {
        "ok": True,
        "message": (
            "If an account exists for that email, a password reset link "
            "has been sent."
        ),
    }

    # Dev convenience ONLY: with no real email provider configured, the UI
    # (and curl/Postman) need a way to actually exercise the reset flow.
    # Never include the token in the response once EMAIL_PROVIDER is a
    # real provider.
    if EMAIL_PROVIDER == "dev" and raw_token:
        response["dev_reset_token"] = raw_token

    return response


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    service.reset_password(db, payload.token, payload.new_password)
    return {"ok": True, "message": "Password updated. Please log in again."}
