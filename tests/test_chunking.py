from backend.rag.pdf_loader import load_pdf
from backend.rag.chunker import chunk_text

text = load_pdf("data/documents/sample.pdf")

chunks = chunk_text(text)

print("Total Chunks:", len(chunks))

print("\nFirst Chunk:\n")
print(chunks[0])

print("\nChunk Length:")
print(len(chunks[0]))