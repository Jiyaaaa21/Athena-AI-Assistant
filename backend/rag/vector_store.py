import chromadb
import uuid

from backend.core.request_context import get_current_user_id

client = chromadb.PersistentClient(
    path="data/chroma_db"
)

collection = client.get_or_create_collection(
    name="athena_docs"
)


def _resolve_user_id(user_id):
    """Phase 12: default to the current request's authenticated user when
    the caller doesn't pass one explicitly. Falls back to the contextvar so
    legacy call sites (RAGTool.run, which only receives a query string and
    has no way to pass user_id) still get correctly scoped."""
    return user_id if user_id is not None else get_current_user_id()


def store_chunks(chunks, embeddings, filename, user_id=None):

    user_id = _resolve_user_id(user_id)

    ids = [
        str(uuid.uuid4())
        for _ in chunks
    ]

    metadatas = [
        {
            "source": filename,
            # Phase 12 addition: every chunk is tagged with its owning user
            # so search_chunks() can filter cross-user leakage at the
            # ChromaDB query level, not just in the SQL layer.
            "user_id": str(user_id) if user_id is not None else "",
        }
        for _ in chunks
    ]

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings.tolist(),
        metadatas=metadatas
    )


def search_chunks(query_embedding, top_k=5, user_id=None):

    user_id = _resolve_user_id(user_id)

    where = {"user_id": str(user_id)} if user_id is not None else None

    results = collection.query(
        query_embeddings=[
            query_embedding.tolist()
        ],
        n_results=top_k,
        where=where,
        # Phase 8 addition: "distances" lets rag_pipeline.rag_answer compute
        # a relevance/confidence score per source. Not requested before, so
        # results never carried any sense of "how sure" a match was.
        include=["documents", "metadatas", "distances"]
    )

    return results


def delete_by_source(filename, user_id=None):
    """
    Phase 2 addition: needed by DELETE /documents/{id} so removing a
    document also removes its embedded chunks, instead of leaving orphaned
    vectors in the collection that the RAG tool would keep retrieving from.

    Phase 12 change: scoped to the owning user so deleting "report.pdf"
    can never delete a different user's same-named document's chunks.
    """

    user_id = _resolve_user_id(user_id)

    where = {
        "$and": [
            {"source": filename},
            {"user_id": str(user_id) if user_id is not None else ""},
        ]
    }

    collection.delete(where=where)
