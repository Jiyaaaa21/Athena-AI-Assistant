"""
Phase 11 — User Profile API

  GET    /me                     — shorthand identity check (id/name/email/...)
  GET    /profile                 — full profile
  PUT    /profile                 — update name / bio
  POST   /profile/avatar          — upload/replace avatar image
  DELETE /profile/avatar          — remove avatar
  POST   /profile/change-password — change password while logged in
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_db, get_current_user
from backend.auth.schemas import ProfileUpdateRequest, UserOut, ChangePasswordRequest
from backend.auth import service
from backend.core.config import AVATAR_UPLOAD_DIR, MAX_AVATAR_SIZE_MB
from backend.core.security import verify_password, hash_password
from backend.database.models import User

router = APIRouter(tags=["profile"])

_ALLOWED_AVATAR_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        bio=user.bio,
        avatar_url=f"/profile/avatar/{user.id}" if user.avatar_path else None,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)


@router.get("/profile", response_model=UserOut)
def get_profile(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)


@router.put("/profile", response_model=UserOut)
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.name is not None:
        current_user.name = payload.name.strip()
    if payload.bio is not None:
        current_user.bio = payload.bio

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return serialize_user(current_user)


@router.post("/profile/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    current_user.password_hash = hash_password(payload.new_password)
    db.add(current_user)
    db.commit()

    # Phase 11: changing your password while logged in invalidates every
    # *other* session, same rationale as the forgot/reset-password flow.
    service.revoke_all_refresh_tokens_for_user(db, current_user.id)

    return {"ok": True, "message": "Password changed. Please log in again on other devices."}


@router.post("/profile/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in _ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image type. Use PNG, JPEG, or WEBP.",
        )

    file_bytes = await file.read()
    max_bytes = MAX_AVATAR_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Avatar image exceeds the {MAX_AVATAR_SIZE_MB} MB limit.",
        )

    os.makedirs(AVATAR_UPLOAD_DIR, exist_ok=True)

    # Phase 12: filename includes the user id and a fresh uuid so avatars
    # are namespaced per-user on disk and old cached URLs are naturally
    # invalidated on re-upload.
    ext = _ALLOWED_AVATAR_TYPES[file.content_type]
    filename = f"user_{current_user.id}_{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(AVATAR_UPLOAD_DIR, filename)

    # Remove the previous avatar file, if any, so we don't accumulate
    # orphaned images forever.
    if current_user.avatar_path:
        old_path = os.path.join(AVATAR_UPLOAD_DIR, current_user.avatar_path)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    with open(save_path, "wb") as f:
        f.write(file_bytes)

    current_user.avatar_path = filename
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return serialize_user(current_user)


@router.delete("/profile/avatar", response_model=UserOut)
def remove_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.avatar_path:
        old_path = os.path.join(AVATAR_UPLOAD_DIR, current_user.avatar_path)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        current_user.avatar_path = None
        db.add(current_user)
        db.commit()
        db.refresh(current_user)

    return serialize_user(current_user)


@router.get("/profile/avatar/{user_id}")
def get_avatar(user_id: int, db: Session = Depends(get_db)):
    """
    Public-ish avatar file serving (no auth required, mirroring how most
    apps serve avatar images directly in <img> tags without attaching
    Authorization headers). Only ever serves the file path stored on the
    User row -- never arbitrary filesystem paths.
    """
    from fastapi.responses import FileResponse

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.avatar_path:
        raise HTTPException(status_code=404, detail="No avatar set for this user.")

    path = os.path.join(AVATAR_UPLOAD_DIR, user.avatar_path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Avatar file missing from disk.")

    return FileResponse(path)
