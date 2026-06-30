"""
agents/rag_agent.py  —  Phase 15 fix

Fixes:
1. "I don't see any uploaded documents" despite docs existing:
   _has_documents() was called in run_stream() which runs on a thread-pool
   executor where the request context (user_id) is not always propagated.
   Fix: removed the pre-flight _has_documents() check entirely. The
   rag_answer() pipeline already handles the empty case gracefully by
   returning an empty sources list and saying "no content found".

2. Irrelevant low-confidence sources shown with badges:
   The pipeline was passing all retrieved chunks through regardless of
   relevance. Added post-retrieval filtering — sources below 40%
   confidence are stripped before display.
"""

from __future__ import annotations
from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw, ask_llm_raw_stream
from backend.core.logger import agent_logger
from backend.rag.rag_pipeline import rag_answer

_RAG_KEYWORDS = {
    "document", "documents", "pdf", "file", "files", "uploaded",
    "according to", "in the document", "from my", "my document",
    "what does the", "based on", "in the report", "report says",
    "resume", "cv", "sop", "notes say", "paper", "abstract",
    "what does it say", "what is in", "summarize the", "summarise the",
    "tell me about the", "from the file", "my pdf",
}

# Only show sources above this threshold in the UI
_DISPLAY_CONFIDENCE_MIN = 40


class RAGAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "rag"

    @property
    def description(self) -> str:
        return (
            "Document intelligence agent. Use when the user asks about uploaded "
            "documents, PDFs, resumes, reports, or any stored knowledge. "
            "Performs semantic search with confidence-scored citations."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _RAG_KEYWORDS)

    def _multi_hop_prompt(self, query: str, rag_answer_text: str, sources: list[dict]) -> str:
        source_list = "\n".join(
            f"- {s.get('title', 'Document')} ({s.get('confidence', '?')}% match)"
            for s in sources[:5]
        )
        history = self.get_conversation_context(turns=4)
        return (
            f"You are Athena, a document intelligence assistant.\n\n"
            f"{history}"
            f"User Question: {query}\n\n"
            f"Retrieved Document Content:\n{rag_answer_text}\n\n"
            f"Sources found:\n{source_list if source_list else 'None above threshold'}\n\n"
            f"Instructions:\n"
            f"1. If the retrieved content contains an answer, provide it clearly "
            f"   and cite which document it came from.\n"
            f"2. If no relevant content was found (sources list is empty or content "
            f"   says 'no relevant content'), say: 'I couldn't find that information "
            f"   in your uploaded documents.' Then offer to search the web instead.\n"
            f"3. Do NOT say you have no access to documents — the content above IS "
            f"   from your documents.\n"
            f"4. Be specific and reference the document filename when citing."
        )

    def _filter_sources(self, sources: list[dict]) -> list[dict]:
        """Remove sources below display threshold."""
        return [s for s in sources if s.get("confidence", 0) >= _DISPLAY_CONFIDENCE_MIN]

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[RAGAgent] query={query!r}")

        steps.append("Searching document store…")
        try:
            rag_result = rag_answer(query)
            raw_answer = rag_result.get("answer", "")
            all_sources = rag_result.get("sources", [])
            # Filter to only show relevant sources
            sources = self._filter_sources(all_sources)
            steps.append(f"Retrieved {len(all_sources)} chunks, {len(sources)} above threshold")
        except Exception as e:
            agent_logger.error(f"[RAGAgent] rag_answer failed: {e}")
            return AgentResult(
                answer=f"I encountered an error searching your documents: {e}",
                agent_name=self.name,
                steps=steps,
                confidence=0,
            )

        steps.append("Synthesising answer…")
        prompt = self._multi_hop_prompt(query, raw_answer, sources)
        final_answer = ask_llm_raw(prompt)

        confidence = max((s.get("confidence", 0) for s in sources), default=0)

        return AgentResult(
            answer=final_answer,
            agent_name=self.name,
            sources=sources,
            steps=steps,
            confidence=confidence,
            metadata={"source_count": len(sources)},
        )

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, None]:
        agent_logger.info(f"[RAGAgent] stream query={query!r}")

        try:
            rag_result = rag_answer(query)
            raw_answer = rag_result.get("answer", "")
            all_sources = rag_result.get("sources", [])
            sources = self._filter_sources(all_sources)
        except Exception as e:
            yield f"I encountered an error searching your documents: {e}"
            return

        prompt = self._multi_hop_prompt(query, raw_answer, sources)
        for chunk in ask_llm_raw_stream(prompt):
            yield chunk
