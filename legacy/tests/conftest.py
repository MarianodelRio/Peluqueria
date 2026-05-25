# tests/conftest.py
"""
Shared fixtures and helpers for the test suite.
All external dependencies (Google Calendar API, WhatsApp API, httpx) are mocked
so tests run without credentials or network access.
"""
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch
import pytz

TZ = pytz.timezone("Europe/Madrid")


# ── Datetime helpers ────────────────────────────────────────────────────────

def aware_dt(year, month, day, hour=0, minute=0):
    """Return a Madrid-aware datetime."""
    return TZ.localize(datetime(year, month, day, hour, minute))


def make_event(event_id="evt1", title="Cita - Test", description="",
               start_dt=None, end_dt=None, all_day=False):
    """Build a fake Google Calendar event dict (as returned by _get_day_events)."""
    if start_dt is None:
        start_dt = aware_dt(2026, 3, 23, 10, 0)
    if end_dt is None:
        end_dt = aware_dt(2026, 3, 23, 10, 30)
    return {
        "id": event_id,
        "title": title,
        "description": description,
        "start": start_dt,
        "end": end_dt,
        "all_day": all_day,
    }


def make_cita_description(nombre="Ana García", telefono="34600000001",
                           estado="confirmada", recordatorio="no", servicio=None):
    desc = (
        f"Nombre: {nombre}\n"
        f"Telefono: {telefono}\n"
    )
    if servicio is not None:
        desc += f"Servicio: {servicio}\n"
    desc += (
        f"Estado: {estado}\n"
        f"Recordatorio: {recordatorio}"
    )
    return desc


# ── Common mock fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_wa(monkeypatch):
    """Patch all WhatsApp send functions to no-ops returning True."""
    with patch("app.services.whatsapp.send_text_message", return_value=True) as txt, \
         patch("app.services.whatsapp.send_interactive", return_value=True) as inter, \
         patch("app.services.whatsapp.send_template", return_value=True) as tmpl:
        yield {"text": txt, "interactive": inter, "template": tmpl}


@pytest.fixture
def mock_cal(monkeypatch):
    """Patch calendar service functions used by conversation handler."""
    with patch("app.services.calendar.get_slots_disponibles", return_value=[]) as slots, \
         patch("app.services.calendar.get_citas_futuras", return_value=[]) as futuras, \
         patch("app.services.calendar.reservar_cita", return_value=("evt_new", None)) as reservar, \
         patch("app.services.calendar.cancelar_cita", return_value=True) as cancelar, \
         patch("app.services.calendar.confirmar_cita", return_value=True) as confirmar:
        yield {
            "slots": slots,
            "futuras": futuras,
            "reservar": reservar,
            "cancelar": cancelar,
            "confirmar": confirmar,
        }
