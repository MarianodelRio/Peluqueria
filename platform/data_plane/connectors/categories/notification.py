"""NotificationConnector ABC — defines the boundary for outbound notification operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NotificationConnector(ABC):
    """Abstract base class for notification connector implementations."""

    @abstractmethod
    def send_text(self, contact_id: str, text: str) -> None:
        """Send a plain text message to the contact."""

    @abstractmethod
    def send_template(
        self,
        contact_id: str,
        template_name: str,
        params: dict[str, str],
    ) -> None:
        """Send a template message to the contact."""

    @abstractmethod
    def send_interactive_buttons(
        self,
        contact_id: str,
        body: str,
        buttons: list[dict[str, Any]],
    ) -> None:
        """Send a message with interactive buttons to the contact."""
