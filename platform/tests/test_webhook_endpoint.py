"""Integration tests for FastAPI webhook endpoints in data_plane.main."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from data_plane.main import create_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_APP_SECRET = "integration_test_secret"
_VERIFY_TOKEN = "integration_verify_token"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv(
        "TENANT_CONFIG_PATH",
        str(Path(__file__).parent / "configs" / "whatsapp_tenant.yaml"),
    )

    with TestClient(create_app()) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _minimal_wa_payload() -> dict:
    """Minimal WhatsApp webhook payload with no 'messages' (status update only)."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_webhook_verify_correct_token(client) -> None:
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": _VERIFY_TOKEN,
            "hub.challenge": "testchallenge",
        },
    )
    assert response.status_code == 200
    assert response.text == "testchallenge"


def test_webhook_verify_wrong_token(client) -> None:
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "testchallenge",
        },
    )
    assert response.status_code == 403


def test_webhook_post_valid_signature_returns_ok(client) -> None:
    payload = _minimal_wa_payload()
    body = json.dumps(payload).encode()
    signature = _sign(body, _APP_SECRET)

    response = client.post(
        "/webhook/whatsapp",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_post_invalid_signature_returns_401(client) -> None:
    payload = _minimal_wa_payload()
    body = json.dumps(payload).encode()

    response = client.post(
        "/webhook/whatsapp",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalidsignature",
        },
    )
    assert response.status_code == 401


def test_health_endpoint_still_works(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
