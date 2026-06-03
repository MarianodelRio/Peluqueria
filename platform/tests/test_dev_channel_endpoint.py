"""Integration tests for the HTTP Dev channel endpoints via TestClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from data_plane.main import create_app

_DEV_CONFIG = str(Path(__file__).parent / "configs" / "dev_tenant.yaml")
_WA_CONFIG = str(Path(__file__).parent / "configs" / "whatsapp_tenant.yaml")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dev_client(monkeypatch, tmp_path):
    monkeypatch.setenv("TENANT_CONFIG_PATH", _DEV_CONFIG)
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def wa_client(monkeypatch, tmp_path):
    monkeypatch.setenv("TENANT_CONFIG_PATH", _WA_CONFIG)
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    with TestClient(create_app()) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_inbound_text_then_get_messages(dev_client):
    """POST a text message; GET /messages should return at least one message."""
    resp = dev_client.post(
        "/inbound",
        json={"contact_id": "user1", "type": "text", "text": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    resp2 = dev_client.get("/messages")
    assert resp2.status_code == 200
    data = resp2.json()
    assert "messages" in data
    assert len(data["messages"]) > 0


def test_multi_turn_advances_state(dev_client):
    """3-turn conversation driving the toy_flow to the CONFIRM state."""
    contact = "user_multi"

    # Turn 1: any text — bot is in MENU (on_enter fires)
    # The bot sends welcome text + buttons on entering MENU
    dev_client.post(
        "/inbound",
        json={"contact_id": contact, "type": "text", "text": "start"},
    )
    dev_client.get("/messages")  # drain

    # Turn 2: select "Book" button — transitions MENU → ENTER_NAME
    dev_client.post(
        "/inbound",
        json={"contact_id": contact, "type": "button_reply", "payload": "opt_book"},
    )
    dev_client.get("/messages")  # drain

    # Turn 3: enter a name — transitions ENTER_NAME → CONFIRM
    dev_client.post(
        "/inbound",
        json={"contact_id": contact, "type": "text", "text": "Maria"},
    )
    msgs_resp = dev_client.get("/messages")
    msgs = msgs_resp.json()["messages"]

    # CONFIRM state sends "Slots ready." text
    texts = [m["text"] for m in msgs if m.get("type") == "text"]
    assert any("Slots ready" in t for t in texts)


def test_drain_on_second_get_returns_empty(dev_client):
    """The second GET /messages call returns an empty list after the first drains."""
    dev_client.post(
        "/inbound",
        json={"contact_id": "user2", "type": "text", "text": "hi"},
    )
    first = dev_client.get("/messages").json()["messages"]
    assert len(first) > 0

    second = dev_client.get("/messages").json()["messages"]
    assert second == []


def test_dev_endpoints_absent_when_whatsapp_config(wa_client):
    """/inbound and /messages are 404 when the channel is whatsapp."""
    resp_inbound = wa_client.post(
        "/inbound",
        json={"contact_id": "user1", "type": "text", "text": "hi"},
    )
    assert resp_inbound.status_code == 404

    resp_messages = wa_client.get("/messages")
    assert resp_messages.status_code == 404


def test_whatsapp_endpoints_absent_when_dev_config(dev_client):
    """/webhook/whatsapp is 404 when the channel is http_dev."""
    resp = dev_client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "anything",
            "hub.challenge": "ch",
        },
    )
    assert resp.status_code == 404


def test_chat_ui_served_for_dev_channel(dev_client):
    response = dev_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "x-data" in response.text


def test_chat_ui_absent_for_whatsapp_channel(wa_client):
    response = wa_client.get("/")
    assert response.status_code == 404
