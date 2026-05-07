# tests/test_scheduler.py
"""
Unit tests for app/services/scheduler.py.
Tests the ENVIAR_CONFIRMACIONES and ENVIAR_RECORDATORIOS toggle guards
that short-circuit each job before doing any real work.
"""
import pytest
from unittest.mock import patch, MagicMock

from app.services.scheduler import job_sync_citas_manuales, job_enviar_recordatorios


# ── job_sync_citas_manuales ────────────────────────────────────────────────────

class TestJobSyncCitasManuales:
    def test_skips_when_confirmaciones_disabled(self, monkeypatch):
        """When ENVIAR_CONFIRMACIONES is False the calendar fetch must not be called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_CONFIRMACIONES", False)
        with patch("app.services.scheduler.cal_service.get_eventos_manuales_sin_confirmar") as mock_fetch:
            job_sync_citas_manuales()
        mock_fetch.assert_not_called()

    def test_runs_when_confirmaciones_enabled(self, monkeypatch):
        """When ENVIAR_CONFIRMACIONES is True the calendar fetch is called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_CONFIRMACIONES", True)
        with patch("app.services.scheduler.cal_service.get_eventos_manuales_sin_confirmar", return_value=[]) as mock_fetch:
            job_sync_citas_manuales()
        mock_fetch.assert_called_once()


# ── job_enviar_recordatorios ───────────────────────────────────────────────────

class TestJobEnviarRecordatorios:
    def test_skips_when_recordatorios_disabled(self, monkeypatch):
        """When ENVIAR_RECORDATORIOS is False the calendar fetch must not be called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_RECORDATORIOS", False)
        with patch("app.services.scheduler.cal_service.get_citas_para_recordatorio") as mock_fetch:
            job_enviar_recordatorios()
        mock_fetch.assert_not_called()

    def test_runs_when_recordatorios_enabled(self, monkeypatch):
        """When ENVIAR_RECORDATORIOS is True the calendar fetch is called."""
        monkeypatch.setattr("app.services.scheduler.ENVIAR_RECORDATORIOS", True)
        with patch("app.services.scheduler.cal_service.get_citas_para_recordatorio", return_value=[]) as mock_fetch:
            job_enviar_recordatorios()
        mock_fetch.assert_called_once()
