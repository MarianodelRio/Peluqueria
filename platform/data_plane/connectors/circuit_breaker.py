"""CircuitBreaker — thread-safe state machine for connector fault tolerance."""

from __future__ import annotations

import threading
import time
from enum import Enum


class _State(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Simple circuit breaker with CLOSED → OPEN → HALF_OPEN → CLOSED transitions.

    :param failure_threshold: number of consecutive failures that open the circuit
    :param recovery_timeout: seconds to wait before transitioning OPEN → HALF_OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state = _State.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """In HALF_OPEN: transition to CLOSED and reset counter. In CLOSED: no-op."""
        with self._lock:
            if self._state == _State.HALF_OPEN:
                self._state = _State.CLOSED
                self._failure_count = 0
                self._opened_at = None

    def record_failure(self) -> None:
        """
        In CLOSED: increment failure count; open circuit when threshold reached.
        In HALF_OPEN: transition back to OPEN and reset the recovery timer.
        """
        with self._lock:
            if self._state == _State.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self._failure_threshold:
                    self._state = _State.OPEN
                    self._opened_at = time.monotonic()
            elif self._state == _State.HALF_OPEN:
                self._state = _State.OPEN
                self._opened_at = time.monotonic()

    def is_open(self) -> bool:
        """
        Return True if the circuit is OPEN and the recovery timeout has NOT elapsed.

        Side-effect: if OPEN and timeout HAS elapsed, transitions to HALF_OPEN and
        returns False (allowing one probe request through).
        """
        with self._lock:
            if self._state == _State.OPEN:
                elapsed = time.monotonic() - (self._opened_at or 0.0)
                if elapsed >= self._recovery_timeout:
                    self._state = _State.HALF_OPEN
                    return False
                return True
            return False

    def reset(self) -> None:
        """Transition to CLOSED and reset all counters. Useful for tests."""
        with self._lock:
            self._state = _State.CLOSED
            self._failure_count = 0
            self._opened_at = None
