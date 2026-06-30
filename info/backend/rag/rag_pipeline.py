from backend.rag.embedder import create_query_embedding
from backend.rag.vector_store import search_chunks
from backend.core.llm import ask_llm_raw


def rag_answer(question):

    query_embedding = create_query_embedding(
        question
    )

    results = search_chunks(
        query_embedding
    )

    retrieved_chunks = "\n\n".join(
        results["documents"][0]
    )

    sources = set()

    # Collect sources safely
    for metadata in results["metadatas"][0]:

        if metadata and "source" in metadata:

            sources.add(
                metadata["source"]
            )

    prompt = f"""
Answer the question using ONLY the provided context.

Context:
{retrieved_chunks}

Question:
{question}

If the answer is unavailable,
say so.
"""

    answer = ask_llm_raw(prompt)

    # Build source section safely
    if sources:

        source_text = "\n".join(
            f"- {source}"
            for source in sources
        )

    else:

        source_text = "No source metadata available"

    return f"""
{answer}

Sources:
{source_text}
"""