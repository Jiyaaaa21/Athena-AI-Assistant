"""
Phase 7 — Global Search API
GET /search?q=...&sources=...&limit=...

Fan-out search across all four knowledge sources in parallel threads:
  • Notes        — SQLite ILIKE on title + content
  • Reminders    — SQLite ILIKE on title
  • Memory       — SQLite ILIKE on content
  • Documents    — ChromaDB semantic (vector) search via the existing embedder

Each result carries:
  source:     "notes" | "reminders" | "memory" | "documents"
  id:         row id (string)
  title:      display title
  excerpt:    short context snippet (≤200 chars)
  score:      0.0–1.0 relevance (keyword=1.0, semantic=from distance)
  meta:       source-specific extra fields
  highlight:  list of character [start, end] spans within `excerpt`
              that match the query (for bold highlighting in the UI)

GET /search/document-chunks?doc_id=...&q=...
  Returns the top matching chunks inside a single document with
  character-level highlight spans — powers the "Highlight Relevant
  Chunks" panel in the Document detail view.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from fastapi import APIRouter, Query

from backend.database.db import SessionLocal
from backend.database.models import Document, Message, Note, Reminder
from backend.core.request_context import get_current_user_id
from backend.rag.embedder import create_query_embedding
from backend.rag.vector_store import search_chunks

router = APIRouter()

# ── Highlight helpers ─────────────────────────────────────────────────────────

def _highlight_spans(text: str, query: str) -> list[list[int]]:
    """
    Return [[start, end], …] character spans where query tokens appear in text.
    Case-insensitive. Overlapping spans are merged.
    """
    spans: list[tuple[int, int]] = []
    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    lo = text.lower()
    for token in tokens:
        start = 0
        while True:
            idx = lo.find(token, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(token)))
            start = idx + 1

    if not spans:
        return []

    # Merge overlapping spans
    spans.sort()
    merged: list[list[int]] = []
    cs, ce = spans[0]
    for s, e in spans[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            merged.append([cs, ce])
            cs, ce = s, e
    merged.append([cs, ce])
    return merged


def _excerpt(text: str, query: str, max_len: int = 200) -> str:
    """Return a snippet centred around the first query match."""
    lo = text.lower()
    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    best = len(text)
    for token in tokens:
        idx = lo.find(token)
        if idx != -1 and idx < best:
            best = idx

    if best == len(text):
        return text[:max_len]

    half = max_len // 2
    start = max(0, best - half)
    end = min(len(text), start + max_len)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


# ── Per-source search functions (each runs in a thread) ──────────────────────

def _search_notes(q: str, limit: int, user_id) -> list[dict]:
    db = SessionLocal()
    try:
        like = f"%{q}%"
        rows = (
            db.query(Note)
            .filter(
                (Note.title.ilike(like)) | (Note.content.ilike(like)),
                Note.user_id == user_id,
            )
            .order_by(Note.id.desc())
            .limit(limit)
            .all()
        )
        results = []
        for n in rows:
            body = n.content or ""
            exc = _excerpt(f"{n.title or ''} {body}", q)
            results.append({
                "source": "notes",
                "id": str(n.id),
                "title": n.title or "(untitled)",
                "excerpt": exc,
                "score": 1.0,
                "highlight": _highlight_spans(exc, q),
                "meta": {
                    "category": n.category,
                    "tags": n.tags.split(",") if n.tags else [],
                    "pinned": bool(n.pinned),
                    "createdAt": n.created_at.isoformat() if n.created_at else None,
                },
            })
        return results
    finally:
        db.close()


def _search_reminders(q: str, limit: int, user_id) -> list[dict]:
    db = SessionLocal()
    try:
        like = f"%{q}%"
        rows = (
            db.query(Reminder)
            .filter(
                (Reminder.title.ilike(like)) | (Reminder.content.ilike(like)),
                Reminder.user_id == user_id,
            )
            .order_by(Reminder.id.desc())
            .limit(limit)
            .all()
        )
        results = []
        for r in rows:
            title = r.title or r.content or ""
            exc = _excerpt(title, q)
            results.append({
                "source": "reminders",
                "id": str(r.id),
                "title": title,
                "excerpt": exc,
                "score": 1.0,
                "highlight": _highlight_spans(exc, q),
                "meta": {
                    "dueAt": r.due_at or r.due_time,
                    "done": bool(r.done),
                    "priority": r.priority,
                    "category": r.category,
                },
            })
        return results
    finally:
        db.close()


def _search_memory(q: str, limit: int, user_id) -> list[dict]:
    db = SessionLocal()
    try:
        like = f"%{q}%"
        rows = (
            db.query(Message)
            .filter(Message.content.ilike(like), Message.user_id == user_id)
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        results = []
        for m in rows:
            exc = _excerpt(m.content or "", q)
            results.append({
                "source": "memory",
                "id": str(m.id),
                "title": exc[:60] + ("…" if len(exc) > 60 else ""),
                "excerpt": exc,
                "score": 1.0,
                "highlight": _highlight_spans(exc, q),
                "meta": {
                    "role": m.role,
                    "createdAt": m.created_at.isoformat() if m.created_at else None,
                },
            })
        return results
    finally:
        db.close()


def _search_documents(q: str, limit: int, user_id) -> list[dict]:
    """
    Semantic search via ChromaDB. Returns top-k chunks with confidence
    scores, then resolves Document metadata from SQLite.
    """
    try:
        embedding = create_query_embedding(q)
        raw = search_chunks(embedding, top_k=min(limit, 10), user_id=user_id)
    except Exception:
        return []

    docs_text = raw.get("documents", [[]])[0]
    metadatas = raw.get("metadatas", [[]])[0]
    distances = raw.get("distances", [[]])[0]

    db = SessionLocal()
    try:
        results = []
        seen_sources: dict[str, dict] = {}  # filename → best result

        for i, chunk_text in enumerate(docs_text):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) and distances[i] is not None else 1.0
            score = round(1.0 / (1.0 + dist), 3)
            filename = meta.get("source", "unknown")

            # Keep only the best-scoring chunk per document for the global
            # search results list. Individual chunks are exposed via the
            # /search/document-chunks endpoint for the detail panel.
            if filename in seen_sources:
                if score > seen_sources[filename]["score"]:
                    seen_sources[filename]["score"] = score
                    seen_sources[filename]["excerpt"] = _excerpt(chunk_text, q)
                    seen_sources[filename]["highlight"] = _highlight_spans(
                        _excerpt(chunk_text, q), q
                    )
                continue

            doc_row = (
                db.query(Document)
                .filter(Document.filename == filename, Document.user_id == user_id)
                .first()
            )
            exc = _excerpt(chunk_text, q)
            seen_sources[filename] = {
                "source": "documents",
                "id": str(doc_row.id) if doc_row else filename,
                "title": filename,
                "excerpt": exc,
                "score": score,
                "highlight": _highlight_spans(exc, q),
                "meta": {
                    "filename": filename,
                    "pages": doc_row.pages if doc_row else None,
                    "chunkCount": doc_row.chunk_count if doc_row else None,
                    "uploadedAt": doc_row.uploaded_at.isoformat() if doc_row and doc_row.uploaded_at else None,
                    "sizeBytes": doc_row.size_bytes if doc_row else None,
                    "documentId": str(doc_row.id) if doc_row else None,
                },
            }

        results = sorted(seen_sources.values(), key=lambda x: -x["score"])
        return results[:limit]
    finally:
        db.close()


# ── Knowledge Graph helper ────────────────────────────────────────────────────

def _build_knowledge_graph(q: str, user_id) -> dict:
    """
    Lightweight knowledge graph: surfaces connections between the query term
    and entities in the workspace. Returns nodes + edges for the frontend.
    Each node is a workspace entity; each edge is "query → entity" or
    "entity → entity" (e.g. a note that references a reminder topic).
    """
    db = SessionLocal()
    try:
        like = f"%{q}%"
        nodes: list[dict] = [{"id": "query", "label": q, "type": "query"}]
        edges: list[dict] = []

        # Notes nodes
        notes = db.query(Note).filter(
            (Note.title.ilike(like)) | (Note.content.ilike(like)),
            Note.user_id == user_id,
        ).limit(5).all()
        for n in notes:
            nid = f"note-{n.id}"
            nodes.append({"id": nid, "label": n.title or "Note", "type": "note"})
            edges.append({"from": "query", "to": nid, "label": "found in"})

        # Reminder nodes
        reminders = db.query(Reminder).filter(
            Reminder.title.ilike(like), Reminder.user_id == user_id
        ).limit(3).all()
        for r in reminders:
            rid = f"reminder-{r.id}"
            nodes.append({"id": rid, "label": r.title or "Reminder", "type": "reminder"})
            edges.append({"from": "query", "to": rid, "label": "found in"})

        # Document nodes (by filename match)
        doc_rows = db.query(Document).filter(
            Document.filename.ilike(like), Document.user_id == user_id
        ).limit(3).all()
        for d in doc_rows:
            did = f"doc-{d.id}"
            nodes.append({"id": did, "label": d.filename, "type": "document"})
            edges.append({"from": "query", "to": did, "label": "found in"})

        # Cross-links: if a note's category matches a reminder's category
        note_cats = {n.category for n in notes if n.category}
        for r in reminders:
            if r.category and r.category in note_cats:
                for n in notes:
                    if n.category == r.category:
                        edges.append({
                            "from": f"note-{n.id}",
                            "to": f"reminder-{r.id}",
                            "label": r.category,
                        })
                        break

        return {"nodes": nodes, "edges": edges}
    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────────────────

ALL_SOURCES = {"notes", "reminders", "memory", "documents"}


@router.get("/search")
def global_search(
    q: str = Query(..., min_length=1),
    sources: Optional[str] = Query(None, description="Comma-separated: notes,reminders,memory,documents"),
    limit: int = Query(5, ge=1, le=20),
    include_graph: bool = Query(False),
):
    """
    Fan-out search. Runs each source in a thread so latency ≈ slowest source,
    not sum of all sources. Returns merged, sorted results.
    """
    requested = (
        {s.strip() for s in sources.split(",")} & ALL_SOURCES
        if sources
        else ALL_SOURCES
    )

    user_id = get_current_user_id()

    tasks: dict[str, any] = {}
    workers = {
        "notes":     lambda: _search_notes(q, limit, user_id),
        "reminders": lambda: _search_reminders(q, limit, user_id),
        "memory":    lambda: _search_memory(q, limit, user_id),
        "documents": lambda: _search_documents(q, limit, user_id),
    }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fn): src
            for src, fn in workers.items()
            if src in requested
        }
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception:
                pass  # individual source failure doesn't kill the whole search

    # Sort: score desc, then by source priority
    source_order = {"documents": 0, "notes": 1, "memory": 2, "reminders": 3}
    results.sort(key=lambda r: (-r["score"], source_order.get(r["source"], 9)))

    response: dict = {
        "query": q,
        "total": len(results),
        "results": results,
        "sources_searched": list(requested),
    }

    if include_graph:
        response["graph"] = _build_knowledge_graph(q, user_id)

    return response


@router.get("/search/document-chunks")
def document_chunks(
    doc_id: str = Query(...),
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
):
    """
    Semantic search within a single document.
    Returns ranked chunks with character-level highlight spans for the
    Document detail panel ("Highlight Relevant Chunks").
    """
    db = SessionLocal()
    try:
        user_id = get_current_user_id()
        doc = db.query(Document).filter(
            Document.id == int(doc_id), Document.user_id == user_id
        ).first()
        if not doc:
            return {"chunks": [], "document": None}

        embedding = create_query_embedding(q)
        raw = search_chunks(embedding, top_k=top_k * 3, user_id=user_id)  # over-fetch then filter

        docs_list = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        chunks = []
        for i, chunk_text in enumerate(docs_list):
            meta = metadatas[i] if i < len(metadatas) else {}
            if meta.get("source") != doc.filename:
                continue
            dist = distances[i] if i < len(distances) and distances[i] is not None else 1.0
            score = round(1.0 / (1.0 + dist), 3)
            chunks.append({
                "index": i,
                "text": chunk_text,
                "score": score,
                "highlight": _highlight_spans(chunk_text, q),
            })
            if len(chunks) >= top_k:
                break

        chunks.sort(key=lambda c: -c["score"])

        return {
            "document": {
                "id": str(doc.id),
                "filename": doc.filename,
                "pages": doc.pages,
                "chunkCount": doc.chunk_count,
                "uploadedAt": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                "sizeBytes": doc.size_bytes,
            },
            "query": q,
            "chunks": chunks,
        }
    except (ValueError, Exception):
        return {"chunks": [], "document": None}
    finally:
        db.close()