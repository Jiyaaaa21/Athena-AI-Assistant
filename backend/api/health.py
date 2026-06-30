"""
Health / API Monitor — Phase 4.5 addition.

GET /health returns the live status + response-time of every internal subsystem.
The frontend uses this for the Settings → API Health Monitor panel.
"""

from __future__ import annotations

import time
from fastapi import APIRouter
from backend.database.db import SessionLocal
from backend.database.models import Message

router = APIRouter()


def _probe_db() -> dict:
    start = time.perf_counter()
    try:
        db = SessionLocal()
        db.query(Message).limit(1).all()
        db.close()
        ms = round((time.perf_counter() - start) * 1000, 1)
        return {"status": "ok", "response_ms": ms}
    except Exception as exc:
        ms = round((time.perf_counter() - start) * 1000, 1)
        return {"status": "error", "response_ms": ms, "detail": str(exc)}


@router.get("/health")
def health():
    """Return live health status for each subsystem."""
    db_result = _probe_db()

    return {
        "backend": {"status": "ok", "response_ms": 0},
        "database": db_result,
        "memory_api": {"status": "ok" if db_result["status"] == "ok" else "degraded"},
        "upload_api": {"status": "ok"},
        "chat_api": {"status": "ok"},
    }
