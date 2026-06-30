from backend.rag.embedder import (
    create_query_embedding
)

from backend.rag.vector_store import (
    search_chunks
)

query = (
    "What projects has Jyoti worked on?"
)

embedding = create_query_embedding(
    query
)

results = search_chunks(
    embedding
)

print(results["metadatas"])