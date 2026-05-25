# services/calendar/locks.py
"""Per-slot booking locks — prevents double-booking race conditions."""
import threading
from datetime import date


class SlotLockRegistry:
    """One Lock per (date, slot). Created on demand, never deleted (bounded set)."""

    def __init__(self):
        self._locks: dict = {}
        self._guard = threading.Lock()

    def get(self, date_: date, hora: str) -> threading.Lock:
        key = f"{date_.isoformat()}_{hora}"
        with self._guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


slot_locks = SlotLockRegistry()
