import hashlib
import io
import os
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, HTTPException
from pypdf import PdfReader

from backend.rag.pdf_loader import load_pdf, get_pdf_page_count
from backend.rag.chunker import chunk_text
from backend.rag.embedder import create_embeddings
from backend.rag.vector_store import store_chunks
from backend.database.db import SessionLocal
from backend.database.models import Document
from backend.core.config import MAX_UPLOAD_SIZE_MB, MAX_UPLOAD_PAGES
from backend.core.request_context import get_current_user_id

router = APIRouter()

DOCUMENTS_DIR = "data/documents"


def user_documents_dir(user_id) -> str:
    """
    Phase 12: every user's uploaded PDFs live under their own subdirectory
    so two users can both upload a file with the same name without one
    overwriting the other's on disk.
    """
    return os.path.join(DOCUMENTS_DIR, str(user_id) if user_id is not None else "_unowned")


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
    docs_dir = user_documents_dir(user_id)

    # Read the whole file into memory once, so we can both hash it (for
    # duplicate detection) and write it to disk from the same bytes,
    # instead of reading the upload stream twice.
    file_bytes = await file.read()
    size_bytes = len(file_bytes)

    # Phase 8: reject oversized files before any disk I/O, hashing, or DB
    # writes -- fail fast and cheaply rather than after partially processing.
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
    # just as expensive to embed as a large file. Checked in-memory (no
    # disk write yet) so a rejected upload leaves nothing behind.
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

        # Phase 2 fix: this directory was never created anywhere, so the
        # original endpoint would throw FileNotFoundError on a fresh checkout.
        os.makedirs(docs_dir, exist_ok=True)

        save_path = f"{docs_dir}/{file.filename}"

        with open(save_path, "wb") as buffer:
            buffer.write(file_bytes)

        # Phase 2: persist a row up front with status="processing" so a
        # concurrent GET /documents (or a slow embed step) shows the file
        # immediately rather than it being invisible until everything finishes.
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
        else:
            document = Document(
                filename=file.filename,
                size_bytes=size_bytes,
                status="processing",
                uploaded_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                user_id=user_id,
            )
            db.add(document)

        db.commit()
        db.refresh(document)

        try:
            # Extract
            text = load_pdf(save_path)
            pages = get_pdf_page_count(save_path)

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
