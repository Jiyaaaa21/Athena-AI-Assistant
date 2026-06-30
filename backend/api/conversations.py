"""
Phase 8: Conversation Management API

Endpoints:
  GET    /conversations                    — list all conversations
  POST   /conversations                    — create new conversation
  GET    /conversations/{id}               — get single conversation with messages
  PUT    /conversations/{id}               — rename / update metadata
  DELETE /conversations/{id}               — delete conversation + messages
  PATCH  /conversations/{id}/star          — toggle star
  PATCH  /conversations/{id}/pin           — toggle pin
  POST   /conversations/{id}/messages      — append a message
  GET    /conversations/search             — search by title or message content

Folder endpoints:
  GET    /folders                          — list folders
  POST   /folders                          — create folder
  PUT    /folders/{id}                     — rename folder
  DELETE /folders/{id}                     — delete folder
  POST   /conversations/{id}/move          — move conversation to folder

Export endpoints:
  GET    /conversations/{id}/export/pdf    — export chat as PDF
  GET    /notes/export                     — export notes (pdf | txt | md)
  GET    /memories/export                  — export memories (pdf | txt | md)
  GET    /documents/{id}/export/summary    — export document summary as PDF
"""

from __future__ import annotations

import io
import textwrap
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.database.db import SessionLocal
from backend.database.models import (
    Conversation, ConversationMessage, Folder,
    Note, Message as GlobalMessage, Document,
)
from backend.core.request_context import get_current_user_id

router = APIRouter()
# Public router — no JWT required (token IS the auth)
public_router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────

def utcnow():
    return datetime.now(timezone.utc)


def _serialize_conv(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title or "New Conversation",
        "createdAt": c.created_at.isoformat() if c.created_at else None,
        "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
        "messageCount": c.message_count or 0,
        "starred": bool(c.starred),
        "pinned": bool(c.pinned),
        "folderId": c.folder_id,
    }


def _serialize_msg(m: ConversationMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
    }


def _serialize_folder(f: Folder) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "createdAt": f.created_at.isoformat() if f.created_at else None,
    }


# ── PDF generation (pure stdlib + fpdf2 fallback to simple text PDF) ─────────

def _build_pdf_bytes(title: str, sections: list[tuple[str, str]]) -> bytes:
    """
    Build a polished, Claude-style PDF: real heading hierarchy, styled
    bullet/numbered lists, a terracotta accent rule under the title, and
    section labels rendered as small caps with a divider — instead of the
    old approach which dumped raw markdown (**bold**, ### headers, * bullets)
    as literal plain-text characters into the page.

    Falls back to ReportLab, then a hand-crafted minimal PDF, if fpdf2
    isn't available or raises something unrecoverable.
    """
    # ── Option 1: fpdf2 — styled, markdown-aware renderer ─────────────────────
    try:
        from fpdf import FPDF  # type: ignore
        import re as _re

        _INK     = (38, 38, 38)
        _MUTED   = (120, 116, 110)
        _ACCENT  = (191, 87, 0)     # terracotta — matches Athena's brand accent
        _RULE    = (225, 220, 212)
        _MARGIN  = 18
        _PAGE_W  = 210  # A4 width in mm

        class _StyledPDF(FPDF):
            def footer(self):
                self.set_y(-15)
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*_MUTED)
                self.cell(0, 10, f"Page {self.page_no()}", align="C")

        _UNICODE_REPLACEMENTS = {
            "\u2014": "-", "\u2013": "-", "\u2192": "->", "\u2713": "v",
            "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
            "\u2026": "...",
            # Bullet char is handled separately (drawn as a dot glyph), so
            # it's intentionally not replaced here.
        }

        def _sanitize(text: str) -> str:
            for uni_char, repl in _UNICODE_REPLACEMENTS.items():
                text = text.replace(uni_char, repl)
            return text.encode("latin-1", errors="replace").decode("latin-1")

        def _wrap_long_tokens(text: str, max_token_len: int = 70) -> str:
            out = []
            for word in text.split(" "):
                if len(word) > max_token_len:
                    out.append(" ".join(
                        word[i:i + max_token_len]
                        for i in range(0, len(word), max_token_len)
                    ))
                else:
                    out.append(word)
            return " ".join(out)

        def _safe_multicell(pdf_obj, w, h, text, align="L"):
            """
            multi_cell wrapper. CRITICAL: must pass new_x="LMARGIN",
            new_y="NEXT" -- fpdf2's default (new_x=XPos.RIGHT) leaves the
            cursor at the page's right edge after writing, so the very
            next multi_cell call computes zero available width and raises
            'Not enough horizontal space to render a single character' on
            perfectly ordinary text. This was the actual root cause of
            exported PDFs stopping after one line of body content.
            """
            safe_text = _wrap_long_tokens(_sanitize(text or " "))
            try:
                try:
                    pdf_obj.multi_cell(w, h, safe_text, new_x="LMARGIN", new_y="NEXT", align=align)
                except TypeError:
                    pdf_obj.multi_cell(w, h, safe_text)
                    pdf_obj.set_x(pdf_obj.l_margin)
            except Exception:
                chunk_size = 60
                for i in range(0, len(safe_text), chunk_size):
                    try:
                        try:
                            pdf_obj.multi_cell(w, h, safe_text[i:i + chunk_size], new_x="LMARGIN", new_y="NEXT", align=align)
                        except TypeError:
                            pdf_obj.multi_cell(w, h, safe_text[i:i + chunk_size])
                            pdf_obj.set_x(pdf_obj.l_margin)
                    except Exception:
                        pass

        def _render_inline(pdf_obj, text, w=0, h=5.2, align="L"):
            """
            Render a body line with **bold**/*italic* spans interpreted via
            fpdf2's markdown=True, instead of printing the literal asterisks.
            """
            safe_text = _wrap_long_tokens(_sanitize(text))
            try:
                pdf_obj.multi_cell(w, h, safe_text, new_x="LMARGIN", new_y="NEXT", align=align, markdown=True)
            except Exception:
                _safe_multicell(pdf_obj, w, h, safe_text, align=align)

        def _classify_line(line: str):
            """
            Classify a single source line as a markdown construct so it can
            be rendered with proper visual styling rather than as raw text.
            Returns (kind, content).
            """
            stripped = line.strip()
            if not stripped:
                return ("blank", "")
            if _re.match(r"^=+$", stripped):
                return ("hr_double", "")
            if _re.match(r"^-{3,}$", stripped):
                return ("hr", "")
            if stripped.startswith("### "):
                return ("h3", stripped[4:])
            if stripped.startswith("## "):
                return ("h2", stripped[3:])
            if stripped.startswith("# "):
                return ("h1", stripped[2:])
            # A standalone bold line is almost always meant as a heading
            # (a very common LLM markdown pattern for document titles).
            if _re.match(r"^\*\*(.+)\*\*$", stripped) and len(stripped) < 90:
                return ("h2", stripped[2:-2])
            if stripped.startswith(("* ", "- ", "\u2022 ")):
                return ("bullet", stripped[2:])
            m = _re.match(r"^(\d+)\.\s+(.*)", stripped)
            if m:
                return ("numbered", (m.group(1), m.group(2)))
            return ("body", line)

        pdf = _StyledPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=22)
        pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
        pdf.add_page()

        # ── Document title ──────────────────────────────────────────────────
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*_INK)
        _safe_multicell(pdf, 0, 9, title)
        pdf.set_draw_color(*_ACCENT)
        pdf.set_line_width(0.8)
        pdf.line(_MARGIN, pdf.get_y() + 1, _MARGIN + 24, pdf.get_y() + 1)
        pdf.ln(8)

        # ── Sections ─────────────────────────────────────────────────────────
        for heading, body in sections:
            if heading:
                is_user = heading.lower().startswith("you")
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(*(_MUTED if is_user else _ACCENT))
                _safe_multicell(pdf, 0, 5, heading.upper())
                pdf.set_draw_color(*_RULE)
                pdf.set_line_width(0.2)
                pdf.line(_MARGIN, pdf.get_y() + 0.5, _PAGE_W - _MARGIN, pdf.get_y() + 0.5)
                pdf.ln(3)

            pdf.set_text_color(*_INK)
            for line in (body or "").splitlines():
                kind, content = _classify_line(line)

                if kind == "blank":
                    pdf.ln(2)
                elif kind == "hr_double":
                    pdf.ln(1)
                elif kind == "hr":
                    pdf.set_draw_color(*_RULE)
                    pdf.line(_MARGIN, pdf.get_y(), _PAGE_W - _MARGIN, pdf.get_y())
                    pdf.ln(3)
                elif kind == "h1":
                    pdf.ln(2)
                    pdf.set_font("Helvetica", "B", 15)
                    pdf.set_text_color(*_INK)
                    _safe_multicell(pdf, 0, 7, content)
                    pdf.ln(1.5)
                    pdf.set_font("Helvetica", "", 10)
                elif kind == "h2":
                    pdf.ln(2.5)
                    pdf.set_font("Helvetica", "B", 12.5)
                    pdf.set_text_color(*_INK)
                    _safe_multicell(pdf, 0, 6.5, content)
                    pdf.ln(1)
                    pdf.set_font("Helvetica", "", 10)
                elif kind == "h3":
                    pdf.ln(2)
                    pdf.set_font("Helvetica", "B", 11)
                    pdf.set_text_color(*_INK)
                    _safe_multicell(pdf, 0, 6, content)
                    pdf.ln(0.5)
                    pdf.set_font("Helvetica", "", 10)
                elif kind == "bullet":
                    pdf.set_font("Helvetica", "", 10)
                    pdf.set_text_color(*_INK)
                    bullet_x = pdf.get_x()
                    pdf.set_x(bullet_x + 4)
                    pdf.set_fill_color(*_ACCENT)
                    pdf.ellipse(bullet_x + 1.5, pdf.get_y() + 2.1, 1.3, 1.3, style="F")
                    _render_inline(pdf, content, w=0)
                    pdf.set_x(_MARGIN)
                elif kind == "numbered":
                    num, txt = content
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.set_text_color(*_ACCENT)
                    pdf.cell(7, 5.2, f"{num}.", new_x="RIGHT", new_y="TOP")
                    pdf.set_font("Helvetica", "", 10)
                    pdf.set_text_color(*_INK)
                    _render_inline(pdf, txt, w=0)
                    pdf.set_x(_MARGIN)
                else:  # body
                    pdf.set_font("Helvetica", "", 10)
                    pdf.set_text_color(*_INK)
                    _render_inline(pdf, content)

            pdf.ln(5)

        result = pdf.output()
        return bytes(result) if isinstance(result, (bytearray, memoryview)) else result

    except ImportError:
        pass
    except Exception:
        # fpdf2 raised something unrecoverable — fall through to ReportLab
        # rather than returning a 500.
        pass

    # ── Option 2: ReportLab ───────────────────────────────────────────────────
    try:
        from reportlab.pdfgen import canvas as rl_canvas  # type: ignore
        from reportlab.lib.pagesizes import letter
        import io as _io

        buf = _io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=letter)
        width, height = letter
        y = height - 60
        left_margin = 40
        right_margin = width - 40
        usable_width = right_margin - left_margin

        def safe_str(s: str) -> str:
            """Strip non-latin chars so ReportLab's built-in fonts don't crash."""
            return s.encode("latin-1", errors="replace").decode("latin-1")

        def wrap_line(text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
            """
            Word-wrap a single logical line into multiple physical lines that
            fit within max_width. Fixes the Phase 16 bug where drawString()
            silently discarded everything past ~110 characters because it
            has no built-in wrapping at all — long paragraphs were truncated
            to a single short fragment in the exported PDF.
            """
            if not text:
                return [""]
            words = text.split(" ")
            wrapped: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if c.stringWidth(candidate, font_name, font_size) <= max_width:
                    current = candidate
                else:
                    if current:
                        wrapped.append(current)
                    # Handle a single word wider than the line (long token)
                    if c.stringWidth(word, font_name, font_size) > max_width:
                        chunk = ""
                        for ch in word:
                            if c.stringWidth(chunk + ch, font_name, font_size) <= max_width:
                                chunk += ch
                            else:
                                wrapped.append(chunk)
                                chunk = ch
                        current = chunk
                    else:
                        current = word
            if current:
                wrapped.append(current)
            return wrapped or [""]

        def draw_wrapped(text: str, font_name: str, font_size: int):
            nonlocal y
            c.setFont(font_name, font_size)
            line_height = font_size + 4
            for physical_line in wrap_line(safe_str(text), font_name, font_size, usable_width):
                if y < 80:
                    c.showPage()
                    c.setFont(font_name, font_size)
                    y = height - 60
                c.drawString(left_margin, y, physical_line)
                y -= line_height

        draw_wrapped(title, "Helvetica-Bold", 16)
        y -= 14
        c.setLineWidth(0.5)
        c.line(left_margin, y, right_margin, y)
        y -= 20

        for heading, body in sections:
            if heading:
                draw_wrapped(heading, "Helvetica-Bold", 11)
            for line in (body or "").splitlines():
                draw_wrapped(line if line.strip() else " ", "Helvetica", 10)
            y -= 6

        c.save()
        return buf.getvalue()

    except ImportError:
        pass

    # ── Option 3: Correct minimal hand-crafted PDF ────────────────────────────
    # Build plain text content first
    lines: list[str] = [title, "=" * min(len(title), 60), ""]
    for heading, body in sections:
        if heading:
            lines.append(f"[ {heading} ]")
        lines.extend((body or "").splitlines())
        lines.append("")

    # Encode as PDF string tokens (escape parens and backslashes)
    def pdf_str(s: str) -> str:
        s = s[:120]  # cap line length
        return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"

    # Build content stream
    stream_lines = ["BT", "/F1 10 Tf", "40 750 Td", "14 TL"]
    for line in lines:
        stream_lines.append(f"{pdf_str(line)} Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
    stream_len = len(stream)

    # Build PDF objects
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    obj4 = f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode() + stream + b"\nendstream\nendobj\n"
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n"

    header = b"%PDF-1.4\n"
    offsets = []
    body_bytes = b""
    for obj in [obj1, obj2, obj3, obj4, obj5]:
        offsets.append(len(header) + len(body_bytes))
        body_bytes += obj

    # Cross-reference table
    xref_offset = len(header) + len(body_bytes)
    xref = b"xref\n0 6\n"
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()

    return header + body_bytes + xref + trailer


def _pdf_response(filename: str, title: str, sections: list[tuple[str, str]]) -> StreamingResponse:
    pdf_bytes = _build_pdf_bytes(title, sections)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Download tokens (solves auth for browser file downloads) ─────────────────
# Browser navigation (window.open / <a href>) can't send Authorization headers.
# Solution: frontend requests a short-lived one-use token, then navigates to
# the token URL. Backend validates token (no JWT needed on that request).

_DOWNLOAD_TOKENS: dict[str, dict] = {}  # token → {conv_id, user_id, expires}
_TOKEN_TTL = 120  # seconds


def _purge_expired_tokens():
    now = time.time()
    expired = [k for k, v in _DOWNLOAD_TOKENS.items() if v["expires"] < now]
    for k in expired:
        del _DOWNLOAD_TOKENS[k]


@router.post("/conversations/{conv_id}/export/token")
def create_export_token(conv_id: int):
    """Issue a short-lived one-use download token for the PDF export."""
    _purge_expired_tokens()
    uid = get_current_user_id()

    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == uid
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    finally:
        db.close()

    token = secrets.token_urlsafe(32)
    _DOWNLOAD_TOKENS[token] = {
        "conv_id": conv_id,
        "user_id": uid,
        "expires": time.time() + _TOKEN_TTL,
    }
    return {"token": token, "expires_in": _TOKEN_TTL}


@public_router.get("/conversations/download/{token}")
def download_conversation_pdf(token: str):
    """
    Token-authenticated PDF download endpoint.
    No JWT required — the token IS the auth.
    Called via direct browser navigation after getting a token.
    """
    _purge_expired_tokens()
    entry = _DOWNLOAD_TOKENS.get(token)
    if not entry or entry["expires"] < time.time():
        _DOWNLOAD_TOKENS.pop(token, None)
        raise HTTPException(status_code=401, detail="Invalid or expired download token")
    # Remove after successful validation (one-use, but keep until response sent)
    _DOWNLOAD_TOKENS.pop(token, None)

    conv_id = entry["conv_id"]
    user_id = entry["user_id"]

    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == user_id
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        msgs = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv_id
        ).order_by(ConversationMessage.id).all()

        sections: list[tuple[str, str]] = []
        meta = (
            f"Created: {conv.created_at.strftime('%Y-%m-%d %H:%M UTC') if conv.created_at else 'Unknown'}\n"
            f"Messages: {conv.message_count or len(msgs)}"
        )
        sections.append(("", meta))
        for m in msgs:
            ts = m.created_at.strftime("%H:%M") if m.created_at else ""
            label = ("You" if m.role == "user" else "Athena") + (f"  [{ts}]" if ts else "")
            sections.append((label, m.content or ""))

        safe_title = (conv.title or "conversation").replace("/", "-").replace("\\", "-")
        try:
            return _pdf_response(f"{safe_title}.pdf", conv.title or "Conversation", sections)
        except Exception as pdf_err:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {pdf_err}")
    finally:
        db.close()



# ── Conversation CRUD ─────────────────────────────────────────────────────────

class ConvCreate(BaseModel):
    title: str = "New Conversation"


class ConvUpdate(BaseModel):
    title: Optional[str] = None
    starred: Optional[bool] = None
    pinned: Optional[bool] = None
    folder_id: Optional[int] = None


class MsgAppend(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class FolderCreate(BaseModel):
    name: str


class FolderUpdate(BaseModel):
    name: str


class MoveConv(BaseModel):
    folder_id: Optional[int] = None   # None = remove from folder


# ── Routes: Conversations ─────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations():
    db = SessionLocal()
    try:
        convs = db.query(Conversation).filter(
            Conversation.user_id == get_current_user_id()
        ).order_by(
            Conversation.pinned.desc(),
            Conversation.updated_at.desc()
        ).all()
        return [_serialize_conv(c) for c in convs]
    finally:
        db.close()


@router.post("/conversations")
def create_conversation(payload: ConvCreate):
    db = SessionLocal()
    try:
        conv = Conversation(
            title=payload.title,
            created_at=utcnow(),
            updated_at=utcnow(),
            user_id=get_current_user_id(),
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return _serialize_conv(conv)
    finally:
        db.close()


@router.get("/conversations/search")
def search_conversations(q: str = Query(..., min_length=1)):
    """Search conversations by title or message content."""
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        q_lower = f"%{q.lower()}%"
        # title matches
        by_title = db.query(Conversation).filter(
            Conversation.title.ilike(q_lower), Conversation.user_id == uid
        ).all()
        title_ids = {c.id for c in by_title}

        # content matches -- joined through Conversation to enforce
        # ownership (ConversationMessage has no user_id column itself).
        matching_msgs = (
            db.query(ConversationMessage)
            .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
            .filter(ConversationMessage.content.ilike(q_lower), Conversation.user_id == uid)
            .all()
        )
        content_conv_ids = {m.conversation_id for m in matching_msgs} - title_ids

        by_content = db.query(Conversation).filter(
            Conversation.id.in_(content_conv_ids), Conversation.user_id == uid
        ).all() if content_conv_ids else []

        all_convs = {c.id: c for c in by_title + by_content}
        return [_serialize_conv(c) for c in all_convs.values()]
    finally:
        db.close()


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: int):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msgs = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv_id
        ).order_by(ConversationMessage.id).all()
        return {
            **_serialize_conv(conv),
            "messages": [_serialize_msg(m) for m in msgs],
        }
    finally:
        db.close()


@router.put("/conversations/{conv_id}")
def update_conversation(conv_id: int, payload: ConvUpdate):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if payload.title is not None:
            conv.title = payload.title
        if payload.starred is not None:
            conv.starred = payload.starred
        if payload.pinned is not None:
            conv.pinned = payload.pinned
        if payload.folder_id is not None:
            conv.folder_id = payload.folder_id
        conv.updated_at = utcnow()
        db.commit()
        db.refresh(conv)
        return _serialize_conv(conv)
    finally:
        db.close()


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv_id
        ).delete()
        db.delete(conv)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.patch("/conversations/{conv_id}/star")
def toggle_star(conv_id: int):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv.starred = not conv.starred
        conv.updated_at = utcnow()
        db.commit()
        db.refresh(conv)
        return _serialize_conv(conv)
    finally:
        db.close()


@router.patch("/conversations/{conv_id}/pin")
def toggle_pin(conv_id: int):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv.pinned = not conv.pinned
        conv.updated_at = utcnow()
        db.commit()
        db.refresh(conv)
        return _serialize_conv(conv)
    finally:
        db.close()


@router.post("/conversations/{conv_id}/messages")
def append_message(conv_id: int, payload: MsgAppend):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msg = ConversationMessage(
            conversation_id=conv_id,
            role=payload.role,
            content=payload.content,
            created_at=utcnow(),
        )
        db.add(msg)
        conv.message_count = (conv.message_count or 0) + 1
        conv.updated_at = utcnow()
        # Auto-title from first user message
        if payload.role == "user" and (conv.title == "New Conversation" or not conv.title):
            conv.title = payload.content[:60] + ("…" if len(payload.content) > 60 else "")
        db.commit()
        db.refresh(msg)
        return _serialize_msg(msg)
    finally:
        db.close()


@router.post("/conversations/{conv_id}/move")
def move_conversation(conv_id: int, payload: MoveConv):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv.folder_id = payload.folder_id
        conv.updated_at = utcnow()
        db.commit()
        db.refresh(conv)
        return _serialize_conv(conv)
    finally:
        db.close()


# ── Routes: Folders ───────────────────────────────────────────────────────────

@router.get("/folders")
def list_folders():
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        folders = db.query(Folder).filter(Folder.user_id == uid).order_by(Folder.name).all()
        # attach conversation counts
        result = []
        for f in folders:
            count = db.query(Conversation).filter(
                Conversation.folder_id == f.id, Conversation.user_id == uid
            ).count()
            d = _serialize_folder(f)
            d["conversationCount"] = count
            result.append(d)
        return result
    finally:
        db.close()


@router.post("/folders")
def create_folder(payload: FolderCreate):
    db = SessionLocal()
    try:
        folder = Folder(name=payload.name, created_at=utcnow(), user_id=get_current_user_id())
        db.add(folder)
        db.commit()
        db.refresh(folder)
        d = _serialize_folder(folder)
        d["conversationCount"] = 0
        return d
    finally:
        db.close()


@router.put("/folders/{folder_id}")
def rename_folder(folder_id: int, payload: FolderUpdate):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == uid).first()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        folder.name = payload.name
        db.commit()
        db.refresh(folder)
        d = _serialize_folder(folder)
        d["conversationCount"] = db.query(Conversation).filter(
            Conversation.folder_id == folder_id, Conversation.user_id == uid
        ).count()
        return d
    finally:
        db.close()


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == uid).first()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        # Unassign conversations from this folder
        db.query(Conversation).filter(
            Conversation.folder_id == folder_id, Conversation.user_id == uid
        ).update({"folder_id": None})
        db.delete(folder)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Routes: Export ────────────────────────────────────────────────────────────

@router.get("/conversations/{conv_id}/export/pdf")
def export_conversation_pdf(conv_id: int):
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == get_current_user_id()
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msgs = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv_id
        ).order_by(ConversationMessage.id).all()

        sections: list[tuple[str, str]] = []
        meta = (
            f"Created: {conv.created_at.strftime('%Y-%m-%d %H:%M UTC') if conv.created_at else 'Unknown'}\n"
            f"Messages: {conv.message_count or len(msgs)}"
        )
        sections.append(("", meta))

        for m in msgs:
            ts = m.created_at.strftime("%H:%M") if m.created_at else ""
            label = ("You" if m.role == "user" else "Athena") + (f"  [{ts}]" if ts else "")
            sections.append((label, m.content or ""))

        safe_title = (conv.title or "conversation").replace("/", "-").replace("\\", "-")
        try:
            return _pdf_response(f"{safe_title}.pdf", conv.title or "Conversation", sections)
        except Exception as pdf_err:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {pdf_err}")
    finally:
        db.close()


@router.get("/notes/export")
def export_notes(fmt: str = Query("pdf", pattern="^(pdf|txt|md)$")):
    db = SessionLocal()
    try:
        notes = db.query(Note).filter(
            Note.user_id == get_current_user_id()
        ).order_by(Note.id.desc()).all()
        if fmt == "pdf":
            sections = []
            for n in notes:
                heading = n.title or "Untitled"
                ts = n.created_at.strftime("%Y-%m-%d") if n.created_at else ""
                body = (n.content or "") + (f"\n\nCategory: {n.category}" if n.category else "")
                sections.append((f"{heading}  [{ts}]", body))
            return _pdf_response("athena-notes.pdf", "Athena Notes", sections)

        lines: list[str] = []
        for n in notes:
            ts = n.created_at.strftime("%Y-%m-%d") if n.created_at else ""
            if fmt == "md":
                lines.append(f"## {n.title or 'Untitled'}  *{ts}*")
                lines.append("")
                lines.append(n.content or "")
                if n.category:
                    lines.append(f"\n*Category: {n.category}*")
                lines.append("\n---\n")
            else:
                lines.append(f"[{ts}] {n.title or 'Untitled'}")
                lines.append(n.content or "")
                lines.append("")

        content = "\n".join(lines).encode("utf-8")
        media = "text/markdown" if fmt == "md" else "text/plain"
        ext = fmt
        return StreamingResponse(
            io.BytesIO(content),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="athena-notes.{ext}"'},
        )
    finally:
        db.close()


@router.get("/memories/export")
def export_memories(fmt: str = Query("pdf", pattern="^(pdf|txt|md)$")):
    db = SessionLocal()
    try:
        msgs = db.query(GlobalMessage).filter(
            GlobalMessage.user_id == get_current_user_id()
        ).order_by(GlobalMessage.id.desc()).all()
        if fmt == "pdf":
            sections = []
            for m in msgs:
                ts = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else ""
                label = ("You" if m.role == "user" else "Athena") + (f"  [{ts}]" if ts else "")
                sections.append((label, m.content or ""))
            return _pdf_response("athena-memories.pdf", "Athena Memories", sections)

        lines: list[str] = []
        for m in msgs:
            ts = m.created_at.isoformat() if m.created_at else ""
            role = "User" if m.role == "user" else "Athena"
            if fmt == "md":
                lines.append(f"**{role}** `{ts}`\n")
                lines.append(m.content or "")
                lines.append("\n---\n")
            else:
                lines.append(f"[{ts}] {role}: {m.content or ''}")
                lines.append("")

        content = "\n".join(lines).encode("utf-8")
        media = "text/markdown" if fmt == "md" else "text/plain"
        return StreamingResponse(
            io.BytesIO(content),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="athena-memories.{fmt}"'},
        )
    finally:
        db.close()


@router.get("/documents/{doc_id}/export/summary")
def export_document_summary_pdf(doc_id: str):
    """
    Generate a metadata + key-insights summary PDF for a document.
    The actual text content comes from the vector store (ChromaDB);
    if unavailable, we produce a metadata-only PDF.
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(
            Document.id == int(doc_id), Document.user_id == get_current_user_id()
        ).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        sections: list[tuple[str, str]] = []

        # Metadata section
        meta_lines = [
            f"Filename : {doc.filename}",
            f"Uploaded : {doc.uploaded_at.strftime('%Y-%m-%d %H:%M UTC') if doc.uploaded_at else 'Unknown'}",
            f"Pages    : {doc.pages or 'Unknown'}",
            f"Size     : {(doc.size_bytes or 0) // 1024} KB",
            f"Chunks   : {doc.chunk_count or 0}",
            f"Status   : {doc.status or 'processed'}",
        ]
        sections.append(("Document Metadata", "\n".join(meta_lines)))

        # Try to fetch top chunks from ChromaDB for key insights
        try:
            from backend.rag.vector_store import VectorStore
            vs = VectorStore()
            results = vs.query(
                query_text=f"key findings summary {doc.filename}",
                n_results=5,
                doc_filter=doc.filename,
            )
            if results:
                insight_text = "\n\n".join(
                    textwrap.fill(r, width=90) for r in results[:5]
                )
                sections.append(("Key Insights (from document content)", insight_text))
        except Exception:
            sections.append(("Key Insights", "Content indexing in progress or not available."))

        safe_name = doc.filename.replace("/", "-").replace("\\", "-")
        return _pdf_response(
            f"{safe_name}-summary.pdf",
            f"Document Summary: {doc.filename}",
            sections,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document id")
    finally:
        db.close()

# ── Phase 15: Seed LLM context when resuming a conversation ──────────────────

@router.post("/conversations/{conv_id}/resume")
def resume_conversation(conv_id: int):
    """
    Called by the frontend when the user selects a conversation from the
    sidebar. Loads that conversation's messages into the global memory table
    so the LLM has full context for the next message.

    This fixes the #1 intelligence gap: switching conversations previously
    made Athena forget everything — it would answer the next message without
    any context from the conversation the user selected.
    """
    db = SessionLocal()
    try:
        uid = get_current_user_id()
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id, Conversation.user_id == uid
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    finally:
        db.close()

    # Seed memory outside the above db session
    from backend.core.memory_service import seed_from_conversation
    seed_from_conversation(conv_id)
    return {"ok": True, "seeded": conv_id}
