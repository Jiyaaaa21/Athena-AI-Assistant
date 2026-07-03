"""
Phase 11 — User Profile API

  GET    /me                     — shorthand identity check (id/name/email/...)
  GET    /profile                 — full profile
  PUT    /profile                 — update name / bio
  POST   /profile/avatar          — upload/replace avatar image
  DELETE /profile/avatar          — remove avatar
  POST   /profile/change-password — change password while logged in
  GET    /profile/export          — Phase 29: download all of the user's data as a zip
  DELETE /profile/me              — Phase 29: permanently delete the account and all its data
"""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_db, get_current_user
from backend.auth.schemas import ProfileUpdateRequest, UserOut, ChangePasswordRequest, DeleteAccountRequest
from backend.auth import service
from backend.core.config import AVATAR_UPLOAD_DIR, MAX_AVATAR_SIZE_MB
from backend.core.logger import agent_logger, error_logger
from backend.core.rate_limit import auth_rate_limiter
from backend.core.security import verify_password, hash_password
from backend.database.models import (
    User, RefreshToken, PasswordResetToken, Message, Note, Reminder,
    Document, DocumentChunk, UserPreference, Conversation, ConversationMessage,
    Folder, VoiceSettings, Goal, Project, ProjectLink, UserFact, AgentCallLog,
    ReminderFired, Timer, Routine, GoogleCalendarToken, PushSubscription,
    UserAction, ProactiveInsight,
)

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


# ── Phase 29: data export ────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Generic SQLAlchemy row -> JSON-safe dict, skipping SQLAlchemy's own
    internal state attribute and converting datetime/date to ISO strings."""
    out = {}
    for col in row.__table__.columns:
        value = getattr(row, col.name)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        out[col.name] = value
    return out


@router.get("/profile/export")
def export_my_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Phase 29: full data export -- every piece of the user's own data,
    bundled as a zip: a single data.json with all structured/textual
    data, plus the actual PDF bytes for every document they own under
    documents/. Deliberately excludes security-sensitive rows that
    aren't really "the user's data" in the export sense: refresh/
    password-reset token hashes, and raw Google OAuth access/refresh
    tokens (exporting those would hand out live credentials, not
    information about the user).
    """
    uid = current_user.id

    data: dict = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "bio": current_user.bio,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
    }

    # Straightforward: one table -> one list of dicts, each keyed by
    # user_id directly.
    direct_tables = {
        "notes": Note,
        "reminders": Reminder,
        "goals": Goal,
        "projects": Project,
        "timers": Timer,
        "routines": Routine,
        "user_facts": UserFact,
        "user_actions": UserAction,
        "proactive_insights": ProactiveInsight,
        "preferences": UserPreference,
        "voice_settings": VoiceSettings,
        "conversations": Conversation,
    }
    for key, model in direct_tables.items():
        rows = db.query(model).filter(model.user_id == uid).all()
        data[key] = [_row_to_dict(r) for r in rows]

    # Conversation messages: nest under each conversation rather than a
    # flat list, since they're meaningless without their parent.
    conv_ids = [c["id"] for c in data["conversations"]]
    if conv_ids:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id.in_(conv_ids))
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        by_conv: dict[int, list[dict]] = {cid: [] for cid in conv_ids}
        for m in messages:
            by_conv[m.conversation_id].append(_row_to_dict(m))
        for conv in data["conversations"]:
            conv["messages"] = by_conv.get(conv["id"], [])

    # Global (older, pre-Conversation-model) chat history.
    data["legacy_messages"] = [
        _row_to_dict(m) for m in db.query(Message).filter(Message.user_id == uid).all()
    ]

    documents = db.query(Document).filter(Document.user_id == uid).all()
    data["documents"] = [
        {k: v for k, v in _row_to_dict(d).items() if k != "file_data"}
        for d in documents
    ]

    # Calendar connection: note that it's connected, but never export the
    # actual OAuth tokens -- see docstring above.
    cal = db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == uid).first()
    data["google_calendar_connected"] = bool(cal)
    if cal:
        data["google_calendar_email"] = cal.google_email

    # Build the zip: data.json + one file per document that actually has
    # bytes stored (some rows could be mid-upload/failed and have none).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(data, indent=2, default=str))
        for d in documents:
            if d.file_data:
                # Guard against duplicate/unsafe filenames colliding or
                # escaping the documents/ folder inside the zip.
                safe_name = os.path.basename(d.filename or f"document_{d.id}.pdf")
                zf.writestr(f"documents/{d.id}_{safe_name}", d.file_data)

    agent_logger.info(f"[profile/export] user {uid} exported {len(documents)} document(s)")

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="athena_export_{uid}.zip"'},
    )


# ── Phase 29: account deletion ───────────────────────────────────────────────

@router.delete("/profile/me")
def delete_my_account(
    payload: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Permanently deletes the account and every row of data it owns.
    Irreversible -- requires the current password to confirm, same
    reasoning as change_password requiring it.

    Explicitly deletes from every table rather than relying solely on
    the database's ON DELETE CASCADE constraints. Both should agree, but
    this project has already had at least one case (the
    58f3c14121da_sync_missing_tables migration) where models.py and the
    actual applied migrations had drifted -- for something this
    consequential and irreversible, verifying correctness by reading
    this function shouldn't require also auditing every past migration
    to confirm cascade constraints truly exist in the live database.
    Deleted in dependency order (children before parents) so this is
    correct regardless of whether those constraints are actually present.
    """
    auth_rate_limiter.check_or_raise(
        str(current_user.id),
        detail="Too many attempts. Please wait a minute and try again.",
    )

    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")

    uid = current_user.id

    try:
        # ── Tables scoped only indirectly (no user_id column of their own) ──
        reminder_ids = [r.id for r in db.query(Reminder.id).filter(Reminder.user_id == uid).all()]
        if reminder_ids:
            db.query(ReminderFired).filter(ReminderFired.reminder_id.in_(reminder_ids)).delete(synchronize_session=False)

        conv_ids = [c.id for c in db.query(Conversation.id).filter(Conversation.user_id == uid).all()]
        if conv_ids:
            db.query(ConversationMessage).filter(ConversationMessage.conversation_id.in_(conv_ids)).delete(synchronize_session=False)

        project_ids = [p.id for p in db.query(Project.id).filter(Project.user_id == uid).all()]
        if project_ids:
            db.query(ProjectLink).filter(ProjectLink.project_id.in_(project_ids)).delete(synchronize_session=False)

        # ── Every directly user_id-owned table ──
        for model in (
            DocumentChunk, RefreshToken, PasswordResetToken, Message, Note,
            Reminder, Document, UserPreference, Conversation, Folder,
            VoiceSettings, Goal, Project, UserFact, AgentCallLog, Timer,
            Routine, GoogleCalendarToken, PushSubscription, UserAction,
            ProactiveInsight,
        ):
            db.query(model).filter(model.user_id == uid).delete(synchronize_session=False)

        # Avatar file, if any -- best-effort, same as DELETE /profile/avatar.
        if current_user.avatar_path:
            old_path = os.path.join(AVATAR_UPLOAD_DIR, current_user.avatar_path)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass

        db.delete(current_user)
        db.commit()
    except Exception as e:
        db.rollback()
        error_logger.error(f"[profile/delete] account deletion failed for user {uid}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong deleting your account. Nothing was deleted -- please try again or contact support.",
        )

    agent_logger.warning(f"[profile/delete] user {uid} ({current_user.email}) permanently deleted their account")

    return {"ok": True, "message": "Your account and all associated data have been permanently deleted."}
