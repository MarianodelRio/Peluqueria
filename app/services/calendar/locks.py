# services/calendar/locks.py
"""Per-slot booking locks — prevents double-booking race conditions."""
import threading
from datetime import date


class SlotLockRegistry:
    """One Lock per (date, slot). Created on demand, purged for past dates."""

    def __init__(self):
        self._locks: dict = {}
        self._guard = threading.Lock()

    def get(self, date_: date, hora: str) -> threading.Lock:
        key = f"{date_.isoformat()}_{hora}"
        with self._guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def purge_before(self, cutoff: date) -> int:
        """Remove all locks for dates strictly before cutoff. Safe because past
        slots cannot be booked — no thread will ever acquire those locks again."""
        cutoff_str = cutoff.isoformat()
        with self._guard:
            old_keys = [k for k in self._locks if k[:10] < cutoff_str]
            for k in old_keys:
                del self._locks[k]
            return len(old_keys)


slot_locks = SlotLockRegistry()
