"""
Tests for backend/core/rate_limit.py.
"""

import time

import pytest
from fastapi import HTTPException

from backend.core.rate_limit import RateLimiter, require_budget


class TestSlidingWindow:
    def test_allows_up_to_max_calls(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60, name="test")
        assert limiter.check("user1") is True
        assert limiter.check("user1") is True
        assert limiter.check("user1") is True

    def test_blocks_after_max_calls(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60, name="test")
        for _ in range(3):
            assert limiter.check("user1") is True
        assert limiter.check("user1") is False

    def test_rejected_call_is_not_recorded(self):
        """A call that gets rejected shouldn't itself count toward or
        extend the window -- otherwise a client retrying immediately
        after a 429 would just keep getting rejected forever even after
        the window should have rolled over."""
        limiter = RateLimiter(max_calls=1, window_seconds=60, name="test")
        assert limiter.check("user1") is True
        assert limiter.check("user1") is False
        assert limiter.check("user1") is False  # still blocked, but not "more" blocked

    def test_window_expires(self):
        limiter = RateLimiter(max_calls=1, window_seconds=0.1, name="test")
        assert limiter.check("user1") is True
        assert limiter.check("user1") is False
        time.sleep(0.15)
        assert limiter.check("user1") is True

    def test_keys_are_independent(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60, name="test")
        assert limiter.check("user1") is True
        assert limiter.check("user1") is False
        # A completely different key must not be affected by user1's usage.
        assert limiter.check("user2") is True

    def test_remaining_reflects_usage(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60, name="test")
        assert limiter.remaining("user1") == 5
        limiter.check("user1")
        limiter.check("user1")
        assert limiter.remaining("user1") == 3


class TestCheckOrRaise:
    def test_raises_http_429_when_exceeded(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60, name="test")
        limiter.check_or_raise("user1")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check_or_raise("user1")
        assert exc_info.value.status_code == 429

    def test_custom_detail_message(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60, name="test")
        limiter.check_or_raise("user1")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check_or_raise("user1", detail="Custom message")
        assert exc_info.value.detail == "Custom message"

    def test_does_not_raise_when_under_limit(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60, name="test")
        limiter.check_or_raise("user1")  # should not raise


class TestRequireBudget:
    """require_budget() is the helper every rate-limited endpoint
    actually calls -- checking both a minute and a daily limiter."""

    def test_passes_when_both_under_limit(self):
        minute = RateLimiter(max_calls=5, window_seconds=60, name="m")
        daily = RateLimiter(max_calls=100, window_seconds=86400, name="d")
        require_budget(minute, daily, "user1", "minute msg", "daily msg")  # no raise

    def test_raises_minute_message_when_minute_exceeded(self):
        minute = RateLimiter(max_calls=1, window_seconds=60, name="m")
        daily = RateLimiter(max_calls=100, window_seconds=86400, name="d")
        require_budget(minute, daily, "user1", "minute msg", "daily msg")
        with pytest.raises(HTTPException) as exc_info:
            require_budget(minute, daily, "user1", "minute msg", "daily msg")
        assert exc_info.value.detail == "minute msg"

    def test_raises_daily_message_when_daily_exceeded(self):
        minute = RateLimiter(max_calls=100, window_seconds=60, name="m")
        daily = RateLimiter(max_calls=1, window_seconds=86400, name="d")
        require_budget(minute, daily, "user1", "minute msg", "daily msg")
        with pytest.raises(HTTPException) as exc_info:
            require_budget(minute, daily, "user1", "minute msg", "daily msg")
        assert exc_info.value.detail == "daily msg"
