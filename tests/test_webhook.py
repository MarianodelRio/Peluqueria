# tests/test_webhook.py
"""
Unit tests for handlers/webhook.py.
FastAPI test client + mocked handle_message.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from fastapi import FastAPI

from app.handlers.webhook import router, _deduplicator

# Minimal app for testing
_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)

VERIFY_TOKEN = "test_token"


@pytest.fixture(autouse=True)
def clear_dedup():
    """Reset deduplication cache between tests."""
    _deduplicator._seen.clear()
    yield
    _deduplicator._seen.clear()


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
                  interactive_id=None, msg_id="msg_001", user_id=""):
    """Helper to build a WhatsApp webhook payload."""
    msg = {"from": phone, "id": msg_id, "type": msg_type, "user_id": user_id}
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
            identifier="34600000001", phone="34600000001",
            text="Hola", interactive_id=None
        )

    def test_button_reply_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "interactive",
                                 interactive_type="button_reply",
                                 interactive_id="menu_book")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            identifier="34600000001", phone="34600000001",
            text=None, interactive_id="menu_book"
        )

    def test_list_reply_dispatched(self, mock_handle):
        payload = _make_payload("34600000001", "interactive",
                                 interactive_type="list_reply",
                                 interactive_id="day_2026-03-23")
        client.post("/webhook", json=payload)
        mock_handle.assert_called_once_with(
            identifier="34600000001", phone="34600000001",
            text=None, interactive_id="day_2026-03-23"
        )

    def test_unknown_message_type_sends_fallback(self, mock_handle):
        payload = _make_payload("34600000001", "audio")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            identifier="34600000001", phone="34600000001",
            text="__unknown__", interactive_id=None
        )

    def test_duplicate_message_id_skipped(self, mock_handle):
        payload = _make_payload(
            "34600000001", "text", body_text="Hola", msg_id="dup_001"
        )
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
        client.post("/webhook", json=payload)
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

    def test_multiple_entries_each_dispatched_once(self, mock_handle):
        """Payload with 2 'entry' items, each with one message, dispatches both."""
        payload = {
            "entry": [
                {"changes": [{"value": {"messages": [
                    {"from": "34600000001", "id": "multi_1", "type": "text",
                     "text": {"body": "Hola"}}
                ]}}]},
                {"changes": [{"value": {"messages": [
                    {"from": "34600000002", "id": "multi_2", "type": "text",
                     "text": {"body": "Adios"}}
                ]}}]},
            ]
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert mock_handle.call_count == 2

    def test_multiple_changes_in_single_entry_each_dispatched_once(self, mock_handle):
        """Payload with 1 'entry' but 2 'changes', each with one message,
        dispatches both."""
        payload = {
            "entry": [{"changes": [
                {"value": {"messages": [
                    {"from": "34600000003", "id": "multi_3", "type": "text",
                     "text": {"body": "Hola"}}
                ]}},
                {"value": {"messages": [
                    {"from": "34600000004", "id": "multi_4", "type": "text",
                     "text": {"body": "Adios"}}
                ]}},
            ]}]
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert mock_handle.call_count == 2


class TestWebhookDedupBeforeRateLimit:
    """Change 6: dedup must run before rate limiting, with a forget() escape
    hatch so a rate-limited message can be redelivered later."""

    def test_duplicate_does_not_consume_rate_limiter_budget(self, mock_handle):
        from app.handlers.webhook import ip_rate_limiter, phone_rate_limiter
        identifier = "34611112222"
        phone_rate_limiter.reset(identifier)
        try:
            first = _make_payload(identifier, "text", body_text="Hola",
                                  msg_id="rl_dup_1")
            client.post("/webhook", json=first)  # consumes 1 of 20

            # Flood retries of the SAME message_id — must be skipped by dedup
            # without touching the rate limiter budget.
            for _ in range(25):
                client.post("/webhook", json=first)

            # A genuinely new message must still get through — proves the
            # duplicate flood never consumed rate-limiter budget.
            second = _make_payload(identifier, "text", body_text="Adios",
                                   msg_id="rl_dup_2")
            resp = client.post("/webhook", json=second)
            assert resp.status_code == 200
            assert mock_handle.call_count == 2
        finally:
            phone_rate_limiter.reset(identifier)
            ip_rate_limiter.reset("testclient")

    def test_rate_limited_message_redelivered_after_forget(self, mock_handle):
        from app.handlers.webhook import ip_rate_limiter, phone_rate_limiter
        identifier = "34633334444"
        phone_rate_limiter.reset(identifier)
        try:
            # Exhaust the phone rate limiter budget (limit=20) with distinct ids.
            for i in range(20):
                payload = _make_payload(identifier, "text", body_text="x",
                                        msg_id=f"rl_fill_{i}")
                client.post("/webhook", json=payload)
            assert mock_handle.call_count == 20

            # Next message is rejected by rate limiting.
            rejected = _make_payload(identifier, "text", body_text="rejected",
                                     msg_id="rl_rejected")
            client.post("/webhook", json=rejected)
            assert mock_handle.call_count == 20

            # Once the limiter allows traffic again, the SAME message_id must
            # still be deliverable — proves forget() was called on rejection.
            phone_rate_limiter.reset(identifier)
            client.post("/webhook", json=rejected)
            assert mock_handle.call_count == 21
        finally:
            phone_rate_limiter.reset(identifier)
            ip_rate_limiter.reset("testclient")


class TestWebhookBsuid:
    """Tests for BSUID (Business-Scoped User ID) identifier handling."""

    BSUID = "ES.1A2B3C4D5E6F"
    PHONE = "34600000001"

    def test_bsuid_in_user_id_phone_in_from(self, mock_handle):
        """BSUID in user_id, phone digits in from → identifier=BSUID, phone=phone."""
        payload = _make_payload(self.PHONE, "text", body_text="Hola",
                                user_id=self.BSUID, msg_id="bsuid_001")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            identifier=self.BSUID, phone=self.PHONE,
            text="Hola", interactive_id=None
        )

    def test_bsuid_in_both_user_id_and_from(self, mock_handle):
        """BSUID in both user_id and from → identifier=BSUID, phone=None."""
        payload = _make_payload(self.BSUID, "text", body_text="Hola",
                                user_id=self.BSUID, msg_id="bsuid_002")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            identifier=self.BSUID, phone=None,
            text="Hola", interactive_id=None
        )

    def test_phone_only_no_user_id_backward_compat(self, mock_handle):
        """Only from with phone digits, no user_id → identifier=phone, phone=phone."""
        payload = _make_payload(self.PHONE, "text", body_text="Hola",
                                msg_id="bsuid_003")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            identifier=self.PHONE, phone=self.PHONE,
            text="Hola", interactive_id=None
        )

    def test_invalid_user_id_not_dispatched(self, mock_handle):
        """Invalid user_id (matches neither phone nor BSUID) → not dispatched."""
        payload = _make_payload(self.PHONE, "text", body_text="Hola",
                                user_id="!invalid!", msg_id="bsuid_004")
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_not_called()

    def test_valid_bsuid_in_user_id_no_from(self, mock_handle):
        """No from field, valid user_id → identifier=BSUID, phone=None."""
        msg = {"id": "bsuid_005", "type": "text", "text": {"body": "Hola"},
               "user_id": self.BSUID}
        payload = {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(
            identifier=self.BSUID, phone=None,
            text="Hola", interactive_id=None
        )
