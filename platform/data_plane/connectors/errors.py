"""Connector error hierarchy."""

from __future__ import annotations


class ConnectorError(Exception):
    """Base exception for all connector errors."""


class TransientConnectorError(ConnectorError):
    """Transient error — tenacity retries on this and CB counts it."""


class PermanentConnectorError(ConnectorError):
    """Permanent error — no retry, no CB failure count."""


class CircuitOpenError(ConnectorError):
    """Raised by the registry when the circuit breaker is OPEN."""
