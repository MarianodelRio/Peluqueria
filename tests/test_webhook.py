# tests/test_webhook.py
"""
Unit tests for handlers/webhook.py.
FastAPI test client + mocked handle_message.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi import FastAPI

from app.handlers.webhook import router, _processed_ids

# Minimal app for testing
_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

VERIFY_TOKEN = "test_token"


@pytest.fixture(autouse=True)
def clear_dedup():
    """Reset deduplication cache between tests."""
    _processed_ids.clear()
    yield
    _processed_ids.clear()


@pytest.fixture
def mock_handle():
    with patch("app.handlers.webhook.handle_message") as m:
        yield m


# ── GET /webhook (verification) ────────────────────────────────────────────────

class TestWebhookVerification:
    def test_valid_verification(self):
        with patch("app.handlers.webhook.WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN):
            resp = client.get("/webhook", params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "my_challenge_123",
            })
        assert resp.status_code == 200
        assert resp.text == "my_challenge_123"

    def test_wrong_token_returns_403(self):
        with patch("app.handlers.webhook.WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN):
            resp = client.get("/webhook", params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "ch",
            })
        assert resp.status_code == 403

    def test_wrong_mode_returns_403(self):
        with patch("app.handlers.webhook.WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN):
            resp = client.get("/webhook", params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "ch",
            })
        assert resp.status_code == 403

    def test_missing_params_returns_403(self):
        resp = client.get("/webhook")
        assert resp.status_code == 403


# ── POST /webhook (message reception) ──────────────────────────────────────────

def _make_payload(phone, msg_type, body_text=None, interactive_type=None,
                  interactive_id=None, msg_id="msg_001"):
    """Helper to build a WhatsApp webhook payload."""
    msg = {"from": phone, "id": msg_id, "type": msg_type}
    if msg_type == "text":
        msg["text"] = {"body": body_text}
    elif msg_type == "interactive":
        if interactive_type == "button_reply":
            msg["interactive"] = {"type": "button_reply",
                                   "button_reply": {"id": interactive_id}}
        elif interactive_type == "list_reply":
            msg["interactive"] = {"type": "list_reply",
                                   "list_reply": {"id": interactive_id}}
    return {
        "entry": [{"changes": [{"value": {"messages": [msg]}}]}]
    }


class TestWebhookPost:
    def test_text_message_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "text", body_text="Hola")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_handle.assert_called_once_with(
            phone="34600000001", text="Hola", interactive_id=None
        )

    def test_button_reply_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "interactive",
                                 interactive_type="button_reply",
                                 interactive_id="menu_book")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            phone="34600000001", text=None, interactive_id="menu_book"
        )

    def test_list_reply_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "interactive",
                                 interactive_type="list_reply",
                                 interactive_id="day_2026-03-23")
        resp = client.post("/webhook", json=payload)
        mock_handle.assert_called_once_with(
            phone="34600000001", text=None, interactive_id="day_2026-03-23"
        )

    def test_unknown_message_type_sends_fallback(self, mock_handle):
        payload = _make_payload("34600000001", "audio")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            phone="34600000001", text="__unknown__", interactive_id=None
        )

    def test_duplicate_message_id_skipped(self, mock_handle):
        payload = _make_payload("34600000001", "text", body_text="Hola", msg_id="dup_001")
        # First delivery
        client.post("/webhook", json=payload)
        # WhatsApp retry (same message_id)
        client.post("/webhook", json=payload)
        # handle_message called only once
        assert mock_handle.call_count == 1

    def test_different_message_ids_both_dispatched(self, mock_handle):
        p1 = _make_payload("34600000001", "text", body_text="Hola", msg_id="msg_A")
        p2 = _make_payload("34600000001", "text", body_text="Adios", msg_id="msg_B")
        client.post("/webhook", json=p1)
        client.post("/webhook", json=p2)
        assert mock_handle.call_count == 2

    def test_empty_payload_returns_ok(self, mock_handle):
        resp = client.post("/webhook", json={})
        assert resp.status_code == 200
        mock_handle.assert_not_called()

    def test_invalid_json_returns_ok(self):
        resp = client.post("/webhook", content=b"not json",
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 200

    def test_empty_text_body_not_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "text", body_text="   ")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_not_called()

    def test_empty_interactive_id_not_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "interactive",
                                 interactive_type="button_reply",
                                 interactive_id="")
        resp = client.post("/webhook", json=payload)
        mock_handle.assert_not_called()

    def test_missing_phone_not_dispatched(self, mock_handle):
        payload = {
            "entry": [{"changes": [{"value": {"messages": [
                {"id": "m1", "type": "text", "text": {"body": "hi"}}   # no "from"
            ]}}]}]
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_not_called()

    def test_no_messages_in_payload_returns_ok(self, mock_handle):
        """Payload with no messages key returns 200 and doesn't dispatch."""
        payload = {"entry": [{"changes": [{"value": {}}]}]}
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_not_called()
