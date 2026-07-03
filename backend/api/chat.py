"""
backend/api/chat.py

ISSUE 3: Added POST /chat/upload-context endpoint for in-chat file/image uploads.
ISSUE 1: Chat stream now passes conversation_id to orchestrator for history retrieval.
All existing endpoints preserved.
"""

import asyncio
import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.agent import process_query
from backend.agents.orchestrator import route_and_stream, ALL_AGENTS
from backend.core.memory_service import add_message
from backend.core.rate_limit import chat_rate_limiter_minute, chat_rate_limiter_daily, require_budget
from backend.core.request_context import get_current_user_id
from backend.database.db import SessionLocal
from backend.database.models import Conversation, ConversationMessage, AgentCallLog

router = APIRouter()

# ── In-process cancellation registry ─────────────────────────────────────────
_cancel_events: dict[str, asyncio.Event] = {}


def utcnow():
    return datetime.now(timezone.utc)


# ── Phase 8 helper ────────────────────────────────────────────────────────────

def _upsert_conversation(conv_id: Optional[int], user_msg: str, assistant_msg: str) -> int:
    db = SessionLocal()
    try:
        user_id = get_current_user_id()
        conv = None
        if conv_id:
            conv = db.query(Conversation).filter(
                Conversation.id == conv_id, Conversation.user_id == user_id
            ).first()

        if not conv:
            title = user_msg[:60] + ("…" if len(user_msg) > 60 else "")
            conv = Conversation(
                title=title,
                created_at=utcnow(),
                updated_at=utcnow(),
                message_count=0,
                user_id=user_id,
            )
            db.add(conv)
            db.flush()

        db.add(ConversationMessage(
            conversation_id=conv.id,
            role="user",
            content=user_msg,
            created_at=utcnow(),
        ))
        db.add(ConversationMessage(
            conversation_id=conv.id,
            role="assistant",
            content=assistant_msg,
            created_at=utcnow(),
        ))

        conv.message_count = (conv.message_count or 0) + 2
        conv.updated_at = utcnow()
        db.commit()
        return conv.id
    finally:
        db.close()


# ── GET /chat — non-streaming (unchanged signature) ──────────────────────────

@router.get("/chat")
def chat(
    message: str | None = None,
    question: str | None = None,
    conv_id: Optional[int] = None,
):
    user_message = message or question
    if not user_message:
        raise HTTPException(status_code=422, detail="message is required")

    # Phase 29: this is a separate entry point from /chat/stream but ends
    # up calling the exact same shared LLM budget via process_query() ->
    # route_and_run() -- needs the same protection, not a second
    # unguarded door into the same resource.
    user_id = get_current_user_id()
    rate_key = str(user_id) if user_id is not None else "unknown"
    require_budget(
        chat_rate_limiter_minute, chat_rate_limiter_daily, rate_key,
        minute_detail="You're sending messages faster than Athena can keep up — please slow down for a moment.",
        daily_detail="You've hit today's message limit for this shared deployment. It resets in 24 hours.",
    )

    try:
        answer, sources = process_query(user_message)
        new_conv_id = _upsert_conversation(conv_id, user_message, answer)
        return {
            "reply": answer,
            "sources": sources or None,
            "conversationId": new_conv_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /agents — list available agents ──────────────────────────────────────

@router.get("/agents")
def list_agents():
    return {
        "agents": [
            {"name": a.name, "description": a.description}
            for a in ALL_AGENTS
        ]
    }


# ── ISSUE 3: In-chat file/image upload ───────────────────────────────────────

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp",
    "text/plain", "text/markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

MAX_CHAT_UPLOAD_MB = 10


@router.post("/chat/upload-context")
async def chat_upload_context(file: UploadFile = File(...)):
    """
    ISSUE 3: Upload a file directly from the chat composer.

    For PDFs: extracts text and returns it as context the frontend can
    append to the next message, and also indexes it into the RAG pipeline.
    For images: returns a base64 data URI the frontend can preview.
    For text: returns raw text content as context.
    """
    max_bytes = MAX_CHAT_UPLOAD_MB * 1024 * 1024
    file_bytes = await file.read()

    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_CHAT_UPLOAD_MB} MB chat upload limit."
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    filename = file.filename or "upload"

    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Supported: PDF, images, text."
        )

    result: dict = {"filename": filename, "content_type": content_type}

    # ── PDF: extract text + index into RAG ───────────────────────────────────
    if content_type == "application/pdf":
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for page in reader.pages[:50]:  # cap at 50 pages for chat context
                pages_text.append(page.extract_text() or "")
            extracted = "\n\n".join(pages_text)
            result["text_context"] = extracted[:8000]  # cap context size
            result["page_count"] = len(reader.pages)

            # Also index into RAG pipeline so it can be retrieved later
            try:
                from backend.rag.chunker import chunk_text
                from backend.rag.embedder import create_embeddings
                from backend.rag.vector_store import store_chunks
                from backend.core.request_context import get_current_user_id
                from backend.core.rate_limit import (
                    upload_rate_limiter_minute, upload_rate_limiter_daily, require_budget,
                )
                user_id = get_current_user_id()
                chunks = chunk_text(extracted)
                if chunks:
                    # Phase 29: this is a separate embedding call site from
                    # api/upload.py (a PDF attached directly in the chat
                    # composer, not through the Documents page) -- shares
                    # the same HF embeddings budget, so it needed the same
                    # protection. A budget rejection here just means
                    # "don't index this one," not a hard failure -- the
                    # extracted text is still usable as inline context for
                    # this one message (see result["text_context"] above),
                    # so this fails soft into result["indexed"] = False
                    # like every other failure mode in this except block.
                    require_budget(
                        upload_rate_limiter_minute, upload_rate_limiter_daily,
                        str(user_id) if user_id is not None else "unknown",
                        minute_detail="Too many document uploads in a short time.",
                        daily_detail="Today's document upload limit has been reached.",
                    )
                    embeddings = create_embeddings(chunks)
                    store_chunks(chunks, embeddings, filename, user_id=user_id)
                    result["indexed"] = True
            except Exception:
                result["indexed"] = False

        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

    # ── Images: return base64 preview ─────────────────────────────────────────
    elif content_type.startswith("image/"):
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        result["image_data_uri"] = f"data:{content_type};base64,{b64}"
        result["size_bytes"] = len(file_bytes)

    # ── Plain text / markdown ─────────────────────────────────────────────────
    elif content_type in ("text/plain", "text/markdown"):
        try:
            text = file_bytes.decode("utf-8", errors="replace")
            result["text_context"] = text[:8000]
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read file: {e}")

    # ── Phase 16: Word documents ──────────────────────────────────────────────
    elif content_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ) or filename.lower().endswith((".docx", ".doc")):
        try:
            import mammoth  # type: ignore
            output = mammoth.extract_raw_text(io.BytesIO(file_bytes))
            result["text_context"] = output.value[:8000]
            result["filename"] = filename
        except ImportError:
            # Fallback: return raw bytes info
            result["text_context"] = f"[Word document: {filename} — install mammoth to extract text]"
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read Word doc: {e}")

    # ── Phase 16: CSV files ───────────────────────────────────────────────────
    elif content_type in ("text/csv", "application/csv") or filename.lower().endswith(".csv"):
        try:
            import csv, io as _io
            text = file_bytes.decode("utf-8", errors="replace")
            reader = csv.reader(_io.StringIO(text))
            rows = list(reader)
            # Show header + first 50 rows
            preview_rows = rows[:51]
            preview = "\n".join([",".join(r) for r in preview_rows])
            if len(rows) > 51:
                preview += f"\n... ({len(rows) - 51} more rows)"
            result["text_context"] = preview[:8000]
            result["filename"] = filename
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read CSV: {e}")

    return result


# ── Phase 13: Streaming via Orchestrator ──────────────────────────────────────

class StreamRequest(BaseModel):
    message: str
    conv_id: Optional[int] = None
    # Phase 28 addition: base64 data URI of an image attached in the
    # composer (e.g. "data:image/png;base64,..."). Previously the actual
    # image bytes never left the browser -- only a text placeholder like
    # "Please analyze this image: photo.jpg" reached the backend, so
    # Athena had no visual data to work with at all. See core/llm.py's
    # ask_llm_with_image_stream() for how this gets used.
    image_data_uri: Optional[str] = None



# ── Phase 16: Background task helpers ────────────────────────────────────────

def _run_auto_title(new_conv_id: int, old_conv_id, user_msg: str, assistant_msg: str):
    """Auto-title a conversation after its first exchange."""
    try:
        # Only auto-title on first message (when conv_id was None = new conv)
        if old_conv_id:
            return
        from backend.core.auto_title import auto_title_conversation
        auto_title_conversation(new_conv_id, user_msg, assistant_msg)
    except Exception as e:
        pass  # Non-critical


def _run_memory_extraction(user_msg: str, assistant_msg: str, user_id):
    """Extract semantic user facts from this exchange."""
    try:
        if not user_id:
            return
        from backend.core.memory_intelligence import extract_and_store_facts
        extract_and_store_facts(user_msg, assistant_msg, user_id)
    except Exception:
        pass  # Non-critical


def _log_agent_call(user_id, agent_name: str, query: str, conv_id: int):
    """Log agent invocation for analytics."""
    try:
        if not user_id:
            return
        db = SessionLocal()
        try:
            db.add(AgentCallLog(
                user_id=user_id,
                agent_name=agent_name or "athena",
                query=query[:500] if query else None,
                success=True,
                conv_id=conv_id,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # Non-critical



async def _stream_generator(message: str, conv_id: Optional[int], stream_id: str, image_data_uri: Optional[str] = None):
    """
    SSE generator — delegates to the multi-agent orchestrator.

    Sends:
      data: {"type":"status","text":"...","agent":"agent_name|null"}
      data: {"type":"token","text":"..."}
      data: {"type":"done","conversationId":N,"sources":[...],"agentName":"...","steps":[...]}
      data: {"type":"error","text":"..."}
    """
    cancel_event = _cancel_events.get(stream_id)
    full_response = ""
    sources = []
    agent_name = "athena"
    steps = []

    def send(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    try:
        event_queue: asyncio.Queue = asyncio.Queue()

        # ── Phase 16 fix: context propagation ─────────────────────────────────
        # loop.run_in_executor() does NOT automatically copy the current
        # contextvars.Context into the worker thread (unlike asyncio.to_thread,
        # which does). This silently broke get_current_user_id() everywhere
        # inside the agent pipeline that runs via this executor — including
        # the reminder agent's timezone lookup, which fell back to UTC for
        # every single user regardless of their actual saved timezone,
        # producing wildly wrong "due in X hours" calculations.
        #
        # Fix: explicitly capture contextvars.copy_context() on the request
        # thread (where the auth dependency already set the user id) and run
        # the orchestrator inside that captured context on the worker thread.
        import contextvars
        captured_context = contextvars.copy_context()

        def _run_orchestrator():
            def _inner():
                try:
                    for event in route_and_stream(message, conv_id=conv_id, image_data_uri=image_data_uri):
                        event_queue.put_nowait(event)
                except Exception as exc:
                    event_queue.put_nowait({"type": "error", "text": str(exc)})
                finally:
                    event_queue.put_nowait(None)  # sentinel
            captured_context.run(_inner)

        loop = asyncio.get_event_loop()
        orchestrator_task = loop.run_in_executor(None, _run_orchestrator)

        while True:
            if cancel_event and cancel_event.is_set():
                break

            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            if event is None:
                break

            etype = event.get("type")

            if etype == "status":
                yield send({
                    "type": "status",
                    "text": event.get("text", ""),
                    "agent": event.get("agent"),
                })

            elif etype == "token":
                chunk = event.get("text", "")
                full_response += chunk
                yield send({"type": "token", "text": chunk})

            elif etype == "done":
                result = event.get("result")
                if result:
                    if not full_response:
                        full_response = result.answer
                    sources = result.sources
                    agent_name = result.agent_name
                    steps = result.steps

            elif etype == "error":
                yield send({"type": "error", "text": event.get("text", "Unknown error")})
                return

        await orchestrator_task

        if full_response:
            add_message("user", message)
            add_message("assistant", full_response)
            new_conv_id = await asyncio.to_thread(
                _upsert_conversation, conv_id, message, full_response
            )

            # ── Phase 16: Background intelligence tasks ───────────────────
            uid = get_current_user_id()

            # 1. Auto-title: rename "New Conversation" after first exchange
            asyncio.create_task(asyncio.to_thread(
                _run_auto_title, new_conv_id, conv_id, message, full_response
            ))

            # 2. Semantic memory: extract user facts from this exchange
            asyncio.create_task(asyncio.to_thread(
                _run_memory_extraction, message, full_response, uid
            ))

            # 3. Agent call logging
            asyncio.create_task(asyncio.to_thread(
                _log_agent_call, uid, agent_name, message, new_conv_id
            ))

        else:
            new_conv_id = conv_id or 0

        yield send({
            "type": "done",
            "conversationId": new_conv_id,
            "sources": sources,
            "agentName": agent_name,
            "steps": steps,
        })

    except Exception as e:
        yield send({"type": "error", "text": str(e)})
    finally:
        _cancel_events.pop(stream_id, None)


@router.post("/chat/stream")
async def chat_stream(payload: StreamRequest, request: Request):
    # Phase 29: protects the shared, free-tier LLM/search budget
    # (GROQ_API_KEY, GEMINI_API_KEY, TAVILY_API_KEY are single keys used by
    # every user of this deployment) from one user -- a runaway script, a
    # future automation bug, or just spamming Enter -- exhausting it for
    # everyone else. Both windows are generous for real human use; this
    # exists to catch bursts/loops, not to throttle normal chatting.
    user_id = get_current_user_id()
    rate_key = str(user_id) if user_id is not None else (request.client.host if request.client else "unknown")
    require_budget(
        chat_rate_limiter_minute, chat_rate_limiter_daily, rate_key,
        minute_detail="You're sending messages faster than Athena can keep up — please slow down for a moment.",
        daily_detail="You've hit today's message limit for this shared deployment. It resets in 24 hours.",
    )

    # Phase 28: /chat/upload-context already caps images at
    # MAX_CHAT_UPLOAD_MB, but that only constrains the normal
    # composer-attach flow. Nothing stopped a request built by hand (or a
    # future frontend bug) from sending an arbitrarily large
    # image_data_uri straight into this endpoint's JSON body. Reject
    # early with the same cap rather than accepting anything.
    if payload.image_data_uri and len(payload.image_data_uri) > MAX_CHAT_UPLOAD_MB * 1024 * 1024 * 2:
        raise HTTPException(
            status_code=413,
            detail=f"Image is too large — please attach one under {MAX_CHAT_UPLOAD_MB} MB.",
        )

    stream_id = request.headers.get("X-Stream-Id") or str(uuid.uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[stream_id] = cancel_event

    # Phase 34 fix: see request_context.set_current_request_timezone()'s
    # docstring for the full reasoning -- closes the "reminder created
    # in UTC because the fire-and-forget timezone sync hadn't landed
    # yet" race by having the browser send its current timezone on the
    # request that actually matters, instead of depending on timing.
    from backend.core.request_context import set_current_request_timezone
    set_current_request_timezone(request.headers.get("X-Timezone") or None)

    return StreamingResponse(
        _stream_generator(payload.message, payload.conv_id, stream_id, payload.image_data_uri),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Stream-Id": stream_id,
        },
    )


class CancelRequest(BaseModel):
    stream_id: str


@router.post("/chat/cancel")
async def chat_cancel(payload: CancelRequest):
    event = _cancel_events.get(payload.stream_id)
    if event:
        event.set()
        return {"ok": True, "cancelled": True}
    return {"ok": True, "cancelled": False}