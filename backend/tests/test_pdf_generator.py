"""
Tests for backend/rag/pdf_generator.py.

Directly guards against the two real bugs found (via manual testing,
not code review) when this module was first written:
  1. multi_cell()'s default cursor position doesn't reset to the left
     margin, which crashed every document past the first line.
  2. Core fonts are Latin-1 only; LLM output routinely isn't.
"""

import pytest

from backend.rag.pdf_generator import build_pdf, _sanitize


def _is_valid_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


class TestBasicGeneration:
    def test_produces_valid_pdf_bytes(self):
        result = build_pdf("Test Title", "Some body text.")
        assert _is_valid_pdf(result)
        assert len(result) > 0

    def test_empty_body(self):
        result = build_pdf("Empty Test", "")
        assert _is_valid_pdf(result)

    def test_empty_title_falls_back(self):
        result = build_pdf("", "Body text with no title given.")
        assert _is_valid_pdf(result)


class TestMultiLineRegression:
    """Regression test for the multi_cell cursor-position bug: any
    document with more than a couple of lines used to crash with
    'Not enough horizontal space to render a single character' because
    the cursor was never reset to the left margin between lines."""

    def test_many_lines_does_not_crash(self):
        body = "\n\n".join(f"Paragraph {i} with some reasonably normal length text." for i in range(50))
        result = build_pdf("Many Lines", body)
        assert _is_valid_pdf(result)

    def test_headings_and_bullets_mixed(self):
        body = (
            "# Heading One\n"
            "Some intro text.\n\n"
            "## Subheading\n"
            "- bullet one\n"
            "- bullet two\n"
            "- bullet three\n\n"
            "More paragraph text after the bullets.\n\n"
            "# Another Heading\n"
            "Final paragraph.\n"
        )
        result = build_pdf("Mixed Content", body)
        assert _is_valid_pdf(result)

    def test_spans_multiple_pages(self):
        # Enough content to force at least one page break.
        body = "\n\n".join(f"## Section {i}\nContent for section {i}. " * 3 for i in range(60))
        result = build_pdf("Long Document", body)
        assert _is_valid_pdf(result)
        # A tiny single-page PDF is a few hundred bytes; a genuinely
        # multi-page one should be meaningfully larger.
        assert len(result) > 2000


class TestUnicodeSanitization:
    """Regression test for the Latin-1-only core font limitation."""

    def test_em_dash_does_not_crash(self):
        result = build_pdf("Title", "Text with an em-dash — right here.")
        assert _is_valid_pdf(result)

    def test_smart_quotes_do_not_crash(self):
        result = build_pdf("Title", "He said \u2018hello\u2019 and \u201cgoodbye\u201d.")
        assert _is_valid_pdf(result)

    def test_ellipsis_does_not_crash(self):
        result = build_pdf("Title", "To be continued\u2026")
        assert _is_valid_pdf(result)

    def test_emoji_does_not_crash(self):
        # Emoji aren't in Latin-1 even after the known-character
        # replacements -- must fall back to '?' rather than raising.
        result = build_pdf("Title", "Great news! \U0001F389")
        assert _is_valid_pdf(result)

    def test_non_latin_script_does_not_crash(self):
        result = build_pdf("Title", "Some Chinese: \u4f60\u597d")
        assert _is_valid_pdf(result)

    def test_sanitize_replaces_em_dash(self):
        assert "--" in _sanitize("a — b")

    def test_sanitize_replaces_smart_quotes(self):
        assert _sanitize("\u2018hi\u2019") == "'hi'"
