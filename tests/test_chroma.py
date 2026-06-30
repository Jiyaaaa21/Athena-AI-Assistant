from backend.rag.pdf_loader import load_pdf
from backend.rag.chunker import chunk_text
from backend.rag.embedder import create_embeddings
from backend.rag.vector_store import store_chunks

text = load_pdf(
    "data/documents/sample.pdf"
)

chunks = chunk_text(text)

embeddings = create_embeddings(chunks)

store_chunks(
    chunks,
    embeddings
)

print("Stored successfully in ChromaDB")