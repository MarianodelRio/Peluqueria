"""Unit tests for CircuitBreaker state machine."""

from __future__ import annotations

import time

from data_plane.connectors.circuit_breaker import CircuitBreaker


def test_initial_state_is_closed() -> None:
    """New CircuitBreaker starts CLOSED — is_open() returns False."""
    cb = CircuitBreaker()
    assert cb.is_open() is False


def test_failure_threshold_transitions_to_open() -> None:
    """Five consecutive failures open the circuit."""
    cb = CircuitBreaker(failure_threshold=5)
    for _ in range(5):
        cb.record_failure()
    assert cb.is_open() is True


def test_open_transitions_to_half_open_after_timeout() -> None:
    """After recovery_timeout elapses, is_open() returns False (transitions to HALF_OPEN)."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.01)
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open() is True

    time.sleep(0.02)
    # Timeout elapsed — transitions to HALF_OPEN, is_open() returns False
    assert cb.is_open() is False


def test_half_open_success_transitions_to_closed() -> None:
    """In HALF_OPEN, record_success() transitions back to CLOSED and resets counter."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.01)
    for _ in range(3):
        cb.record_failure()
    time.sleep(0.02)
    cb.is_open()  # trigger HALF_OPEN transition

    cb.record_success()
    assert cb.is_open() is False

    # Counter reset: a single failure should NOT open the circuit
    cb.record_failure()
    assert cb.is_open() is False


def test_half_open_failure_reopens() -> None:
    """In HALF_OPEN, record_failure() transitions back to OPEN."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.01)
    for _ in range(3):
        cb.record_failure()
    time.sleep(0.02)
    cb.is_open()  # trigger HALF_OPEN transition

    cb.record_failure()
    assert cb.is_open() is True


def test_reset_clears_state() -> None:
    """reset() transitions to CLOSED regardless of current state."""
    cb = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open() is True

    cb.reset()
    assert cb.is_open() is False
