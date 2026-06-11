# tests/test_scheduler.py
"""
Unit tests for app/services/scheduler.py.
Tests the ENVIAR_CONFIRMACIONES and ENVIAR_RECORDATORIOS toggle guards
that short-circuit each job before doing any real work.
"""
from datetime import datetime
from unittest.mock import patch, MagicMock
import pytz

from app.services.scheduler import job_sync_citas_manuales, job_enviar_recordatorios

TZ = pytz.timezone("Europe/Madrid")


def _make_manual_event(
        event_id: str, telefono: str = "34600000001", nombre: str = "Ana"):
    """Build a minimal manual event dict as returned by
    get_eventos_manuales_sin_confirmar."""
    start_dt = TZ.localize(datetime(2026, 6, 1, 10, 0))
    return {
        'id': event_id,
        'title': f'Corte de pelo - {nombre}',
        'nombre': nombre,
        'description': (
            f'Nombre: {nombre}\nTelefono: {telefono}'
            '\nEstado: pendiente\nRecordatorio: no'
        ),
        'telefono': telefono,
        'start': start_dt,
        'service_key': 'corte',
    }


# ── job_sync_citas_manuales ────────────────────────────────────────────────────

class TestJobSyncCitasManuales:
    def test_skips_when_confirmaciones_disabled(self, monkeypatch):
        """When ENVIAR_CONFIRMACIONES is False the calendar fetch must not be called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_CONFIRMACIONES", False)
        with patch(
            "app.services.scheduler.cal_service"
            ".get_eventos_manuales_sin_confirmar"
        ) as mock_fetch:
            job_sync_citas_manuales()
        mock_fetch.assert_not_called()

    def test_runs_when_confirmaciones_enabled(self, monkeypatch):
        """When ENVIAR_CONFIRMACIONES is True the calendar fetch is called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_CONFIRMACIONES", True)
        with patch(
            "app.services.scheduler.cal_service"
            ".get_eventos_manuales_sin_confirmar",
            return_value=[],
        ) as mock_fetch:
            job_sync_citas_manuales()
        mock_fetch.assert_called_once()

    def test_processes_events_without_refetching(self, monkeypatch):
        """2 pending manual events → send_template x2,
        marcar_manual_confirmado x2, _get_service never called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_CONFIRMACIONES", True)
        events = [
            _make_manual_event("evt1", "34600000001"),
            _make_manual_event("evt2", "34600000002"),
        ]
        mock_get_service = MagicMock()
        _cal = "app.services.scheduler.cal_service"
        _wa = "app.services.scheduler.wa_service"
        with patch(f"{_cal}.get_eventos_manuales_sin_confirmar",
                   return_value=events), \
             patch(f"{_wa}.send_template",
                   return_value=True) as mock_send, \
             patch(f"{_cal}.marcar_manual_confirmado",
                   return_value=True) as mock_mark, \
             patch("app.services.calendar._get_service", mock_get_service):
            job_sync_citas_manuales()
        assert mock_send.call_count == 2
        assert mock_mark.call_count == 2
        mock_get_service.assert_not_called()

    def test_processes_multiple_events_sequentially(self, monkeypatch):
        """3 pending manual events → send_template x3, marcar_manual_confirmado x3."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_CONFIRMACIONES", True)
        events = [
            _make_manual_event("evt1", "34600000001", "Ana"),
            _make_manual_event("evt2", "34600000002", "Luis"),
            _make_manual_event("evt3", "34600000003", "María"),
        ]
        _cal = "app.services.scheduler.cal_service"
        _wa = "app.services.scheduler.wa_service"
        with patch(f"{_cal}.get_eventos_manuales_sin_confirmar",
                   return_value=events), \
             patch(f"{_wa}.send_template",
                   return_value=True) as mock_send, \
             patch(f"{_cal}.marcar_manual_confirmado",
                   return_value=True) as mock_mark:
            job_sync_citas_manuales()
        assert mock_send.call_count == 3
        assert mock_mark.call_count == 3


# ── job_enviar_recordatorios ───────────────────────────────────────────────────

class TestJobEnviarRecordatorios:
    def test_skips_when_recordatorios_disabled(self, monkeypatch):
        """When ENVIAR_RECORDATORIOS is False the calendar fetch must not be called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_RECORDATORIOS", False)
        with patch(
            "app.services.scheduler.cal_service"
            ".get_citas_para_recordatorio"
        ) as mock_fetch:
            job_enviar_recordatorios()
        mock_fetch.assert_not_called()

    def test_runs_when_recordatorios_enabled(self, monkeypatch):
        """When ENVIAR_RECORDATORIOS is True the calendar fetch is called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_RECORDATORIOS", True)
        with patch(
            "app.services.scheduler.cal_service"
            ".get_citas_para_recordatorio",
            return_value=[],
        ) as mock_fetch:
            job_enviar_recordatorios()
        mock_fetch.assert_called_once()
