import secrets
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.database.db import SessionLocal
from backend.database.models import Document
from backend.rag.vector_store import delete_by_source
from backend.api.upload import _serialize as serialize
from backend.core.request_context import get_current_user_id

router = APIRouter()

# ── Document download tokens (solves iframe auth) ─────────────────────────────
_DOC_TOKENS: dict[str, dict] = {}
_TOKEN_TTL = 60  # seconds — longer since PDF rendering can be slow


def _purge_doc_tokens():
    now = time.time()
    for k in [k for k, v in _DOC_TOKENS.items() if v["expires"] < now]:
        del _DOC_TOKENS[k]


@router.post("/documents/{document_id}/file-token")
def create_document_file_token(document_id: str):
    """Issue a short-lived token so the browser iframe can load the PDF."""
    _purge_doc_tokens()
    uid = get_current_user_id()
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(
            Document.id == int(document_id), Document.user_id == uid
        ).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
    finally:
        db.close()
    token = secrets.token_urlsafe(32)
    _DOC_TOKENS[token] = {
        "document_id": document_id,
        "user_id": uid,
        "expires": time.time() + _TOKEN_TTL,
    }
    return {"token": token}


@router.get("/documents/file/{token}")
def get_document_file_by_token(token: str):
    """Token-authenticated file serving — used by browser iframes."""
    _purge_doc_tokens()
    entry = _DOC_TOKENS.get(token)
    if not entry or entry["expires"] < time.time():
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # Don't pop — allow multiple loads (browser may request twice for PDF)
    document_id = entry["document_id"]
    user_id = entry["user_id"]
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(
            Document.id == int(document_id), Document.user_id == user_id
        ).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        # Phase 25 fix: the PDF used to be read back from local disk
        # (data/documents/...), which is wiped on every Render free-tier
        # redeploy/restart/idle spin-down. The bytes now live directly on
        # the Document row in Postgres, so they're served straight from
        # there instead of the filesystem.
        if not doc.file_data:
            raise HTTPException(status_code=404, detail="File data missing for this document")
        return Response(
            content=doc.file_data,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=\"{doc.filename}\""},
        )
    finally:
        db.close()


@router.get("/documents")
def list_documents():

    db = SessionLocal()

    try:
        documents = (
            db.query(Document)
            .filter(Document.user_id == get_current_user_id())
            .order_by(Document.id.desc())
            .all()
        )
        return [serialize(d) for d in documents]

    finally:
        db.close()


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str):

    db = SessionLocal()

    try:
        document = db.query(Document).filter(
            Document.id == int(document_id), Document.user_id == get_current_user_id()
        ).first()

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        if not document.file_data:
            raise HTTPException(
                status_code=404,
                detail="The file is missing — try re-uploading this document.",
            )

        return Response(
            content=document.file_data,
            media_type="application/pdf",
            # Phase 9 fix: "attachment" (the default when filename is set)
            # tells the browser to download the file -- the iframe just
            # rendered blank. "inline" lets the browser's PDF viewer show it.
            headers={"Content-Disposition": f"inline; filename=\"{document.filename}\""},
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document id")

    finally:
        db.close()


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):

    db = SessionLocal()

    try:
        document = db.query(Document).filter(
            Document.id == int(document_id), Document.user_id == get_current_user_id()
        ).first()

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        try:
            delete_by_source(document.filename, user_id=document.user_id)
        except Exception:
            pass

        db.delete(document)
        db.commit()

        return {"ok": True}

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document id")

    finally:
        db.close()