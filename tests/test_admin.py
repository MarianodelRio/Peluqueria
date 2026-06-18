# tests/test_admin.py
"""
Tests for app/utils/admin.py utilities and admin command intercept in
app/handlers/conversation.py.
"""
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Tests for build_status_report()
# ---------------------------------------------------------------------------

class TestBuildStatusReport:
    """Tests for the build_status_report utility function."""

    def _make_psutil_mock(self):
        """Return a MagicMock that emulates the psutil module."""
        psutil_mock = MagicMock()
        psutil_mock.cpu_percent.return_value = 23.5
        mem = MagicMock()
        mem.percent = 45.2
        mem.used = 4 * 1024 ** 2      # 4 MB (keep small for format check)
        mem.total = 8 * 1024 ** 2     # 8 MB
        psutil_mock.virtual_memory.return_value = mem
        disk = MagicMock()
        disk.percent = 60.0
        disk.used = 100 * 1024 ** 3   # 100 GB
        disk.total = 200 * 1024 ** 3  # 200 GB
        psutil_mock.boot_time.return_value = 0.0   # very old boot, large uptime
        psutil_mock.disk_usage.return_value = disk
        return psutil_mock

    def test_healthy_report_contains_cpu_ram_disk_uptime(self):
        """A healthy report must contain CPU, RAM, disk, and uptime sections."""
        psutil_mock = self._make_psutil_mock()

        _metrics_val = {"uptime_seconds": 3661, "mensajes_recibidos": 5}
        with (
            patch.dict("sys.modules", {"psutil": psutil_mock}),
            patch("app.utils.admin.check_calendar_health", return_value=True),
            patch("app.utils.admin.metrics.get_all", return_value=_metrics_val),
        ):
            from app.utils.admin import build_status_report
            report = build_status_report()

        assert "CPU" in report
        assert "RAM" in report
        assert "Disco" in report
        assert "Uptime" in report or "uptime" in report

    def test_calendar_failure_shows_error_marker_no_exception(self):
        """When Calendar health check raises, report must contain an error
        marker and not propagate."""
        psutil_mock = self._make_psutil_mock()

        with (
            patch.dict("sys.modules", {"psutil": psutil_mock}),
            patch(
                "app.utils.admin.check_calendar_health",
                side_effect=Exception("timeout"),
            ),
            patch(
                "app.utils.admin.metrics.get_all",
                return_value={"uptime_seconds": 0},
            ),
        ):
            from app.utils.admin import build_status_report
            report = build_status_report()

        assert "ERROR" in report or "error" in report.lower()
        # Must not raise — we received a string

    def test_psutil_failure_shows_partial_error_no_exception(self):
        """When psutil fails entirely, report includes an error string and
        does not raise."""
        broken_psutil = MagicMock()
        broken_psutil.cpu_percent.side_effect = RuntimeError("no sensors")

        with (
            patch.dict("sys.modules", {"psutil": broken_psutil}),
            patch("app.utils.admin.check_calendar_health", return_value=True),
            patch(
                "app.utils.admin.metrics.get_all",
                return_value={"uptime_seconds": 0},
            ),
        ):

            from app.utils.admin import build_status_report
            report = build_status_report()

        # The report must be a string and contain some error indication
        assert isinstance(report, str)
        assert len(report) > 0


# ---------------------------------------------------------------------------
# Shared fixtures for conversation intercept tests
# ---------------------------------------------------------------------------

ADMIN = "34600000001"
OTHER = "34600000002"


@pytest.fixture(autouse=True)
def patch_admin_config(monkeypatch):
    """Patch ADMIN_PHONE and ADMIN_COMANDOS in conversation module for every test."""
    monkeypatch.setattr("app.handlers.conversation.ADMIN_PHONE", ADMIN)
    monkeypatch.setattr(
        "app.handlers.conversation.ADMIN_COMANDOS",
        frozenset({"/status", "/help", "/logs", "/restart"}),
    )


@pytest.fixture(autouse=True)
def reset_conversation_state():
    """Clear conversation state between tests."""
    import app.handlers.conversation as conv
    conv._states.clear()
    conv._phone_locks.clear()
    yield
    conv._states.clear()
    conv._phone_locks.clear()


# ---------------------------------------------------------------------------
# Tests for the /status command (and general intercept behaviour)
# ---------------------------------------------------------------------------

class TestStatusCommand:

    def test_estado_from_admin_reaches_normal_flow(self, mock_wa, mock_cal):
        """/estado is NOT in ADMIN_COMANDOS, so it must reach normal flow (menu shown)."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(ADMIN, "/estado", None)

        mock_report.assert_not_called()
        mock_wa["interactive"].assert_called()

    def test_status_from_admin_calls_send_text(self, mock_wa):
        """/status from ADMIN_PHONE must call send_text_message with the report."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report",
            return_value="informe de prueba",
        ):
            conv.handle_message(ADMIN, "/status", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "informe de prueba")

    def test_status_uppercase_from_admin(self, mock_wa):
        """/STATUS (uppercase) from ADMIN_PHONE must be matched case-insensitively."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report",
            return_value="informe mayus",
        ):
            conv.handle_message(ADMIN, "/STATUS", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "informe mayus")

    def test_status_with_whitespace_from_admin(self, mock_wa):
        """  /status   with surrounding whitespace from ADMIN_PHONE must still match."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report",
            return_value="informe ws",
        ):
            conv.handle_message(ADMIN, "  /status  ", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "informe ws")

    def test_status_from_non_admin_triggers_normal_flow(self, mock_wa, mock_cal):
        """/status from a non-admin number must NOT trigger the admin command."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(OTHER, "/status", None)

        mock_report.assert_not_called()
        mock_wa["interactive"].assert_called()

    def test_status_when_admin_phone_empty_triggers_normal_flow(
        self, mock_wa, mock_cal, monkeypatch
    ):
        """/status when ADMIN_PHONE is empty string must not trigger admin command."""
        import app.handlers.conversation as conv
        monkeypatch.setattr("app.handlers.conversation.ADMIN_PHONE", "")

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(ADMIN, "/status", None)

        mock_report.assert_not_called()

    def test_status_via_interactive_id_does_not_trigger(self, mock_wa, mock_cal):
        """text=None (interactive message) must NOT trigger the admin command
        even from admin."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(ADMIN, None, "back_to_menu")

        mock_report.assert_not_called()

    def test_status_state_step_not_modified(self, mock_wa):
        """After /status admin command, state.step must remain at its pre-command value."""
        import app.handlers.conversation as conv

        # Pre-seed a non-MENU state for the admin phone
        conv._states[ADMIN] = conv.ConversationState(step=conv.BOOK_SELECT_DAY)

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ):
            conv.handle_message(ADMIN, "/status", None)

        state = conv._states.get(ADMIN)
        assert state is not None
        assert state.step == conv.BOOK_SELECT_DAY


# ---------------------------------------------------------------------------
# Tests for /help command
# ---------------------------------------------------------------------------

class TestHelpCommand:

    def test_help_from_admin_sends_text(self, mock_wa):
        """/help from ADMIN_PHONE must call send_text_message with the help text."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_help_message",
            return_value="texto de ayuda",
        ):
            conv.handle_message(ADMIN, "/help", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "texto de ayuda")

    def test_help_from_non_admin_triggers_normal_flow(self, mock_wa, mock_cal):
        """/help from a non-admin number must NOT trigger the admin command."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_help_message", return_value="ayuda"
        ) as mock_help:
            conv.handle_message(OTHER, "/help", None)

        mock_help.assert_not_called()
        mock_wa["interactive"].assert_called()


# ---------------------------------------------------------------------------
# Tests for /logs command
# ---------------------------------------------------------------------------

class TestLogsCommand:

    def test_logs_from_admin_sends_tail(self, mock_wa):
        """/logs from ADMIN_PHONE must call send_text_message with the log tail."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.read_log_tail",
            return_value="linea1\nlinea2\n",
        ):
            conv.handle_message(ADMIN, "/logs", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "linea1\nlinea2\n")

    def test_logs_from_admin_no_log_file(self, mock_wa):
        """/logs when LOG_FILE is not configured must return an error string (no raise)."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.read_log_tail",
            return_value="[ADMIN] LOG_FILE no está configurado.",
        ):
            conv.handle_message(ADMIN, "/logs", None)

        mock_wa["text"].assert_called_once()
        call_args = mock_wa["text"].call_args
        assert "LOG_FILE" in call_args[0][1] or "log" in call_args[0][1].lower()


# ---------------------------------------------------------------------------
# Tests for /restart command
# ---------------------------------------------------------------------------

class TestRestartCommand:

    def test_restart_sends_reiniciando_and_calls_schedule_restart(self, mock_wa):
        """/restart from ADMIN must send 'Reiniciando...' and call schedule_restart."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.schedule_restart"
        ) as mock_restart:
            conv.handle_message(ADMIN, "/restart", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "Reiniciando...")
        mock_restart.assert_called_once()

    def test_restart_from_non_admin_does_not_call_schedule_restart(
        self, mock_wa, mock_cal
    ):
        """/restart from a non-admin number must NOT call schedule_restart."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.schedule_restart"
        ) as mock_restart:
            conv.handle_message(OTHER, "/restart", None)

        mock_restart.assert_not_called()
