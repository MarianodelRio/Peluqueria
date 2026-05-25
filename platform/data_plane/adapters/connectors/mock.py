"""Mock connector adapter — returns preset responses or raises on demand."""

from __future__ import annotations

from typing import Any

from data_plane.ports.connector import ConnectorPort


class MockConnector(ConnectorPort):
    """
    Test double for ConnectorPort.

    :param responses: mapping of (connector, operation) -> response dict
    :param raise_on: set of (connector, operation) pairs that should raise RuntimeError
    """

    def __init__(
        self,
        responses: dict[tuple[str, str], dict[str, Any]] | None = None,
        raise_on: set[tuple[str, str]] | None = None,
    ) -> None:
        self._responses: dict[tuple[str, str], dict[str, Any]] = responses or {}
        self._raise_on: set[tuple[str, str]] = raise_on or set()
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self, connector: str, operation: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        key = (connector, operation)
        self.calls.append(
            {"connector": connector, "operation": operation, "params": params}
        )
        if key in self._raise_on:
            raise RuntimeError(
                f"[MOCK_CONNECTOR] Configured to raise for {connector}.{operation}"
            )
        return self._responses.get(key, {})
