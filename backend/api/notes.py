from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import Note
from backend.core.request_context import get_current_user_id

router = APIRouter()


# ---------- Schemas ----------
# Field names here mirror src/lib/mock.ts `Note` exactly so the frontend
# needs zero changes: { id, title, body, pinned, color?, createdAt }
# Roadmap addition: category? and tags? (string[]) -- both optional so
# existing callers that don't send them keep working unchanged.

class NoteCreate(BaseModel):
    title: str
    body: str = ""
    pinned: bool = False
    color: str | None = None
    category: str | None = None
    tags: list[str] = []


class NoteUpdate(BaseModel):
    title: str
    body: str = ""
    pinned: bool = False
    color: str | None = None
    category: str | None = None
    tags: list[str] = []


# ---------- Helpers ----------

def serialize(note: Note) -> dict:
    created_at = note.created_at or datetime.now(timezone.utc)
    return {
        "id": str(note.id),
        "title": note.title or "",
        "body": note.content or "",
        "pinned": bool(note.pinned),
        "color": note.color,
        "createdAt": created_at.isoformat(),
        "category": note.category,
        "tags": note.tags.split(",") if note.tags else [],
    }


def _tags_to_db(tags: list[str] | None) -> str | None:
    """Comma-joined string for storage; None when empty so the column stays
    NULL rather than an empty string."""
    if not tags:
        return None
    cleaned = [t.strip() for t in tags if t.strip()]
    return ",".join(cleaned) if cleaned else None


# ---------- Routes ----------

@router.get("/notes")
def list_notes():

    db = SessionLocal()

    try:
        notes = (
            db.query(Note)
            .filter(Note.user_id == get_current_user_id())
            .order_by(Note.id.desc())
            .all()
        )
        return [serialize(n) for n in notes]

    finally:
        db.close()


@router.post("/notes")
def create_note(payload: NoteCreate):

    db = SessionLocal()

    try:
        note = Note(
            title=payload.title,
            content=payload.body,  # `content` is the legacy/shared column
            pinned=payload.pinned,
            color=payload.color,
            category=payload.category,
            tags=_tags_to_db(payload.tags),
            created_at=datetime.now(timezone.utc),
            user_id=get_current_user_id(),
        )

        db.add(note)
        db.commit()
        db.refresh(note)

        return serialize(note)

    finally:
        db.close()


@router.put("/notes/{note_id}")
def update_note(note_id: str, payload: NoteUpdate):

    db = SessionLocal()

    try:
        note = db.query(Note).filter(
            Note.id == int(note_id), Note.user_id == get_current_user_id()
        ).first()

        if not note:
            raise HTTPException(status_code=404, detail="Note not found")

        note.title = payload.title
        note.content = payload.body
        note.pinned = payload.pinned
        note.color = payload.color
        note.category = payload.category
        note.tags = _tags_to_db(payload.tags)

        db.commit()
        db.refresh(note)

        return serialize(note)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid note id")

    finally:
        db.close()


@router.delete("/notes/{note_id}")
def delete_note(note_id: str):

    db = SessionLocal()

    try:
        note = db.query(Note).filter(
            Note.id == int(note_id), Note.user_id == get_current_user_id()
        ).first()

        if not note:
            raise HTTPException(status_code=404, detail="Note not found")

        db.delete(note)
        db.commit()

        return {"ok": True}

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid note id")

    finally:
        db.close()