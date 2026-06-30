"""
agents/research_agent.py  —  Phase 13

Research Agent: performs multi-step research on a topic by:
1. Decomposing the query into sub-questions
2. Pulling relevant context from RAG (documents) + news
3. Synthesising a structured research brief

Streams natively via Groq streaming.
"""

from __future__ import annotations

import asyncio
from typing import Generator

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw, ask_llm_raw_stream
from backend.core.logger import agent_logger
from backend.tools.news import NewsTool
from backend.rag.rag_pipeline import rag_answer
from backend.core.request_context import get_current_user_id

_news_tool = NewsTool()

_RESEARCH_KEYWORDS = {
    "research", "analyse", "analyze", "summarise", "summarize",
    "explain", "overview", "breakdown", "compare", "investigate",
    "study", "report", "brief", "deep dive", "what is", "how does",
    "tell me about", "pros and cons", "advantages", "disadvantages",
}


class ResearchAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return (
            "Deep research agent. Use for in-depth analysis, explanations, "
            "comparisons, topic overviews, or any query requiring synthesis "
            "from multiple sources. Combines document knowledge with live news."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _RESEARCH_KEYWORDS)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _decompose(self, query: str) -> list[str]:
        """Ask the LLM to break the query into 2-4 focused sub-questions."""
        history = self.get_conversation_context(turns=4)
        prompt = (
            f"{history}"
            f"Break the following research query into 2-4 specific sub-questions "
            f"that together fully address it. If the query is a short follow-up "
            f"(e.g. 'basics', 'start with phase 1', 'tell me more'), use the "
            f"conversation history above to infer the actual topic.\n"
            f"Return ONLY a numbered list, nothing else.\n\n"
            f"Query: {query}"
        )
        raw = ask_llm_raw(prompt)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        # Extract actual questions (strip leading "1." etc.)
        questions = []
        for line in lines:
            for sep in (". ", ") ", "- "):
                if sep in line:
                    questions.append(line.split(sep, 1)[-1].strip())
                    break
            else:
                if line:
                    questions.append(line)
        return questions[:4] if questions else [query]

    def _gather_sources(self, sub_questions: list[str], query: str) -> tuple[str, list[dict]]:
        """Gather context from RAG documents and news headlines."""
        sources = []
        context_parts = []

        # RAG: search documents for the main query
        try:
            rag_result = rag_answer(query)
            if rag_result.get("answer"):
                context_parts.append(f"[From your documents]\n{rag_result['answer']}")
                sources.extend(rag_result.get("sources", []))
        except Exception:
            pass

        # News: use the first sub-question as search term
        try:
            news_topic = sub_questions[0] if sub_questions else query
            news_text = _news_tool.run(news_topic[:80])
            if news_text and "error" not in news_text.lower():
                context_parts.append(f"[Recent news]\n{news_text}")
        except Exception:
            pass

        context = "\n\n".join(context_parts) if context_parts else "No external context available."
        return context, sources

    def _synthesis_prompt(self, query: str, sub_questions: list[str], context: str) -> str:
        sq_text = "\n".join(f"- {q}" for q in sub_questions)
        history = self.get_conversation_context(turns=4)
        return (
            f"You are Athena, an expert research assistant.\n\n"
            f"{history}"
            f"Research Query: {query}\n\n"
            f"Sub-questions to address:\n{sq_text}\n\n"
            f"Available context:\n{context}\n\n"
            f"IMPORTANT: If this query is a follow-up to the conversation above, "
            f"make sure your answer continues the established topic and references "
            f"prior context where relevant.\n\n"
            f"Write a comprehensive, well-structured research brief that:\n"
            f"1. Directly answers the query\n"
            f"2. Addresses each sub-question\n"
            f"3. Cites sources where relevant\n"
            f"4. Ends with a concise 'Key Takeaways' section\n\n"
            f"Use clear headings and be thorough but concise."
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = []
        agent_logger.info(f"[ResearchAgent] query={query!r}")

        steps.append("Decomposing query into sub-questions…")
        sub_questions = self._decompose(query)
        steps.append(f"Sub-questions: {sub_questions}")

        steps.append("Gathering context from documents and news…")
        gathered_context, sources = self._gather_sources(sub_questions, query)

        steps.append("Synthesising research brief…")
        prompt = self._synthesis_prompt(query, sub_questions, gathered_context)
        answer = ask_llm_raw(prompt)

        return AgentResult(
            answer=answer,
            agent_name=self.name,
            sources=sources,
            steps=steps,
            confidence=85,
            metadata={"sub_questions": sub_questions},
        )

    def run_stream(
        self, query: str, context: dict | None = None
    ) -> Generator[str, None, None]:
        agent_logger.info(f"[ResearchAgent] stream query={query!r}")

        sub_questions = self._decompose(query)
        gathered_context, sources = self._gather_sources(sub_questions, query)
        prompt = self._synthesis_prompt(query, sub_questions, gathered_context)

        for chunk in ask_llm_raw_stream(prompt):
            yield chunk
