from backend.rag.pdf_loader import load_pdf
from backend.rag.chunker import chunk_text
from backend.rag.embedder import create_embeddings

text = load_pdf(
    "data/documents/sample.pdf"
)

chunks = chunk_text(text)

embeddings = create_embeddings(chunks)

print("Number of Chunks:", len(chunks))
print("Embedding Shape:", embeddings.shape)