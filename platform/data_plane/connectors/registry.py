"""ConnectorRegistry — routes invoke() calls to typed adapters with retry + CB."""

from __future__ import annotations

import logging
from typing import Any, Callable

import tenacity
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from data_plane.connectors.circuit_breaker import CircuitBreaker
from data_plane.connectors.errors import (
    CircuitOpenError,
    PermanentConnectorError,
    TransientConnectorError,
)
from data_plane.ports.connector import ConnectorPort

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level tenacity helper
# ---------------------------------------------------------------------------


@tenacity.retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(TransientConnectorError),
    reraise=True,
)
def _call_with_retry(method: Callable[..., Any], params: dict[str, Any]) -> Any:
    """Call method(**params) with tenacity retry logic on TransientConnectorError."""
    return method(**params)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ConnectorRegistry(ConnectorPort):
    """
    Routes invoke() calls to typed category adapters.

    :param config: mapping of category name → {"adapter": str, "credentials": dict}
    :param adapter_factories: mapping of adapter name → factory callable(credentials) → adapter
    """

    def __init__(
        self,
        config: dict[str, dict[str, Any]],
        adapter_factories: dict[str, Callable[[dict[str, Any]], Any]],
    ) -> None:
        self._adapters: dict[str, Any] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

        for category, category_cfg in config.items():
            adapter_name = category_cfg["adapter"]
            if adapter_name not in adapter_factories:
                raise KeyError(
                    f"[REGISTRY] Unknown adapter '{adapter_name}' for category "
                    f"'{category}'. Available: {list(adapter_factories)}"
                )
            credentials = category_cfg.get("credentials", {})
            self._adapters[category] = adapter_factories[adapter_name](credentials)
            self._circuit_breakers[category] = CircuitBreaker()

    # ------------------------------------------------------------------
    # ConnectorPort implementation
    # ------------------------------------------------------------------

    def invoke(
        self, connector: str, operation: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        adapter = self._adapters.get(connector)
        if adapter is None:
            raise PermanentConnectorError(
                f"[REGISTRY] Unknown connector category: {connector}"
            )

        cb = self._circuit_breakers[connector]
        if cb.is_open():
            raise CircuitOpenError(
                f"[REGISTRY] Circuit breaker OPEN for connector '{connector}'"
            )

        try:
            result = self._invoke_with_retry(adapter, operation, params)
        except PermanentConnectorError:
            raise
        except CircuitOpenError:
            raise
        except TransientConnectorError:
            cb.record_failure()
            raise

        cb.record_success()
        return result

    def _invoke_with_retry(
        self, adapter: Any, operation: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        method = getattr(adapter, operation, None)
        if method is None:
            raise PermanentConnectorError(
                f"[REGISTRY] Operation '{operation}' not found on "
                f"{type(adapter).__name__}"
            )

        value = _call_with_retry(method, params)

        # Normalize return value to dict
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return {"items": value}
