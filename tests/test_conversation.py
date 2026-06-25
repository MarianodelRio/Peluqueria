# tests/test_conversation.py
"""
Unit tests for handlers/conversation.py.
Google Calendar and WhatsApp are fully mocked.
Validates state transitions, business rules and concurrency protection.
"""
import pytest
import threading
import time
from datetime import date, datetime, timedelta
from unittest.mock import patch
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
        cal.get_event_by_id.return_value = None
        cal.reservar_cita.return_value = ("evt_new", None)
        cal.cancelar_cita.return_value = True
        cal.confirmar_cita.return_value = True
        cal.mover_cita.return_value = ("evt_new", None)
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
        mock_cal.get_slots_disponibles_for_days.return_value = {
            date(2026, 3, 23): ["10:00", "10:30"],
            date(2026, 3, 24): ["10:00", "10:30"],
        }
        with patch("app.handlers.conversation.get_next_days",
                   return_value=[date(2026, 3, 23), date(2026, 3, 24)]):
            send(interactive_id="service_corte")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_DAY
        assert state.selected_service == SERVICIOS["corte"]

    def test_service_mechas_has_60_min_duration(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        mock_cal.get_slots_disponibles_for_days.return_value = {
            date(2026, 3, 23): ["10:00"],
        }
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
        mock_cal.get_slots_disponibles_for_days.return_value = {}
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
        mock_cal.get_slots_disponibles.return_value = [
            "10:00", "10:30", "16:00", "16:30"
        ]
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
        """get_slots_disponibles is called with the service's duracion_min
        (30 for corte)."""
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

    def test_confirm_api_error_shows_message(self, mock_wa, mock_cal):
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
        mock_cal.get_event_by_id.return_value = {
            "id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))
        }
        send(interactive_id="reminder_confirm_evt1")
        mock_cal.confirmar_cita.assert_called_once_with("evt1")
        mock_wa.send_text_message.assert_called()

    def test_reminder_confirm_event_not_found_resets_menu(self, mock_wa, mock_cal):
        mock_cal.get_event_by_id.return_value = None
        send(interactive_id="reminder_confirm_evt_missing")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None
        mock_cal.confirmar_cita.assert_not_called()

    def test_reminder_cancel_cancels_directly(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        mock_cal.get_event_by_id.return_value = {
            "id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))
        }
        mock_cal.cancelar_cita.return_value = True
        send(interactive_id="reminder_cancel_evt1")
        mock_cal.cancelar_cita.assert_called_once_with("evt1")
        assert conv._states.get(PHONE) is None
        mock_wa.send_interactive.assert_called()

    def test_reminder_cancel_event_not_found_resets_menu(self, mock_wa, mock_cal):
        mock_cal.get_event_by_id.return_value = None
        send(interactive_id="reminder_cancel_evt_missing")
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_reminder_response_intercepted_regardless_of_state(self, mock_wa, mock_cal):
        """Reminder buttons are handled no matter what state the conversation is in."""
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME   # deep in booking flow
        mock_cal.get_event_by_id.return_value = {
            "id": "evt_xyz", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))
        }
        send(interactive_id="reminder_confirm_evt_xyz")
        mock_cal.confirmar_cita.assert_called_once_with("evt_xyz")

    def test_reminder_confirm_uses_get_event_by_id_not_full_list(
            self, mock_wa, mock_cal):
        """_handle_reminder_response calls get_event_by_id, not get_citas_futuras."""
        mock_cal.get_event_by_id.return_value = {
            "id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))
        }
        send(interactive_id="reminder_confirm_evt1")
        mock_cal.get_event_by_id.assert_called_once_with("evt1", PHONE)
        mock_cal.get_citas_futuras.assert_not_called()

    def test_reminder_cancel_uses_get_event_by_id_not_full_list(
            self, mock_wa, mock_cal):
        """_handle_reminder_response calls get_event_by_id, not get_citas_futuras."""
        mock_cal.get_event_by_id.return_value = {
            "id": "evt1", "start": TZ.localize(datetime(2026, 3, 25, 10, 0))
        }
        mock_cal.cancelar_cita.return_value = True
        send(interactive_id="reminder_cancel_evt1")
        mock_cal.get_event_by_id.assert_called_once_with("evt1", PHONE)
        mock_cal.get_citas_futuras.assert_not_called()

    def test_reminder_confirm_for_other_phone_returns_not_found(
            self, mock_wa, mock_cal):
        """get_event_by_id returning None (phone mismatch) is treated as not found."""
        mock_cal.get_event_by_id.return_value = None
        send(interactive_id="reminder_confirm_evt1")
        mock_cal.confirmar_cita.assert_not_called()
        mock_wa.send_text_message.assert_called()


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

    def test_stale_citas_cache_entry_purged(self):
        import app.handlers.conversation as conv
        import app.services.calendar as cal
        cal._citas_cache["stale_phone"] = ([], time.time() - 999)
        try:
            conv.clean_expired_states()
            assert "stale_phone" not in cal._citas_cache
        finally:
            cal._citas_cache.pop("stale_phone", None)

    def test_fresh_citas_cache_entry_kept(self):
        import app.handlers.conversation as conv
        import app.services.calendar as cal
        cal._citas_cache["fresh_phone"] = ([], time.time())
        try:
            conv.clean_expired_states()
            assert "fresh_phone" in cal._citas_cache
        finally:
            cal._citas_cache.pop("fresh_phone", None)


# ── Mechas conversation flow ───────────────────────────────────────────────────

class TestMechasConversationFlow:
    """Validate that the state machine stores calendar-layer slots
    correctly for mechas."""

    def _setup_day_state(self, servicio_key):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_DAY
        state.selected_service = SERVICIOS[servicio_key]
        state.available_days = [date(2026, 3, 24)]
        return state

    def test_book_mechas_afternoon_slots_respect_presencia(self, mock_wa, mock_cal):
        """After selecting a day for mechas, only the 3 pre-filtered
        slots are stored."""
        import app.handlers.conversation as conv
        self._setup_day_state("mechas")
        # Calendar layer already applied presencia_cliente_min filtering
        # — only 3 slots remain
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
        """After selecting a day for corte (no presencia restriction),
        all 8 slots are stored."""
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
        results = []
        barrier = threading.Barrier(2)

        def worker(interactive_id):
            barrier.wait()   # both threads start at the same time
            send(PHONE, interactive_id=interactive_id)
            results.append(interactive_id)

        t1 = threading.Thread(target=worker, args=("menu_view",))
        t2 = threading.Thread(target=worker, args=("menu_book",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both must have completed without raising
        assert len(results) == 2


# ── Range-fetch optimisation ───────────────────────────────────────────────────

class TestBookSelectServiceRangeFetch:
    def test_handle_book_select_service_uses_range_call(self, mock_wa, mock_cal):
        """After service-pick, get_slots_disponibles_for_days is called
        once and get_slots_disponibles is not called."""
        import app.handlers.conversation as conv

        today = date(2026, 5, 12)
        days = [today + timedelta(days=i) for i in range(15)]

        slots_by_day = {d: ["10:00", "10:30"] for d in days}
        mock_cal.get_slots_disponibles_for_days.return_value = slots_by_day
        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30"]

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_SERVICE

        with patch("app.handlers.conversation.get_next_days", return_value=days):
            send(interactive_id="service_corte")

        assert mock_cal.get_slots_disponibles_for_days.call_count == 1
        assert mock_cal.get_slots_disponibles.call_count == 0

    def test_handle_book_select_service_then_select_day_no_extra_range_call(
            self, mock_wa, mock_cal):
        """After service-pick then day-pick, for_days is called only
        once (at service step)."""
        import app.handlers.conversation as conv

        today = date(2026, 5, 12)
        days = [today + timedelta(days=i) for i in range(15)]

        slots_by_day = {d: ["10:00", "10:30"] for d in days}
        mock_cal.get_slots_disponibles_for_days.return_value = slots_by_day
        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30"]

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_SERVICE

        with patch("app.handlers.conversation.get_next_days", return_value=days):
            send(interactive_id="service_corte")

        # Now dispatch a day-pick
        day_id = f"day_{days[1].isoformat()}"
        send(interactive_id=day_id)

        # for_days should still be called only once (from the service step)
        assert mock_cal.get_slots_disponibles_for_days.call_count == 1


# ── Event booking flow ────────────────────────────────────────────────────────

class TestEventBookingFlow:
    """Tests for the special-event booking path (mode='evento')."""

    def test_menu_book_event_inactive_shows_menu(self, mock_wa, mock_cal):
        """menu_book_event is a no-op when EVENTO_ACTIVO is False — stays at MENU."""
        import app.handlers.conversation as conv
        with patch("app.handlers.conversation.EVENTO_ACTIVO", False):
            send(interactive_id="menu_book_event")
        mock_wa.send_interactive.assert_called()
        # State stays at MENU (not advanced to BOOK_SELECT_SERVICE)
        state = conv._get(PHONE)
        assert state.step == conv.MENU

    def test_menu_book_event_active_sets_mode_evento(self, mock_wa, mock_cal):
        """menu_book_event when active sets mode='evento' and goes
        to BOOK_SELECT_SERVICE."""
        import app.handlers.conversation as conv
        with patch("app.handlers.conversation.EVENTO_ACTIVO", True):
            send(interactive_id="menu_book_event")
        state = conv._get(PHONE)
        assert state.mode == 'evento'
        assert state.step == conv.BOOK_SELECT_SERVICE

    def test_mode_normal_by_default(self, mock_wa, mock_cal):
        """Normal menu_book path leaves mode='normal'."""
        import app.handlers.conversation as conv
        send(interactive_id="menu_book")
        state = conv._get(PHONE)
        assert state.mode == 'normal'

    def test_event_service_select_uses_get_event_days(self, mock_wa, mock_cal):
        """When mode='evento', _handle_book_select_service calls
        get_event_days (not get_next_days)."""
        import app.handlers.conversation as conv
        event_day = date(2099, 12, 25)
        mock_cal.get_slots_disponibles_for_days.return_value = {
            event_day: ["10:00", "11:00"]
        }

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_SERVICE
        state.mode = 'evento'

        with patch("app.handlers.conversation.get_event_days",
                   return_value=[event_day]) as mock_ged, \
             patch("app.handlers.conversation.get_next_days") as mock_gnd:
            send(interactive_id="service_corte")

        mock_ged.assert_called_once()
        mock_gnd.assert_not_called()

    def test_event_service_select_no_days_shows_event_message(self, mock_wa, mock_cal):
        """When mode='evento' and no event days exist, show msg_evento_sin_dias."""
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_SERVICE
        state.mode = 'evento'

        with patch("app.handlers.conversation.get_event_days", return_value=[]):
            send(interactive_id="service_corte")

        mock_wa.send_text_message.assert_called()
        text_call = mock_wa.send_text_message.call_args[0][1]
        assert "evento" in text_call.lower()

    def test_event_select_day_calls_get_slots_disponibles_evento(
            self, mock_wa, mock_cal):
        """When mode='evento', selecting a day calls get_slots_disponibles
        with mode='evento'."""
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        event_day = date(2099, 12, 25)

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_DAY
        state.mode = 'evento'
        state.selected_service = SERVICIOS["corte"]
        state.available_days = [event_day]

        mock_cal.get_slots_disponibles.return_value = ["10:00", "10:30"]
        send(interactive_id=f"day_{event_day.isoformat()}")

        mock_cal.get_slots_disponibles.assert_called_once()
        call_kwargs = mock_cal.get_slots_disponibles.call_args
        args, kwargs = call_kwargs
        assert kwargs.get('mode') == 'evento'

    def test_event_flow_slot_taken_uses_get_slots_disponibles_evento(
            self, mock_wa, mock_cal):
        """When mode='evento' and slot_taken, alternatives fetched
        via get_slots_disponibles with mode='evento'."""
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        event_day = date(2099, 12, 25)

        state = conv._get(PHONE)
        state.step = conv.BOOK_ENTER_NAME
        state.mode = 'evento'
        state.selected_service = SERVICIOS["corte"]
        state.selected_date = event_day
        state.selected_slot = "10:00"
        state.available_days = [event_day]
        state.available_slots = ["10:00", "10:30"]

        mock_cal.reservar_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = ["10:30", "11:00"]

        send(text="Ana García")

        mock_cal.get_slots_disponibles.assert_called_once()
        call_kwargs = mock_cal.get_slots_disponibles.call_args
        args, kwargs = call_kwargs
        assert kwargs.get('mode') == 'evento'

    def test_to_menu_resets_mode(self, mock_wa, mock_cal):
        """After _to_menu, mode is reset (state is cleared by _clear)."""
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.mode = 'evento'
        state.step = conv.BOOK_SELECT_DAY
        send(interactive_id="back_to_menu")
        # State was cleared; new state would have default mode='normal'
        new_state = conv._get(PHONE)
        assert new_state.mode == 'normal'


# ── Move flow ──────────────────────────────────────────────────────────────────

class TestMoveFlow:
    _DEFAULT_DESC = (
        "Nombre: Ana García\nTelefono: +34600000001\n"
        "Servicio: corte\nEstado: confirmada\nRecordatorio: no"
    )

    def make_cita(self, event_id="evt1", description=None):
        return {
            "id": event_id,
            "start": TZ.localize(datetime(2026, 3, 25, 10, 0)),
            "description": (
                description if description is not None else self._DEFAULT_DESC
            ),
        }

    def test_menu_move_no_citas_returns_to_menu(self, mock_wa, mock_cal):
        mock_cal.get_citas_futuras.return_value = []
        send(interactive_id="menu_move")
        mock_wa.send_text_message.assert_called()
        import app.handlers.conversation as conv
        assert conv._states.get(PHONE) is None

    def test_menu_move_with_citas_transitions_to_move_select(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        mock_cal.get_citas_futuras.return_value = [self.make_cita()]
        send(interactive_id="menu_move")
        state = conv._get(PHONE)
        assert state.step == conv.MOVE_SELECT_CITA
        mock_wa.send_interactive.assert_called()

    def test_move_select_valid_event_saves_source_and_goes_to_service(
        self, mock_wa, mock_cal
    ):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.MOVE_SELECT_CITA
        state.move_citas = [self.make_cita("evt1")]
        send(interactive_id="move_appt_evt1")
        state = conv._get(PHONE)
        assert state.move_source_event_id == "evt1"
        assert state.step == conv.BOOK_SELECT_SERVICE

    def test_move_select_valid_event_uses_nombre_from_description(
        self, mock_wa, mock_cal
    ):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.MOVE_SELECT_CITA
        state.move_citas = [self.make_cita("evt1")]
        send(interactive_id="move_appt_evt1")
        state = conv._get(PHONE)
        assert state.move_source_nombre == "Ana García"

    def test_move_select_nombre_fallback_when_missing(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.MOVE_SELECT_CITA
        # Cita with no Nombre field in description
        state.move_citas = [
            self.make_cita("evt1", description="Telefono: +34600000001")
        ]
        send(interactive_id="move_appt_evt1")
        state = conv._get(PHONE)
        assert state.move_source_nombre == "Cliente"

    def test_move_select_unknown_id_resets_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.MOVE_SELECT_CITA
        state.move_citas = [self.make_cita("evt1")]
        send(interactive_id="move_appt_evt_unknown")
        assert conv._states.get(PHONE) is None
        mock_wa.send_text_message.assert_called()

    def test_move_select_invalid_prefix_resets_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        state = conv._get(PHONE)
        state.step = conv.MOVE_SELECT_CITA
        state.move_citas = [self.make_cita("evt1")]
        send(interactive_id="cancel_appt_evt1")
        assert conv._states.get(PHONE) is None

    def test_move_hour_select_calls_execute_mover_not_enter_name(
        self, mock_wa, mock_cal
    ):
        """When move_source_event_id is set, selecting an hour calls mover_cita,
        not enter_name."""
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        mock_cal.mover_cita.return_value = ("new_evt", None)

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.available_slots = ["10:00", "10:30"]
        state.available_days = [date(2026, 3, 23)]
        state.selected_service = SERVICIOS["corte"]
        state.move_source_event_id = "evt_old"
        state.move_source_nombre = "Ana García"

        send(interactive_id="hour_2026-03-23_1000")

        # State should be cleared (move succeeded) — not at BOOK_ENTER_NAME
        assert conv._states.get(PHONE) is None

    def test_move_success_clears_state(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        mock_cal.mover_cita.return_value = ("new_evt", None)

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.available_slots = ["10:00"]
        state.available_days = [date(2026, 3, 23)]
        state.selected_service = SERVICIOS["corte"]
        state.move_source_event_id = "evt_old"
        state.move_source_nombre = "Ana García"

        send(interactive_id="hour_2026-03-23_1000")
        assert conv._states.get(PHONE) is None
        mock_wa.send_interactive.assert_called()

    def test_move_slot_taken_offers_alternatives(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        mock_cal.mover_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = ["10:30", "11:00"]

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.available_slots = ["10:00"]
        state.available_days = [date(2026, 3, 23)]
        state.selected_service = SERVICIOS["corte"]
        state.move_source_event_id = "evt_old"
        state.move_source_nombre = "Ana García"

        send(interactive_id="hour_2026-03-23_1000")
        state = conv._get(PHONE)
        assert state.step == conv.BOOK_SELECT_HOUR
        mock_wa.send_text_message.assert_called()

    def test_move_slot_taken_no_alternatives_goes_to_day(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        mock_cal.mover_cita.return_value = (None, "slot_taken")
        mock_cal.get_slots_disponibles.return_value = []

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.available_slots = ["10:00"]
        state.available_days = [date(2026, 3, 23)]
        state.selected_service = SERVICIOS["corte"]
        state.move_source_event_id = "evt_old"
        state.move_source_nombre = "Ana García"

        send(interactive_id="hour_2026-03-23_1000")
        assert conv._get(PHONE).step == conv.BOOK_SELECT_DAY

    def test_move_error_goes_to_menu(self, mock_wa, mock_cal):
        import app.handlers.conversation as conv
        from app.config import SERVICIOS
        mock_cal.mover_cita.return_value = (None, "error")

        state = conv._get(PHONE)
        state.step = conv.BOOK_SELECT_HOUR
        state.selected_date = date(2026, 3, 23)
        state.available_slots = ["10:00"]
        state.available_days = [date(2026, 3, 23)]
        state.selected_service = SERVICIOS["corte"]
        state.move_source_event_id = "evt_old"
        state.move_source_nombre = "Ana García"

        send(interactive_id="hour_2026-03-23_1000")
        assert conv._states.get(PHONE) is None
        mock_wa.send_text_message.assert_called()

    def test_menu_move_button_present_in_main_menu_buttons(self, mock_wa, mock_cal):
        """menu_move button is present in the non-event main menu."""
        from app.utils.interactive import build_main_menu
        from unittest.mock import patch
        with patch("app.utils.interactive.EVENTO_ACTIVO", False):
            menu = build_main_menu()
        buttons = menu["interactive"]["action"]["buttons"]
        ids = [b["reply"]["id"] for b in buttons]
        assert "menu_move" in ids

    def test_menu_move_row_present_in_main_menu_list(self, mock_wa, mock_cal):
        """menu_move row is present in the event-active main menu list."""
        from app.utils.interactive import build_main_menu
        from unittest.mock import patch
        with patch("app.utils.interactive.EVENTO_ACTIVO", True):
            menu = build_main_menu()
        rows = menu["interactive"]["action"]["sections"][0]["rows"]
        ids = [r["id"] for r in rows]
        assert "menu_move" in ids


# ── Handle message resilience ──────────────────────────────────────────────────

class TestHandleMessageResilience:
    """Tests for the two-layer delivery resilience wrapper in handle_message."""

    def test_exception_in_process_triggers_fallback(self):
        """When _process_message raises, the fallback message is sent,
        state is cleared, and handler_errors is incremented."""
        from unittest.mock import patch, MagicMock
        from app.utils import metrics
        import app.handlers.conversation as conv

        before = metrics._counters.get("handler_errors", 0)

        with patch("app.handlers.conversation.wa") as mock_wa_obj, \
             patch("app.handlers.conversation._process_message",
                   side_effect=RuntimeError("boom")):
            mock_wa_obj.begin_delivery_tracking.return_value = None
            mock_wa_obj.reply_was_delivered.return_value = True
            mock_wa_obj.send_text_message.return_value = True

            conv._states.clear()
            conv.handle_message(PHONE, text="hola", interactive_id=None)

        assert metrics._counters.get("handler_errors", 0) > before
        assert conv._states.get(PHONE) is None
        calls = [str(c) for c in mock_wa_obj.send_text_message.call_args_list]
        assert any("problema de conexión" in c for c in calls)

    def test_undelivered_reply_triggers_fallback(self):
        """When _process_message succeeds but reply_was_delivered returns False,
        the fallback is sent and reply_delivery_failed is incremented."""
        from unittest.mock import patch
        from app.utils import metrics
        import app.handlers.conversation as conv

        before = metrics._counters.get("reply_delivery_failed", 0)

        with patch("app.handlers.conversation.wa") as mock_wa_obj, \
             patch("app.handlers.conversation._process_message"):
            mock_wa_obj.begin_delivery_tracking.return_value = None
            mock_wa_obj.reply_was_delivered.return_value = False
            mock_wa_obj.send_text_message.return_value = True

            conv._states.clear()
            conv.handle_message(PHONE, text="hola", interactive_id=None)

        assert metrics._counters.get("reply_delivery_failed", 0) > before
        mock_wa_obj.send_text_message.assert_called()

    def test_committed_exception_sends_ok_message(self):
        """When _ctx.committed is True before exception, fallback sends
        the 'registrado correctamente' message."""
        from unittest.mock import patch
        import app.handlers.conversation as conv

        def commit_then_raise(phone, text, interactive_id):
            conv._ctx.committed = True
            raise RuntimeError("network error after write")

        with patch("app.handlers.conversation.wa") as mock_wa_obj, \
             patch("app.handlers.conversation._process_message",
                   side_effect=commit_then_raise):
            mock_wa_obj.begin_delivery_tracking.return_value = None
            mock_wa_obj.reply_was_delivered.return_value = True
            mock_wa_obj.send_text_message.return_value = True

            conv._states.clear()
            conv.handle_message(PHONE, text="hola", interactive_id=None)

        calls = [str(c) for c in mock_wa_obj.send_text_message.call_args_list]
        assert any("registrado correctamente" in c for c in calls)

    def test_happy_path_no_fallback(self):
        """When _process_message succeeds and reply_was_delivered is True,
        neither fallback message is sent."""
        from unittest.mock import patch
        import app.handlers.conversation as conv

        with patch("app.handlers.conversation.wa") as mock_wa_obj, \
             patch("app.handlers.conversation._process_message"):
            mock_wa_obj.begin_delivery_tracking.return_value = None
            mock_wa_obj.reply_was_delivered.return_value = True
            mock_wa_obj.send_text_message.return_value = True

            conv._states.clear()
            conv.handle_message(PHONE, text="hola", interactive_id=None)

        for call in mock_wa_obj.send_text_message.call_args_list:
            text_arg = str(call)
            assert "problema de conexión" not in text_arg
            assert "registrado correctamente" not in text_arg
