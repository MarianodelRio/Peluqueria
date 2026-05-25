"""Unit tests for WhatsAppAdapter."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timezone
from unittest.mock import MagicMock

from data_plane.adapters.channel.whatsapp import WhatsAppAdapter
from data_plane.engine.outputs import (
    ButtonDef,
    ListRowDef,
    ListSectionDef,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendTextOutput,
)
from shared.domain.messages import MessageType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APP_SECRET = "test_secret"
_VERIFY_TOKEN = "test_verify_token"


def _make_adapter() -> WhatsAppAdapter:
    return WhatsAppAdapter(
        tenant_id="tenant_1",
        phone_number_id="12345",
        access_token="token_abc",
        app_secret=_APP_SECRET,
        verify_token=_VERIFY_TOKEN,
    )


def _text_payload(from_number: str, text: str, timestamp: int = 1700000000) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": from_number,
                                    "timestamp": str(timestamp),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _interactive_payload(
    from_number: str, itype: str, reply_id: str, timestamp: int = 1700000000
) -> dict:
    if itype == "button_reply":
        interactive_block = {
            "type": "button_reply",
            "button_reply": {"id": reply_id, "title": "Button title"},
        }
    else:
        interactive_block = {
            "type": "list_reply",
            "list_reply": {"id": reply_id, "title": "Row title"},
        }
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": from_number,
                                    "timestamp": str(timestamp),
                                    "type": "interactive",
                                    "interactive": interactive_block,
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _status_payload() -> dict:
    """Webhook payload with no 'messages' key (e.g., delivery status update)."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [{"id": "msg_id", "status": "delivered"}]
                        }
                    }
                ]
            }
        ]
    }


def _make_hmac(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# receive() tests
# ---------------------------------------------------------------------------


def test_receive_text_message() -> None:
    adapter = _make_adapter()
    payload = _text_payload("5491112345678", "Hello world", 1700000000)
    msg = adapter.receive(payload)

    assert msg is not None
    assert msg.message_type == MessageType.TEXT
    assert msg.text == "Hello world"
    assert msg.payload is None
    assert msg.contact_id == "5491112345678"
    assert msg.tenant_id == "tenant_1"
    assert msg.timestamp.tzinfo == timezone.utc


def test_receive_button_reply() -> None:
    adapter = _make_adapter()
    payload = _interactive_payload("5491112345678", "button_reply", "opt_book")
    msg = adapter.receive(payload)

    assert msg is not None
    assert msg.message_type == MessageType.BUTTON_REPLY
    assert msg.payload == "opt_book"
    assert msg.text is None


def test_receive_list_reply() -> None:
    adapter = _make_adapter()
    payload = _interactive_payload("5491112345678", "list_reply", "slot_09_00")
    msg = adapter.receive(payload)

    assert msg is not None
    assert msg.message_type == MessageType.LIST_REPLY
    assert msg.payload == "slot_09_00"
    assert msg.text is None


def test_receive_status_update_returns_none() -> None:
    adapter = _make_adapter()
    msg = adapter.receive(_status_payload())
    assert msg is None


def test_receive_malformed_payload_returns_none() -> None:
    adapter = _make_adapter()
    assert adapter.receive({}) is None
    assert adapter.receive({"entry": []}) is None
    assert adapter.receive({"entry": [{"changes": []}]}) is None


# ---------------------------------------------------------------------------
# verify_signature() tests
# ---------------------------------------------------------------------------


def test_verify_signature_correct_hmac() -> None:
    adapter = _make_adapter()
    body = b'{"test": "payload"}'
    sig = _make_hmac(_APP_SECRET, body)
    assert adapter.verify_signature(body, sig) is True


def test_verify_signature_wrong_signature() -> None:
    adapter = _make_adapter()
    body = b'{"test": "payload"}'
    assert adapter.verify_signature(body, "sha256=deadbeef") is False


def test_verify_signature_empty_app_secret() -> None:
    adapter = WhatsAppAdapter(
        tenant_id="t",
        phone_number_id="p",
        access_token="a",
        app_secret="",
        verify_token="v",
    )
    body = b'{"test": "payload"}'
    sig = _make_hmac("something", body)
    assert adapter.verify_signature(body, sig) is False


def test_verify_signature_empty_signature_header() -> None:
    adapter = _make_adapter()
    body = b'{"test": "payload"}'
    assert adapter.verify_signature(body, "") is False


# ---------------------------------------------------------------------------
# send() tests
# ---------------------------------------------------------------------------


def _adapter_with_mock_client(status_code: int = 200) -> tuple[WhatsAppAdapter, MagicMock]:
    adapter = _make_adapter()
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = "error body"
    adapter._client = MagicMock()
    adapter._client.post.return_value = mock_response
    return adapter, adapter._client


def test_send_text_output_posts_correct_body() -> None:
    adapter, mock_client = _adapter_with_mock_client()
    output = SendTextOutput(text="Hello!")
    adapter.send("5491112345678", output)

    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "5491112345678"
    assert body["type"] == "text"
    assert body["text"]["body"] == "Hello!"
    assert body["text"]["preview_url"] is False


def test_send_interactive_buttons_output_posts_correct_body() -> None:
    adapter, mock_client = _adapter_with_mock_client()
    output = SendInteractiveButtonsOutput(
        body="Choose an option:",
        buttons=(
            ButtonDef(id="btn_1", title="Option 1"),
            ButtonDef(id="btn_2", title="Option 2"),
        ),
    )
    adapter.send("5491112345678", output)

    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["type"] == "interactive"
    interactive = body["interactive"]
    assert interactive["type"] == "button"
    assert interactive["body"]["text"] == "Choose an option:"
    buttons = interactive["action"]["buttons"]
    assert len(buttons) == 2
    assert buttons[0]["reply"]["id"] == "btn_1"
    assert buttons[1]["reply"]["title"] == "Option 2"


def test_send_interactive_list_output_posts_correct_body() -> None:
    adapter, mock_client = _adapter_with_mock_client()
    output = SendInteractiveListOutput(
        body="Pick a slot:",
        button_label="View slots",
        sections=(
            ListSectionDef(
                title="Morning",
                rows=(
                    ListRowDef(id="slot_09", title="09:00", description="Available"),
                    ListRowDef(id="slot_10", title="10:00", description="Available"),
                ),
            ),
        ),
    )
    adapter.send("5491112345678", output)

    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["type"] == "interactive"
    interactive = body["interactive"]
    assert interactive["type"] == "list"
    assert interactive["body"]["text"] == "Pick a slot:"
    assert interactive["action"]["button"] == "View slots"
    sections = interactive["action"]["sections"]
    assert len(sections) == 1
    assert sections[0]["title"] == "Morning"
    rows = sections[0]["rows"]
    assert len(rows) == 2
    assert rows[0]["id"] == "slot_09"
    assert rows[1]["description"] == "Available"


def test_send_http_4xx_does_not_raise() -> None:
    adapter, _ = _adapter_with_mock_client(status_code=400)
    # Must not raise
    adapter.send("5491112345678", SendTextOutput(text="Hi"))


def test_send_http_5xx_does_not_raise() -> None:
    adapter, _ = _adapter_with_mock_client(status_code=500)
    # Must not raise
    adapter.send("5491112345678", SendTextOutput(text="Hi"))
