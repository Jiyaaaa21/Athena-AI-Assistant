"""
backend/rag/pdf_generator.py — Phase 29: document generation

Turns a title + body text into a real, downloadable PDF using fpdf2
(already an unused dependency in requirements.txt before this). No new
dependency, no new cost.

fpdf2's built-in core fonts (Helvetica, Times, Courier) only support
Latin-1 -- they raise FPDFUnicodeEncodingException on anything outside
that range, and LLM-generated text routinely includes characters like
em-dashes (—), smart quotes ('' ""), and ellipses (…) that aren't in
Latin-1. Rather than bundling a Unicode TTF font (adds a binary asset
and deployment complexity for a personal-assistant PDF export), this
sanitizes text to their closest ASCII equivalents first. Anything left
outside Latin-1 after that is replaced with '?' rather than crashing
the whole generation.
"""

from __future__ import annotations

import re

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# Common "smart"/typographic characters LLMs produce -> ASCII equivalents.
_UNICODE_REPLACEMENTS = {
    "\u2014": "--",   # em dash
    "\u2013": "-",    # en dash
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote / apostrophe
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # ellipsis
    "\u2022": "-",    # bullet
    "\u00a0": " ",    # non-breaking space
}

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")


def _sanitize(text: str) -> str:
    for unicode_char, ascii_equiv in _UNICODE_REPLACEMENTS.items():
        text = text.replace(unicode_char, ascii_equiv)
    # Anything still outside Latin-1 (emoji, other scripts, etc.) becomes
    # '?' rather than raising and losing the whole document.
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _write_line(pdf: FPDF, height: float, text: str) -> None:
    """
    multi_cell()'s DEFAULT leaves the cursor at new_x=XPos.RIGHT (the end
    of the text just rendered), not back at the left margin -- the next
    multi_cell() call then starts from wherever that happened to land,
    which on anything past the first line raises "Not enough horizontal
    space to render a single character" once it drifts far enough right.
    Every line in this module goes through this helper specifically so
    that reset is never accidentally missed on a future edit.
    """
    pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_pdf(title: str, body_text: str) -> bytes:
    """
    Renders a title + body into a simple, clean PDF. body_text may use a
    minimal subset of markdown (# headings, - bullets) which get basic
    visual treatment; everything else is plain paragraph text.
    """
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    _write_line(pdf, 10, _sanitize(title.strip() or "Untitled Document"))
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 11)

    for raw_line in body_text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            pdf.ln(4)
            continue

        heading_match = _MD_HEADING_RE.match(line)
        bullet_match = _MD_BULLET_RE.match(line)

        if heading_match:
            level = len(heading_match.group(1))
            heading_text = _sanitize(heading_match.group(2).strip())
            size = max(16 - (level * 2), 11)
            pdf.set_font("Helvetica", "B", size)
            pdf.ln(2)
            _write_line(pdf, 8, heading_text)
            pdf.set_font("Helvetica", "", 11)
        elif bullet_match:
            bullet_text = _sanitize(bullet_match.group(1).strip())
            _write_line(pdf, 7, f"    - {bullet_text}")
        else:
            _write_line(pdf, 7, _sanitize(line.strip()))

    return bytes(pdf.output())