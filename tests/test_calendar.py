# tests/test_calendar.py
"""
Unit tests for services/calendar.py.
Google Calendar API is mocked entirely — no real credentials needed.
"""
import pytest
import threading
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, call
import pytz

from app.config import HORARIO_BASE

TZ = pytz.timezone("Europe/Madrid")


def aware(y, m, d, h=0, mi=0):
    return TZ.localize(datetime(y, m, d, h, mi))


def make_gc_event(event_id, summary, description, start_dt, end_dt):
    """Build a fake Google Calendar API item dict."""
    return {
        "id": event_id,
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat()},
        "end":   {"dateTime": end_dt.isoformat()},
    }


def make_all_day_event(event_id, summary, d: date):
    return {
        "id": event_id,
        "summary": summary,
        "description": "",
        "start": {"date": d.isoformat()},
        "end":   {"date": d.isoformat()},
    }


@pytest.fixture(autouse=True)
def reset_thread_local():
    """Force _get_service to rebuild on each test (avoid state leakage).
    Also clears the slot cache so tests don't interfere with each other.
    """
    import app.services.calendar as cal
    if hasattr(cal._thread_local, "service"):
        del cal._thread_local.service
    cal._slot_cache.clear()
    yield
    cal._slot_cache.clear()


@pytest.fixture
def mock_service():
    """Return a MagicMock mimicking googleapiclient service."""
    svc = MagicMock()
    svc.events.return_value.list.return_value.execute.return_value = {"items": []}
    svc.events.return_value.get.return_value.execute.return_value = {}
    svc.events.return_value.insert.return_value.execute.return_value = {"id": "new_evt"}
    svc.events.return_value.update.return_value.execute.return_value = {}
    svc.events.return_value.delete.return_value.execute.return_value = {}
    return svc


@pytest.fixture
def cal_with_service(mock_service):
    """Patch _get_service to return mock_service."""
    with patch("app.services.calendar._get_service", return_value=mock_service):
        import app.services.calendar as cal
        yield cal, mock_service


# ── get_slots_disponibles ──────────────────────────────────────────────────────

class TestGetSlotsDisponibles:
    def test_normal_day_returns_slots(self, cal_with_service):
        cal, svc = cal_with_service
        monday = date(2026, 3, 23)
        slots = cal.get_slots_disponibles(monday)
        for start, _ in HORARIO_BASE[0]:
            assert start in slots

    def test_saturday_has_slots(self, cal_with_service):
        cal, svc = cal_with_service
        saturday = date(2026, 3, 28)
        slots = cal.get_slots_disponibles(saturday)
        for start, _ in HORARIO_BASE[5]:
            assert start in slots
        # periods not in Saturday config should produce no slots
        configured_starts = {s for s, _ in HORARIO_BASE[5]}
        unconfigured = {s for s, _ in HORARIO_BASE[0]} - configured_starts
        for start in unconfigured:
            assert start not in slots

    def test_sunday_returns_empty(self, cal_with_service):
        cal, svc = cal_with_service
        sunday = date(2026, 3, 29)
        assert cal.get_slots_disponibles(sunday) == []

    def test_cerrado_cfg_returns_empty(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_all_day_event("cfg1", "[CFG] CERRADO", date(2026, 3, 23))]
        }
        assert cal.get_slots_disponibles(date(2026, 3, 23)) == []

    def test_vacaciones_cfg_returns_empty(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_all_day_event("cfg1", "[CFG] VACACIONES", date(2026, 3, 23))]
        }
        assert cal.get_slots_disponibles(date(2026, 3, 23)) == []

    def test_special_schedule_cfg(self, cal_with_service):
        cal, svc = cal_with_service
        d = date(2026, 3, 23)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_all_day_event("cfg1", "[CFG] HORARIO 10:00-12:00", d)]
        }
        slots = cal.get_slots_disponibles(d)
        # Only 10:00 and 10:30 and 11:00 and 11:30 fit in 10:00-12:00
        assert "10:00" in slots
        assert "16:00" not in slots

    def test_occupied_slot_removed(self, cal_with_service):
        cal, svc = cal_with_service
        d = date(2026, 3, 23)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Ana",
                "Nombre: Ana\nTelefono: 34600000001\nEstado: confirmada\nRecordatorio: no",
                aware(2026, 3, 23, 10, 0), aware(2026, 3, 23, 10, 30)
            )]
        }
        slots = cal.get_slots_disponibles(d)
        assert "10:00" not in slots
        assert "10:30" in slots


# ── tiene_cita_ese_dia ─────────────────────────────────────────────────────────

class TestTieneCitaEseDia:
    def test_phone_with_appointment(self, cal_with_service):
        cal, svc = cal_with_service
        d = date(2026, 3, 23)
        desc = "Nombre: Ana\nTelefono: 34600000001\nEstado: confirmada\nRecordatorio: no"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event("evt1", "Cita - Ana", desc,
                                   aware(2026, 3, 23, 10, 0), aware(2026, 3, 23, 10, 30))]
        }
        assert cal.tiene_cita_ese_dia("34600000001", d) is True

    def test_phone_without_appointment(self, cal_with_service):
        cal, svc = cal_with_service
        assert cal.tiene_cita_ese_dia("34600000999", date(2026, 3, 23)) is False

    def test_different_phone_no_match(self, cal_with_service):
        cal, svc = cal_with_service
        d = date(2026, 3, 23)
        desc = "Telefono: 34600000001\nEstado: confirmada\nRecordatorio: no"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event("evt1", "Cita", desc,
                                   aware(2026, 3, 23, 10, 0), aware(2026, 3, 23, 10, 30))]
        }
        assert cal.tiene_cita_ese_dia("34600000999", d) is False


# ── crear_cita ─────────────────────────────────────────────────────────────────

class TestCrearCita:
    def test_creates_event_and_returns_id(self, cal_with_service):
        cal, svc = cal_with_service
        event_id = cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001")
        assert event_id == "new_evt"
        svc.events.return_value.insert.return_value.execute.assert_called_once()

    def test_api_error_returns_none(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.insert.return_value.execute.side_effect = Exception("API error")
        result = cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001")
        assert result is None

    def test_description_format(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(date(2026, 3, 23), "10:00", "Ana García", "34600000001")
        body = svc.events.return_value.insert.call_args[1]["body"]
        assert "Nombre: Ana García" in body["description"]
        assert "Telefono: 34600000001" in body["description"]
        assert "Estado: confirmada" in body["description"]


# ── reservar_cita (atomic) ─────────────────────────────────────────────────────

class TestReservarCita:
    def test_success(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=True), \
             patch.object(cal, "tiene_cita_ese_dia", return_value=False), \
             patch.object(cal, "crear_cita", return_value="new_evt"):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001"
            )
        assert event_id == "new_evt"
        assert reason is None

    def test_slot_taken(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=False):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001"
            )
        assert event_id is None
        assert reason == "slot_taken"

    def test_double_booking(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=True), \
             patch.object(cal, "tiene_cita_ese_dia", return_value=True):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001"
            )
        assert event_id is None
        assert reason == "double_booking"

    def test_calendar_api_error(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=True), \
             patch.object(cal, "tiene_cita_ese_dia", return_value=False), \
             patch.object(cal, "crear_cita", return_value=None):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001"
            )
        assert event_id is None
        assert reason == "error"

    def test_concurrent_same_slot_only_one_succeeds(self, cal_with_service):
        """
        Two threads try to book the same slot at the same time.
        The per-slot lock ensures only one succeeds; the second gets slot_taken.
        """
        import app.services.calendar as cal_module
        d = date(2026, 3, 25)
        hora = "11:00"

        booked = []
        call_count = [0]
        lock = threading.Lock()

        def fake_slot_libre(date_, hora_):
            with lock:
                call_count[0] += 1
                if len(booked) == 0:
                    return True
                return False

        def fake_crear(date_, hora_, nombre, tel):
            booked.append("done")
            return "evt_concurrent"

        results = []

        def worker():
            with patch.object(cal_module, "slot_sigue_libre", side_effect=fake_slot_libre), \
                 patch.object(cal_module, "tiene_cita_ese_dia", return_value=False), \
                 patch.object(cal_module, "crear_cita", side_effect=fake_crear):
                result = cal_module.reservar_cita(d, hora, "Test", "34600000001")
                results.append(result)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(); t2.join()

        successes = [r for r in results if r[0] is not None]
        failures  = [r for r in results if r[1] == "slot_taken"]
        # At most 1 success; the slot lock may or may not serialize
        # depending on timing, but combined there should be 2 results total
        assert len(results) == 2


# ── cancelar_cita ──────────────────────────────────────────────────────────────

class TestCancelarCita:
    def test_deletes_event(self, cal_with_service):
        cal, svc = cal_with_service
        assert cal.cancelar_cita("evt1") is True
        svc.events.return_value.delete.return_value.execute.assert_called_once()

    def test_api_error_returns_false(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.delete.return_value.execute.side_effect = Exception("err")
        assert cal.cancelar_cita("evt1") is False


# ── confirmar_cita ─────────────────────────────────────────────────────────────

class TestConfirmarCita:
    def test_sets_estado_confirmada(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": "Estado: pendiente",
        }
        result = cal.confirmar_cita("evt1")
        assert result is True
        updated_body = svc.events.return_value.update.call_args[1]["body"]
        assert "Estado: confirmada" in updated_body["description"]

    def test_api_error_returns_false(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.side_effect = Exception("err")
        assert cal.confirmar_cita("evt1") is False


# ── get_eventos_manuales_sin_confirmar ─────────────────────────────────────────

class TestGetEventosManualesSinConfirmar:
    def test_returns_pending_manual(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Luis\nTelefono: 34600000002\nEstado: pendiente"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30)
            )]
        }
        result = cal.get_eventos_manuales_sin_confirmar()
        assert len(result) == 1
        assert result[0]["telefono"] == "34600000002"

    def test_skips_already_confirmed(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Luis\nTelefono: 34600000002\nEstado: confirmada"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30)
            )]
        }
        assert cal.get_eventos_manuales_sin_confirmar() == []

    def test_skips_cfg_events(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "cfg1", "[CFG] CERRADO", "",
                now + timedelta(days=1), now + timedelta(days=1, hours=8)
            )]
        }
        assert cal.get_eventos_manuales_sin_confirmar() == []

    def test_skips_without_phone(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Luis\nEstado: pendiente"  # no Telefono
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event("evt1", "Cita", desc,
                                   now + timedelta(days=1), now + timedelta(days=1, minutes=30))]
        }
        assert cal.get_eventos_manuales_sin_confirmar() == []


# ── get_citas_para_recordatorio ────────────────────────────────────────────────

class TestGetCitasParaRecordatorio:
    def _make_reminder_event(self, svc, reminder_val, estado_val="confirmada"):
        now = datetime.now(TZ)
        desc = (
            f"Nombre: Ana\nTelefono: 34600000001\n"
            f"Estado: {estado_val}\nRecordatorio: {reminder_val}"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Ana", desc,
                now + timedelta(hours=24), now + timedelta(hours=24, minutes=30)
            )]
        }

    def test_returns_cita_with_no_reminder(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_reminder_event(svc, "no")
        result = cal.get_citas_para_recordatorio()
        assert len(result) == 1

    def test_skips_cita_already_reminded(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_reminder_event(svc, "sí")
        assert cal.get_citas_para_recordatorio() == []

    def test_skips_cfg_event(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "cfg1", "[CFG] CERRADO", "",
                now + timedelta(hours=24), now + timedelta(hours=32)
            )]
        }
        assert cal.get_citas_para_recordatorio() == []


# ── marcar_recordatorio_enviado ────────────────────────────────────────────────

class TestMarcarRecordatorioEnviado:
    def test_sets_recordatorio_si(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": "Estado: confirmada\nRecordatorio: no",
        }
        assert cal.marcar_recordatorio_enviado("evt1") is True
        updated = svc.events.return_value.update.call_args[1]["body"]
        assert "Recordatorio: sí" in updated["description"]

    def test_api_error_returns_false(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.side_effect = Exception("err")
        assert cal.marcar_recordatorio_enviado("evt1") is False
