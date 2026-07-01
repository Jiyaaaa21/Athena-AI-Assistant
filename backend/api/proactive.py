"""
backend/api/proactive.py  —  Phase 23

Endpoints for the proactive-insight feed:

  GET    /proactive/insights          recent insights for the current user
  POST   /proactive/insights/{id}/dismiss   mark one as dismissed
  POST   /proactive/trigger           force one evaluation cycle for the
                                        current user right now (mirrors
                                        POST /push/test -- lets Settings
                                        surface a "Test" button instead of
                                        making someone wait up to
                                        PROACTIVE_INTERVAL_SECONDS to see
                                        whether this is wired up at all)

All routes are mounted with the standard JWT dependency in main.py, same
as every other user-data router.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import ProactiveInsight
from backend.core.request_context import get_current_user_id

router = APIRouter()


class InsightOut(BaseModel):
    id: int
    kind: str
    message: str
    delivered: bool
    dismissed: bool
    createdAt: str

    class Config:
        from_attributes = True


def _to_out(row: ProactiveInsight) -> InsightOut:
    return InsightOut(
        id=row.id,
        kind=row.kind,
        message=row.message,
        delivered=row.delivered,
        dismissed=row.dismissed,
        createdAt=row.created_at.isoformat() if row.created_at else "",
    )


@router.get("/proactive/insights", response_model=list[InsightOut])
def list_insights(include_dismissed: bool = False, limit: int = 20):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        q = db.query(ProactiveInsight).filter(ProactiveInsight.user_id == uid)
        if not include_dismissed:
            q = q.filter(ProactiveInsight.dismissed == False)
        rows = q.order_by(ProactiveInsight.created_at.desc()).limit(min(limit, 100)).all()
        return [_to_out(r) for r in rows]
    finally:
        db.close()


@router.post("/proactive/insights/{insight_id}/dismiss")
def dismiss_insight(insight_id: int):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        row = (
            db.query(ProactiveInsight)
            .filter(ProactiveInsight.id == insight_id, ProactiveInsight.user_id == uid)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Insight not found")
        row.dismissed = True
        db.commit()
        return {"dismissed": True}
    finally:
        db.close()


@router.post("/proactive/trigger")
def trigger_now():
    """
    Forces one evaluation pass for the CURRENT user only (not every user,
    unlike the background engine's full cycle) -- so this stays cheap and
    request-scoped instead of accidentally running the whole-system loop
    on demand.
    """
    uid = get_current_user_id()
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from backend.core.proactive_engine import _process_user
    db = SessionLocal()
    try:
        outcome, insight = _process_user(db, uid)
        if outcome == "generated" and insight:
            return {"generated": True, "insight": _to_out(insight)}

        reasons = {
            "cooldown": (
                "You already got an insight recently — Athena won't send another "
                "one until the cooldown window passes (PROACTIVE_MIN_GAP_MINUTES)."
            ),
            "no_context": (
                "Nothing in your data cleared even the basic bar to ask — no overdue "
                "or upcoming reminders, no active goals, no calendar events in the next 2 hours."
            ),
            "llm_declined": (
                "Athena looked at your context but decided it wasn't worth interrupting "
                "you for right now — check the backend logs for the model's stated reason."
            ),
            "parse_error": (
                "The model's decision didn't come back as valid JSON — check the backend "
                "logs for the raw response."
            ),
            "error": "Something went wrong while evaluating your context — check the backend logs.",
        }
        return {"generated": False, "reason": reasons.get(outcome, f"Nothing worth surfacing right now ({outcome}).")}
    finally:
        db.close()