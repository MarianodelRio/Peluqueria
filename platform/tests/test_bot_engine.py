"""End-to-end tests for the Bot Engine (Fase 1)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_plane.adapters.connectors.mock import MockConnector
from data_plane.adapters.state_store.in_memory import InMemoryStateStore
from data_plane.engine.bot import Bot
from data_plane.engine.flow import load_flow
from data_plane.engine.outputs import (
    SendInteractiveButtonsOutput,
    SendTextOutput,
)
from shared.domain.conversation import ConversationState
from shared.domain.messages import InternalMessage, MessageType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FLOW_PATH = Path(__file__).parent / "flows" / "toy_flow.yaml"

FLOW = load_flow(FLOW_PATH.read_text())


def _load_flow():
    return load_flow(FLOW_PATH.read_text())


def _make_bot(
    connector: MockConnector | None = None,
    state_store: InMemoryStateStore | None = None,
) -> Bot:
    flow = _load_flow()
    return Bot(
        flow=flow,
        state_store=state_store or InMemoryStateStore(),
        connector=connector or MockConnector(),
    )


def _msg(
    text: str | None = None,
    payload: str | None = None,
    message_type: MessageType = MessageType.TEXT,
    tenant_id: str = "t1",
    contact_id: str = "c1",
) -> InternalMessage:
    return InternalMessage(
        tenant_id=tenant_id,
        contact_id=contact_id,
        message_type=message_type,
        text=text,
        payload=payload,
        timestamp=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_new_conversation_first_message_no_match_triggers_fallback_on_enter() -> None:
    """Fresh contact sends 'hola' — MENU fallback fires → welcome text + buttons."""
    bot = _make_bot()
    outputs = bot.handle_message(_msg(text="hola"))

    assert len(outputs) == 2
    assert isinstance(outputs[0], SendTextOutput)
    assert "Welcome" in outputs[0].text
    assert isinstance(outputs[1], SendInteractiveButtonsOutput)
    assert outputs[1].buttons[0].id == "opt_book"


def test_button_reply_transitions_to_enter_name() -> None:
    """Payload 'opt_book' from MENU → state=ENTER_NAME, outputs prompt."""
    store = InMemoryStateStore()
    bot = _make_bot(state_store=store)

    # Seed state at MENU
    store.save(
        ConversationState(
            tenant_id="t1",
            contact_id="c1",
            current_state="MENU",
            data={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )

    outputs = bot.handle_message(
        _msg(payload="opt_book", message_type=MessageType.BUTTON_REPLY)
    )

    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "ENTER_NAME"
    assert len(outputs) == 1
    assert isinstance(outputs[0], SendTextOutput)
    assert "name" in outputs[0].text.lower()


def test_text_captured_in_set_data_and_transitions_to_confirm() -> None:
    """Text 'Carlos' from ENTER_NAME → CONFIRM, data['customer_name']=='Carlos'."""
    store = InMemoryStateStore()
    bot = _make_bot(state_store=store)

    store.save(
        ConversationState(
            tenant_id="t1",
            contact_id="c1",
            current_state="ENTER_NAME",
            data={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )

    bot.handle_message(_msg(text="Carlos", message_type=MessageType.TEXT))

    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "CONFIRM"
    assert saved.data["customer_name"] == "Carlos"


def test_invoke_connector_called_with_correct_params_and_result_stored() -> None:
    """Text 'Ana' from ENTER_NAME triggers invoke_connector; result stored in data."""
    store = InMemoryStateStore()
    mock = MockConnector(
        responses={("calendar", "list_slots"): {"slots": ["09:00", "10:00"]}},
    )
    bot = _make_bot(connector=mock, state_store=store)

    store.save(
        ConversationState(
            tenant_id="t1",
            contact_id="c1",
            current_state="ENTER_NAME",
            data={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )

    bot.handle_message(_msg(text="Ana", message_type=MessageType.TEXT))

    assert len(mock.calls) == 1
    call = mock.calls[0]
    assert call["connector"] == "calendar"
    assert call["operation"] == "list_slots"
    assert call["params"]["name"] == "Ana"

    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.data["available_slots"] == {"slots": ["09:00", "10:00"]}


def test_global_transition_fires_from_any_state() -> None:
    """From CONFIRM, payload 'back_to_menu' → state=MENU."""
    store = InMemoryStateStore()
    bot = _make_bot(state_store=store)

    store.save(
        ConversationState(
            tenant_id="t1",
            contact_id="c1",
            current_state="CONFIRM",
            data={"customer_name": "Test"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )

    outputs = bot.handle_message(
        _msg(payload="back_to_menu", message_type=MessageType.BUTTON_REPLY)
    )

    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "MENU"
    # MENU on_enter fires: welcome text + buttons
    assert len(outputs) == 2
    assert isinstance(outputs[0], SendTextOutput)
    assert isinstance(outputs[1], SendInteractiveButtonsOutput)


def test_fallback_same_state_re_executes_on_enter() -> None:
    """Unknown message in ENTER_NAME → stays in ENTER_NAME, on_enter re-runs."""
    store = InMemoryStateStore()
    bot = _make_bot(state_store=store)

    store.save(
        ConversationState(
            tenant_id="t1",
            contact_id="c1",
            current_state="ENTER_NAME",
            data={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )

    # Send a button reply that doesn't match any transition in ENTER_NAME
    outputs = bot.handle_message(
        _msg(payload="unknown_button", message_type=MessageType.BUTTON_REPLY)
    )

    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "ENTER_NAME"
    assert len(outputs) == 1
    assert isinstance(outputs[0], SendTextOutput)
    assert "name" in outputs[0].text.lower()


def test_in_memory_state_store_persists_between_calls() -> None:
    """InMemoryStateStore save/get/delete lifecycle."""
    store = InMemoryStateStore()

    state = ConversationState(
        tenant_id="t1",
        contact_id="c1",
        current_state="MENU",
        data={"foo": "bar"},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    store.save(state)

    retrieved = store.get("t1", "c1")
    assert retrieved is not None
    assert retrieved.current_state == "MENU"
    assert retrieved.data["foo"] == "bar"

    # Mutation of retrieved does not affect stored copy
    retrieved.data["foo"] = "mutated"
    still_stored = store.get("t1", "c1")
    assert still_stored is not None
    assert still_stored.data["foo"] == "bar"

    store.delete("t1", "c1")
    assert store.get("t1", "c1") is None


def test_mock_connector_raises_when_configured() -> None:
    """MockConnector with raise_on raises RuntimeError on matching call."""
    mock = MockConnector(raise_on={("calendar", "list_slots")})

    with pytest.raises(RuntimeError):
        mock.invoke("calendar", "list_slots", {})


def test_end_to_end_three_messages_fresh_store():
    store = InMemoryStateStore()
    mock = MockConnector(responses={("calendar", "list_slots"): {"slots": ["09:00"]}})
    bot = Bot(FLOW, store, mock)

    # Message 1: unrecognized text → MENU fallback fires on_enter
    outputs1 = bot.handle_message(_msg(message_type=MessageType.TEXT, text="hola"))
    state1 = store.get("t1", "c1")
    assert state1.current_state == "MENU"
    assert len(outputs1) == 2
    assert isinstance(outputs1[0], SendTextOutput)
    assert "Welcome" in outputs1[0].text
    assert isinstance(outputs1[1], SendInteractiveButtonsOutput)
    assert outputs1[1].buttons[0].id == "opt_book"

    # Message 2: opt_book button → transition to ENTER_NAME
    outputs2 = bot.handle_message(
        _msg(message_type=MessageType.BUTTON_REPLY, payload="opt_book")
    )
    state2 = store.get("t1", "c1")
    assert state2.current_state == "ENTER_NAME"
    assert len(outputs2) == 1
    assert isinstance(outputs2[0], SendTextOutput)
    assert "name" in outputs2[0].text.lower()

    # Message 3: text "Carlos" → CONFIRM, set_data captured, connector invoked
    outputs3 = bot.handle_message(_msg(message_type=MessageType.TEXT, text="Carlos"))
    state3 = store.get("t1", "c1")
    assert state3.current_state == "CONFIRM"
    assert state3.data["customer_name"] == "Carlos"
    assert len(outputs3) == 1
    assert isinstance(outputs3[0], SendTextOutput)
    assert outputs3[0].text == "Slots ready."
