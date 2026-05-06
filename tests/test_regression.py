# tests/test_regression.py
"""
Regression tests for bugs found during quality review.
Each test is named after the bug it covers.
"""
import pytest
import threading
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock
import pytz

TZ = pytz.timezone("Europe/Madrid")
PHONE = "34600000001"


@pytest.fixture(autouse=True)
def clear_states():
    import app.handlers.conversation as conv
    conv._states.clear()
    conv._phone_locks.clear()
    yield
    conv._states.clear()
    conv._phone_locks.clear()


@pytest.fixture
def mock_wa():
    with patch("app.handlers.conversation.wa") as wa:
        wa.send_text_message.return_value = True
        wa.send_interactive.return_value = True
        yield wa


@pytest.fixture
def mock_cal():
    with patch("app.handlers.conversation.cal") as cal:
        cal.get_slots_disponibles.return_value = ["10:00", "10:30", "16:00", "16:30"]
        cal.get_citas_futuras.return_value = []
        cal.reservar_cita.return_value = ("evt_new", None)
        cal.cancelar_cita.return_value = True
        cal.confirmar_cita.return_value = True
        yield cal


def send(phone=PHONE, text=None, interactive_id=None):
    from app.handlers.conversation import handle_message
    handle_message(phone=phone, text=text, interactive_id=interactive_id)


# ── Bug 1: confirmar_cita return value was ignored ─────────────────────────────

class TestReminderConfirmChecksReturnValue:
    def test_confirm_success_sends_confirmed_message(self, mock_wa, mock_cal):
        """confirmar_cita succeeds → user sees 'confirmada'."""
        mock_cal.confirmar_cita.return_value = True
        mock_cal.get_citas_futuras.return_value = [{
            'id': 'evt1',
            'title': 'Corte de pelo - Test',
            'description': 'Nombre: Test\nTelefono: 34600000001\nEstado: pendiente',
            'start': TZ.localize(datetime(2026, 3, 23, 10, 0)),
            'end':   TZ.localize(datetime(2026, 3, 23, 10, 30)),
        }]
        send(interactive_id="reminder_confirm_evt1")
        args = mock_wa.send_text_message.call_args_list
        texts = [call.args[1] for call in args]
        assert any("confirmada" in t.lower() for t in texts)

    def test_confirm_failure_sends_error_message(self, mock_wa, mock_cal):
        """confirmar_cita fails → user sees error, NOT false 'confirmada'."""
        mock_cal.confirmar_cita.return_value = False
        mock_cal.get_citas_futuras.return_value = [{
            'id': 'evt1',
            'title': 'Corte de pelo - Test',
            'description': 'Nombre: Test\nTelefono: 34600000001\nEstado: pendiente',
            'start': TZ.localize(datetime(2026, 3, 23, 10, 0)),
            'end':   TZ.localize(datetime(2026, 3, 23, 10, 30)),
        }]
        send(interactive_id="reminder_confirm_evt1")
        args = mock_wa.send_text_message.call_args_list
        texts = [call.args[1] for call in args]
        # Must NOT send the success message
        assert not any("confirmada" in t and "✅" in t for t in texts)
        # Must send an error message
        assert any("contacta" in t.lower() or "pudo" in t.lower() for t in texts)


# ── Bug 2: slot_taken recovery sent ALL day slots to build_hours_list ──────────

class TestSlotTakenRecoveryRespectsPeriodLimit:
    def setup_confirm_state(self):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.selected_date = date(2026, 3, 23)
        state.selected_slot = "10:00"
        state.selected_service = SERVICIOS["corte"]
        state.available_days = [date(2026, 3, 23)]
        return state

    def test_slot_taken_with_both_periods_shows_period_picker(self, mock_wa, mock_cal):
        """When slot_taken and both morning+afternoon available → period picker (not raw list)."""
        import app.handlers.conversation as conv
        self.setup_confirm_state()
        mock_cal.reservar_cita.return_value = (None, "slot_taken")
        # 8 morning + 8 afternoon = 16 slots — would exceed WhatsApp limit if passed directly
        mock_cal.get_slots_disponibles.return_value = [
            "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
            "16:00", "16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
        ]
        send(text="Ana")
        state = conv._get(PHONE)
        # Must go to period selection, not directly to hour selection
        assert state.step == conv.BOOK_SELECT_PERIOD

    def test_slot_taken_only_morning_goes_to_hour_select(self, mock_wa, mock_cal):
        """When slot_taken and only morning available → hour select (8 slots ≤ limit)."""
        import app.handlers.conversation as conv
        self.setup_confirm_state()
        mock_cal.reservar_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = [
            "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"
        ]
        send(text="Ana")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_HOUR
        # Only morning slots → max 8 → within WhatsApp limit
        assert len(state.available_slots) <= 8


class TestChangeHourRespectsPeriodLimit:
    def setup_confirm_state(self):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.selected_date = date(2026, 3, 23)
        state.selected_slot = "10:00"
        state.selected_service = SERVICIOS["corte"]
        state.available_days = [date(2026, 3, 23)]
        return state

    def test_slot_taken_only_afternoon_goes_direct(self, mock_wa, mock_cal):
        """slot_taken with only afternoon slots → directly to hour select (within limit)."""
        import app.handlers.conversation as conv
        self.setup_confirm_state()
        mock_cal.reservar_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = [
            "16:00", "16:30", "17:00", "17:30"
        ]
        send(text="Ana")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_HOUR
        assert len(state.available_slots) <= 8


# ── Bug 3: phone with '+' prefix not matched ───────────────────────────────────

class TestPhoneNormalisationInParseTel:
    def test_plus_prefix_stripped(self):
        from app.utils.parser import parse_tel
        # Barber writes +34... in Calendar — must match WhatsApp '34...' format
        assert parse_tel("Telefono: +34600000001") == "34600000001"

    def test_no_plus_unchanged(self):
        from app.utils.parser import parse_tel
        assert parse_tel("Telefono: 34600000001") == "34600000001"

    def test_plus_with_spaces_stripped(self):
        from app.utils.parser import parse_tel
        assert parse_tel("Telefono: +34 600 000 001") == "34600000001"


class TestPhoneNormalisationInCalendar:
    """Ensure get_citas_futuras finds manual appointments
    even if the barber stored the phone as '+34...' instead of '34...'."""

    def _make_service(self, desc):
        svc = MagicMock()
        svc.events.return_value.list.return_value.execute.return_value = {
            "items": [{
                "id": "evt1",
                "summary": "Cita - Test",
                "description": desc,
                "start": {"dateTime": TZ.localize(datetime(2026, 3, 23, 10, 0)).isoformat()},
                "end":   {"dateTime": TZ.localize(datetime(2026, 3, 23, 10, 30)).isoformat()},
            }]
        }
        return svc

    def test_get_citas_futuras_finds_plus_prefix(self):
        import app.services.calendar as cal
        if hasattr(cal._thread_local, "service"):
            del cal._thread_local.service
        svc = self._make_service("Telefono: +34600000001\nEstado: confirmada")
        with patch("app.services.calendar._get_service", return_value=svc):
            citas = cal.get_citas_futuras("34600000001")
        assert len(citas) == 1

    def test_get_citas_futuras_finds_no_country_code(self):
        import app.services.calendar as cal
        if hasattr(cal._thread_local, "service"):
            del cal._thread_local.service
        svc = self._make_service("Telefono: 600000001\nEstado: confirmada")
        with patch("app.services.calendar._get_service", return_value=svc):
            citas = cal.get_citas_futuras("34600000001")
        assert len(citas) == 1


# ── Bug 4: clean_expired_states thread safety ──────────────────────────────────

class TestCleanExpiredStatesThreadSafety:
    def test_no_runtime_error_when_state_modified_concurrently(self):
        """
        Simulate clean_expired_states running while handle_message creates states.
        Should complete without RuntimeError.
        """
        import app.handlers.conversation as conv

        errors = []
        barrier = threading.Barrier(2)

        def writer():
            barrier.wait()
            for i in range(50):
                # Rapidly add and remove states
                conv._states[f"phone_{i}"] = conv.ConversationState()
                conv._states.pop(f"phone_{i}", None)

        def cleaner():
            barrier.wait()
            for _ in range(50):
                try:
                    conv.clean_expired_states()
                except RuntimeError as e:
                    errors.append(str(e))

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=cleaner)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert errors == [], f"RuntimeError in clean_expired_states: {errors}"

    def test_expired_states_removed(self):
        import app.handlers.conversation as conv
        state = conv._get("stale_phone")
        state.last_interaction = TZ.localize(datetime(2020, 1, 1))
        conv.clean_expired_states()
        assert "stale_phone" not in conv._states

    def test_active_states_kept(self):
        import app.handlers.conversation as conv
        state = conv._get("active_phone")
        state.last_interaction = datetime.now(TZ)
        conv.clean_expired_states()
        assert "active_phone" in conv._states


# ── Bug 5: no max length on name ───────────────────────────────────────────────

class TestNameMaxLength:
    def setup_state(self):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.selected_date = date(2026, 3, 23)
        state.selected_slot = "10:00"
        state.selected_service = SERVICIOS["corte"]
        state.available_days = [date(2026, 3, 23)]
        return state

    def test_very_long_name_rejected(self, mock_wa, mock_cal):
        """A 200-char name must be rejected, not stored."""
        import app.handlers.conversation as conv
        self.setup_state()
        send(text="A" * 200)
        # State must stay in BOOK_ENTER_NAME (not advance)
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_ENTER_NAME
        assert state.nombre is None
        mock_wa.send_text_message.assert_called()

    def test_normal_name_accepted(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = ("evt_new", None)
        send(text="Ana García")
        # Valid name books directly and clears state
        assert mock_wa.send_interactive.call_count >= 1
        assert conv._states.get(PHONE) is None

    def test_boundary_100_chars_accepted(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = ("evt_new", None)
        send(text="A" * 100)
        # Valid name (exactly at limit) books directly and clears state
        assert mock_wa.send_interactive.call_count >= 1
        assert conv._states.get(PHONE) is None

    def test_boundary_101_chars_rejected(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(text="A" * 101)
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_ENTER_NAME


# ── Bug 6: None state guard in _handle_book_confirm ───────────────────────────

class TestBookConfirmNoneGuard:
    def test_confirm_with_none_selected_date_resets_to_menu(self, mock_wa, mock_cal):
        """If selected_date is None (corrupted state), go to menu instead of crashing."""
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.selected_date = None  # corrupted
        state.selected_slot = "10:00"
        state.selected_service = SERVICIOS["corte"]
        send(text="AnaGuard")
        # Should not raise; should reset to menu
        assert conv._states.get(PHONE) is None

    def test_confirm_with_none_selected_slot_resets_to_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.selected_date = date(2026, 3, 23)
        state.selected_slot = None  # corrupted
        state.selected_service = SERVICIOS["corte"]
        send(text="AnaGuard")
        assert conv._states.get(PHONE) is None


# ── Config invariant: presencia_cliente_min >= duracion_min ───────────────────

class TestValidateConfigInvariant:
    def test_validate_config_rejects_presencia_below_duracion(self):
        """validate_config must raise RuntimeError when presencia_cliente_min < duracion_min."""
        from unittest.mock import patch
        from app.config import validate_config

        bad_servicios = {
            "bad": {"nombre": "X", "precio": 10, "duracion_min": 30, "presencia_cliente_min": 10}
        }
        with patch.multiple(
            "app.config",
            WHATSAPP_PHONE_NUMBER_ID="x",
            WHATSAPP_ACCESS_TOKEN="x",
            WHATSAPP_VERIFY_TOKEN="x",
            GOOGLE_CALENDAR_ID="x",
            SERVICIOS=bad_servicios,
        ):
            with pytest.raises(RuntimeError, match="presencia_cliente_min"):
                validate_config()
