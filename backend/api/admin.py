"""
backend/api/admin.py — Phase 31: real admin surface

  GET  /clear-memory                       — Phase <original>: per-user
                                              self-service action (clears
                                              the CALLING user's own
                                              memory). Not actually an
                                              admin action -- kept here
                                              unchanged since this file
                                              already existed and callers
                                              already depend on this path,
                                              but everything below this is
                                              new and genuinely admin-only.

  GET  /admin/users                        — list all users + data summary
  GET  /admin/users/{user_id}              — one user's detail
  POST /admin/users/{user_id}/deactivate   — lock a user out (is_active=False)
  POST /admin/users/{user_id}/reactivate   — undo the above
  POST /admin/users/{user_id}/revoke-sessions — force logout everywhere
  GET  /admin/audit-log                    — recent admin actions
  GET  /admin/overview                     — aggregate usage stats

Every route below /clear-memory requires require_admin (see
auth/dependencies.py) -- a valid JWT AND is_admin=True. See
core/config.py's ADMIN_EMAILS for how a user becomes an admin; there is
no endpoint here to grant admin to someone else, deliberately (that's a
real feature a personal-assistant deployment doesn't need yet).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import service
from backend.auth.dependencies import get_db, require_admin
from backend.core.memory_service import clear_memory
from backend.core.rate_limit import (
    chat_rate_limiter_daily, voice_rate_limiter_daily, upload_rate_limiter_daily,
)
from backend.database.models import (
    User, Note, Reminder, Goal, Project, Document, Conversation,
    Timer, Routine, GoogleCalendarToken, AdminAuditLog,
)

router = APIRouter()


@router.get("/clear-memory")
def reset_memory():
    clear_memory()
    return {"message": "Memory cleared"}


def _log_admin_action(
    db: Session, admin: User, action: str,
    target: User | None = None, detail: str | None = None,
):
    db.add(AdminAuditLog(
        admin_user_id=admin.id,
        admin_email=admin.email,
        action=action,
        target_user_id=target.id if target else None,
        target_email=target.email if target else None,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()


def _user_summary(db: Session, user: User) -> dict:
    """Counts, not full data -- this is an overview list, not a data
    dump. GET /admin/users/{id} (or the export endpoint each user
    already has for their own data) is the place for full detail."""
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "counts": {
            "notes": db.query(func.count(Note.id)).filter(Note.user_id == user.id).scalar(),
            "reminders": db.query(func.count(Reminder.id)).filter(Reminder.user_id == user.id).scalar(),
            "goals": db.query(func.count(Goal.id)).filter(Goal.user_id == user.id).scalar(),
            "projects": db.query(func.count(Project.id)).filter(Project.user_id == user.id).scalar(),
            "documents": db.query(func.count(Document.id)).filter(Document.user_id == user.id).scalar(),
            "conversations": db.query(func.count(Conversation.id)).filter(Conversation.user_id == user.id).scalar(),
            "timers": db.query(func.count(Timer.id)).filter(Timer.user_id == user.id).scalar(),
            "routines": db.query(func.count(Routine.id)).filter(Routine.user_id == user.id).scalar(),
        },
        "google_calendar_connected": db.query(GoogleCalendarToken).filter(GoogleCalendarToken.user_id == user.id).first() is not None,
        # Phase 29's shared free-tier budgets, per user -- lets an admin
        # actually see who's close to (or already at) today's limit
        # instead of only finding out when they hit a 429 and ask why.
        "usage_today": {
            "chat_remaining": chat_rate_limiter_daily.remaining(str(user.id)),
            "voice_remaining": voice_rate_limiter_daily.remaining(str(user.id)),
            "uploads_remaining": upload_rate_limiter_daily.remaining(str(user.id)),
        },
    }


@router.get("/admin/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return {"users": [_user_summary(db, u) for u in users], "total": len(users)}


@router.get("/admin/users/{user_id}")
def get_user_detail(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_summary(db, user)


@router.post("/admin/users/{user_id}/deactivate")
def deactivate_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if user_id == admin.id:
        # The obvious footgun: an admin locking themselves out with no
        # way back in short of direct DB access.
        raise HTTPException(status_code=400, detail="You can't deactivate your own account.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.add(user)
    # Deactivating without also killing existing sessions would be
    # theater -- get_current_user checks is_active on every request, so
    # this alone does work, but revoking sessions too means it takes
    # effect immediately rather than "on their next token refresh".
    service.revoke_all_refresh_tokens_for_user(db, user.id)
    _log_admin_action(db, admin, "deactivate_user", target=user)

    return {"ok": True, "message": f"{user.email} has been deactivated."}


@router.post("/admin/users/{user_id}/reactivate")
def reactivate_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.add(user)
    _log_admin_action(db, admin, "reactivate_user", target=user)

    return {"ok": True, "message": f"{user.email} has been reactivated."}


@router.post("/admin/users/{user_id}/revoke-sessions")
def revoke_user_sessions(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    service.revoke_all_refresh_tokens_for_user(db, user.id)
    _log_admin_action(db, admin, "revoke_sessions", target=user)

    return {"ok": True, "message": f"All sessions for {user.email} have been revoked."}


@router.get("/admin/audit-log")
def get_audit_log(
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    limit = min(max(limit, 1), 500)
    rows = (
        db.query(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "entries": [
            {
                "id": r.id,
                "admin_email": r.admin_email,
                "action": r.action,
                "target_email": r.target_email,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/admin/overview")
def get_overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar()  # noqa: E712
    admin_users = db.query(func.count(User.id)).filter(User.is_admin == True).scalar()  # noqa: E712
    connected_calendars = db.query(func.count(GoogleCalendarToken.id)).scalar()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "deactivated_users": total_users - active_users,
        "admin_users": admin_users,
        "google_calendar_connections": connected_calendars,
        "totals": {
            "notes": db.query(func.count(Note.id)).scalar(),
            "reminders": db.query(func.count(Reminder.id)).scalar(),
            "goals": db.query(func.count(Goal.id)).scalar(),
            "documents": db.query(func.count(Document.id)).scalar(),
            "conversations": db.query(func.count(Conversation.id)).scalar(),
        },
    }