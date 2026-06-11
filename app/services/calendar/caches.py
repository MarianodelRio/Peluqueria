# services/calendar/caches.py
"""TTL-based in-memory caches for slot availability and per-phone appointments."""
import threading
import time
from typing import Any, Optional

from app.config import SLOT_CACHE_TTL_SEC, CITAS_CACHE_TTL_SEC


class TTLCache:
    """
    Thread-safe TTL cache.

    Internal storage: dict[key] = (value, timestamp_float).
    raw_data returns a reference to the same internal dict so legacy shims
    that do cal._slot_cache[key] = ... mutate the live cache object.
    """

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._data: dict = {}
        self._lock = threading.Lock()

    @property
    def raw_data(self) -> dict:
        """Return the underlying dict by reference (for legacy shim compatibility)."""
        return self._data

    def get(self, key) -> Optional[Any]:
        now = time.time()
        with self._lock:
            if key in self._data:
                value, ts = self._data[key]
                if now - ts < self._ttl:
                    return value
            return None

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = (value, time.time())

    def invalidate(self, key) -> None:
        if key is None:
            return
        with self._lock:
            self._data.pop(key, None)

    def invalidate_matching(self, predicate) -> None:
        with self._lock:
            keys = [k for k in self._data if predicate(k)]
            for k in keys:
                self._data.pop(k, None)

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = time.time()
        with self._lock:
            keys = [
                k for k, (_, ts) in list(self._data.items())
                if now - ts >= self._ttl
            ]
            for k in keys:
                self._data.pop(k, None)
            return len(keys)

    def __contains__(self, key) -> bool:
        return self.get(key) is not None


slot_cache = TTLCache(SLOT_CACHE_TTL_SEC)
citas_cache = TTLCache(CITAS_CACHE_TTL_SEC)
