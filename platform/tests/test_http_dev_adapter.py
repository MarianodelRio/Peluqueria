"""Unit tests for HttpDevChannelAdapter — no FastAPI app required."""

from __future__ import annotations

import pytest

from data_plane.adapters.channel.http_dev import HttpDevChannelAdapter
from data_plane.engine.outputs import (
    ButtonDef,
    ListRowDef,
    ListSectionDef,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendTextOutput,
)
from shared.domain.messages import MessageType


@pytest.fixture()
def adapter() -> HttpDevChannelAdapter:
    return HttpDevChannelAdapter("test_tenant")


# ---------------------------------------------------------------------------
# receive() tests
# ---------------------------------------------------------------------------


def test_receive_text_returns_internal_message(adapter):
    msg = adapter.receive({"contact_id": "user1", "type": "text", "text": "hello"})
    assert msg is not None
    assert msg.contact_id == "user1"
    assert msg.message_type == MessageType.TEXT
    assert msg.text == "hello"
    assert msg.payload is None
    assert msg.tenant_id == "test_tenant"


def test_receive_button_reply(adapter):
    msg = adapter.receive(
        {"contact_id": "user1", "type": "button_reply", "payload": "opt_book"}
    )
    assert msg is not None
    assert msg.message_type == MessageType.BUTTON_REPLY
    assert msg.payload == "opt_book"
    assert msg.text is None


def test_receive_list_reply(adapter):
    msg = adapter.receive(
        {"contact_id": "user1", "type": "list_reply", "payload": "item_1"}
    )
    assert msg is not None
    assert msg.message_type == MessageType.LIST_REPLY
    assert msg.payload == "item_1"
    assert msg.text is None


def test_receive_missing_contact_id_returns_none(adapter):
    result = adapter.receive({"type": "text", "text": "hello"})
    assert result is None


def test_receive_text_missing_text_field_returns_none(adapter):
    result = adapter.receive({"contact_id": "user1", "type": "text"})
    assert result is None


# ---------------------------------------------------------------------------
# send() / drain() tests
# ---------------------------------------------------------------------------


def test_send_enqueues_serialized_output(adapter):
    adapter.send("user1", SendTextOutput(text="Hi there"))
    items = adapter.drain()
    assert len(items) == 1
    assert items[0]["type"] == "text"
    assert items[0]["text"] == "Hi there"
    assert items[0]["contact_id"] == "user1"


def test_drain_clears_queue(adapter):
    adapter.send("user1", SendTextOutput(text="First"))
    first_drain = adapter.drain()
    assert len(first_drain) == 1
    second_drain = adapter.drain()
    assert second_drain == []


def test_drain_empty_queue(adapter):
    assert adapter.drain() == []


# ---------------------------------------------------------------------------
# verify_signature() test
# ---------------------------------------------------------------------------


def test_verify_signature_always_true(adapter):
    assert adapter.verify_signature(b"any body", "any_sig") is True
    assert adapter.verify_signature(b"", "") is True


# ---------------------------------------------------------------------------
# send() serialisation tests for complex output types
# ---------------------------------------------------------------------------


def test_send_buttons_serialized_correctly(adapter):
    output = SendInteractiveButtonsOutput(
        body="Choose an option",
        buttons=(
            ButtonDef(id="btn_a", title="Option A"),
            ButtonDef(id="btn_b", title="Option B"),
        ),
    )
    adapter.send("user1", output)
    items = adapter.drain()
    assert len(items) == 1
    item = items[0]
    assert item["type"] == "interactive_buttons"
    assert item["body"] == "Choose an option"
    assert item["contact_id"] == "user1"
    assert len(item["buttons"]) == 2
    assert item["buttons"][0] == {"id": "btn_a", "title": "Option A"}
    assert item["buttons"][1] == {"id": "btn_b", "title": "Option B"}


def test_send_list_serialized_correctly(adapter):
    output = SendInteractiveListOutput(
        body="Pick a slot",
        button_label="View slots",
        sections=(
            ListSectionDef(
                title="Morning",
                rows=(
                    ListRowDef(id="slot_9", title="09:00", description="Available"),
                    ListRowDef(id="slot_10", title="10:00", description=""),
                ),
            ),
        ),
    )
    adapter.send("user1", output)
    items = adapter.drain()
    assert len(items) == 1
    item = items[0]
    assert item["type"] == "interactive_list"
    assert item["body"] == "Pick a slot"
    assert item["button_label"] == "View slots"
    assert item["contact_id"] == "user1"
    assert len(item["sections"]) == 1
    section = item["sections"][0]
    assert section["title"] == "Morning"
    assert len(section["rows"]) == 2
    assert section["rows"][0] == {"id": "slot_9", "title": "09:00", "description": "Available"}
    assert section["rows"][1] == {"id": "slot_10", "title": "10:00", "description": ""}
