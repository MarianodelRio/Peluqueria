"""Tests for ConnectorRegistry — routing, retry, and circuit breaker behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_plane.adapters.connectors.mock_calendar import MockCalendarAdapter
from data_plane.adapters.connectors.mock_notification import MockNotificationAdapter
from data_plane.adapters.state_store.in_memory import InMemoryStateStore
from data_plane.connectors.errors import (
    CircuitOpenError,
    PermanentConnectorError,
    TransientConnectorError,
)
from data_plane.connectors.registry import ConnectorRegistry
from data_plane.engine.bot import Bot
from data_plane.engine.flow import load_flow
from data_plane.engine.outputs import SendTextOutput
from shared.domain.conversation import ConversationState
from shared.domain.messages import InternalMessage, MessageType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FLOW_PATH = Path(__file__).parent / "flows" / "toy_flow.yaml"


def _make_registry(
    calendar_adapter: MockCalendarAdapter | None = None,
    notification_adapter: MockNotificationAdapter | None = None,
) -> ConnectorRegistry:
    """Build a ConnectorRegistry with the given adapters injected as factories."""
    cal = calendar_adapter or MockCalendarAdapter()
    notif = notification_adapter or MockNotificationAdapter()
    factories = {
        "mock_calendar": lambda creds, _cal=cal: _cal,
        "mock_notification": lambda creds, _notif=notif: _notif,
    }
    return ConnectorRegistry(
        config={
            "calendar": {"adapter": "mock_calendar"},
            "notification": {"adapter": "mock_notification"},
        },
        adapter_factories=factories,
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


def test_registry_routes_calendar_list_slots() -> None:
    """invoke('calendar', 'list_slots', {}) routes to MockCalendarAdapter."""
    adapter = MockCalendarAdapter()
    registry = _make_registry(calendar_adapter=adapter)

    result = registry.invoke("calendar", "list_slots", {})

    assert result == {"items": ["09:00", "10:00"]}
    assert len(adapter.calls) == 1


def test_registry_routes_notification_send_text() -> None:
    """invoke('notification', 'send_text', ...) routes to MockNotificationAdapter."""
    adapter = MockNotificationAdapter()
    registry = _make_registry(notification_adapter=adapter)

    result = registry.invoke(
        "notification", "send_text", {"contact_id": "c1", "text": "hi"}
    )

    assert result == {}
    assert len(adapter.calls) == 1


def test_unknown_category_raises_permanent_error() -> None:
    """Invoking an unknown connector category raises PermanentConnectorError."""
    registry = _make_registry()

    with pytest.raises(PermanentConnectorError):
        registry.invoke("payments", "pay", {})


def test_unknown_operation_raises_permanent_error() -> None:
    """Invoking a nonexistent operation on a valid category raises PermanentConnectorError."""
    adapter = MockCalendarAdapter()
    registry = _make_registry(calendar_adapter=adapter)

    with pytest.raises(PermanentConnectorError):
        registry.invoke("calendar", "nonexistent_op", {})


def test_transient_error_retries_and_succeeds() -> None:
    """With transient_failures=2, adapter is called 3 times and final result succeeds."""
    adapter = MockCalendarAdapter(transient_failures=2)
    registry = _make_registry(calendar_adapter=adapter)

    result = registry.invoke("calendar", "list_slots", {})

    assert len(adapter.calls) == 3
    assert result == {"items": ["09:00", "10:00"]}


def test_three_transient_errors_exhaust_retries() -> None:
    """With transient_failures=3, all 3 retry attempts fail — TransientConnectorError raised."""
    adapter = MockCalendarAdapter(transient_failures=3)
    registry = _make_registry(calendar_adapter=adapter)

    with pytest.raises(TransientConnectorError):
        registry.invoke("calendar", "list_slots", {})


def test_five_failures_open_circuit() -> None:
    """Five transient failures open the circuit; 6th call raises CircuitOpenError."""
    # Use transient_failures=100 so every call always raises TransientConnectorError.
    # With 3 retry attempts per invoke() call, we need 2 invoke() calls to get 5
    # recorded failures (call 1: 3 attempts, call 2: 2 attempts before CB opens mid-retry).
    # Simpler approach: use CB with failure_threshold=5, one failure per invoke call
    # by patching the CB. Actually easiest: use transient_failures=1 so each invoke()
    # call fails on the 1st attempt and retries succeed on 2nd... no.
    #
    # The cleanest approach: each invoke() call that exhausts retries counts as ONE
    # CB failure (record_failure called once per invoke, not per retry).
    # With transient_failures=100: each invoke() → 3 attempts → TransientConnectorError
    # → CB.record_failure() once → after 5 invoke calls → CB opens.
    adapter = MockCalendarAdapter(transient_failures=100)
    registry = _make_registry(calendar_adapter=adapter)

    for _ in range(5):
        with pytest.raises(TransientConnectorError):
            registry.invoke("calendar", "list_slots", {})

    with pytest.raises(CircuitOpenError):
        registry.invoke("calendar", "list_slots", {})

    # Each of the 5 invoke calls made 3 retry attempts = 15 adapter calls total
    assert len(adapter.calls) == 15


def test_circuit_open_does_not_call_adapter() -> None:
    """After circuit opens, subsequent calls do not reach the adapter."""
    adapter = MockCalendarAdapter(transient_failures=100)
    registry = _make_registry(calendar_adapter=adapter)

    for _ in range(5):
        with pytest.raises(TransientConnectorError):
            registry.invoke("calendar", "list_slots", {})

    calls_before = len(adapter.calls)

    with pytest.raises(CircuitOpenError):
        registry.invoke("calendar", "list_slots", {})

    # Adapter call count must not have increased
    assert len(adapter.calls) == calls_before


def test_bot_engine_with_registry() -> None:
    """End-to-end: Bot with ConnectorRegistry processes toy_flow correctly."""
    flow = load_flow(FLOW_PATH.read_text())
    store = InMemoryStateStore()
    calendar_adapter = MockCalendarAdapter()
    registry = _make_registry(calendar_adapter=calendar_adapter)

    bot = Bot(flow=flow, state_store=store, connector=registry)

    # Seed state at ENTER_NAME so the next message triggers invoke_connector
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

    # Sending a text transitions ENTER_NAME → CONFIRM, which calls calendar.list_slots
    outputs = bot.handle_message(_msg(text="Ana", message_type=MessageType.TEXT))

    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "CONFIRM"
    assert saved.data["customer_name"] == "Ana"

    # The invoke_connector result is a list (unwrapped from {"items": [...]})
    assert saved.data["available_slots"] == ["09:00", "10:00"]

    # on_enter of CONFIRM sends "Slots ready."
    assert len(outputs) == 1
    assert isinstance(outputs[0], SendTextOutput)
    assert outputs[0].text == "Slots ready."

    # Adapter was called exactly once
    assert len(calendar_adapter.calls) == 1
