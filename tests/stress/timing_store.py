# tests/stress/timing_store.py
"""
Thread-safe timing store for stress test latency measurements.
Tracks e2e latency (enqueue → respond) and processing latency (acquire → respond).
"""
import threading
import time


def _pct(vals, p):
    """Return the p-th percentile of vals. Returns 0 if vals is empty."""
    if not vals:
        return 0
    sorted_vals = sorted(vals)
    idx = int(len(sorted_vals) * p / 100)
    # Clamp to last element for p=100
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


class TimingStore:
    """
    Collects per-message timing data for stress testing.

    Lifecycle per message:
      mark_enqueued(phone, t)  — message arrived at webhook
      mark_started(phone, t)   — semaphore acquired, processing started
      mark_responded(phone)    — whatsapp send called (processing done)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._in_flight: dict[str, float] = {}   # phone → t_enqueue
        self._start_times: dict[str, float] = {}  # phone → t_start (or t_enqueue)
        self._samples: list[dict] = []
        self._dropped: int = 0

    def mark_enqueued(self, phone: str, t: float) -> None:
        with self._lock:
            self._in_flight[phone] = t
            self._start_times[phone] = t

    def mark_started(self, phone: str, t: float) -> None:
        with self._lock:
            self._start_times[phone] = t

    def mark_responded(self, phone: str) -> None:
        with self._lock:
            t_respond = time.time()
            t_enqueue = self._in_flight.pop(phone, None)
            t_start = self._start_times.pop(phone, None)
            if t_enqueue is not None and t_start is not None:
                self._samples.append({
                    "e2e_ms": (t_respond - t_enqueue) * 1000,
                    "processing_ms": (t_respond - t_start) * 1000,
                })

    def mark_dropped(self, phone: str) -> None:
        with self._lock:
            self._dropped += 1
            self._in_flight.pop(phone, None)
            self._start_times.pop(phone, None)

    def get_stats(self) -> dict:
        with self._lock:
            samples = list(self._samples)
            dropped = self._dropped
            in_flight = len(self._in_flight)

        e2e_vals = [s["e2e_ms"] for s in samples]
        proc_vals = [s["processing_ms"] for s in samples]

        return {
            "count": len(samples),
            "e2e_ms": {
                "p50": _pct(e2e_vals, 50),
                "p95": _pct(e2e_vals, 95),
                "p99": _pct(e2e_vals, 99),
            },
            "processing_ms": {
                "p50": _pct(proc_vals, 50),
                "p95": _pct(proc_vals, 95),
            },
            "dropped": dropped,
            "in_flight": in_flight,
        }

    def clear(self) -> None:
        with self._lock:
            self._samples = []
            self._dropped = 0
            # Do NOT clear _in_flight or _start_times


# Module-level singleton
store = TimingStore()
