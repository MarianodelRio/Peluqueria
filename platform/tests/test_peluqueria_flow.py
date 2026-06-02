"""Integration tests for the peluqueria flow using MockCalendarAdapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from data_plane.adapters.connectors.mock_calendar import MockCalendarAdapter
from data_plane.main import create_app

_PELO_CONFIG = str(Path(__file__).parent / "configs" / "peluqueria_dev_tenant.yaml")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pelo_client(monkeypatch, tmp_path):
    monkeypatch.setenv("TENANT_CONFIG_PATH", _PELO_CONFIG)
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    with TestClient(create_app()) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_menu_book_returns_service_list(pelo_client):
    """Selecting 'Reservar cita' from MENU navigates to BOOK_SELECT_SERVICE with service buttons."""
    pelo_client.post(
        "/inbound",
        json={"contact_id": "c1", "type": "button_reply", "payload": "menu_book"},
    )
    msgs = pelo_client.get("/messages").json()["messages"]
    assert any(m.get("type") == "interactive_buttons" for m in msgs)
    # Ensure service options are present in the buttons
    button_ids = [
        b["id"]
        for m in msgs
        if m.get("type") == "interactive_buttons"
        for b in m.get("buttons", [])
    ]
    assert "service_corte" in button_ids


def test_full_booking_flow(monkeypatch, tmp_path):
    """Navigate the full booking flow and assert the confirmation message is shown."""
    available_days = [{"id": "day_2025-03-10", "title": "Lun 10 mar"}]
    available_slots = [{"id": "hour_2025-03-10_1000", "title": "10:00"}]
    book_result = {
        "success": True,
        "event_id": "evt_abc",
        "message": "Cita reservada el lun 10 mar a las 10:00",
    }
    mock = MockCalendarAdapter(
        preset_available_days=available_days,
        preset_slots_for_day=available_slots,
        preset_book_result=book_result,
    )
    monkeypatch.setenv("TENANT_CONFIG_PATH", _PELO_CONFIG)
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        "data_plane.main.MockCalendarAdapter",
        lambda **kwargs: mock,
    )

    with TestClient(create_app()) as client:
        contact = "c_full"

        # Step 1: select "Reservar cita" -> BOOK_SELECT_SERVICE
        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "menu_book"},
        )
        client.get("/messages")  # drain

        # Step 2: select service -> BOOK_SELECT_DAY (mock returns available_days)
        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "service_corte"},
        )
        client.get("/messages")  # drain

        # Step 3: select day -> BOOK_SELECT_PERIOD
        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "day_2025-03-10"},
        )
        client.get("/messages")  # drain

        # Step 4: select morning -> BOOK_SELECT_HOUR (mock returns available_slots)
        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "period_morning"},
        )
        client.get("/messages")  # drain

        # Step 5: select hour -> BOOK_ENTER_NAME
        client.post(
            "/inbound",
            json={
                "contact_id": contact,
                "type": "button_reply",
                "payload": "hour_2025-03-10_1000",
            },
        )
        client.get("/messages")  # drain

        # Step 6: enter name -> BOOK_CONFIRM (mock books, returns preset message)
        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "text", "text": "Juan"},
        )
        msgs = client.get("/messages").json()["messages"]

    texts = [m.get("text", "") for m in msgs if m.get("type") == "text"]
    assert any("Cita" in t for t in texts), f"Expected 'Cita' in texts: {texts}"


def test_view_appointments_empty(pelo_client):
    """MockCalendarAdapter returns [] for get_future_appointments -> empty_text shown."""
    pelo_client.post(
        "/inbound",
        json={"contact_id": "c1", "type": "button_reply", "payload": "menu_view"},
    )
    msgs = pelo_client.get("/messages").json()["messages"]
    texts = [m.get("text", "") for m in msgs if m.get("type") == "text"]
    assert any("No tienes citas" in t for t in texts), f"Expected empty text, got: {texts}"


def test_cancel_flow(monkeypatch, tmp_path):
    """MockCalendarAdapter with one appointment preset; selecting it sends cancellation message."""
    appts = [{"id": "cancel_appt_evt_xyz", "title": "Lun 10 mar · 10:00 · Corte"}]
    mock = MockCalendarAdapter(preset_appointments=appts)
    monkeypatch.setenv("TENANT_CONFIG_PATH", _PELO_CONFIG)
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        "data_plane.main.MockCalendarAdapter",
        lambda **kwargs: mock,
    )

    with TestClient(create_app()) as client:
        contact = "c_cancel"

        # Navigate to CANCEL_SELECT
        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "menu_cancel"},
        )
        client.get("/messages")  # drain

        # Select the appointment to cancel -> CANCEL_CONFIRM
        client.post(
            "/inbound",
            json={
                "contact_id": contact,
                "type": "button_reply",
                "payload": "cancel_appt_evt_xyz",
            },
        )
        msgs = client.get("/messages").json()["messages"]

    texts = [m.get("text", "") for m in msgs if m.get("type") == "text"]
    assert any("cancelada" in t for t in texts), f"Expected 'cancelada' in texts: {texts}"


def test_slot_unavailable(monkeypatch, tmp_path):
    """MockCalendarAdapter with preset_book_result success=False shows error message."""
    available_days = [{"id": "day_2025-03-10", "title": "Lun 10 mar"}]
    available_slots = [{"id": "hour_2025-03-10_1000", "title": "10:00"}]
    book_result = {
        "success": False,
        "event_id": None,
        "message": "Ese horario ya no está disponible",
    }
    mock = MockCalendarAdapter(
        preset_available_days=available_days,
        preset_slots_for_day=available_slots,
        preset_book_result=book_result,
    )
    monkeypatch.setenv("TENANT_CONFIG_PATH", _PELO_CONFIG)
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        "data_plane.main.MockCalendarAdapter",
        lambda **kwargs: mock,
    )

    with TestClient(create_app()) as client:
        contact = "c_unavail"

        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "menu_book"},
        )
        client.get("/messages")  # drain

        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "service_corte"},
        )
        client.get("/messages")  # drain

        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "day_2025-03-10"},
        )
        client.get("/messages")  # drain

        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "button_reply", "payload": "period_morning"},
        )
        client.get("/messages")  # drain

        client.post(
            "/inbound",
            json={
                "contact_id": contact,
                "type": "button_reply",
                "payload": "hour_2025-03-10_1000",
            },
        )
        client.get("/messages")  # drain

        client.post(
            "/inbound",
            json={"contact_id": contact, "type": "text", "text": "Ana"},
        )
        msgs = client.get("/messages").json()["messages"]

    texts = [m.get("text", "") for m in msgs if m.get("type") == "text"]
    assert any("disponible" in t for t in texts), f"Expected unavailability message, got: {texts}"
