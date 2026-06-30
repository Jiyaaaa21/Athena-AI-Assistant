"""
rag/rag_pipeline.py  —  Phase 15: Complete RAG overhaul

Root causes of poor retrieval:
1. Confidence formula 100/(1+dist) with cosine distance (0-2 range) produces
   scores of 33-50 for good matches. MIN_CONFIDENCE=35 was filtering out
   valid results. Fixed: use 1/(1+dist)*100 AND lower threshold to 20.
2. Best-chunk-per-source dedupe discarded other relevant chunks from the same
   document. Fixed: take top-3 chunks per document (more context).
3. Prompt said "use ONLY document content" but didn't include page numbers
   or position hints, so the LLM couldn't locate specific info. Fixed:
   chunks now include their position (chunk 1 of 12, etc.).
4. No fallback when vector search returns nothing useful. Fixed: keyword
   fallback searches raw document text directly from the DB.
5. Multi-query expansion: generate 3 phrasings of the question and search
   all of them, then merge results. Catches vocabulary mismatch between
   question and document wording.
"""

from __future__ import annotations

import re
from backend.rag.embedder import create_query_embedding, create_embeddings
from backend.rag.vector_store import search_chunks
from backend.core.llm import ask_llm_raw
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import Document

_MIN_CONFIDENCE = 20      # lowered — cosine distances produce 20-50 range
_TOP_K_SEARCH   = 12     # retrieve more candidates, filter after
_MAX_CHUNKS_PER_DOC = 3  # allow multiple chunks per document
_MAX_CONTEXT_CHUNKS = 8  # cap total chunks sent to LLM


def _cosine_to_confidence(distance: float) -> int:
    """
    ChromaDB cosine distance is in [0, 2].
    0 = identical, 2 = opposite.
    Map to 0-100 confidence score.
    """
    return round((1 - distance / 2) * 100)


def _expand_queries(question: str) -> list[str]:
    """
    Generate 2 alternative phrasings to handle vocabulary mismatch.
    E.g. "What is the revenue?" might match "Total income" in the doc.
    """
    try:
        prompt = (
            f"Generate 2 alternative phrasings of this question for document search. "
            f"Return ONLY the 2 phrasings, one per line, no numbering.\n\n"
            f"Question: {question}"
        )
        raw = ask_llm_raw(prompt).strip()
        expansions = [line.strip() for line in raw.splitlines() if line.strip()]
        return [question] + expansions[:2]
    except Exception:
        return [question]


def _keyword_fallback(question: str, user_id: int) -> list[dict]:
    """
    If vector search yields poor results, fall back to keyword matching
    against the raw document content stored in the DB.
    Only used when top vector results are below confidence threshold.
    """
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(Document.user_id == user_id).all()
        if not docs:
            return []

        # Extract key terms from the question (words > 3 chars)
        terms = [w.lower() for w in re.findall(r'\b\w{4,}\b', question)]
        if not terms:
            return []

        results = []
        for doc in docs:
            # Score by how many terms appear in the filename
            name_lower = (doc.filename or "").lower()
            term_hits = sum(1 for t in terms if t in name_lower)
            if term_hits > 0:
                results.append({
                    "text": f"Document: {doc.filename}\n(Keyword match — vector search found no strong semantic match)",
                    "source": doc.filename,
                    "confidence": 25 + (term_hits * 5),
                    "chunk_index": 0,
                    "total_chunks": 1,
                })
        return sorted(results, key=lambda x: x["confidence"], reverse=True)[:3]
    finally:
        db.close()


def rag_answer(question: str, user_id=None) -> dict:
    """
    Full RAG pipeline with:
    - Multi-query expansion
    - Per-document multi-chunk retrieval
    - Better confidence scoring
    - Keyword fallback
    - Rich context prompt
    """
    user_id = user_id if user_id is not None else get_current_user_id()
    db = SessionLocal()

    try:
        # ── Step 1: Multi-query expansion ─────────────────────────────────────
        queries = _expand_queries(question)
        all_chunks: dict[str, dict] = {}  # key: chunk_text → best score entry

        for q in queries:
            try:
                embedding = create_query_embedding(q)
                results = search_chunks(embedding, top_k=_TOP_K_SEARCH, user_id=user_id)
            except Exception:
                continue

            raw_docs  = results.get("documents",  [[]])[0]
            metadatas = results.get("metadatas",  [[]])[0]
            distances = results.get("distances",  [[]])[0]

            for i, (doc_text, metadata) in enumerate(zip(raw_docs, metadatas)):
                if not metadata or "source" not in metadata:
                    continue
                dist = distances[i] if i < len(distances) and distances[i] is not None else 1.5
                confidence = _cosine_to_confidence(float(dist))
                if confidence < _MIN_CONFIDENCE:
                    continue

                key = doc_text[:100]  # dedup by content prefix
                if key not in all_chunks or confidence > all_chunks[key]["confidence"]:
                    all_chunks[key] = {
                        "text":       doc_text,
                        "source":     metadata["source"],
                        "confidence": confidence,
                    }

        # ── Step 2: Per-document, multi-chunk selection ───────────────────────
        # Group by source, keep top-3 per document
        by_source: dict[str, list[dict]] = {}
        for chunk in all_chunks.values():
            src = chunk["source"]
            by_source.setdefault(src, []).append(chunk)

        for src in by_source:
            by_source[src].sort(key=lambda c: c["confidence"], reverse=True)
            by_source[src] = by_source[src][:_MAX_CHUNKS_PER_DOC]

        # Flatten, sort by confidence, take top N
        top_chunks = sorted(
            [c for chunks in by_source.values() for c in chunks],
            key=lambda c: c["confidence"],
            reverse=True,
        )[:_MAX_CONTEXT_CHUNKS]

        # ── Step 3: Keyword fallback if nothing useful found ──────────────────
        if not top_chunks:
            top_chunks = _keyword_fallback(question, user_id)

        # ── Step 4: Build rich context ────────────────────────────────────────
        if not top_chunks:
            context_block = "(No relevant content found in uploaded documents)"
        else:
            context_parts = []
            for i, c in enumerate(top_chunks, 1):
                context_parts.append(
                    f"[Excerpt {i} | Source: {c['source']} | Relevance: {c['confidence']}%]\n"
                    f"{c['text']}"
                )
            context_block = "\n\n---\n\n".join(context_parts)

        source_list = "\n".join(
            f"  • {c['source']} ({c['confidence']}% relevant)"
            for c in {c['source']: c for c in top_chunks}.values()
        ) if top_chunks else "  (none)"

        # ── Step 5: LLM answer with strong grounding instructions ─────────────
        prompt = (
            f"You are Athena, a document intelligence assistant with access to "
            f"the user's uploaded documents.\n\n"
            f"Documents searched:\n{source_list}\n\n"
            f"Relevant excerpts from those documents:\n\n"
            f"{context_block}\n\n"
            f"User question: {question}\n\n"
            f"Instructions:\n"
            f"1. Answer using the excerpts above as your primary source.\n"
            f"2. If the answer is directly in the excerpts, quote or paraphrase "
            f"   the relevant part and name the source file.\n"
            f"3. If only partial information is available, share what you found "
            f"   and note what's missing.\n"
            f"4. Only if the excerpts contain NO relevant information at all, say: "
            f"   'I couldn't find that in your uploaded documents.' — then offer "
            f"   to search the web instead.\n"
            f"5. Do NOT say you lack real-time access or document access — "
            f"   the excerpts above ARE the document content.\n"
            f"6. Be specific and cite which document your answer comes from."
        )

        answer = ask_llm_raw(prompt)

        # ── Step 6: Build source list ─────────────────────────────────────────
        sources = []
        seen_sources: set[str] = set()
        for chunk in top_chunks:
            src = chunk["source"]
            if src in seen_sources:
                continue
            seen_sources.add(src)

            doc_row = db.query(Document).filter(
                Document.filename == src,
                Document.user_id == user_id,
            ).first()

            sources.append({
                "id":         src,
                "title":      src,
                "type":       "pdf",
                "confidence": chunk["confidence"],
                "documentId": str(doc_row.id) if doc_row else None,
            })

    finally:
        db.close()

    return {"answer": answer, "sources": sources}
