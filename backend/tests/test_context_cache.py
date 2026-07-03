"""
Tests for the context-cache TTL logic in backend/core/llm.py.

Regression guard for a real bug: the cache was previously invalidated
ONLY by an explicit call to invalidate_context_cache(), which turned out
to be wired up from exactly one place in the whole codebase -- not from
any of the actual reminder/note/goal creation tools used in normal chat.
A user could create a reminder via chat, then immediately ask about it,
and get an answer built from a context block cached from before that
reminder existed. The TTL is what bounds that staleness regardless of
which write paths remember to invalidate explicitly.
"""

import time

import backend.core.llm as llm


class TestContextCacheTTL:
    def setup_method(self):
        llm._ctx_cache.clear()
        llm.CONTEXT_CACHE_TTL_SECONDS = 45  # restore default in case a test changed it

    def test_roundtrip(self):
        llm._cache_set("ctx_1", "hello world")
        assert llm._cache_get("ctx_1") == "hello world"

    def test_missing_key_returns_none(self):
        assert llm._cache_get("does_not_exist") is None

    def test_entry_expires_after_ttl(self):
        llm.CONTEXT_CACHE_TTL_SECONDS = 0.05
        llm._cache_set("ctx_2", "expires soon")
        time.sleep(0.1)
        assert llm._cache_get("ctx_2") is None

    def test_expired_entry_is_removed_from_dict(self):
        """Not just inaccessible via _cache_get -- actually cleaned up,
        so the dict doesn't grow unboundedly with dead entries."""
        llm.CONTEXT_CACHE_TTL_SECONDS = 0.05
        llm._cache_set("ctx_3", "expires soon")
        time.sleep(0.1)
        llm._cache_get("ctx_3")
        assert "ctx_3" not in llm._ctx_cache

    def test_entry_within_ttl_is_still_valid(self):
        llm.CONTEXT_CACHE_TTL_SECONDS = 60
        llm._cache_set("ctx_4", "still fresh")
        time.sleep(0.05)
        assert llm._cache_get("ctx_4") == "still fresh"

    def test_lru_eviction_keeps_newest_50(self):
        llm.CONTEXT_CACHE_TTL_SECONDS = 999
        for i in range(55):
            llm._cache_set(f"ctx_{i}", f"value_{i}")
            time.sleep(0.001)  # distinct timestamps
        assert len(llm._ctx_cache) == 50
        assert "ctx_0" not in llm._ctx_cache
        assert "ctx_54" in llm._ctx_cache

    def test_per_user_keys_are_independent(self):
        llm._cache_set("ctx_user_1", "user 1's context")
        llm._cache_set("ctx_user_2", "user 2's context")
        assert llm._cache_get("ctx_user_1") == "user 1's context"
        assert llm._cache_get("ctx_user_2") == "user 2's context"

