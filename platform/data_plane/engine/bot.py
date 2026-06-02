"""Bot: wires together the flow interpreter, state store, and connector port."""

from __future__ import annotations

import logging
from datetime import date, datetime

from data_plane.ports.connector import ConnectorPort
from data_plane.ports.state_store import StateStorePort
from shared.domain.conversation import ConversationState
from shared.domain.messages import InternalMessage

from .flow import Flow
from .interpreter import FlowInterpreter
from .outputs import Output

log = logging.getLogger(__name__)


class Bot:
    """Handles a single inbound message end-to-end."""

    def __init__(
        self,
        flow: Flow,
        state_store: StateStorePort,
        connector: ConnectorPort,
    ) -> None:
        self._flow = flow
        self._state_store = state_store
        self._connector = connector
        self._interpreter = FlowInterpreter(flow)

    def handle_message(self, message: InternalMessage) -> list[Output]:
        try:
            state = self._state_store.get(message.tenant_id, message.contact_id)

            if state is None:
                state = ConversationState(
                    tenant_id=message.tenant_id,
                    contact_id=message.contact_id,
                    current_state=self._flow.initial_state,
                    data={},
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

            state.data["today"] = date.today().isoformat()
            new_state, outputs = self._interpreter.process(
                message, state, self._connector
            )
            new_state.updated_at = datetime.utcnow()
            self._state_store.save(new_state)
            return outputs
        except Exception:
            log.exception("[BOT] Unhandled error while processing message")
            return []
