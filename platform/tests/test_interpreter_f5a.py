"""Unit tests for F5a interpreter features."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from data_plane.adapters.connectors.mock import MockConnector
from data_plane.adapters.state_store.in_memory import InMemoryStateStore
from data_plane.engine.bot import Bot
from data_plane.engine.flow import load_flow
from data_plane.engine.interpreter import DataProxy, _resolve
from data_plane.engine.outputs import (
    SendOptionsOutput,
    SendTextOutput,
)
from shared.domain.conversation import ConversationState
from shared.domain.messages import InternalMessage, MessageType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OPTIONS_FLOW_PATH = Path(__file__).parent / "flows" / "options_flow.yaml"
OPTIONS_FLOW = load_flow(OPTIONS_FLOW_PATH.read_text())


def _msg(
    text: str | None = None,
    payload: str | None = None,
    message_type: MessageType = MessageType.LIST_REPLY,
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


def _state(current: str, data: dict | None = None) -> ConversationState:
    return ConversationState(
        tenant_id="t1",
        contact_id="c1",
        current_state=current,
        data=data or {},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _make_bot(
    flow=None, data: dict | None = None, current_state: str = "MENU"
) -> tuple[Bot, InMemoryStateStore]:
    store = InMemoryStateStore()
    connector = MockConnector()
    f = flow or OPTIONS_FLOW
    bot = Bot(flow=f, state_store=store, connector=connector)
    store.save(_state(current_state, data))
    return bot, store


# ---------------------------------------------------------------------------
# Test 1 — nested template resolution
# ---------------------------------------------------------------------------


def test_nested_template_resolves_deep_value() -> None:
    """{{data.booking_result.success}} resolves to the nested dict value."""
    data = {"booking_result": {"success": "true", "id": "abc123"}}
    msg = _msg()
    result = _resolve("Result: {{data.booking_result.success}}", msg, data)
    assert result == "Result: true"


def test_nested_template_missing_intermediate_returns_empty() -> None:
    """{{data.missing.key}} returns empty string when intermediate key absent."""
    data = {}
    msg = _msg()
    result = _resolve("{{data.missing.key}}", msg, data)
    assert result == ""


# ---------------------------------------------------------------------------
# Test 2 — on_payload_prefix match and extract_suffix_as storage
# ---------------------------------------------------------------------------


def test_prefix_match_stores_suffix() -> None:
    """on_payload_prefix 'svc_' matches 'svc_corte' and stores 'corte' in data."""
    bot, store = _make_bot(current_state="MENU")
    bot.handle_message(_msg(payload="svc_corte", message_type=MessageType.LIST_REPLY))
    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "SELECT_DAY"
    assert saved.data["selected_service"] == "corte"


def test_prefix_no_match_stays_in_state() -> None:
    """Payload without matching prefix does not trigger transition."""
    bot, store = _make_bot(current_state="MENU")
    bot.handle_message(_msg(payload="other_thing", message_type=MessageType.LIST_REPLY))
    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "MENU"


# ---------------------------------------------------------------------------
# Test 3 — service expansion after prefix match
# ---------------------------------------------------------------------------


def test_service_expansion_after_prefix_match() -> None:
    """After prefix match on 'svc_corte', service properties are expanded into data."""
    bot, store = _make_bot(current_state="MENU")
    bot.handle_message(_msg(payload="svc_corte", message_type=MessageType.LIST_REPLY))
    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.data.get("service_name") == "Corte de pelo"
    assert saved.data.get("service_duracion_min") == 30
    assert saved.data.get("service_price") == "10€"
    assert saved.data.get("service_presencia_min") == 30


def test_no_service_expansion_for_unknown_suffix() -> None:
    """Prefix match on unknown service suffix stores suffix but adds no service_ keys."""
    bot, store = _make_bot(current_state="MENU")
    bot.handle_message(_msg(payload="svc_unknown", message_type=MessageType.LIST_REPLY))
    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.data["selected_service"] == "unknown"
    assert "service_name" not in saved.data


# ---------------------------------------------------------------------------
# Test 4 — condition on transition
# ---------------------------------------------------------------------------


def test_condition_skips_transition_when_data_empty() -> None:
    """condition: 'data.selected_service' prevents transition when data is empty."""
    bot, store = _make_bot(current_state="SELECT_DAY", data={})
    bot.handle_message(_msg(payload="day_2026-06-01", message_type=MessageType.LIST_REPLY))
    saved = store.get("t1", "c1")
    assert saved is not None
    # Condition fails → falls back to MENU (SELECT_DAY fallback is MENU)
    assert saved.current_state == "MENU"


def test_condition_allows_transition_when_data_set() -> None:
    """condition: 'data.selected_service' fires transition when data has the key."""
    bot, store = _make_bot(current_state="SELECT_DAY", data={"selected_service": "corte"})
    bot.handle_message(_msg(payload="day_2026-06-01", message_type=MessageType.LIST_REPLY))
    saved = store.get("t1", "c1")
    assert saved is not None
    assert saved.current_state == "DONE"
    assert saved.data["selected_date"] == "2026-06-01"


# ---------------------------------------------------------------------------
# Test 5 — send_dynamic_options with non-empty list
# ---------------------------------------------------------------------------


def test_send_dynamic_options_produces_send_options_output() -> None:
    """send_dynamic_options action with list in state.data emits SendOptionsOutput."""
    days = [
        {"id": "day_mon", "title": "Lunes"},
        {"id": "day_tue", "title": "Martes"},
    ]
    bot, store = _make_bot(
        current_state="MENU",
        data={"available_days": days},
    )
    # Transition from MENU to SELECT_DAY; SELECT_DAY on_enter fires send_dynamic_options
    outputs = bot.handle_message(_msg(payload="svc_corte", message_type=MessageType.LIST_REPLY))
    assert any(isinstance(o, SendOptionsOutput) for o in outputs), (
        f"Expected SendOptionsOutput in outputs, got: {outputs}"
    )
    opt_output = next(o for o in outputs if isinstance(o, SendOptionsOutput))
    assert opt_output.body == "Elige día"
    assert opt_output.button_label == "Ver días"
    assert len(opt_output.options) == 2
    assert opt_output.options[0].id == "day_mon"
    assert opt_output.options[1].title == "Martes"


# ---------------------------------------------------------------------------
# Test 6 — send_dynamic_options with empty list and empty_text
# ---------------------------------------------------------------------------


def test_send_dynamic_options_empty_list_emits_empty_text() -> None:
    """send_dynamic_options with empty list and empty_text emits SendTextOutput(empty_text)."""
    bot, store = _make_bot(
        current_state="MENU",
        data={"available_days": []},
    )
    outputs = bot.handle_message(_msg(payload="svc_corte", message_type=MessageType.LIST_REPLY))
    assert any(isinstance(o, SendTextOutput) for o in outputs), (
        f"Expected SendTextOutput in outputs, got: {outputs}"
    )
    text_output = next(o for o in outputs if isinstance(o, SendTextOutput))
    assert text_output.text == "No hay días disponibles."


# ---------------------------------------------------------------------------
# Test 7 — DataProxy
# ---------------------------------------------------------------------------


def test_data_proxy_present_key_returns_value() -> None:
    proxy = DataProxy({"foo": "bar"})
    assert proxy.foo == "bar"


def test_data_proxy_missing_key_returns_none() -> None:
    proxy = DataProxy({"foo": "bar"})
    assert proxy.missing is None


def test_data_proxy_nested_dict_returns_data_proxy() -> None:
    proxy = DataProxy({"nested": {"key": "value"}})
    nested = proxy.nested
    assert isinstance(nested, DataProxy)
    assert nested.key == "value"


def test_data_proxy_nested_missing_returns_none() -> None:
    proxy = DataProxy({"nested": {"key": "value"}})
    assert proxy.nested.missing is None


def test_data_proxy_truthy_for_non_empty_string() -> None:
    proxy = DataProxy({"service": "corte"})
    assert bool(proxy.service) is True


def test_data_proxy_falsy_for_none() -> None:
    proxy = DataProxy({})
    assert bool(proxy.service) is False
