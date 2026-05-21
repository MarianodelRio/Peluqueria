import threading
from datetime import datetime, timedelta


class MessageDeduplicator:
    """In-memory message-ID dedup with TTL."""

    def __init__(self, ttl_minutes: int) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._seen: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def seen(self, message_id: str) -> bool:
        now = datetime.now()
        with self._lock:
            expired = [k for k, ts in self._seen.items() if now - ts > self._ttl]
            for k in expired:
                del self._seen[k]
            if message_id in self._seen:
                return True
            self._seen[message_id] = now
            return False
