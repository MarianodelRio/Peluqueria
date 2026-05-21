# tests/test_rate_limiter.py
"""Unit tests for app/utils/rate_limiter.py."""
import threading
from unittest.mock import patch

import pytest

from app.utils.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_within_limit_returns_true(self):
        rl = RateLimiter(limit=3, window_seconds=60)
        assert rl.check("key") is True
        assert rl.check("key") is True

    def test_at_limit_returns_false(self):
        rl = RateLimiter(limit=3, window_seconds=60)
        assert rl.check("key") is True
        assert rl.check("key") is True
        assert rl.check("key") is True
        assert rl.check("key") is False

    def test_old_entries_dropped_after_window(self):
        rl = RateLimiter(limit=3, window_seconds=60)
        base_time = 1000.0
        with patch("app.utils.rate_limiter.time.time", return_value=base_time):
            rl.check("key")
            rl.check("key")
            rl.check("key")
            # Limit reached at base_time
            assert rl.check("key") is False
        # Advance past the window
        with patch("app.utils.rate_limiter.time.time", return_value=base_time + 61.0):
            # Old entries are now expired; call should succeed
            assert rl.check("key") is True

    def test_separate_keys_have_separate_buckets(self):
        rl = RateLimiter(limit=2, window_seconds=60)
        # Exhaust "a"
        assert rl.check("a") is True
        assert rl.check("a") is True
        assert rl.check("a") is False
        # "b" is unaffected
        assert rl.check("b") is True

    def test_concurrent_check_is_thread_safe(self):
        limit = 10
        num_threads = 20
        rl = RateLimiter(limit=limit, window_seconds=60)
        barrier = threading.Barrier(num_threads)
        results = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            result = rl.check("shared_key")
            with lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == limit
        assert results.count(False) == num_threads - limit
