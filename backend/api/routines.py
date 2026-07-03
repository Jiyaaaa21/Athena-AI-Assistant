"""
backend/api/routines.py  —  Phase 18

Named multi-step voice macros — "Hey Athena, good morning" running
several actions in sequence (weather, reminders, goals review) in one
shot, the way Alexa Routines / Siri Shortcuts work.

CRUD for managing routines, plus POST /routines/{id}/run which executes
every step through the normal agent orchestrator and returns a combined
response.
"""
from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import Routine
from backend.core.request_context import get_current_user_id
from backend.core.rate_limit import chat_rate_limiter_minute, chat_rate_limiter_daily, require_budget

router = APIRouter()


def _serialize(r: Routine) -> dict:
    try:
        steps = json.loads(r.steps)
    except Exception:
        steps = []
    return {
        "id": r.id,
        "name": r.name,
        "triggerPhrase": r.trigger_phrase,
        "steps": steps,
        "enabled": r.enabled,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }


class RoutineIn(BaseModel):
    name: str
    trigger_phrase: str
    steps: list[str]
    enabled: bool = True


@router.get("/routines")
def list_routines():
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        routines = db.query(Routine).filter(Routine.user_id == uid).order_by(Routine.created_at.desc()).all()
        return {"routines": [_serialize(r) for r in routines]}
    finally:
        db.close()


@router.post("/routines")
def create_routine(body: RoutineIn):
    if not body.steps:
        raise HTTPException(status_code=400, detail="A routine needs at least one step")
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        routine = Routine(
            user_id=uid,
            name=body.name,
            trigger_phrase=body.trigger_phrase.lower().strip(),
            steps=json.dumps(body.steps),
            enabled=body.enabled,
        )
        db.add(routine)
        db.commit()
        db.refresh(routine)
        return _serialize(routine)
    finally:
        db.close()


@router.put("/routines/{routine_id}")
def update_routine(routine_id: int, body: RoutineIn):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        r = db.query(Routine).filter(Routine.id == routine_id, Routine.user_id == uid).first()
        if not r:
            raise HTTPException(status_code=404, detail="Routine not found")
        r.name = body.name
        r.trigger_phrase = body.trigger_phrase.lower().strip()
        r.steps = json.dumps(body.steps)
        r.enabled = body.enabled
        db.commit()
        db.refresh(r)
        return _serialize(r)
    finally:
        db.close()


@router.delete("/routines/{routine_id}")
def delete_routine(routine_id: int):
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        r = db.query(Routine).filter(Routine.id == routine_id, Routine.user_id == uid).first()
        if not r:
            raise HTTPException(status_code=404, detail="Routine not found")
        db.delete(r)
        db.commit()
        return {"deleted": routine_id}
    finally:
        db.close()


def find_matching_routine(query: str, uid: int) -> Routine | None:
    """
    Used by the orchestrator to check if a user's message matches a
    routine's trigger phrase before falling through to normal agent
    routing. Loose substring match, case-insensitive.
    """
    db = SessionLocal()
    try:
        routines = db.query(Routine).filter(Routine.user_id == uid, Routine.enabled == True).all()
        q = query.lower().strip()
        for r in routines:
            if r.trigger_phrase and r.trigger_phrase in q:
                return r
        return None
    finally:
        db.close()


@router.post("/routines/{routine_id}/run")
def run_routine(routine_id: int):
    """Execute every step in order through the agent orchestrator, return combined results."""
    from backend.agents.orchestrator import route_and_run

    uid = get_current_user_id()
    db = SessionLocal()
    try:
        r = db.query(Routine).filter(Routine.id == routine_id, Routine.user_id == uid).first()
        if not r:
            raise HTTPException(status_code=404, detail="Routine not found")
        steps = json.loads(r.steps)
    finally:
        db.close()

    rate_key = str(uid) if uid is not None else "unknown"

    results = []
    for step_query in steps:
        # Phase 29: check per-step, not just once for the whole request --
        # a routine with several steps makes that many separate LLM
        # calls through route_and_run() below, all drawing on the same
        # shared budget /chat/stream protects. If the budget runs out
        # partway through, remaining steps get a clear message instead
        # of silently continuing to spend past the limit.
        try:
            require_budget(
                chat_rate_limiter_minute, chat_rate_limiter_daily, rate_key,
                minute_detail="Rate limit exceeded — please wait a moment before running more routine steps.",
                daily_detail="You've hit today's usage limit for this shared deployment. It resets in 24 hours.",
            )
        except HTTPException as e:
            results.append({"query": step_query, "answer": f"(Skipped: {e.detail})", "agent": "rate_limited"})
            continue

        try:
            result = route_and_run(step_query)
            results.append({"query": step_query, "answer": result.answer, "agent": result.agent_name})
        except Exception as e:
            results.append({"query": step_query, "answer": f"(This step failed: {e})", "agent": "error"})

    combined = f"Running your \"{r.name}\" routine:\n\n" + "\n\n---\n\n".join(
        f"**{res['query']}**\n{res['answer']}" for res in results
    )

    return {"routineName": r.name, "steps": results, "combinedAnswer": combined}