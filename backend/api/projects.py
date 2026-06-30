"""
backend/api/projects.py  —  Phase 14: Project Awareness API

Projects group conversations, notes, reminders, and documents
around a common theme (e.g. "Deploy Athena", "UPSC Prep").

Endpoints:
  GET    /projects                    — list projects
  POST   /projects                    — create project
  PUT    /projects/{id}               — update project
  DELETE /projects/{id}               — delete project
  POST   /projects/{id}/link          — link an entity to a project
  DELETE /projects/{id}/link/{link_id} — remove a link
  GET    /projects/{id}/items         — get all linked entities for a project
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import Project, ProjectLink, Note, Reminder, Document, Conversation
from backend.core.request_context import get_current_user_id

router = APIRouter()


def utcnow():
    return datetime.now(timezone.utc)


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str
    description: str | None = None
    status: str = "active"


class LinkCreate(BaseModel):
    entity_type: str   # "conversation" | "note" | "reminder" | "document"
    entity_id: int


def _serialize_project(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
        "updatedAt": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/projects")
def list_projects():
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        projects = (
            db.query(Project)
            .filter(Project.user_id == uid)
            .order_by(Project.updated_at.desc())
            .all()
        )
        return [_serialize_project(p) for p in projects]
    finally:
        db.close()


@router.post("/projects")
def create_project(payload: ProjectCreate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        project = Project(
            user_id=uid,
            name=payload.name,
            description=payload.description,
            status="active",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return _serialize_project(project)
    except Exception as e:
        db.rollback()
        if "UNIQUE constraint failed" in str(e) or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="A project with this name already exists")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/projects/{project_id}")
def update_project(project_id: int, payload: ProjectUpdate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == uid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project.name = payload.name
        project.description = payload.description
        project.status = payload.status
        db.commit()
        db.refresh(project)
        return _serialize_project(project)
    finally:
        db.close()


@router.delete("/projects/{project_id}")
def delete_project(project_id: int):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == uid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        db.delete(project)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/projects/{project_id}/link")
def link_entity(project_id: int, payload: LinkCreate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == uid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check for duplicate link
        existing = db.query(ProjectLink).filter(
            ProjectLink.project_id == project_id,
            ProjectLink.entity_type == payload.entity_type,
            ProjectLink.entity_id == payload.entity_id,
        ).first()
        if existing:
            return {"id": existing.id, "already_linked": True}

        link = ProjectLink(
            project_id=project_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
        )
        db.add(link)
        # Bump project updated_at so it surfaces in context
        project.updated_at = utcnow()
        db.commit()
        db.refresh(link)
        return {"id": link.id, "already_linked": False}
    finally:
        db.close()


@router.delete("/projects/{project_id}/link/{link_id}")
def remove_link(project_id: int, link_id: int):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == uid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        link = db.query(ProjectLink).filter(
            ProjectLink.id == link_id, ProjectLink.project_id == project_id
        ).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        db.delete(link)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("/projects/{project_id}/items")
def get_project_items(project_id: int):
    """Return all entities linked to a project with their details."""
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == uid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        links = db.query(ProjectLink).filter(ProjectLink.project_id == project_id).all()

        items = []
        for link in links:
            item: dict | None = None
            try:
                if link.entity_type == "note":
                    n = db.query(Note).filter(Note.id == link.entity_id, Note.user_id == uid).first()
                    if n:
                        item = {"type": "note", "id": n.id, "title": n.title or n.content[:50]}
                elif link.entity_type == "reminder":
                    r = db.query(Reminder).filter(Reminder.id == link.entity_id, Reminder.user_id == uid).first()
                    if r:
                        item = {"type": "reminder", "id": r.id, "title": r.title or r.content, "done": r.done}
                elif link.entity_type == "document":
                    d = db.query(Document).filter(Document.id == link.entity_id, Document.user_id == uid).first()
                    if d:
                        item = {"type": "document", "id": d.id, "title": d.filename}
                elif link.entity_type == "conversation":
                    c = db.query(Conversation).filter(Conversation.id == link.entity_id, Conversation.user_id == uid).first()
                    if c:
                        item = {"type": "conversation", "id": c.id, "title": c.title}
            except Exception:
                pass

            if item:
                item["link_id"] = link.id
                items.append(item)

        return {
            "project": _serialize_project(project),
            "items": items,
        }
    finally:
        db.close()