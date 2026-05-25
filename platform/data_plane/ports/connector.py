"""ConnectorPort ABC — defines the boundary for external connector calls."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConnectorPort(ABC):
    @abstractmethod
    def invoke(
        self, connector: str, operation: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Invoke an operation on a named connector and return the result."""
