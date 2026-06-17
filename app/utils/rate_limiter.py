import threading
import time


class RateLimiter:
    """Sliding-window rate limiter, keyed by string. Thread-safe.
    Stale entries inside a bucket are filtered on each check."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = [
                ts for ts in self._buckets.get(key, [])
                if now - ts < self._window
            ]
            if len(bucket) >= self._limit:
                self._buckets[key] = bucket
                return False
            bucket.append(now)
            self._buckets[key] = bucket
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def purge_inactive(self) -> int:
        now = time.time()
        with self._lock:
            inactive = [
                k for k, ts in self._buckets.items()
                if not any(now - t < self._window for t in ts)
            ]
            for k in inactive:
                del self._buckets[k]
            return len(inactive)
