# tests/test_conversation.py
"""
Unit tests for handlers/conversation.py.
Google Calendar and WhatsApp are fully mocked.
Validates state transitions, business rules and concurrency protection.
"""
import pytest
import threading
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, call
import pytz

TZ = pytz.timezone("Europe/Madrid")

PHONE = "34600000001"


@pytest.fixture(autouse=True)
def clear_states():
    """Reset in-memory state store before each test."""
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
        cal.get_slots_disponibles.return_value = ["10:00", "10:30", "11:00",
                                                   "16:00", "16:30", "17:00"]
        cal.get_citas_futuras.return_value = []
        cal.reservar_cita.return_value = ("evt_new", None)
        cal.cancelar_cita.return_value = True
        cal.confirmar_cita.return_value = True
        yield cal


def send(phone=PHONE, text=None, interactive_id=None):
    """Shorthand to call handle_message."""
    from app.handlers.conversation import handle_message
    handle_message(phone=phone, text=text, interactive_id=interactive_id)


# ── Initial state / MENU ───────────────────────────────────────────────────────

class TestMenuState:
    def test_unknown_text_shows_menu(self, mock_wa, mock_cal):
        send(text="hola")
        mock_wa.send_interactive.assert_called()

    def test_back_to_menu_from_any_state(self, mock_wa, mock_cal):
        """back_to_menu interactive_id always resets to MENU."""
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_DAY
        send(interactive_id="back_to_menu")
        assert conv._states.get(PHONE) is None  # cleared by _to_menu

    def test_menu_book_transitions_to_select_service(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        send(interactive_id="menu_book")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_SERVICE

    def test_menu_book_sends_service_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        send(interactive_id="menu_book")
        mock_wa.send_interactive.assert_called()
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_SERVICE

    def test_menu_view_transitions_to_view(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        send(interactive_id="menu_view")
        state = conv._get(PHONE)
        assert state.step == conv.VIEW_APPOINTMENTS

    def test_menu_cancel_no_citas_returns_to_menu(self, mock_wa, mock_cal):
        mock_cal.get_citas_futuras.return_value = []
        send(interactive_id="menu_cancel")
        mock_wa.send_text_message.assert_called()

    def test_menu_cancel_with_citas_transitions(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        mock_cal.get_citas_futuras.return_value = [
            {"id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))}
        ]
        send(interactive_id="menu_cancel")
        state = conv._get(PHONE)
        assert state.step == conv.CANCEL_SELECT


# ── BOOK_SELECT_SERVICE ────────────────────────────────────────────────────────

class TestBookSelectService:
    def setup_method(self):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_SERVICE

    def test_service_corte_transitions_to_select_day(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30"]
        with patch("app.handlers.conversation.get_next_days",
                   return_value=[date(2026, 3, 23), date(2026, 3, 24)]):
            send(interactive_id="service_corte")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_DAY
        assert state.selected_service == SERVICIOS["corte"]

    def test_service_mechas_has_60_min_duration(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        mock_cal.get_slots_disponibles.return_value = ["10:00"]
        with patch("app.handlers.conversation.get_next_days",
                   return_value=[date(2026, 3, 23)]):
            send(interactive_id="service_mechas")
        state = conv._get(PHONE)
        assert state.selected_service['duracion_min'] == 60

    def test_invalid_button_resets_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        send(interactive_id="service_unknown")
        assert conv._states.get(PHONE) is None

    def test_no_days_available_shows_message(self, mock_wa, mock_cal):
        mock_cal.get_slots_disponibles.return_value = []
        with patch("app.handlers.conversation.get_next_days",
                   return_value=[date(2026, 3, 23)]):
            send(interactive_id="service_corte")
        mock_wa.send_text_message.assert_called()


# ── BOOK_SELECT_DAY ────────────────────────────────────────────────────────────

class TestBookSelectDay:
    def setup_state(self):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_DAY
        state.available_days = [date(2026, 3, 23), date(2026, 3, 24)]
        state.selected_service = SERVICIOS["corte"]
        return state

    def test_valid_day_both_periods_goes_to_period_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        # Slots covering both morning and afternoon
        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30", "16:00", "16:30"]
        send(interactive_id="day_2026-03-23")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_PERIOD

    def test_valid_day_only_morning_goes_to_hour_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30"]
        send(interactive_id="day_2026-03-23")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_HOUR

    def test_valid_day_only_afternoon_goes_to_hour_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.get_slots_disponibles.return_value = ["16:00", "16:30"]
        send(interactive_id="day_2026-03-23")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_HOUR

    def test_day_not_in_available_resets_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(interactive_id="day_2026-04-01")   # not in available_days
        assert conv._states.get(PHONE) is None

    def test_invalid_date_format_resets_menu(self, mock_wa, mock_cal):
        self.setup_state()
        send(interactive_id="day_not-a-date")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_no_slots_shows_message_and_keeps_day_list(self, mock_wa, mock_cal):
        self.setup_state()
        mock_cal.get_slots_disponibles.return_value = []
        send(interactive_id="day_2026-03-23")
        mock_wa.send_text_message.assert_called()

    def test_get_slots_called_with_service_duracion_min(self, mock_wa, mock_cal):
        """get_slots_disponibles is called with the service's duracion_min (30 for corte)."""
        from app.config import SERVICIOS
        self.setup_state()
        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30"]
        send(interactive_id="day_2026-03-23")
        call_kwargs = mock_cal.get_slots_disponibles.call_args
        assert call_kwargs is not None
        # duracion_min may be positional or keyword
        args, kwargs = call_kwargs
        duracion = kwargs.get('duracion_min', args[1] if len(args) > 1 else None)
        assert duracion == SERVICIOS["corte"]["duracion_min"]

    def test_mechas_service_uses_60_min_duration(self, mock_wa, mock_cal):
        """get_slots_disponibles is called with duracion_min=60 for mechas service."""
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = self.setup_state()
        state.selected_service = SERVICIOS["mechas"]
        mock_cal.get_slots_disponibles.return_value = ["10:00"]
        send(interactive_id="day_2026-03-23")
        call_kwargs = mock_cal.get_slots_disponibles.call_args
        assert call_kwargs is not None
        args, kwargs = call_kwargs
        duracion = kwargs.get('duracion_min', args[1] if len(args) > 1 else None)
        assert duracion == 60


# ── BOOK_SELECT_PERIOD ──────────────────────────────────────────────────────────

class TestBookSelectPeriod:
    def setup_state(self):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_PERIOD
        state.selected_date = date(2026, 3, 23)
        state.all_day_slots = ["10:00", "10:30", "16:00", "16:30"]
        state.available_days = [date(2026, 3, 23)]
        return state

    def test_period_morning_goes_to_hour_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(interactive_id="period_morning")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_HOUR
        assert "10:00" in state.available_slots
        assert "16:00" not in state.available_slots

    def test_period_afternoon_goes_to_hour_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(interactive_id="period_afternoon")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_HOUR
        assert "16:00" in state.available_slots
        assert "10:00" not in state.available_slots

    def test_unknown_id_resets_menu(self, mock_wa, mock_cal):
        self.setup_state()
        send(interactive_id="period_evening")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_back_to_day_goes_to_select_day(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(interactive_id="back_to_day")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_DAY


# ── BOOK_SELECT_HOUR ───────────────────────────────────────────────────────────

class TestBookSelectHour:
    def setup_state(self, slots=None):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.available_slots = slots or ["10:00", "10:30"]
        state.available_days = [date(2026, 3, 23)]
        return state

    def test_valid_slot_goes_to_enter_name(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(interactive_id="hour_2026-03-23_1000")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_ENTER_NAME
        assert state.selected_slot == "10:00"

    def test_slot_not_in_available_resets_menu(self, mock_wa, mock_cal):
        self.setup_state(slots=["10:30"])
        send(interactive_id="hour_2026-03-23_1000")   # 10:00 not available
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_back_to_day_goes_to_select_day(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(interactive_id="back_to_day")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_DAY

    def test_malformed_hour_id_resets_menu(self, mock_wa, mock_cal):
        self.setup_state()
        send(interactive_id="hour_badformat")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_back_to_period_goes_to_period_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.all_day_slots = ["10:00", "10:30", "16:00", "16:30"]
        state.available_slots = ["10:00", "10:30"]
        state.available_days = [date(2026, 3, 23)]
        send(interactive_id="back_to_period")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_PERIOD


# ── BOOK_ENTER_NAME ────────────────────────────────────────────────────────────

class TestBookEnterName:
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

    def test_valid_name_books_directly(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = ("evt_new", None)
        send(text="Ana García")
        assert conv._states.get(PHONE) is None
        mock_wa.send_interactive.assert_called()

    def test_short_name_asks_again(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        send(text="A")
        assert conv._get(PHONE).step == conv.BOOK_ENTER_NAME
        mock_wa.send_text_message.assert_called()

    def test_interactive_id_in_name_state_resets_menu(self, mock_wa, mock_cal):
        """Any button press while waiting for name → go to menu."""
        self.setup_state()
        send(interactive_id="book_confirm")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None


# ── BOOK_ENTER_NAME (booking outcomes) ────────────────────────────────────────

class TestBookConfirm:
    def setup_state(self):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.selected_date = date(2026, 3, 23)
        state.selected_slot = "10:00"
        state.selected_service = SERVICIOS["corte"]
        state.nombre = "Ana"
        state.available_days = [date(2026, 3, 23)]
        return state

    def test_confirm_success_clears_state(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = ("evt_new", None)
        send(text="Ana")
        assert conv._states.get(PHONE) is None
        mock_wa.send_interactive.assert_called()

    def test_confirm_slot_taken_shows_alternatives(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = ["10:30", "11:00"]
        send(text="Ana")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_HOUR

    def test_confirm_slot_taken_no_alternatives_shows_day_list(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = []
        send(text="Ana")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_DAY

    def test_confirm_double_booking_shows_message(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = (None, "double_booking")
        send(text="Ana")
        assert conv._states.get(PHONE) is None   # _to_menu clears it
        mock_wa.send_text_message.assert_called()

    def test_confirm_api_error_shows_message(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        self.setup_state()
        mock_cal.reservar_cita.return_value = (None, "error")
        send(text="Ana")
        mock_wa.send_text_message.assert_called()


# ── CANCEL flow ────────────────────────────────────────────────────────────────

class TestCancelFlow:
    def make_cita(self, event_id="evt1"):
        return {"id": event_id, "start": TZ.localize(datetime(2026, 3, 25, 10, 0))}

    def test_cancel_select_valid_event_cancels_immediately(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.CANCEL_SELECT
        state.cancel_citas = [self.make_cita("evt1")]
        mock_cal.cancelar_cita.return_value = True
        send(interactive_id="cancel_appt_evt1")
        mock_cal.cancelar_cita.assert_called_once_with("evt1")
        assert conv._states.get(PHONE) is None
        mock_wa.send_interactive.assert_called()

    def test_cancel_select_event_not_found_returns_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.CANCEL_SELECT
        state.cancel_citas = []
        send(interactive_id="cancel_appt_evt1")
        assert conv._states.get(PHONE) is None
        mock_cal.get_citas_futuras.assert_not_called()

    def test_cancel_api_error_shows_error_message(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.CANCEL_SELECT
        state.cancel_citas = [self.make_cita("evt1")]
        mock_cal.cancelar_cita.return_value = False
        send(interactive_id="cancel_appt_evt1")
        mock_wa.send_text_message.assert_called()


# ── Reminder responses ─────────────────────────────────────────────────────────

class TestReminderResponses:
    def test_reminder_confirm_confirms_appointment(self, mock_wa, mock_cal):
        mock_cal.get_citas_futuras.return_value = [
            {"id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))}
        ]
        send(interactive_id="reminder_confirm_evt1")
        mock_cal.confirmar_cita.assert_called_once_with("evt1")
        mock_wa.send_text_message.assert_called()

    def test_reminder_confirm_event_not_found_resets_menu(self, mock_wa, mock_cal):
        mock_cal.get_citas_futuras.return_value = []
        send(interactive_id="reminder_confirm_evt_missing")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None
        mock_cal.confirmar_cita.assert_not_called()

    def test_reminder_cancel_cancels_directly(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        mock_cal.get_citas_futuras.return_value = [
            {"id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))}
        ]
        mock_cal.cancelar_cita.return_value = True
        send(interactive_id="reminder_cancel_evt1")
        mock_cal.cancelar_cita.assert_called_once_with("evt1")
        assert conv._states.get(PHONE) is None
        mock_wa.send_interactive.assert_called()

    def test_reminder_cancel_event_not_found_resets_menu(self, mock_wa, mock_cal):
        mock_cal.get_citas_futuras.return_value = []
        send(interactive_id="reminder_cancel_evt_missing")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_reminder_response_intercepted_regardless_of_state(self, mock_wa, mock_cal):
        """Reminder buttons are handled no matter what state the conversation is in."""
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME   # deep in booking flow
        mock_cal.get_citas_futuras.return_value = [
            {"id": "evt_xyz", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))}
        ]
        send(interactive_id="reminder_confirm_evt_xyz")
        mock_cal.confirmar_cita.assert_called_once_with("evt_xyz")


# ── Text input routing ─────────────────────────────────────────────────────────

class TestTextInputRouting:
    def test_text_in_book_select_day_resets_to_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_DAY
        send(text="quiero el martes")
        assert conv._states.get(PHONE) is None

    def test_unknown_type_triggers_menu(self, mock_wa, mock_cal):
        """__unknown__ text (audio/image/video from webhook) → menu."""
        send(text="__unknown__")
        mock_wa.send_interactive.assert_called()


# ── State expiry (clean_expired_states) ───────────────────────────────────────

class TestCleanExpiredStates:
    def test_expired_state_removed(self):
        import app.handlers.conversation as conv
        state = conv._get("old_phone")
        # Backdate last_interaction beyond expiry threshold
        state.last_interaction = TZ.localize(datetime(2020, 1, 1))
        conv.clean_expired_states()
        assert "old_phone" not in conv._states

    def test_recent_state_kept(self):
        import app.handlers.conversation as conv
        state = conv._get("new_phone")
        state.last_interaction = datetime.now(TZ)
        conv.clean_expired_states()
        assert "new_phone" in conv._states


# ── Mechas conversation flow ───────────────────────────────────────────────────

class TestMechasConversationFlow:
    """Validate that the state machine stores calendar-layer slots correctly for mechas."""

    def _setup_day_state(self, servicio_key):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_DAY
        state.selected_service = SERVICIOS[servicio_key]
        state.available_days = [date(2026, 3, 24)]
        return state

    def test_book_mechas_afternoon_slots_respect_presencia(self, mock_wa, mock_cal):
        """After selecting a day for mechas, only the 3 pre-filtered slots are stored."""
        import app.handlers.conversation as conv
        self._setup_day_state("mechas")
        # Calendar layer already applied presencia_cliente_min filtering — only 3 slots remain
        mock_cal.get_slots_disponibles.return_value = ["17:00", "17:30", "18:00"]
        send(interactive_id="day_2026-03-24")
        state = conv._get(PHONE)
        # Only afternoon slots → single period → goes directly to BOOK_SELECT_HOUR
        assert state.step == conv.BOOK_SELECT_HOUR
        assert "17:00" in state.available_slots
        assert "17:30" in state.available_slots
        assert "18:00" in state.available_slots
        assert len(state.available_slots) == 3

    def test_book_corte_afternoon_offers_more_slots(self, mock_wa, mock_cal):
        """After selecting a day for corte (no presencia restriction), all 8 slots are stored."""
        import app.handlers.conversation as conv
        self._setup_day_state("corte")
        mock_cal.get_slots_disponibles.return_value = [
            "17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30"
        ]
        send(interactive_id="day_2026-03-24")
        state = conv._get(PHONE)
        # Only afternoon slots → single period → goes directly to BOOK_SELECT_HOUR
        assert state.step == conv.BOOK_SELECT_HOUR
        assert len(state.available_slots) == 8
        assert "20:30" in state.available_slots


# ── Concurrency: per-phone lock ────────────────────────────────────────────────

class TestPerPhoneLock:
    def test_concurrent_messages_same_phone_serialised(self, mock_wa, mock_cal):
        """
        Two threads send to the same phone simultaneously.
        With the per-phone lock, state transitions must not interleave.
        """
        import app.handlers.conversation as conv
        results = []
        barrier = threading.Barrier(2)

        def worker(interactive_id):
            barrier.wait()   # both threads start at the same time
            send(PHONE, interactive_id=interactive_id)
            results.append(interactive_id)

        t1 = threading.Thread(target=worker, args=("menu_view",))
        t2 = threading.Thread(target=worker, args=("menu_book",))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Both must have completed without raising
        assert len(results) == 2
