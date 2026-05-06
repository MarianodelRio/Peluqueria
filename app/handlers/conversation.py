# handlers/conversation.py
"""
Conversation state machine for WhatsApp interactive flow.

States:
  MENU                   - main menu
  BOOK_SELECT_DAY        - user choosing a day
  BOOK_SELECT_HOUR       - user choosing a time slot
  VIEW_APPOINTMENTS      - showing user's future appointments
  CANCEL_SELECT          - user choosing which appointment to cancel (cancels immediately)

Rules:
  - Any text input (not interactive_id) outside MENU → menu to menu
  - Unknown interactive_id in any state → menu to menu
  - back_to_menu from any state → menu
"""
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
import pytz

from app.config import TIMEZONE, ESTADO_EXPIRACION_MIN, HORARIO_BASE, BOOKING_WINDOW_DAYS, SERVICIOS
from app.services import calendar as cal
from app.services import whatsapp as wa
from app.utils.interactive import (
    build_main_menu, build_days_list, build_period_select, build_hours_list,
    build_appointments_view,
    build_cancel_select,
    build_service_select,
    build_back_to_menu_message,
)
from app.utils.slots import get_next_days
from app.utils.messages import (
    msg_sin_slots, msg_doble_reserva, msg_slot_no_disponible,
    msg_cita_confirmada, msg_cancelacion_ok,
    msg_sin_citas, msg_error_creando_cita,
)

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

# ── State constants ────────────────────────────────────────────────────────
MENU = "MENU"
BOOK_SELECT_SERVICE = "BOOK_SELECT_SERVICE"
BOOK_SELECT_DAY = "BOOK_SELECT_DAY"
BOOK_SELECT_PERIOD = "BOOK_SELECT_PERIOD"
BOOK_SELECT_HOUR = "BOOK_SELECT_HOUR"
BOOK_ENTER_NAME = "BOOK_ENTER_NAME"
VIEW_APPOINTMENTS = "VIEW_APPOINTMENTS"
CANCEL_SELECT = "CANCEL_SELECT"


@dataclass
class ConversationState:
    step: str = MENU
    available_days: list = field(default_factory=list)
    selected_date: Optional[date] = None
    all_day_slots: list = field(default_factory=list)   # all slots for selected day
    available_slots: list = field(default_factory=list)  # slots for selected period
    selected_slot: Optional[str] = None
    selected_service: Optional[dict] = field(default=None)
    nombre: Optional[str] = None
    cancel_event_id: Optional[str] = None
    cancel_citas: list = field(default_factory=list)
    last_interaction: datetime = field(
        default_factory=lambda: datetime.now(pytz.timezone(TIMEZONE))
    )

    def touch(self):
        self.last_interaction = datetime.now(pytz.timezone(TIMEZONE))


# In-memory state store
_states: dict[str, ConversationState] = {}

# Per-phone lock — prevents concurrent processing of messages from the same number
_phone_locks: dict[str, threading.Lock] = {}
_phone_locks_guard = threading.Lock()


def _get_phone_lock(phone: str) -> threading.Lock:
    with _phone_locks_guard:
        if phone not in _phone_locks:
            _phone_locks[phone] = threading.Lock()
        return _phone_locks[phone]


# ── State store helpers ────────────────────────────────────────────────────

def _get(phone: str) -> ConversationState:
    if phone not in _states:
        _states[phone] = ConversationState()
    return _states[phone]


def _clear(phone: str):
    _states.pop(phone, None)


def clean_expired_states():
    """Remove states inactive for more than ESTADO_EXPIRACION_MIN minutes."""
    now = datetime.now(TZ)
    # Snapshot items first — iterating a live dict while another thread may
    # add/remove keys raises RuntimeError in CPython.
    snapshot = list(_states.items())
    expired = [
        p for p, s in snapshot
        if (now - s.last_interaction).total_seconds() > ESTADO_EXPIRACION_MIN * 60
    ]
    for p in expired:
        logger.info(f"[CONV] Expired state for {p}")
        _states.pop(p, None)
        with _phone_locks_guard:
            _phone_locks.pop(p, None)


# ── Entry point ────────────────────────────────────────────────────────────

def handle_message(phone: str, text: Optional[str], interactive_id: Optional[str]):
    """
    Main entry point called by webhook handler.
    text: set for text messages or unknown types (__unknown__)
    interactive_id: set for button_reply / list_reply

    Acquires a per-phone lock so that concurrent deliveries for the same
    number (e.g. WhatsApp retries) are serialised and don't corrupt state.
    """
    with _get_phone_lock(phone):
        _process_message(phone, text, interactive_id)


def _process_message(phone: str, text: Optional[str], interactive_id: Optional[str]):
    """Inner handler — called inside the per-phone lock."""
    state = _get(phone)
    state.touch()

    # Global: back_to_menu from any state
    if interactive_id == "back_to_menu":
        _to_menu(phone)
        return

    # Reminder template responses handled regardless of current state
    if interactive_id and interactive_id.startswith("reminder_"):
        _handle_reminder_response(phone, interactive_id)
        return

    # Text input outside MENU → menu, EXCEPT BOOK_ENTER_NAME which expects text
    if text is not None and state.step not in (MENU, BOOK_ENTER_NAME):
        logger.info(f"[CONV] Text input in state {state.step} for {phone} → menu")
        _to_menu(phone)
        return

    # BOOK_ENTER_NAME expects only text — any button press → menu
    if interactive_id is not None and state.step == BOOK_ENTER_NAME:
        _to_menu(phone)
        return

    # Route by state
    dispatch = {
        MENU:                _handle_menu,
        BOOK_SELECT_SERVICE: _handle_book_select_service,
        BOOK_SELECT_DAY:     _handle_book_select_day,
        BOOK_SELECT_PERIOD:  _handle_book_select_period,
        BOOK_SELECT_HOUR:    _handle_book_select_hour,
        BOOK_ENTER_NAME:     _handle_book_enter_name,
        VIEW_APPOINTMENTS:   _handle_view_appointments,
        CANCEL_SELECT:       _handle_cancel_select,
    }
    handler = dispatch.get(state.step)
    if handler:
        handler(phone, state, interactive_id or text or "")
    else:
        _to_menu(phone)


# ── Navigation helpers ─────────────────────────────────────────────────────

def _to_menu(phone: str):
    """Reset state and show main menu. Used for fallback and normal navigation."""
    _clear(phone)
    wa.send_interactive(phone, build_main_menu())


def _go_to_hour_select(phone: str, state: ConversationState, d: date, slots: list):
    """
    Navigate to hour selection from any booking step.
    Splits slots into morning/afternoon and shows period picker when both
    are available, so build_hours_list never receives more than 8 slots
    (WhatsApp limit: 8 content rows + 2 nav rows = 10 max).
    """
    state.all_day_slots = slots
    morning, afternoon = _split_periods(slots)
    if morning and afternoon:
        base_morning, base_afternoon = _base_period_ranges(d)
        state.step = BOOK_SELECT_PERIOD
        wa.send_interactive(phone, build_period_select(
            d,
            base_morning or f"{morning[0]}-{morning[-1]}",
            base_afternoon or f"{afternoon[0]}-{afternoon[-1]}",
        ))
    elif morning:
        state.available_slots = morning
        state.step = BOOK_SELECT_HOUR
        wa.send_interactive(phone, build_hours_list(d, morning))
    else:
        state.available_slots = afternoon
        state.step = BOOK_SELECT_HOUR
        wa.send_interactive(phone, build_hours_list(d, afternoon))


# ── MENU ───────────────────────────────────────────────────────────────────

def _handle_menu(phone: str, state: ConversationState, value: str):
    if value == "menu_book":
        state.step = BOOK_SELECT_SERVICE
        wa.send_interactive(phone, build_service_select())
        return

    elif value == "menu_view":
        citas = cal.get_citas_futuras(phone)
        state.step = VIEW_APPOINTMENTS
        wa.send_interactive(phone, build_appointments_view(citas))

    elif value == "menu_cancel":
        citas = cal.get_citas_futuras(phone)
        if not citas:
            wa.send_text_message(phone, msg_sin_citas())
            _to_menu(phone)
            return
        state.cancel_citas = citas
        state.step = CANCEL_SELECT
        wa.send_interactive(phone, build_cancel_select(citas))

    else:
        # First contact or unrecognized → show menu
        wa.send_interactive(phone, build_main_menu())


# ── BOOK: SELECT SERVICE ───────────────────────────────────────────────────

def _handle_book_select_service(phone: str, state: ConversationState, value: str):
    service_map = {
        "service_corte":       "corte",
        "service_corte_barba": "corte_barba",
        "service_mechas":      "mechas",
    }
    key = service_map.get(value)
    if not key:
        _to_menu(phone)
        return
    state.selected_service = SERVICIOS[key]
    days = get_next_days(BOOKING_WINDOW_DAYS)
    available_days = [d for d in days if cal.get_slots_disponibles(
        d, duracion_min=state.selected_service['duracion_min'])]
    if not available_days:
        wa.send_text_message(phone, msg_sin_slots())
        _to_menu(phone)
        return
    state.available_days = available_days
    state.step = BOOK_SELECT_DAY
    wa.send_interactive(phone, build_days_list(available_days))


# ── BOOK: SELECT DAY ───────────────────────────────────────────────────────

def _split_periods(slots: list) -> tuple:
    """Split slots into morning (< 14h) and afternoon (>= 14h)."""
    morning = [s for s in slots if int(s.split(':')[0]) < 14]
    afternoon = [s for s in slots if int(s.split(':')[0]) >= 14]
    return morning, afternoon


def _base_period_ranges(d: date) -> tuple:
    """
    Return (morning_range, afternoon_range) from HORARIO_BASE for a given date.
    Each range is 'HH:MM-HH:MM' or None if that period is not configured.
    """
    periods = HORARIO_BASE.get(d.weekday(), [])
    morning_range = None
    afternoon_range = None
    for start, end in periods:
        if int(start.split(":")[0]) < 14:
            morning_range = f"{start}-{end}"
        else:
            afternoon_range = f"{start}-{end}"
    return morning_range, afternoon_range


def _handle_book_select_day(phone: str, state: ConversationState, value: str):
    if not state.selected_service:
        _to_menu(phone)
        return

    if not value.startswith("day_"):
        _to_menu(phone)
        return

    try:
        selected_date = date.fromisoformat(value.removeprefix("day_"))
    except ValueError:
        _to_menu(phone)
        return

    if selected_date not in state.available_days:
        _to_menu(phone)
        return

    slots = cal.get_slots_disponibles(selected_date, duracion_min=state.selected_service['duracion_min'])
    if not slots:
        wa.send_text_message(phone, msg_sin_slots())
        wa.send_interactive(phone, build_days_list(state.available_days))
        return

    state.selected_date = selected_date
    _go_to_hour_select(phone, state, selected_date, slots)


# ── BOOK: SELECT PERIOD ────────────────────────────────────────────────────

def _handle_book_select_period(phone: str, state: ConversationState, value: str):
    morning, afternoon = _split_periods(state.all_day_slots)

    if value == "period_morning":
        slots = morning
    elif value == "period_afternoon":
        slots = afternoon
    else:
        _to_menu(phone)
        return

    if not slots:
        wa.send_text_message(phone, msg_sin_slots())
        wa.send_interactive(phone, build_days_list(state.available_days))
        state.step = BOOK_SELECT_DAY
        return

    state.available_slots = slots
    state.step = BOOK_SELECT_HOUR
    wa.send_interactive(phone, build_hours_list(state.selected_date, slots, show_change_period=True))


# ── BOOK: SELECT HOUR ──────────────────────────────────────────────────────

def _handle_book_select_hour(phone: str, state: ConversationState, value: str):
    if value == "change_day":
        state.step = BOOK_SELECT_DAY
        wa.send_interactive(phone, build_days_list(state.available_days))
        return

    if value == "change_period":
        morning, afternoon = _split_periods(state.all_day_slots)
        if morning and afternoon:
            base_morning, base_afternoon = _base_period_ranges(state.selected_date)
            state.step = BOOK_SELECT_PERIOD
            wa.send_interactive(phone, build_period_select(
                state.selected_date,
                base_morning or f"{morning[0]}-{morning[-1]}",
                base_afternoon or f"{afternoon[0]}-{afternoon[-1]}",
            ))
        else:
            _to_menu(phone)
        return

    if not value.startswith("hour_"):
        _to_menu(phone)
        return

    # Parse: hour_{YYYY-MM-DD}_{HHMM}
    try:
        parts = value.removeprefix("hour_").split("_")  # ['2026-03-25', '1030']
        selected_date = date.fromisoformat(parts[0])
        raw_time = parts[1]  # '1030'
        slot = f"{raw_time[:2]}:{raw_time[2:]}"  # '10:30'
    except (ValueError, IndexError):
        _to_menu(phone)
        return

    if selected_date != state.selected_date or slot not in state.available_slots:
        _to_menu(phone)
        return

    state.selected_slot = slot
    state.step = BOOK_ENTER_NAME
    wa.send_text_message(phone, "¿Cuál es tu nombre y apellidos?")


# ── BOOK: ENTER NAME ──────────────────────────────────────────────────────

_NOMBRE_MAX_LEN = 100  # Google Calendar summary field limit is 1024 bytes; keep it reasonable

def _handle_book_enter_name(phone: str, state: ConversationState, value: str):
    nombre = value.strip().replace('\n', ' ').replace('\r', '')
    if len(nombre) < 2:
        wa.send_text_message(phone, "Por favor, escribe tu nombre (mínimo 2 letras).")
        return
    if len(nombre) > _NOMBRE_MAX_LEN:
        wa.send_text_message(phone, "El nombre es demasiado largo. Por favor, escribe tu nombre.")
        return

    if not state.selected_date or not state.selected_slot:
        logger.error("[CONV] _handle_book_enter_name: incomplete state for %s", phone)
        _to_menu(phone)
        return

    state.nombre = nombre
    d = state.selected_date
    hora = state.selected_slot

    event_id, reason = cal.reservar_cita(d, hora, nombre, phone, state.selected_service)

    if reason == 'slot_taken':
        logger.warning(f"[CONV] Slot {d} {hora} taken for {phone}")
        slots = cal.get_slots_disponibles(d, duracion_min=state.selected_service['duracion_min'])
        if slots:
            wa.send_text_message(phone, msg_slot_no_disponible())
            _go_to_hour_select(phone, state, d, slots)
        else:
            wa.send_text_message(phone, msg_sin_slots())
            state.step = BOOK_SELECT_DAY
            wa.send_interactive(phone, build_days_list(state.available_days))

    elif reason == 'double_booking':
        logger.info(f"[CONV] {phone} already has appointment on {d}")
        wa.send_text_message(phone, msg_doble_reserva())
        _to_menu(phone)

    elif reason == 'error':
        wa.send_text_message(phone, msg_error_creando_cita())
        _to_menu(phone)

    else:
        wa.send_interactive(phone, build_back_to_menu_message(msg_cita_confirmada(d, hora, state.selected_service)))
        _clear(phone)


# ── VIEW APPOINTMENTS ──────────────────────────────────────────────────────

def _handle_view_appointments(phone: str, state: ConversationState, value: str):
    # Any interaction (tap on a cita row or back_to_menu) → go to menu
    _to_menu(phone)


# ── CANCEL: SELECT ─────────────────────────────────────────────────────────

def _handle_cancel_select(phone: str, state: ConversationState, value: str):
    if not value.startswith("cancel_appt_"):
        _to_menu(phone)
        return

    event_id = value.removeprefix("cancel_appt_")
    if not event_id:
        _to_menu(phone)
        return

    # Look up event in cached citas
    citas = state.cancel_citas
    cita = next((c for c in citas if c['id'] == event_id), None)
    if not cita:
        wa.send_text_message(phone, "No se encontró esa cita.")
        _to_menu(phone)
        return

    if cal.cancelar_cita(event_id):
        wa.send_interactive(phone, build_back_to_menu_message(msg_cancelacion_ok()))
        _clear(phone)
    else:
        wa.send_text_message(phone, "No se pudo cancelar la cita. Por favor, contáctanos.")
        _to_menu(phone)


# ── REMINDER RESPONSES ─────────────────────────────────────────────────────

def _handle_reminder_response(phone: str, interactive_id: str):
    """
    Handle quick reply buttons from reminder template.
    reminder_confirm_{event_id} → confirm appointment
    reminder_cancel_{event_id}  → start cancellation flow
    """
    if interactive_id.startswith("reminder_confirm_"):
        event_id = interactive_id.removeprefix("reminder_confirm_")
        citas = cal.get_citas_futuras(phone)
        cita = next((c for c in citas if c['id'] == event_id), None)
        if not cita:
            wa.send_text_message(phone, "No se encontró esa cita.")
            _to_menu(phone)
            return
        if cal.confirmar_cita(event_id):
            wa.send_text_message(phone, "¡Tu cita está confirmada! ✅")
        else:
            wa.send_text_message(phone, "No se pudo confirmar la cita. Por favor, contáctanos.")
        _to_menu(phone)

    elif interactive_id.startswith("reminder_cancel_"):
        event_id = interactive_id.removeprefix("reminder_cancel_")
        citas = cal.get_citas_futuras(phone)
        cita = next((c for c in citas if c['id'] == event_id), None)
        if not cita:
            wa.send_text_message(phone, "No se encontró esa cita.")
            _to_menu(phone)
            return
        if cal.cancelar_cita(event_id):
            wa.send_interactive(phone, build_back_to_menu_message(msg_cancelacion_ok()))
            _clear(phone)
        else:
            wa.send_text_message(phone, "No se pudo cancelar la cita. Por favor, contáctanos.")
            _to_menu(phone)

    else:
        _to_menu(phone)
