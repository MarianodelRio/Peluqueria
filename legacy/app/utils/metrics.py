# utils/metrics.py
"""Thread-safe in-memory metrics counters."""
import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_start_time = time.time()


def inc(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] += value


def get_all() -> dict:
    with _lock:
        return {
            **dict(_counters),
            "uptime_seconds": int(time.time() - _start_time),
        }
