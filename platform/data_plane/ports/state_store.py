"""StateStorePort ABC — defines persistence boundary for conversation state."""

from __future__ import annotations

from abc import ABC, abstractmethod

from shared.domain.conversation import ConversationState


class StateStorePort(ABC):
    @abstractmethod
    def get(self, tenant_id: str, contact_id: str) -> ConversationState | None:
        """Return the conversation state for this tenant+contact, or None if absent."""

    @abstractmethod
    def save(self, state: ConversationState) -> None:
        """Persist the given conversation state."""

    @abstractmethod
    def delete(self, tenant_id: str, contact_id: str) -> None:
        """Remove the conversation state for this tenant+contact."""
