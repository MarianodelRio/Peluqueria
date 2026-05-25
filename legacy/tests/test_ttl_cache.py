# tests/test_ttl_cache.py
"""
Unit tests for the TTLCache class in app.services.calendar.caches.
No external dependencies — pure in-process tests.
"""
import time
import pytest

from app.services.calendar.caches import TTLCache


class TestTTLCache:

    def test_get_returns_none_for_missing_key(self):
        cache = TTLCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_set_then_get_returns_value(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", ["slot1", "slot2"])
        result = cache.get("key1")
        assert result == ["slot1", "slot2"]

    def test_expired_entry_returns_none(self):
        """Entry set with a 0.05s TTL expires almost immediately."""
        cache = TTLCache(ttl_seconds=0.05)
        cache.set("key1", "value")
        # Entry is fresh right after setting
        assert cache.get("key1") == "value"
        time.sleep(0.1)
        # Entry should now be expired
        assert cache.get("key1") is None

    def test_invalidate_removes_key(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", "value")
        assert cache.get("key1") == "value"
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_invalidate_matching_removes_matching_keys(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("2026-03-24_30_30", ["10:00"])
        cache.set("2026-03-24_60_30", ["10:00"])
        cache.set("evt_2026-03-24_30_30", ["10:00"])
        cache.set("2026-03-25_30_30", ["11:00"])  # different date — should be kept

        date_str = "2026-03-24"
        cache.invalidate_matching(
            lambda k: k.startswith(date_str) or k.startswith(f"evt_{date_str}")
        )

        assert cache.get("2026-03-24_30_30") is None
        assert cache.get("2026-03-24_60_30") is None
        assert cache.get("evt_2026-03-24_30_30") is None
        # Different date must survive
        assert cache.get("2026-03-25_30_30") is not None

    def test_purge_expired_removes_stale_returns_count(self):
        cache = TTLCache(ttl_seconds=0.05)
        cache.set("key1", "v1")
        cache.set("key2", "v2")
        cache.set("key3", "v3")
        time.sleep(0.1)
        # Add a fresh entry after the sleep so it survives purge
        cache.set("fresh_key", "fresh")

        removed = cache.purge_expired()

        assert removed == 3
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None
        assert cache.get("fresh_key") == "fresh"
