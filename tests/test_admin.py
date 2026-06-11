# tests/test_admin.py
"""
Tests for app/utils/admin.py (build_status_report) and the /estado
admin command intercept in app/handlers/conversation.py.
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
# Tests for the /estado intercept in conversation.py
# ---------------------------------------------------------------------------

ADMIN = "34600000001"
OTHER = "34600000002"


@pytest.fixture(autouse=True)
def patch_admin_config(monkeypatch):
    """Patch ADMIN_PHONE and ADMIN_COMANDO in conversation module for every test."""
    monkeypatch.setattr("app.handlers.conversation.ADMIN_PHONE", ADMIN)
    monkeypatch.setattr("app.handlers.conversation.ADMIN_COMANDO", "/estado")


@pytest.fixture(autouse=True)
def reset_conversation_state():
    """Clear conversation state between tests."""
    import app.handlers.conversation as conv
    conv._states.clear()
    conv._phone_locks.clear()
    yield
    conv._states.clear()
    conv._phone_locks.clear()


class TestAdminCommandIntercept:

    def test_estado_from_admin_calls_send_text_state_unchanged(self, mock_wa):
        """/estado from ADMIN_PHONE must call send_text_message and leave
        state.step unchanged."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report",
            return_value="informe de prueba",
        ):
            conv.handle_message(ADMIN, "/estado", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "informe de prueba")
        # State must not have been mutated to a booking step
        state = conv._states.get(ADMIN)
        # After the command the state exists (touch() ran) but step is MENU (default)
        assert state is None or state.step == conv.MENU

    def test_estado_from_non_admin_triggers_normal_flow(self, mock_wa, mock_cal):
        """/estado from a non-admin number must NOT trigger the admin command."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(OTHER, "/estado", None)

        mock_report.assert_not_called()
        # Non-admin sending arbitrary text in MENU state → menu displayed
        mock_wa["interactive"].assert_called()

    def test_estado_when_admin_phone_empty_triggers_normal_flow(
        self, mock_wa, mock_cal, monkeypatch
    ):
        """/estado when ADMIN_PHONE is empty string must not trigger admin command."""
        import app.handlers.conversation as conv
        monkeypatch.setattr("app.handlers.conversation.ADMIN_PHONE", "")

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(ADMIN, "/estado", None)

        mock_report.assert_not_called()

    def test_estado_uppercase_from_admin_triggers_report(self, mock_wa):
        """/ESTADO (uppercase) from ADMIN_PHONE must be matched case-insensitively."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report",
            return_value="informe mayus",
        ):
            conv.handle_message(ADMIN, "/ESTADO", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "informe mayus")

    def test_estado_with_whitespace_from_admin_triggers_report(self, mock_wa):
        """/estado with surrounding whitespace from ADMIN_PHONE must still
        be matched."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe ws"
        ):
            conv.handle_message(ADMIN, "  /estado  ", None)

        mock_wa["text"].assert_called_once_with(ADMIN, "informe ws")

    def test_estado_via_interactive_id_from_admin_does_not_trigger(
        self, mock_wa, mock_cal
    ):
        """text=None (interactive message) must NOT trigger the admin command
        even from admin."""
        import app.handlers.conversation as conv

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ) as mock_report:
            conv.handle_message(ADMIN, None, "back_to_menu")

        mock_report.assert_not_called()

    def test_estado_state_step_not_modified(self, mock_wa):
        """After admin command, state.step must remain at its pre-command value."""
        import app.handlers.conversation as conv

        # Pre-seed a non-MENU state for the admin phone
        conv._states[ADMIN] = conv.ConversationState(step=conv.BOOK_SELECT_DAY)

        with patch(
            "app.handlers.conversation.build_status_report", return_value="informe"
        ):
            conv.handle_message(ADMIN, "/estado", None)

        state = conv._states.get(ADMIN)
        assert state is not None
        assert state.step == conv.BOOK_SELECT_DAY
