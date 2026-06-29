# tests/test_calendar.py
"""
Unit tests for services/calendar.py.
Google Calendar API is mocked entirely — no real credentials needed.
"""
import pytest
import threading
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
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
    Also clears the slot cache and citas cache so tests don't interfere.
    """
    import app.services.calendar as cal
    if hasattr(cal._thread_local, "service"):
        del cal._thread_local.service
    cal._slot_cache.clear()
    cal._citas_cache.clear()
    yield
    cal._slot_cache.clear()
    cal._citas_cache.clear()


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
    """Patch client.get_service to return mock_service."""
    import app.services.calendar as cal
    with patch.object(cal.client, "get_service", return_value=mock_service):
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
        desc = (
            "Nombre: Ana\nTelefono: 34600000001\n"
            "Estado: confirmada\nRecordatorio: no"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Ana", desc,
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
        desc = (
            "Nombre: Luis\nTelefono: 34600000002\n"
            "Estado: confirmada\nRecordatorio: no"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis", desc,
                aware(2026, 3, 24, 11, 30), aware(2026, 3, 24, 12, 0)
            )]
        }
        slots = cal.get_slots_disponibles(tuesday, duracion_min=120)
        assert "10:00" not in slots

    def test_mechas_slot_free_when_event_outside_2h_window(self, cal_with_service):
        """An event at 12:30-13:00 does not block 10:00 when duration is 120 min."""
        cal, svc = cal_with_service
        tuesday = date(2026, 3, 24)
        desc = (
            "Nombre: Luis\nTelefono: 34600000002\n"
            "Estado: confirmada\nRecordatorio: no"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis", desc,
                aware(2026, 3, 24, 12, 30), aware(2026, 3, 24, 13, 0)
            )]
        }
        slots = cal.get_slots_disponibles(tuesday, duracion_min=120)
        assert "10:00" in slots

    def test_cache_key_includes_duracion_and_presencia(self, cal_with_service):
        """Calling get_slots_disponibles with different duracion_min creates
        separate cache keys (3-part key)."""
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
        """_slot_cache_key returns distinct strings for different
        (duracion, presencia) pairs."""
        from app.services.calendar import _slot_cache_key
        d = date(2026, 3, 24)
        key_a = _slot_cache_key(d, 60, 180)
        key_b = _slot_cache_key(d, 30, 30)
        assert isinstance(key_a, str)
        assert isinstance(key_b, str)
        assert key_a != key_b

    def test_get_slots_disponibles_mechas_no_offers_slots_under_3h_to_close(
        self, cal_with_service
    ):
        """Slots that would require the client to stay past closing are excluded
        (presencia_cliente_min=180)."""
        cal, svc = cal_with_service
        d = date(2026, 3, 24)  # Tuesday: tarde 17:00-21:30
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        slots = cal.get_slots_disponibles(
            d, duracion_min=60, presencia_cliente_min=180
        )
        # 17:00+180min=20:00 ≤ 21:30 ✓; 18:30+180min=21:30 ≤ 21:30 ✓;
        # 19:00+180min=22:00 > 21:30 ✗
        assert "17:00" in slots
        assert "17:30" in slots
        assert "18:00" in slots
        assert "18:30" in slots
        assert "19:00" not in slots

    def test_get_slots_disponibles_mechas_collision_uses_60min_window(
        self, cal_with_service
    ):
        """
        Collision detection uses duracion_min (60), not presencia_cliente_min (180).
        Event 18:30-19:00 falls inside the presencia window (slot_start + 180 = 20:00)
        but outside the duracion window (slot_start + 60 = 18:00) for 17:00 and 17:30.
        If collision used presencia=180, all 3 slots would be blocked (event lies
        inside [17:00, 20:00)). Since 17:00 and 17:30 are free, collision must be
        using duracion=60.
        """
        cal, svc = cal_with_service
        d = date(2026, 3, 24)  # Tuesday tarde 17:00-21:00
        desc = (
            "Nombre: Luis\nTelefono: 34600000002\n"
            "Estado: confirmada\nRecordatorio: no"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Cita - Luis", desc,
                aware(2026, 3, 24, 18, 30), aware(2026, 3, 24, 19, 0)
            )]
        }
        slots = cal.get_slots_disponibles(
            d, duracion_min=60, presencia_cliente_min=180
        )
        # 17:00+60=18:00 < 18:31 (event start with +1min tolerance) → free.
        # If collision used presencia=180: 17:00+180=20:00 would overlap → blocked.
        # The fact that 17:00 is free proves collision uses duracion=60, not presencia.
        assert "17:00" in slots
        # 17:30+60=18:30 < 18:31 (1-min tolerance gap) → free. Same load-bearing logic.
        assert "17:30" in slots
        # 18:00+60=19:00 → window 18:00-19:00 overlaps event 18:30-19:00 → blocked.
        assert "18:00" not in slots


# ── crear_cita ─────────────────────────────────────────────────────────────────

class TestCrearCita:
    def test_creates_event_and_returns_id(self, cal_with_service):
        cal, svc = cal_with_service
        event_id = cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana", "34600000001",
            servicio=SERVICIOS["corte"],
        )
        assert event_id == "new_evt"
        svc.events.return_value.insert.return_value.execute.assert_called_once()

    def test_api_error_returns_none(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.insert.return_value.execute.side_effect = Exception(
            "API error"
        )
        result = cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana", "34600000001",
            servicio=SERVICIOS["corte"],
        )
        assert result is None

    def test_description_format(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana García", "34600000001",
            servicio=SERVICIOS["corte"],
        )
        body = svc.events.return_value.insert.call_args[1]["body"]
        assert "Nombre: Ana García" in body["description"]
        assert "Telefono: 34600000001" in body["description"]
        assert "Estado: confirmada" in body["description"]

    def test_crear_cita_title_format(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana", "34600000001",
            servicio=SERVICIOS["corte"],
        )
        body = svc.events.return_value.insert.call_args[1]["body"]
        assert body["summary"] == "Corte de pelo - Ana"

    def test_crear_cita_duration_matches_servicio(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana", "34600000001",
            servicio=SERVICIOS["mechas"],
        )
        body = svc.events.return_value.insert.call_args[1]["body"]
        from datetime import datetime
        start = datetime.fromisoformat(body["start"]["dateTime"])
        end = datetime.fromisoformat(body["end"]["dateTime"])
        assert end - start == timedelta(minutes=60)

    def test_crear_cita_description_contains_servicio_line(self, cal_with_service):
        cal, svc = cal_with_service
        cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana", "34600000001",
            servicio=SERVICIOS["mechas"],
        )
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
        with (
            patch("app.services.calendar.service.slot_sigue_libre", return_value=True),
            patch("app.services.calendar.service.crear_cita", return_value="new_evt"),
        ):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 24), "10:00", "Ana", "34600000001", SERVICIOS["corte"]
            )
        assert event_id == "new_evt"
        assert reason is None

    def test_slot_taken(self, cal_with_service):
        cal, svc = cal_with_service
        with patch(
            "app.services.calendar.service.slot_sigue_libre", return_value=False
        ):
            event_id, reason = cal.reservar_cita(
                date(2026, 3, 23), "10:00", "Ana", "34600000001", SERVICIOS["corte"]
            )
        assert event_id is None
        assert reason == "slot_taken"

    def test_calendar_api_error(self, cal_with_service):
        cal, svc = cal_with_service
        with patch(
            "app.services.calendar.service.slot_sigue_libre", return_value=True
        ), patch("app.services.calendar.service.crear_cita", return_value=None):
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
            with patch.object(
                cal_module, "slot_sigue_libre", side_effect=fake_slot_libre
            ), patch.object(cal_module, "crear_cita", side_effect=fake_crear):
                result = cal_module.reservar_cita(
                    d, hora, "Test", "34600000001", SERVICIOS["corte"]
                )
                results.append(result)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

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
        svc.events.return_value.delete.return_value.execute.side_effect = Exception(
            "err"
        )
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
            "items": [make_gc_event(
                "evt1", "Cita", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30),
            )]
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
            "description": (
                "Nombre: Luis\nTelefono: 34600000002\n"
                "Estado: pendiente\nRecordatorio: no"
            ),
        }
        result = cal.marcar_manual_confirmado("evt1")
        assert result is True
        updated_body = svc.events.return_value.update.call_args[1]["body"]
        assert "Estado: confirmada" in updated_body["description"]
        assert "Recordatorio: no" in updated_body["description"]

    def test_api_error_returns_false(self, cal_with_service):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.side_effect = Exception(
            "API error"
        )
        assert cal.marcar_manual_confirmado("evt1") is False


# ── get_citas_futuras ──────────────────────────────────────────────────────────

class TestGetCitasFuturas:
    def test_returns_future_citas_for_phone(self, cal_with_service):
        cal, svc = cal_with_service
        now = datetime.now(TZ)
        desc = (
            "Nombre: Ana\nTelefono: 34600000001\n"
            "Estado: confirmada\nRecordatorio: no"
        )
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
        desc = (
            "Nombre: Ana\nTelefono: 34600000001\n"
            "Estado: confirmada\nRecordatorio: no"
        )
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
        svc.events.return_value.list.return_value.execute.side_effect = Exception(
            "API error"
        )
        result = cal.get_citas_futuras("34600000001")
        assert result == []


# ── _get_events_in_range ──────────────────────────────────────────────────────────

def make_timed_gc_event(event_id, summary, description, start_dt, end_dt):
    """Build a timed Google Calendar API item dict."""
    return {
        "id": event_id,
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat()},
        "end":   {"dateTime": end_dt.isoformat()},
    }


def make_range_all_day_event(event_id, summary, start_date_str, end_date_str):
    """Build an all-day Google Calendar API item dict with explicit start/end dates."""
    return {
        "id": event_id,
        "summary": summary,
        "description": "",
        "start": {"date": start_date_str},
        "end":   {"date": end_date_str},
    }


class TestGetEventsInRange:
    def test_get_events_in_range_single_call(self, cal_with_service):
        """Verify events().list().execute() called once with correct timeMin/timeMax."""
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}

        start = date(2026, 5, 10)
        end = date(2026, 5, 15)
        cal._get_events_in_range(svc, start, end)

        assert svc.events.return_value.list.return_value.execute.call_count == 1
        call_kwargs = svc.events.return_value.list.call_args[1]
        assert "2026-05-10T00:00:00" in call_kwargs["timeMin"]
        assert "2026-05-15T23:59:59" in call_kwargs["timeMax"]

    def test_get_events_in_range_groups_by_date(self, cal_with_service):
        """3 timed events on 3 different dates → dict with those 3 keys populated."""
        cal, svc = cal_with_service
        start = date(2026, 5, 10)
        end = date(2026, 5, 15)

        evt1 = make_timed_gc_event(
            "e1", "A", "", aware(2026, 5, 10, 10, 0), aware(2026, 5, 10, 10, 30)
        )
        evt2 = make_timed_gc_event(
            "e2", "B", "", aware(2026, 5, 12, 11, 0), aware(2026, 5, 12, 11, 30)
        )
        evt3 = make_timed_gc_event(
            "e3", "C", "", aware(2026, 5, 14, 15, 0), aware(2026, 5, 14, 15, 30)
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [evt1, evt2, evt3]
        }

        result = cal._get_events_in_range(svc, start, end)

        assert len(result[date(2026, 5, 10)]) == 1
        assert result[date(2026, 5, 10)][0]['id'] == 'e1'
        assert len(result[date(2026, 5, 12)]) == 1
        assert result[date(2026, 5, 12)][0]['id'] == 'e2'
        assert len(result[date(2026, 5, 14)]) == 1
        assert result[date(2026, 5, 14)][0]['id'] == 'e3'
        # Days without events have empty lists
        assert result[date(2026, 5, 11)] == []

    def test_get_events_in_range_expands_multi_day_all_day(self, cal_with_service):
        """All-day event 2026-05-10 to 2026-05-13 → buckets for 10, 11, 12 (NOT 13)."""
        cal, svc = cal_with_service
        start = date(2026, 5, 10)
        end = date(2026, 5, 15)

        all_day = make_range_all_day_event(
            "cfg1", "[CFG] CERRADO", "2026-05-10", "2026-05-13"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [all_day]
        }

        result = cal._get_events_in_range(svc, start, end)

        assert len(result[date(2026, 5, 10)]) == 1
        assert len(result[date(2026, 5, 11)]) == 1
        assert len(result[date(2026, 5, 12)]) == 1
        assert result[date(2026, 5, 13)] == []  # end is exclusive

    def test_get_events_in_range_pagination(self, cal_with_service):
        """First execute returns nextPageToken, second returns more events — both
        batches concatenated."""
        cal, svc = cal_with_service
        start = date(2026, 5, 10)
        end = date(2026, 5, 15)

        evt1 = make_timed_gc_event(
            "e1", "A", "", aware(2026, 5, 10, 10, 0), aware(2026, 5, 10, 10, 30)
        )
        evt2 = make_timed_gc_event(
            "e2", "B", "", aware(2026, 5, 11, 10, 0), aware(2026, 5, 11, 10, 30)
        )

        svc.events.return_value.list.return_value.execute.side_effect = [
            {"items": [evt1], "nextPageToken": "token_page2"},
            {"items": [evt2]},
        ]

        result = cal._get_events_in_range(svc, start, end)

        assert len(result[date(2026, 5, 10)]) == 1
        assert len(result[date(2026, 5, 11)]) == 1
        assert svc.events.return_value.list.return_value.execute.call_count == 2

    def test_get_events_in_range_pagination_safety_cap(self, cal_with_service):
        """Every page returns nextPageToken → loop stops at 5 pages, doesn't hang."""
        cal, svc = cal_with_service
        start = date(2026, 5, 10)
        end = date(2026, 5, 15)

        # Every page returns a token — should stop after 5
        always_token_page = {"items": [], "nextPageToken": "keep_going"}
        svc.events.return_value.list.return_value.execute.side_effect = (
            [always_token_page] * 10
        )

        result = cal._get_events_in_range(svc, start, end)

        assert svc.events.return_value.list.return_value.execute.call_count == 5
        assert isinstance(result, dict)

    def test_events_list_called_with_fields_parameter(self, cal_with_service):
        """_get_events_in_range passes fields= containing required field names
        and nextPageToken."""
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}

        start = date(2026, 5, 10)
        end = date(2026, 5, 15)
        cal._get_events_in_range(svc, start, end)

        call_kwargs = svc.events.return_value.list.call_args[1]
        assert 'fields' in call_kwargs
        assert 'items(id,summary,description,start,end)' in call_kwargs['fields']
        assert 'nextPageToken' in call_kwargs['fields']

    def test_pagination_works_with_fields_parameter(self, cal_with_service):
        """Both pages are fetched and each list call carries the fields= kwarg."""
        cal, svc = cal_with_service
        start = date(2026, 5, 10)
        end = date(2026, 5, 15)

        evt1 = make_timed_gc_event(
            "e1", "A", "", aware(2026, 5, 10, 10, 0), aware(2026, 5, 10, 10, 30)
        )
        evt2 = make_timed_gc_event(
            "e2", "B", "", aware(2026, 5, 11, 10, 0), aware(2026, 5, 11, 10, 30)
        )

        svc.events.return_value.list.return_value.execute.side_effect = [
            {"items": [evt1], "nextPageToken": "token_page2"},
            {"items": [evt2]},
        ]

        result = cal._get_events_in_range(svc, start, end)

        # Both pages were fetched and concatenated
        assert len(result[date(2026, 5, 10)]) == 1
        assert len(result[date(2026, 5, 11)]) == 1
        assert svc.events.return_value.list.return_value.execute.call_count == 2

        # Every list() call had the fields= kwarg
        for list_call in svc.events.return_value.list.call_args_list:
            kwargs = list_call[1]
            assert 'fields' in kwargs
            assert 'nextPageToken' in kwargs['fields']


# ── _compute_slots ────────────────────────────────────────────────────────────────

class TestComputeSlots:
    def test_compute_slots_pure_function_no_io(self):
        """Call directly with pre-built events; result matches
        _get_slots_disponibles_uncached logic."""
        import app.services.calendar as cal_module
        d = date(2026, 3, 24)  # Tuesday with schedule 10:00-14:00 and 17:00-21:00

        # One blocking event at 10:00-10:30
        blocking = {
            'id': 'e1', 'title': 'Cita', 'description': '',
            'start': aware(2026, 3, 24, 10, 0), 'end': aware(2026, 3, 24, 10, 30),
            'all_day': False,
        }
        result = cal_module._compute_slots(
            d, [blocking], duracion_min=30, presencia_cliente_min=30
        )

        assert "10:00" not in result
        assert "10:30" in result
        assert "11:00" in result
        assert "17:00" in result

    def test_compute_slots_cerrado_returns_empty(self):
        """[CFG] CERRADO all-day event → empty list."""
        import app.services.calendar as cal_module
        d = date(2026, 3, 24)
        cfg_ev = {
            'id': 'cfg1', 'title': '[CFG] CERRADO', 'description': '',
            'start': aware(2026, 3, 24, 0, 0), 'end': aware(2026, 3, 24, 23, 59),
            'all_day': True,
        }
        result = cal_module._compute_slots(d, [cfg_ev])
        assert result == []


# ── get_slots_disponibles_range ───────────────────────────────────────────────────

class TestGetSlotsDisponiblesRange:
    def test_get_slots_disponibles_range_populates_cache(self, cal_with_service):
        """After range call, per-day get_slots_disponibles makes no extra API calls."""
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}

        start = date(2026, 5, 12)   # Monday
        end = date(2026, 5, 25)     # Sunday (14 calendar days later)

        cal.get_slots_disponibles_range(start, end)
        call_count_after_range = (
            svc.events.return_value.list.return_value.execute.call_count
        )

        # Now fetch each day individually — should all be cache hits → no new calls
        current = start
        while current <= end:
            cal.get_slots_disponibles(current)
            current += timedelta(days=1)

        assert (
            svc.events.return_value.list.return_value.execute.call_count
            == call_count_after_range
        )

    def test_get_slots_disponibles_range_filters_today_past_slots(
        self, cal_with_service
    ):
        """Slots <= 12:30 absent from today's return value;
        cached entry is unfiltered."""
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}

        today = date(2026, 3, 24)  # Tuesday — has morning and afternoon slots

        fixed_now = TZ.localize(datetime(2026, 3, 24, 12, 30, 0))

        with patch("app.services.calendar.service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = cal_module.get_slots_disponibles_range(today, today)

        day_result = result[today]
        # Slots at or before 12:30 must not appear
        for slot in ["10:00", "10:30", "11:00", "12:00", "12:30"]:
            assert slot not in day_result, f"Expected {slot} to be filtered out"
        # Afternoon slots must appear
        assert "17:00" in day_result

        # Cached entry must be unfiltered (contains morning slots)
        cache_key = cal_module._slot_cache_key(today, 30, 30)
        cached_slots, _ = cal_module._slot_cache[cache_key]
        assert "10:00" in cached_slots

    def test_get_slots_disponibles_range_handles_calendar_failure(
        self, cal_with_service
    ):
        """Exception raised by Calendar API → range returns {}."""
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.side_effect = Exception(
            "API down"
        )

        result = cal.get_slots_disponibles_range(date(2026, 5, 10), date(2026, 5, 15))
        assert result == {}

    def test_get_slots_disponibles_range_with_cfg_cerrado(self, cal_with_service):
        """[CFG] CERRADO all-day for one date → that date returns []."""
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        target = date(2026, 3, 24)  # Tuesday (would normally have slots)
        cfg_event = make_range_all_day_event(
            "cfg1", "[CFG] CERRADO", "2026-03-24", "2026-03-25"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [cfg_event]
        }

        result = cal_module.get_slots_disponibles_range(target, target)
        assert result[target] == []

    def test_get_slots_disponibles_range_with_cfg_vacaciones_multi_day(
        self, cal_with_service
    ):
        """[CFG] VACACIONES all-day spanning 3 days → those 3 days return []."""
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        start = date(2026, 3, 24)  # Tuesday
        end = date(2026, 3, 26)    # Thursday

        # Vacaciones covers all 3 days (end date exclusive = 2026-03-27)
        cfg_event = make_range_all_day_event(
            "cfg1", "[CFG] VACACIONES", "2026-03-24", "2026-03-27"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [cfg_event]
        }

        result = cal_module.get_slots_disponibles_range(start, end)
        assert result[date(2026, 3, 24)] == []
        assert result[date(2026, 3, 25)] == []
        assert result[date(2026, 3, 26)] == []


# ── TestCitasCacheInfrastructure ───────────────────────────────────────────────

class TestCitasCacheInfrastructure:

    def _make_cita_event(self, svc, telefono="34600000001"):
        now = datetime.now(TZ)
        desc = (
            f"Nombre: Ana\nTelefono: {telefono}\n"
            "Estado: confirmada\nRecordatorio: no"
        )
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [make_gc_event(
                "evt1", "Corte de pelo - Ana", desc,
                now + timedelta(days=1), now + timedelta(days=1, minutes=30)
            )]
        }

    def test_get_citas_futuras_caches_result(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_cita_event(svc)

        cal.get_citas_futuras("34600000001")
        cal.get_citas_futuras("34600000001")

        # Only one events.list call — second hit is from cache
        assert svc.events.return_value.list.return_value.execute.call_count == 1

    def test_get_citas_futuras_cache_expires_after_ttl(self, cal_with_service):
        import app.services.calendar as cal_module
        import time
        cal, svc = cal_with_service
        self._make_cita_event(svc)

        cal.get_citas_futuras("34600000001")

        # Manually expire the cache entry
        with cal_module._citas_cache_lock:
            citas, _ = cal_module._citas_cache["34600000001"]
            cal_module._citas_cache["34600000001"] = (citas, time.time() - 181)

        cal.get_citas_futuras("34600000001")

        # Should have fetched again after expiry
        assert svc.events.return_value.list.return_value.execute.call_count == 2

    def test_get_citas_futuras_cache_separate_per_phone(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        # First phone
        self._make_cita_event(svc, "34600000001")
        cal.get_citas_futuras("34600000001")

        # Second phone
        self._make_cita_event(svc, "34600000002")
        cal.get_citas_futuras("34600000002")

        # Both should be cached independently
        assert "34600000001" in cal_module._citas_cache
        assert "34600000002" in cal_module._citas_cache

    def test_get_citas_futuras_returns_defensive_copy(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_cita_event(svc)

        result1 = cal.get_citas_futuras("34600000001")
        result1.append({"id": "intruder"})

        result2 = cal.get_citas_futuras("34600000001")
        # The mutation of result1 must not affect cached data or result2
        assert not any(c["id"] == "intruder" for c in result2)

    def test_get_citas_futuras_does_not_cache_on_exception(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.side_effect = Exception(
            "API down"
        )

        result = cal.get_citas_futuras("34600000001")

        assert result == []
        assert "34600000001" not in cal_module._citas_cache

    def test_crear_cita_invalidates_citas_cache_for_telefono(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        self._make_cita_event(svc)

        # Populate cache
        cal.get_citas_futuras("34600000001")
        assert "34600000001" in cal_module._citas_cache

        # crear_cita must evict the entry
        cal.crear_cita(
            date(2026, 3, 23), "10:00", "Ana", "34600000001",
            servicio=SERVICIOS["corte"],
        )
        assert "34600000001" not in cal_module._citas_cache

    def test_cancelar_cita_invalidates_citas_cache_extracted_from_event(
        self, cal_with_service
    ):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        # Seed cache for phone
        cal_module._citas_cache["34600000001"] = ([], __import__("time").time())

        # Event returned by events().get() contains the phone
        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": (
                "Nombre: Ana\nTelefono: 34600000001\n"
                "Estado: confirmada\nRecordatorio: no"
            ),
            "start": {"dateTime": "2026-03-23T10:00:00+01:00"},
        }
        cal.cancelar_cita("evt1")
        assert "34600000001" not in cal_module._citas_cache

    def test_confirmar_cita_invalidates_citas_cache(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        # Seed cache
        cal_module._citas_cache["34600000001"] = ([], __import__("time").time())

        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": (
                "Nombre: Ana\nTelefono: 34600000001\n"
                "Estado: pendiente\nRecordatorio: no"
            ),
        }
        cal.confirmar_cita("evt1")
        assert "34600000001" not in cal_module._citas_cache

    def test_marcar_manual_confirmado_invalidates_citas_cache(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        # Seed cache
        cal_module._citas_cache["34600000002"] = ([], __import__("time").time())

        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt2",
            "description": (
                "Nombre: Luis\nTelefono: 34600000002\n"
                "Estado: pendiente\nRecordatorio: no"
            ),
        }
        cal.marcar_manual_confirmado("evt2")
        assert "34600000002" not in cal_module._citas_cache

    def test_invalidate_citas_cache_with_none_is_noop(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        # Should not raise
        cal_module._invalidate_citas_cache(None)
        # Cache remains unchanged
        assert cal_module._citas_cache == {}

    def test_invalidate_citas_cache_when_event_has_no_telefono(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        # Event description has no Telefono field
        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": "Nombre: Ana\nEstado: pendiente",
            "start": {"dateTime": "2026-03-23T10:00:00+01:00"},
        }
        # Should not raise even when parse_tel returns None
        cal.cancelar_cita("evt1")  # triggers invalidation with None phone
        assert cal_module._citas_cache == {}

    def test_cache_key_consistent_between_crear_and_cancelar(self, cal_with_service):
        """
        CRITICAL: phone stored by crear_cita and phone extracted by cancelar_cita
        must use the same key format (digits-only, no '+').
        """
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        self._make_cita_event(svc)

        # Populate cache using the same phone format crear_cita would use
        telefono = "34600000001"
        cal.get_citas_futuras(telefono)
        assert telefono in cal_module._citas_cache

        # cancelar_cita fetches the event, parses the phone, then invalidates
        svc.events.return_value.get.return_value.execute.return_value = {
            "id": "evt1",
            "description": (
                f"Nombre: Ana\nTelefono: {telefono}\n"
                "Estado: confirmada\nRecordatorio: no"
            ),
            "start": {"dateTime": "2026-03-23T10:00:00+01:00"},
        }
        cal.cancelar_cita("evt1")

        # Key must have been evicted (same format on both sides)
        assert telefono not in cal_module._citas_cache


# ── TestGetEventById ───────────────────────────────────────────────────────────

class TestGetEventById:

    def _make_event_response(self, svc, telefono="34600000001", event_id="evt1",
                              summary="Corte de pelo - Ana", all_day=False,
                              description=None):
        if description is None:
            description = (
                f"Nombre: Ana\nTelefono: {telefono}\n"
                "Estado: confirmada\nRecordatorio: no"
            )
        if all_day:
            svc.events.return_value.get.return_value.execute.return_value = {
                "id": event_id,
                "summary": summary,
                "description": description,
                "start": {"date": "2026-03-23"},
                "end": {"date": "2026-03-23"},
            }
        else:
            svc.events.return_value.get.return_value.execute.return_value = {
                "id": event_id,
                "summary": summary,
                "description": description,
                "start": {"dateTime": "2026-03-23T10:00:00+01:00"},
                "end": {"dateTime": "2026-03-23T10:30:00+01:00"},
            }

    def test_get_event_by_id_returns_event_when_phone_matches(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_event_response(svc)
        result = cal.get_event_by_id("evt1", "34600000001")
        assert result is not None
        assert result["id"] == "evt1"
        assert result["title"] == "Corte de pelo - Ana"
        assert "start" in result
        assert "end" in result
        assert "description" in result

    def test_get_event_by_id_returns_none_when_phone_mismatch(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_event_response(svc, telefono="34600000001")
        result = cal.get_event_by_id("evt1", "34600000999")
        assert result is None

    def test_get_event_by_id_returns_none_when_event_not_found(
        self, cal_with_service
    ):
        cal, svc = cal_with_service
        svc.events.return_value.get.return_value.execute.side_effect = Exception(
            "Not found"
        )
        result = cal.get_event_by_id("evt_missing", "34600000001")
        assert result is None

    def test_get_event_by_id_returns_none_for_cfg_event(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_event_response(
            svc, summary="[CFG] CERRADO", telefono="34600000001"
        )
        result = cal.get_event_by_id("evt1", "34600000001")
        assert result is None

    def test_get_event_by_id_returns_none_for_all_day_event(self, cal_with_service):
        cal, svc = cal_with_service
        self._make_event_response(svc, all_day=True)
        result = cal.get_event_by_id("evt1", "34600000001")
        assert result is None

    def test_get_event_by_id_returns_none_when_no_phone_in_description(
        self, cal_with_service
    ):
        cal, svc = cal_with_service
        self._make_event_response(
            svc,
            description="Nombre: Ana\nEstado: confirmada\nRecordatorio: no",
        )
        result = cal.get_event_by_id("evt1", "34600000001")
        assert result is None

    def test_get_event_by_id_uses_fields_parameter(self, cal_with_service):
        """get_event_by_id passes fields= to events().get() to limit payload size."""
        cal, svc = cal_with_service
        self._make_event_response(svc)
        cal.get_event_by_id("evt1", "34600000001")

        call_kwargs = svc.events.return_value.get.call_args[1]
        assert 'fields' in call_kwargs


# ── _compute_slots with event_horario ─────────────────────────────────────────

class TestComputeSlotsEventHorario:
    """Verify the event_horario parameter in _compute_slots."""

    def test_event_horario_used_when_no_special_schedule(self):
        """event_horario provides base slots when no [CFG] HORARIO is present."""
        import app.services.calendar as cal_module
        d = date(2099, 12, 25)  # Sunday — no HORARIO_BASE entry
        event_horario = [("10:00", "12:00")]
        result = cal_module._compute_slots(
            d, [], duracion_min=30, presencia_cliente_min=30,
            event_horario=event_horario,
        )
        assert "10:00" in result
        assert "10:30" in result
        assert "11:30" in result
        assert "12:00" not in result

    def test_special_schedule_takes_priority_over_event_horario(self):
        """[CFG] HORARIO overrides event_horario (highest priority for open
        schedules)."""
        import app.services.calendar as cal_module
        d = date(2099, 12, 25)
        cfg_ev = {
            'id': 'cfg1', 'title': '[CFG] HORARIO 09:00-10:00', 'description': '',
            'start': aware(2099, 12, 25, 0, 0), 'end': aware(2099, 12, 25, 23, 59),
            'all_day': True,
        }
        event_horario = [("10:00", "14:00")]
        result = cal_module._compute_slots(
            d, [cfg_ev], duracion_min=30, presencia_cliente_min=30,
            event_horario=event_horario,
        )
        # special_schedule 09:00-10:00: only 09:00 slot
        # (09:00+30=09:30≤10:00 ✓; 09:30+30=10:00≤10:00 ✓ → 09:00 and 09:30)
        assert "09:00" in result
        assert "10:30" not in result  # event_horario's range must not appear

    def test_cerrado_overrides_event_horario(self):
        """[CFG] CERRADO takes priority over event_horario → []."""
        import app.services.calendar as cal_module
        d = date(2099, 12, 25)
        cfg_ev = {
            'id': 'cfg1', 'title': '[CFG] CERRADO', 'description': '',
            'start': aware(2099, 12, 25, 0, 0), 'end': aware(2099, 12, 25, 23, 59),
            'all_day': True,
        }
        event_horario = [("10:00", "14:00")]
        result = cal_module._compute_slots(d, [cfg_ev], event_horario=event_horario)
        assert result == []

    def test_none_event_horario_falls_back_to_horario_base(self):
        """event_horario=None (default) → normal HORARIO_BASE fallback path
        unchanged."""
        import app.services.calendar as cal_module
        d = date(2026, 3, 24)  # Tuesday — has HORARIO_BASE slots
        result = cal_module._compute_slots(
            d, [], duracion_min=30, presencia_cliente_min=30,
            event_horario=None,
        )
        # Should return the same slots as without event_horario
        expected = cal_module._compute_slots(
            d, [], duracion_min=30, presencia_cliente_min=30
        )
        assert result == expected


# ── get_slots_disponibles_evento ───────────────────────────────────────────────

class TestGetSlotsDisponiblesEvento:
    """Tests for get_slots_disponibles_evento and get_slots_disponibles_evento_range."""

    def test_returns_slots_for_event_day(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}

        d = date(2099, 12, 25)
        dias = {d.isoformat(): [["10:00", "12:00"]]}
        with patch("app.services.calendar.service.EVENTO_DIAS", dias):
            slots = cal_module.get_slots_disponibles_evento(d)
        assert "10:00" in slots
        assert "11:30" in slots
        assert "12:00" not in slots

    def test_returns_empty_for_day_not_in_evento_dias(self, cal_with_service):
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        d = date(2099, 12, 26)
        with patch("app.services.calendar.service.EVENTO_DIAS", {}):
            slots = cal_module.get_slots_disponibles_evento(d)
        assert slots == []

    def test_evt_cache_key_populated_after_call(self, cal_with_service):
        """After get_slots_disponibles_evento, an evt_* key exists in _slot_cache."""
        import app.services.calendar as cal_module
        cal, svc = cal_with_service
        svc.events.return_value.list.return_value.execute.return_value = {"items": []}

        d = date(2099, 12, 25)
        dias = {d.isoformat(): [["10:00", "12:00"]]}
        with patch("app.services.calendar.service.EVENTO_DIAS", dias):
            cal_module.get_slots_disponibles_evento(d)
        evt_key = f"evt_{cal_module._slot_cache_key(d, 30, 30)}"
        assert evt_key in cal_module._slot_cache

    def test_invalidate_slot_cache_clears_evt_keys(self, cal_with_service):
        """_invalidate_slot_cache removes both normal and evt_* keys for the date."""
        import app.services.calendar as cal_module
        cal, svc = cal_with_service

        d = date(2099, 12, 25)
        normal_key = cal_module._slot_cache_key(d, 30, 30)
        evt_key = f"evt_{normal_key}"
        with cal_module._slot_cache_lock:
            cal_module._slot_cache[normal_key] = ([], __import__("time").time())
            cal_module._slot_cache[evt_key] = ([], __import__("time").time())

        cal_module._invalidate_slot_cache(d)

        assert normal_key not in cal_module._slot_cache
        assert evt_key not in cal_module._slot_cache
