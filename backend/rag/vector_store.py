"""
rag/vector_store.py — Phase 25: moved off ChromaDB / local disk entirely.

Why this changed
-----------------
ChromaDB's PersistentClient wrote to data/chroma_db on local disk. On
Render's free tier that disk is ephemeral: every redeploy, restart, and
routine spin-down/cold-start cycle (free instances sleep after ~15 minutes
idle) silently wiped it. A document could show "Indexed" in the UI
forever while its actual embeddings were gone the next time the service
woke back up.

This version stores chunks + embeddings as rows in the same Postgres
database (Neon, persistent) everything else already uses, via the
DocumentChunk model. Similarity search is done in Python with numpy
cosine similarity over the current user's own chunks. At the scale this
app operates at (a personal assistant's own documents -- dozens to a few
hundred chunks per user), this is comfortably fast and keeps the whole
fix at zero additional cost: no new service, no paid disk, no new
dependency, and it works unmodified against both the Postgres deployment
and a local SQLite file for dev.

Public API is unchanged (store_chunks / search_chunks / delete_by_source)
so every existing call site (api/upload.py, api/documents.py,
rag/rag_pipeline.py) needs no changes at all beyond this file.
"""

from __future__ import annotations

import json

import numpy as np

from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import DocumentChunk


def _resolve_user_id(user_id):
    """Same fallback behaviour as before: default to the current request's
    authenticated user when the caller doesn't pass one explicitly."""
    return user_id if user_id is not None else get_current_user_id()


def store_chunks(chunks, embeddings, filename, user_id=None, document_id=None):
    user_id = _resolve_user_id(user_id)

    db = SessionLocal()
    try:
        rows = [
            DocumentChunk(
                document_id=document_id,
                user_id=user_id,
                source=filename,
                chunk_index=i,
                text=chunk,
                embedding=json.dumps(np.asarray(vec, dtype=np.float32).tolist()),
            )
            for i, (chunk, vec) in enumerate(zip(chunks, embeddings))
        ]
        db.bulk_save_objects(rows)
        db.commit()
    finally:
        db.close()


def _cosine_distance(query_vec: np.ndarray, chunk_vec: np.ndarray) -> float:
    """
    Returns a distance in [0, 2] where 0 = identical, 2 = opposite --
    matching exactly what rag_pipeline._cosine_to_confidence() expects
    (this is the same contract the old ChromaDB cosine-space collection
    was supposed to provide, before the metric-mismatch bug).
    """
    qn = np.linalg.norm(query_vec)
    cn = np.linalg.norm(chunk_vec)
    if qn == 0 or cn == 0:
        return 2.0  # maximally dissimilar rather than dividing by zero
    cosine_similarity = float(np.dot(query_vec, chunk_vec) / (qn * cn))
    cosine_similarity = max(-1.0, min(1.0, cosine_similarity))  # clamp fp drift
    return 1.0 - cosine_similarity


def search_chunks(query_embedding, top_k=5, user_id=None):
    """
    Returns results shaped exactly like a ChromaDB query response
    (results["documents"][0], ["metadatas"][0], ["distances"][0]) so
    rag_pipeline.py -- written against that shape -- needs no changes.
    """
    user_id = _resolve_user_id(user_id)
    query_vec = np.asarray(query_embedding, dtype=np.float32)

    db = SessionLocal()
    try:
        q = db.query(DocumentChunk)
        if user_id is not None:
            q = q.filter(DocumentChunk.user_id == user_id)
        rows = q.all()

        scored = []
        for row in rows:
            try:
                chunk_vec = np.asarray(json.loads(row.embedding), dtype=np.float32)
            except (TypeError, ValueError):
                continue
            dist = _cosine_distance(query_vec, chunk_vec)
            scored.append((dist, row))

        scored.sort(key=lambda pair: pair[0])
        top = scored[:top_k]

        documents = [row.text for _dist, row in top]
        metadatas = [{"source": row.source, "user_id": str(row.user_id or "")} for _dist, row in top]
        distances = [dist for dist, _row in top]

        return {
            "documents": [documents],
            "metadatas": [metadatas],
            "distances": [distances],
        }
    finally:
        db.close()


def delete_by_source(filename, user_id=None):
    """
    Phase 12: scoped to the owning user so deleting "report.pdf" can never
    delete a different user's same-named document's chunks.
    """
    user_id = _resolve_user_id(user_id)

    db = SessionLocal()
    try:
        q = db.query(DocumentChunk).filter(DocumentChunk.source == filename)
        if user_id is not None:
            q = q.filter(DocumentChunk.user_id == user_id)
        q.delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()