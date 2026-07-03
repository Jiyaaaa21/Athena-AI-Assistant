import hashlib
import io
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, HTTPException
from pypdf import PdfReader

from backend.rag.pdf_loader import load_pdf, get_pdf_page_count
from backend.rag.chunker import chunk_text
from backend.rag.embedder import create_embeddings
from backend.rag.vector_store import store_chunks, delete_by_source
from backend.database.db import SessionLocal
from backend.database.models import Document
from backend.core.config import MAX_UPLOAD_SIZE_MB, MAX_UPLOAD_PAGES
from backend.core.rate_limit import upload_rate_limiter_minute, upload_rate_limiter_daily, require_budget
from backend.core.request_context import get_current_user_id

router = APIRouter()


def _serialize(document: Document) -> dict:
    return {
        "id": str(document.id),
        "name": document.filename,
        "size": document.size_bytes,
        "uploadedAt": document.uploaded_at.isoformat() if document.uploaded_at else None,
        "status": document.status,
        "pages": document.pages,
        "chunkCount": document.chunk_count,
    }


@router.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...)
):

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    user_id = get_current_user_id()

    # Read the whole file into memory once, so we can both hash it (for
    # duplicate detection) and persist it, instead of reading the upload
    # stream twice.
    file_bytes = await file.read()
    size_bytes = len(file_bytes)

    # Phase 8: reject oversized files before any DB writes -- fail fast and
    # cheaply rather than after partially processing.
    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File is {size_bytes / 1024 / 1024:.1f} MB, which exceeds "
                f"the {MAX_UPLOAD_SIZE_MB} MB upload limit."
            ),
        )

    # Phase 8: also cap page count -- a small-but-extremely-long PDF can be
    # just as expensive to embed as a large file.
    try:
        page_count = len(PdfReader(io.BytesIO(file_bytes)).pages)
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't read this PDF — it may be corrupted.")

    if page_count > MAX_UPLOAD_PAGES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This PDF has {page_count} pages, which exceeds the "
                f"{MAX_UPLOAD_PAGES}-page upload limit."
            ),
        )

    content_hash = hashlib.sha256(file_bytes).hexdigest()

    db = SessionLocal()

    try:
        # Phase 12: dedup checks are scoped to the current user only --
        # two different users uploading byte-identical content (e.g. a
        # public PDF) must never collide or short-circuit each other.
        hash_match = (
            db.query(Document)
            .filter(Document.content_hash == content_hash, Document.user_id == user_id)
            .first()
        )

        # Phase 7: true duplicate -- identical file content already
        # uploaded under a *different* filename. Block it rather than
        # silently re-embedding the same content twice and cluttering the
        # document list and the vector store with redundant chunks.
        if hash_match and hash_match.filename != file.filename:
            uploaded_date = (
                hash_match.uploaded_at.date().isoformat()
                if hash_match.uploaded_at
                else "an earlier date"
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This file's content is already uploaded as "
                    f"\"{hash_match.filename}\" (uploaded {uploaded_date})."
                ),
            )

        # Phase 7: identical content re-uploaded under the same filename --
        # genuinely nothing changed, so skip re-processing entirely and just
        # hand back the existing record (saves an embedding pass).
        if hash_match and hash_match.filename == file.filename:
            return _serialize(hash_match)

        # Phase 29: protects the Hugging Face embeddings API (HF_TOKEN) --
        # a distinct shared resource from chat completions, own budget.
        # Checked here -- after the dedup short-circuit above (so a
        # re-upload of identical content, which never reaches
        # create_embeddings(), doesn't consume budget it never actually
        # uses) but before any Document row is created (so a rejected
        # request doesn't leave a misleading "failed" row behind).
        require_budget(
            upload_rate_limiter_minute, upload_rate_limiter_daily,
            str(user_id) if user_id is not None else "unknown",
            minute_detail="Too many document uploads in a short time — please wait a moment.",
            daily_detail="You've hit today's document upload limit for this shared deployment. It resets in 24 hours.",
        )

        # Phase 25 fix: PDFs used to be written to data/documents/... on
        # local disk, which is wiped on every Render free-tier redeploy,
        # restart, or idle spin-down. Persisting the raw bytes in the
        # Document row itself (Postgres/Neon, which is not on that
        # ephemeral disk) means the file survives exactly as long as its
        # database row does -- no separate storage system to keep in sync,
        # at zero additional cost.
        # Same filename + different hash = legitimate re-upload/update of an
        # existing document; overwrite it in place rather than erroring.
        # Phase 12: scoped to the current user -- one user re-uploading
        # "resume.pdf" must never touch another user's row of the same name.
        existing = db.query(Document).filter(
            Document.filename == file.filename, Document.user_id == user_id
        ).first()

        if existing:
            document = existing
            document.status = "processing"
            document.size_bytes = size_bytes
            document.content_hash = content_hash
            document.file_data = file_bytes
            # Phase 25 fix: a re-upload never removed the previous chunks
            # for this document, so every re-upload silently accumulated a
            # duplicate, stale set of embeddings alongside the fresh ones.
            # Harmless-looking with ChromaDB on ephemeral disk (the old
            # chunks usually got wiped before anyone noticed), but a real
            # bug now that storage is durable -- clear them before
            # re-embedding.
            delete_by_source(file.filename, user_id=user_id)
        else:
            document = Document(
                filename=file.filename,
                size_bytes=size_bytes,
                status="processing",
                uploaded_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                user_id=user_id,
                file_data=file_bytes,
            )
            db.add(document)

        db.commit()
        db.refresh(document)

        try:
            # Extract (PdfReader accepts a file-like object directly, so no
            # disk round-trip is needed here either).
            text = load_pdf(io.BytesIO(file_bytes))
            pages = get_pdf_page_count(io.BytesIO(file_bytes))

            # Chunk
            chunks = chunk_text(text)

            # Embed
            embeddings = create_embeddings(chunks)

            # Store
            store_chunks(
                chunks,
                embeddings,
                file.filename,
                user_id=user_id,
                document_id=document.id,
            )

            document.status = "processed"
            document.pages = pages
            document.chunk_count = len(chunks)
            db.commit()
            db.refresh(document)

        except Exception:
            document.status = "failed"
            db.commit()
            raise

        return _serialize(document)

    finally:
        db.close()