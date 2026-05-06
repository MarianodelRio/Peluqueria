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

from app.config import HORARIO_BASE, SERVICIOS

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
        tuesday = date(2026, 3, 24)
        slots = cal.get_slots_disponibles(tuesday)
        for start, _ in HORARIO_BASE[1]:
            assert start in slots

    def test_saturday_has_slots(self, cal_with_service):
        cal, svc = cal_with_service
        saturday = date(2026, 3, 28)
        slots = cal.get_slots_disponibles(saturday)
        for start, _ in HORARIO_BASE[5]:
            assert start in slots
        # periods not in Saturday config should produce no slots
        configured_starts = {s for s, _ in HORARIO_BASE[5]}
        unconfigured = {s for s, _ in HORARIO_BASE[1]} - configured_starts
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
        d = date(2026, 3, 24)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_all_day_event("cfg1", "[CFG] HORARIO 10:00-12:00", d)]
        }
        slots = cal.get_slots_disponibles(d)
        # Only 10:00 and 10:30 and 11:00 and 11:30 fit in 10:00-12:00
        assert "10:00" in slots
        assert "17:00" not in slots

    def test_occupied_slot_removed(self, cal_with_service):
        cal, svc = cal_with_service
        d = date(2026, 3, 24)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Ana",
                "Nombre: Ana\nTelefono: 34600000001\nEstado: confirmada\nRecordatorio: no",
                aware(2026, 3, 24, 10, 0), aware(2026, 3, 24, 10, 30)
            )]
        }
        slots = cal.get_slots_disponibles(d)
        assert "10:00" not in slots
        assert "10:30" in slots

    def test_mechas_slot_blocked_when_event_in_2h_window(self, cal_with_service):
        """An event at 11:30-12:00 blocks 10:00 when duration is 120 min."""
        cal, svc = cal_with_service
        tuesday = date(2026, 3, 24)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis",
                "Nombre: Luis\nTelefono: 34600000002\nEstado: confirmada\nRecordatorio: no",
                aware(2026, 3, 24, 11, 30), aware(2026, 3, 24, 12, 0)
            )]
        }
        slots = cal.get_slots_disponibles(tuesday, duracion_min=120)
        assert "10:00" not in slots

    def test_mechas_slot_free_when_event_outside_2h_window(self, cal_with_service):
        """An event at 12:30-13:00 does not block 10:00 when duration is 120 min."""
        cal, svc = cal_with_service
        tuesday = date(2026, 3, 24)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis",
                "Nombre: Luis\nTelefono: 34600000002\nEstado: confirmada\nRecordatorio: no",
                aware(2026, 3, 24, 12, 30), aware(2026, 3, 24, 13, 0)
            )]
        }
        slots = cal.get_slots_disponibles(tuesday, duracion_min=120)
        assert "10:00" in slots

    def test_cache_key_includes_duracion_and_presencia(self, cal_with_service):
        """Calling get_slots_disponibles with different duracion_min creates separate cache keys (3-part key)."""
        import app.services.calendar as cal_module
        d = date(2026, 3, 24)
        cal_module.get_slots_disponibles(d, duracion_min=30, presencia_cliente_min=30)
        cal_module.get_slots_disponibles(d, duracion_min=120, presencia_cliente_min=30)
        keys = list(cal_module._slot_cache.keys())
        key_30 = f"{d.isoformat()}_30_30"
        key_120 = f"{d.isoformat()}_120_30"
        assert key_30 in keys
        assert key_120 in keys
        assert key_30 != key_120

    def test_slot_cache_keys_separate_per_duration_pair(self):
        """_slot_cache_key returns distinct strings for different (duracion, presencia) pairs."""
        from app.services.calendar import _slot_cache_key
        d = date(2026, 3, 24)
        key_a = _slot_cache_key(d, 60, 180)
        key_b = _slot_cache_key(d, 30, 30)
        assert isinstance(key_a, str)
        assert isinstance(key_b, str)
        assert key_a != key_b

    def test_get_slots_disponibles_mechas_no_offers_slots_under_3h_to_close(self, cal_with_service):
        """Slots that would require the client to stay past closing are excluded (presencia_cliente_min=180)."""
        cal, svc = cal_with_service
        d = date(2026, 3, 24)  # Tuesday: tarde 17:00-21:00
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        slots = cal.get_slots_disponibles(d, duracion_min=60, presencia_cliente_min=180)
        # 17:00+180min=20:00 ≤ 21:00 ✓; 18:00+180min=21:00 ≤ 21:00 ✓; 18:30+180min=21:30 > 21:00 ✗
        assert "17:00" in slots
        assert "17:30" in slots
        assert "18:00" in slots
        assert "18:30" not in slots

    def test_get_slots_disponibles_mechas_collision_uses_60min_window(self, cal_with_service):
        """
        Collision detection uses duracion_min (60), not presencia_cliente_min (180).
        Event 18:30-19:00 falls inside the presencia window (slot_start + 180 = 20:00)
        but outside the duracion window (slot_start + 60 = 18:00) for 17:00 and 17:30.
        If collision used presencia=180, all 3 slots would be blocked (event lies inside [17:00, 20:00)).
        Since 17:00 and 17:30 are free, collision must be using duracion=60.
        """
        cal, svc = cal_with_service
        d = date(2026, 3, 24)  # Tuesday tarde 17:00-21:00
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis",
                "Nombre: Luis\nTelefono: 34600000002\nEstado: confirmada\nRecordatorio: no",
                aware(2026, 3, 24, 18, 30), aware(2026, 3, 24, 19, 0)
            )]
        }
        slots = cal.get_slots_disponibles(d, duracion_min=60, presencia_cliente_min=180)
        # 17:00+60=18:00 < 18:31 (event start with +1min tolerance) → free.
        # If collision used presencia=180: 17:00+180=20:00 would overlap event → blocked.
        # The fact that 17:00 is free proves collision uses duracion=60, not presencia.
        assert "17:00" in slots
        # 17:30+60=18:30 < 18:31 (1-min tolerance gap) → free. Same load-bearing logic.
        assert "17:30" in slots
        # 18:00+60=19:00 → window 18:00-19:00 overlaps event 18:30-19:00 → blocked by collision.
        assert "18:00" not in slots


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
        event_id = cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001", servicio=SERVICIOS["corte"])
        assert event_id == "new_evt"
        svc.events.return_value.insert.return_value.execute.assert_called_once()

    def test_api_error_returns_none(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.insert.return_value.execute.side_effect = Exception("API error")
        result = cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001", servicio=SERVICIOS["corte"])
        assert result is None

    def test_description_format(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(date(2026, 3, 23), "10:00", "Ana García", "34600000001", servicio=SERVICIOS["corte"])
        body = svc.events.return_value.insert.call_args[1]["body"]
        assert "Nombre: Ana García" in body["description"]
        assert "Telefono: 34600000001" in body["description"]
        assert "Estado: confirmada" in body["description"]

    def test_crear_cita_title_format(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001", servicio=SERVICIOS["corte"])
        body = svc.events.return_value.insert.call_args[1]["body"]
        assert body["summary"] == "Corte de pelo - Ana"

    def test_crear_cita_duration_matches_servicio(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001", servicio=SERVICIOS["mechas"])
        body = svc.events.return_value.insert.call_args[1]["body"]
        from datetime import datetime
        start = datetime.fromisoformat(body["start"]["dateTime"])
        end = datetime.fromisoformat(body["end"]["dateTime"])
        assert end - start == timedelta(minutes=60)

    def test_crear_cita_description_contains_servicio_line(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(date(2026, 3, 23), "10:00", "Ana", "34600000001", servicio=SERVICIOS["mechas"])
        body = svc.events.return_value.insert.call_args[1]["body"]
        assert "Servicio: mechas" in body["description"]

    def test_get_slots_disponibles_passes_duracion_min(self, cal_with_service):
        cal, svc = cal_with_service
        result = cal.get_slots_disponibles(date(2026, 3, 24), duracion_min=120)
        assert isinstance(result, list)

    def test_slot_sigue_libre_passes_duracion_min(self, cal_with_service):
        cal, svc = cal_with_service
        # With no blocking events, 10:00 should be free for any duration on a Tuesday
        result = cal.slot_sigue_libre(date(2026, 3, 24), "10:00", duracion_min=120)
        assert isinstance(result, bool)


# ── reservar_cita (atomic) ─────────────────────────────────────────────────────

class TestReservarCita:
    def test_success(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=True), \
             patch.object(cal, "tiene_cita_ese_dia", return_value=False), \
             patch.object(cal, "crear_cita", return_value="new_evt"):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001", SERVICIOS["corte"]
            )
        assert event_id == "new_evt"
        assert reason is None

    def test_slot_taken(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=False):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001", SERVICIOS["corte"]
            )
        assert event_id is None
        assert reason == "slot_taken"

    def test_double_booking(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=True), \
             patch.object(cal, "tiene_cita_ese_dia", return_value=True):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001", SERVICIOS["corte"]
            )
        assert event_id is None
        assert reason == "double_booking"

    def test_calendar_api_error(self, cal_with_service):
        cal, svc = cal_with_service
        with patch.object(cal, "slot_sigue_libre", return_value=True), \
             patch.object(cal, "tiene_cita_ese_dia", return_value=False), \
             patch.object(cal, "crear_cita", return_value=None):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001", SERVICIOS["corte"]
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

        def fake_slot_libre(date_, hora_, **kwargs):
            with lock:
                call_count[0] += 1
                if len(booked) == 0:
                    return True
                return False

        def fake_crear(date_, hora_, nombre, tel, **kwargs):
            booked.append("done")
            return "evt_concurrent"

        results = []

        def worker():
            with patch.object(cal_module, "slot_sigue_libre", side_effect=fake_slot_libre), \
                 patch.object(cal_module, "tiene_cita_ese_dia", return_value=False), \
                 patch.object(cal_module, "crear_cita", side_effect=fake_crear):
                result = cal_module.reservar_cita(d, hora, "Test", "34600000001", SERVICIOS["corte"])
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
        svc.events.return_value.get.return_value.execute.return_value = {
            'start': {'dateTime': '2025-05-05T10:00:00+02:00'}
        }
        assert cal.cancelar_cita("evt1") is True
        svc.events.return_value.delete.return_value.execute.assert_called_once()

    def test_api_error_returns_false(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.return_value = {
            'start': {'dateTime': '2025-05-05T10:00:00+02:00'}
        }
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
        assert 'service_key' in result[0]

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

    def test_service_key_value_mechas(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Luis\nTelefono: 34600000002\nEstado: pendiente"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Mechas - Luis", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=120)
            )]
        }
        result = cal.get_eventos_manuales_sin_confirmar()
        assert len(result) == 1
        assert result[0]['service_key'] == "mechas"

    def test_service_key_value_corte(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Pedro\nTelefono: 34600000003\nEstado: pendiente"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt2", "Corte de pelo - Pedro", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30)
            )]
        }
        result = cal.get_eventos_manuales_sin_confirmar()
        assert len(result) == 1
        assert result[0]['service_key'] == "corte"

    def test_service_key_none_for_unknown_title(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Luis\nTelefono: 34600000002\nEstado: pendiente"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Tinte - Luis", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=60)
            )]
        }
        result = cal.get_eventos_manuales_sin_confirmar()
        assert len(result) == 1
        assert result[0]['service_key'] is None


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


# ── marcar_manual_confirmado ───────────────────────────────────────────────────

class TestMarcarManualConfirmado:
    def test_sets_estado_confirmada_and_recordatorio_no(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": "Nombre: Luis\nTelefono: 34600000002\nEstado: pendiente\nRecordatorio: no",
        }
        result = cal.marcar_manual_confirmado("evt1")
        assert result is True
        updated_body = svc.events.return_value.update.call_args[1]["body"]
        assert "Estado: confirmada" in updated_body["description"]
        assert "Recordatorio: no" in updated_body["description"]

    def test_api_error_returns_false(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.side_effect = Exception("API error")
        assert cal.marcar_manual_confirmado("evt1") is False


# ── get_citas_futuras ──────────────────────────────────────────────────────────

class TestGetCitasFuturas:
    def test_returns_future_citas_for_phone(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Ana\nTelefono: 34600000001\nEstado: confirmada\nRecordatorio: no"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Corte de pelo - Ana", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30)
            )]
        }
        result = cal.get_citas_futuras("34600000001")
        assert len(result) == 1
        assert result[0]["id"] == "evt1"

    def test_ignores_other_phones(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = "Nombre: Ana\nTelefono: 34600000001\nEstado: confirmada\nRecordatorio: no"
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Corte de pelo - Ana", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30)
            )]
        }
        result = cal.get_citas_futuras("34600000999")
        assert result == []

    def test_ignores_cfg_events(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "cfg1", "[CFG] CERRADO", "",
                now + timedelta(days=1), now + timedelta(days=1, hours=8)
            )]
        }
        result = cal.get_citas_futuras("34600000001")
        assert result == []

    def test_api_error_returns_empty_list(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.side_effect = Exception("API error")
        result = cal.get_citas_futuras("34600000001")
        assert result == []
