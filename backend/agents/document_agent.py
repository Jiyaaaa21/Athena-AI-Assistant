"""
backend/agents/document_agent.py — Phase 29

Handles "write a summary of X as a PDF", "create a document about Y",
"turn that into a PDF I can download", "generate a report on Z".

Design: writes the actual document content via the LLM (this is a good
use of the LLM -- writing prose is what it's for, unlike calculator.py
where precision matters and the LLM is deliberately NOT trusted to
compute), renders it to a real PDF via rag/pdf_generator.py, and saves
it through the exact same Document storage api/upload.py already uses
(Postgres, not local disk -- same reasoning as the Phase 25 fix: a
generated file living only on Render's ephemeral disk would vanish on
the next redeploy/restart/idle spin-down). This means a generated
document shows up in the user's Documents page immediately, with full
preview/download/delete already working -- no new delivery mechanism
needed in the frontend at all.
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone

from backend.agents.base import BaseAgent, AgentResult
from backend.core.llm import ask_llm_raw
from backend.core.logger import agent_logger
from backend.core.rate_limit import upload_rate_limiter_minute, upload_rate_limiter_daily, require_budget
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import Document
from backend.rag.chunker import chunk_text
from backend.rag.embedder import create_embeddings
from backend.rag.pdf_generator import build_pdf
from backend.rag.pdf_loader import get_pdf_page_count
from backend.rag.vector_store import store_chunks

_DOC_KEYWORDS = {
    "create a pdf", "generate a pdf", "make a pdf", "as a pdf",
    "export as pdf", "download this as", "create a document",
    "generate a document", "write a report", "write me a document",
    "turn that into a pdf", "turn this into a pdf", "pdf of this",
    "give me a pdf", "make me a document",
}


class DocumentAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "document"

    @property
    def description(self) -> str:
        return (
            "Document generation agent. Use when the user wants a real, "
            "downloadable PDF file created -- 'write a summary of X as a "
            "PDF', 'create a document about Y', 'turn that into a PDF', "
            "'generate a report on Z'. NOT for saving quick notes (that's "
            "the notes agent) -- this produces an actual PDF file that "
            "appears in the user's Documents page."
        )

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in _DOC_KEYWORDS)

    def _generate_title(self, query: str, content: str) -> str:
        prompt = (
            "Give a short, clean title (under 8 words, no quotes, no "
            "punctuation at the end) for a document based on this request "
            f"and content.\n\nRequest: {query}\n\nContent preview: "
            f"{content[:300]}\n\nTitle:"
        )
        title = ask_llm_raw(prompt).strip().strip('"').strip("'")
        return title[:100] if title else "Generated Document"

    def _generate_content(self, query: str) -> str:
        history = self.get_conversation_context(turns=6)
        prompt = (
            f"You are Athena, writing the actual content of a document the "
            f"user asked for. Write complete, well-organized prose -- use "
            f"markdown-style '# Heading' and '## Subheading' lines for "
            f"structure and '- item' for bullet points where it genuinely "
            f"helps readability. Do NOT include a title line (that's "
            f"handled separately) -- start directly with the content. "
            f"Write the full document now, not a summary of what you would "
            f"write.\n\n{history}\nRequest: {query}\n\nDocument content:"
        )
        return ask_llm_raw(prompt).strip()

    def run(self, query: str, context: dict | None = None) -> AgentResult:
        steps = ["Writing the document content…"]
        user_id = get_current_user_id()

        content = self._generate_content(query)
        if not content:
            return AgentResult(
                answer="I couldn't come up with content for that document — could you be more specific about what you'd like in it?",
                agent_name=self.name,
                steps=steps,
                confidence=30,
            )

        steps.append("Choosing a title…")
        title = self._generate_title(query, content)

        steps.append("Rendering PDF…")
        try:
            pdf_bytes = build_pdf(title, content)
        except Exception as e:
            agent_logger.error(f"[DocumentAgent] PDF render failed: {e}")
            return AgentResult(
                answer=f"I wrote the content but ran into a problem turning it into a PDF ({e}). Here's the content instead:\n\n{content}",
                agent_name=self.name,
                steps=steps,
                confidence=40,
            )

        filename = f"{title.strip().replace(' ', '_')[:60] or 'document'}.pdf"
        content_hash = hashlib.sha256(pdf_bytes).hexdigest()

        db = SessionLocal()
        try:
            document = Document(
                filename=filename,
                size_bytes=len(pdf_bytes),
                status="processing",
                uploaded_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                user_id=user_id,
                file_data=pdf_bytes,
            )
            db.add(document)
            db.commit()
            db.refresh(document)

            try:
                pages = get_pdf_page_count(io.BytesIO(pdf_bytes))
            except Exception:
                pages = 1

            # Phase 29: index into RAG too, same as an uploaded document,
            # so a later "what did that report say about X" can actually
            # find it. Best-effort: a generated document is still fully
            # usable (viewable/downloadable from the Documents page) even
            # if indexing fails or the embeddings budget is exhausted --
            # this only affects whether it's *searchable*, not whether it
            # exists.
            chunk_count = 0
            try:
                require_budget(
                    upload_rate_limiter_minute, upload_rate_limiter_daily,
                    str(user_id) if user_id is not None else "unknown",
                    minute_detail="Too many documents generated in a short time.",
                    daily_detail="Today's document generation limit has been reached.",
                )
                steps.append("Indexing for search…")
                chunks = chunk_text(content)
                if chunks:
                    embeddings = create_embeddings(chunks)
                    store_chunks(chunks, embeddings, filename, user_id=user_id, document_id=document.id)
                    chunk_count = len(chunks)
            except Exception as e:
                agent_logger.warning(f"[DocumentAgent] indexing skipped for doc {document.id}: {e}")

            document.status = "processed"
            document.pages = pages
            document.chunk_count = chunk_count
            db.commit()
        finally:
            db.close()

        agent_logger.info(f"[DocumentAgent] generated {filename!r} for user {user_id} ({len(pdf_bytes)} bytes, {pages} pages)")

        return AgentResult(
            answer=(
                f"I've created **{title}** as a PDF ({pages} page{'s' if pages != 1 else ''}) "
                f"— you'll find it in your Documents page, ready to preview or download."
            ),
            agent_name=self.name,
            steps=steps,
            confidence=90,
            metadata={"document_id": document.id, "filename": filename, "pages": pages},
        )