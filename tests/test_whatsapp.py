# tests/test_whatsapp.py
"""
Unit tests for services/whatsapp.py.
httpx.Client is mocked — no real network calls.
"""
import pytest
from unittest.mock import MagicMock, patch
import httpx


@pytest.fixture(autouse=True)
def mock_httpx_client():
    """Patch the module-level _client with a fresh MagicMock for every test."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    with patch("app.services.whatsapp._client", mock_client):
        yield mock_client


def get_posted_body(mock_client):
    """Helper: extract the json= kwarg from the last _client.post call."""
    return mock_client.post.call_args[1]["json"]


# ── send_text_message ──────────────────────────────────────────────────────────

class TestSendTextMessage:
    def test_returns_true_on_success(self, mock_httpx_client):
        from app.services.whatsapp import send_text_message
        assert send_text_message("34600000001", "Hola") is True

    def test_posts_correct_type(self, mock_httpx_client):
        from app.services.whatsapp import send_text_message
        send_text_message("34600000001", "Hola mundo")
        body = get_posted_body(mock_httpx_client)
        assert body["type"] == "text"
        assert body["text"]["body"] == "Hola mundo"

    def test_posts_to_correct_recipient(self, mock_httpx_client):
        from app.services.whatsapp import send_text_message
        send_text_message("34600000001", "Msg")
        body = get_posted_body(mock_httpx_client)
        assert body["to"] == "34600000001"

    def test_returns_false_on_http_error(self, mock_httpx_client):
        from app.services.whatsapp import send_text_message
        mock_httpx_client.post.return_value.raise_for_status.side_effect = (
            httpx.HTTPStatusError(
                "err",
                request=MagicMock(),
                response=MagicMock(status_code=400, text="bad"),
            )
        )
        assert send_text_message("34600000001", "Hola") is False

    def test_returns_false_on_network_error(self, mock_httpx_client):
        from app.services.whatsapp import send_text_message
        mock_httpx_client.post.side_effect = Exception("connection refused")
        assert send_text_message("34600000001", "Hola") is False

    def test_messaging_product_whatsapp(self, mock_httpx_client):
        from app.services.whatsapp import send_text_message
        send_text_message("34600000001", "Test")
        body = get_posted_body(mock_httpx_client)
        assert body["messaging_product"] == "whatsapp"


# ── send_interactive ───────────────────────────────────────────────────────────

class TestSendInteractive:
    def test_returns_true_on_success(self, mock_httpx_client):
        from app.services.whatsapp import send_interactive
        payload = {"type": "interactive", "interactive": {"type": "button"}}
        assert send_interactive("34600000001", payload) is True

    def test_payload_merged_into_body(self, mock_httpx_client):
        from app.services.whatsapp import send_interactive
        payload = {
            "type": "interactive",
            "interactive": {"type": "button", "body": {"text": "Hola"}},
        }
        send_interactive("34600000001", payload)
        body = get_posted_body(mock_httpx_client)
        assert body["type"] == "interactive"
        assert body["to"] == "34600000001"
        assert body["messaging_product"] == "whatsapp"

    def test_returns_false_on_error(self, mock_httpx_client):
        from app.services.whatsapp import send_interactive
        mock_httpx_client.post.side_effect = Exception("err")
        assert send_interactive("34600000001", {}) is False


# ── send_template ──────────────────────────────────────────────────────────────

class TestSendTemplate:
    def test_returns_true_on_success(self, mock_httpx_client):
        from app.services.whatsapp import send_template
        assert send_template("34600000001", "recordatorio_cita", "es", []) is True

    def test_correct_template_structure(self, mock_httpx_client):
        from app.services.whatsapp import send_template
        components = [{"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}]
        send_template("34600000001", "recordatorio_cita", "es", components)
        body = get_posted_body(mock_httpx_client)
        assert body["type"] == "template"
        assert body["template"]["name"] == "recordatorio_cita"
        assert body["template"]["language"]["code"] == "es"
        assert body["template"]["components"] == components

    def test_returns_false_on_error(self, mock_httpx_client):
        from app.services.whatsapp import send_template
        mock_httpx_client.post.side_effect = Exception("err")
        assert send_template("34600000001", "tmpl", "es", []) is False


# ── TestRetry429 ───────────────────────────────────────────────────────────────

def _make_429_response():
    """Helper: build a mock httpx response with status 429 and no retry-after."""
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    return resp


def _make_429_error():
    resp = _make_429_response()
    return httpx.HTTPStatusError("rate limited", request=MagicMock(), response=resp)


class TestRetry429:
    def test_retry_succeeds_on_second_attempt(self, mock_httpx_client):
        """429 on first call, success on second → returns True, called twice."""
        from app.services.whatsapp import send_text_message
        import app.services.whatsapp as wa_mod

        ok_response = MagicMock()
        ok_response.raise_for_status.return_value = None

        err_response = _make_429_response()

        call_count = {"n": 0}

        def post_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.HTTPStatusError(
                    "rate limited",
                    request=MagicMock(),
                    response=err_response,
                )
            return ok_response

        with patch.object(mock_httpx_client, "post", side_effect=post_side_effect), \
             patch.object(wa_mod, "time") as mock_time:
            mock_time.sleep.return_value = None
            result = send_text_message("34600000001", "Hola")

        assert result is True
        assert call_count["n"] == 2

    def test_exhausted_429_returns_false(self, mock_httpx_client):
        """All attempts return 429 → send_text_message returns False and
        whatsapp_errors metric is incremented."""
        from app.services.whatsapp import send_text_message
        import app.services.whatsapp as wa_mod
        from app.utils import metrics

        err_response = _make_429_response()

        def post_side_effect(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "rate limited",
                request=MagicMock(),
                response=err_response,
            )

        before = metrics._counters.get("whatsapp_errors", 0)
        with patch.object(mock_httpx_client, "post", side_effect=post_side_effect), \
             patch.object(wa_mod, "time") as mock_time:
            mock_time.sleep.return_value = None
            result = send_text_message("34600000001", "Hola")

        assert result is False
        assert metrics._counters.get("whatsapp_errors", 0) > before

    def test_retry_after_header_is_capped(self, mock_httpx_client):
        """When 429 includes Retry-After: 9999, sleep is called with at most _RETRY_AFTER_CAP."""
        from app.services.whatsapp import send_text_message, _RETRY_AFTER_CAP
        import app.services.whatsapp as wa_mod

        err_resp = MagicMock()
        err_resp.status_code = 429
        err_resp.headers = {"Retry-After": "9999"}

        def post_side_effect(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "rate limited",
                request=MagicMock(),
                response=err_resp,
            )

        sleep_calls = []

        with patch.object(mock_httpx_client, "post", side_effect=post_side_effect), \
             patch("app.services.whatsapp.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            send_text_message("34600000001", "Hola")

        assert len(sleep_calls) > 0
        assert all(s <= _RETRY_AFTER_CAP for s in sleep_calls)


# ── TestDeliveryTracking ───────────────────────────────────────────────────────

class TestDeliveryTracking:
    def test_delivered_true_after_success(self, mock_httpx_client):
        """After begin_delivery_tracking + successful send, reply_was_delivered is True."""
        from app.services.whatsapp import (
            begin_delivery_tracking, send_text_message, reply_was_delivered
        )
        begin_delivery_tracking()
        send_text_message("34600000001", "Hola")
        assert reply_was_delivered() is True

    def test_delivered_false_after_failure(self, mock_httpx_client):
        """After begin_delivery_tracking + failed send, reply_was_delivered is False."""
        from app.services.whatsapp import (
            begin_delivery_tracking, send_text_message, reply_was_delivered
        )
        mock_httpx_client.post.return_value.raise_for_status.side_effect = (
            httpx.HTTPStatusError(
                "err",
                request=MagicMock(),
                response=MagicMock(status_code=400, text="bad"),
            )
        )
        begin_delivery_tracking()
        send_text_message("34600000001", "Hola")
        assert reply_was_delivered() is False

    def test_default_true_without_tracking(self):
        """reply_was_delivered returns True when begin_delivery_tracking was never called."""
        from app.services.whatsapp import _delivery, begin_delivery_tracking, reply_was_delivered
        if hasattr(_delivery, "attempted"):
            del _delivery.attempted
        assert reply_was_delivered() is True
