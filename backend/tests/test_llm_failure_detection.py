"""
Tests for backend/core/llm.py's ask_llm_raw_or_none().

Regression guard for a real bug: WebSearchAgent's city/topic extraction
used plain ask_llm_raw(), so a Groq+Gemini outage meant the failure
message itself got treated as a city name and handed to WeatherTool,
producing a confusing secondary error ("City 'I'm having trouble
reaching...' not found") instead of clearly reporting the outage.
"""

from unittest.mock import patch

from backend.core.llm import ask_llm_raw_or_none, _BOTH_PROVIDERS_FAILED_MESSAGE


class TestAskLlmRawOrNone:
    def test_returns_real_content_on_success(self):
        with patch("backend.core.llm.ask_llm_raw", return_value="Mumbai"):
            assert ask_llm_raw_or_none("extract the city") == "Mumbai"

    def test_returns_none_on_provider_failure(self):
        with patch("backend.core.llm.ask_llm_raw", return_value=_BOTH_PROVIDERS_FAILED_MESSAGE):
            assert ask_llm_raw_or_none("extract the city") is None

    def test_returns_none_even_with_surrounding_whitespace(self):
        with patch("backend.core.llm.ask_llm_raw", return_value=f"  {_BOTH_PROVIDERS_FAILED_MESSAGE}  "):
            assert ask_llm_raw_or_none("extract the city") is None

    def test_does_not_false_positive_on_similar_text(self):
        """A real answer that happens to mention being unavailable in
        some other context must not be swallowed -- only an EXACT match
        on the known failure string should return None."""
        with patch("backend.core.llm.ask_llm_raw", return_value="The service was unavailable yesterday."):
            assert ask_llm_raw_or_none("summarize") == "The service was unavailable yesterday."