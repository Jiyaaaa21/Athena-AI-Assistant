from backend.rag.embedder import create_query_embedding
from backend.rag.vector_store import search_chunks

query = "What projects has Jyoti worked on?"

query_embedding = create_query_embedding(
    query
)

results = search_chunks(
    query_embedding
)

print(results["documents"][0])