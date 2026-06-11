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
