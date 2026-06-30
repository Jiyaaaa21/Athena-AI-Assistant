from fastapi import APIRouter, UploadFile, File
import shutil

from backend.rag.pdf_loader import load_pdf
from backend.rag.chunker import chunk_text
from backend.rag.embedder import create_embeddings
from backend.rag.vector_store import store_chunks
from backend.api.response import (
    success_response,
    error_response
)
router = APIRouter()


@router.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...)
):

    save_path = f"data/documents/{file.filename}"

    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(
            file.file,
            buffer
        )

    # Extract
    text = load_pdf(save_path)

    # Chunk
    chunks = chunk_text(text)

    # Embed
    embeddings = create_embeddings(chunks)

    # Store
    store_chunks(
        chunks,
        embeddings,
        file.filename
    )

    return success_response(
    {
        "message": "Document processed successfully",
        "filename": file.filename,
        "chunks": len(chunks)
    }
)