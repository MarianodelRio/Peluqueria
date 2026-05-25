"""In-memory adapter for StateStorePort — for testing and development."""

from __future__ import annotations

import copy

from data_plane.ports.state_store import StateStorePort
from shared.domain.conversation import ConversationState


class InMemoryStateStore(StateStorePort):
    """Thread-unsafe in-memory state store. Suitable for tests only."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], ConversationState] = {}

    def get(self, tenant_id: str, contact_id: str) -> ConversationState | None:
        key = (tenant_id, contact_id)
        existing = self._store.get(key)
        if existing is None:
            return None
        return copy.deepcopy(existing)

    def save(self, state: ConversationState) -> None:
        key = (state.tenant_id, state.contact_id)
        self._store[key] = copy.deepcopy(state)

    def delete(self, tenant_id: str, contact_id: str) -> None:
        self._store.pop((tenant_id, contact_id), None)
