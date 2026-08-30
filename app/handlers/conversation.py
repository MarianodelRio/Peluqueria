# handlers/conversation.py
"""
Conversation state machine for WhatsApp interactive flow.

States:
  MENU                   - main menu
  BOOK_SELECT_DAY        - user choosing a day
  BOOK_SELECT_HOUR       - user choosing a time slot
  VIEW_APPOINTMENTS      - showing user's future appointments
  CANCEL_SELECT          - user choosing which appointment to cancel
                           (cancels immediately)

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

from app.config import (
    TIMEZONE, ESTADO_EXPIRACION_MIN, HORARIO_BASE, BOOKING_WINDOW_DAYS,
    SERVICIOS, CITAS_CACHE_TTL_SEC, EVENTO_ACTIVO, ADMIN_PHONE, ADMIN_COMANDOS,
    MAX_CITAS_ACTIVAS, EVENTO_DIAS,
)
from app.utils.admin import (
    build_status_report, build_help_message, read_log_tail, schedule_restart,
)
from app.services import calendar as cal
from app.services import whatsapp as wa
from app.utils.interactive import (
    build_main_menu, build_days_list, build_period_select, build_hours_list,
    build_appointments_view,
    build_cancel_select,
    build_move_select,
    build_service_select,
    build_back_to_menu_message,
)
from app.utils.slots import get_next_days, get_event_days
from app.utils.messages import (
    msg_sin_slots, msg_slot_no_disponible,
    msg_cita_confirmada, msg_cancelacion_ok,
    msg_sin_citas, msg_error_creando_cita, msg_evento_sin_dias,
    msg_cita_movida, msg_cita_no_encontrada,
    msg_reintentar, msg_accion_ok_sin_confirmar,
    msg_limite_citas, msg_nombre_por_texto,
)
from app.utils import metrics
from app.utils.parser import parse_nombre
from app.utils.security import mask_phone

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
MOVE_SELECT_CITA = "MOVE_SELECT_CITA"

UNKNOWN_INPUT = "__unknown__"   # tipos de mensaje no soportados (audio, imagen…)


@dataclass
class ConversationState:
    step: str = MENU
    phone: Optional[str] = None
    available_days: list = field(default_factory=list)
    selected_date: Optional[date] = None
    all_day_slots: list = field(default_factory=list)   # all slots for selected day
    available_slots: list = field(default_factory=list)  # slots for selected period
    selected_slot: Optional[str] = None
    selected_service: Optional[dict] = field(default=None)
    nombre: Optional[str] = None
    cancel_event_id: Optional[str] = None
    cancel_citas: list = field(default_factory=list)
    move_source_event_id: Optional[str] = None
    move_source_nombre: Optional[str] = None
    move_citas: list = field(default_factory=list)
    mode: str = 'normal'  # 'normal' for standard flow, 'evento' for special-event flow
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
_ctx = threading.local()


def _get_phone_lock(phone: str) -> threading.Lock:
    with _phone_locks_guard:
        if phone not in _phone_locks:
            _phone_locks[phone] = threading.Lock()
        return _phone_locks[phone]


def _safe_fallback(identifier: str) -> None:
    _clear(identifier)
    if getattr(_ctx, "committed", False):
        wa.send_text_message(identifier, msg_accion_ok_sin_confirmar())
    else:
        wa.send_text_message(identifier, msg_reintentar())


# ── State store helpers ────────────────────────────────────────────────────

def _get(phone: str) -> ConversationState:
    if phone not in _states:
        _states[phone] = ConversationState()
    return _states[phone]


def _clear(phone: str):
    _states.pop(phone, None)


def clean_expired_states():
    """Remove states inactive for more than ESTADO_EXPIRACION_MIN minutes."""
    import time as _time
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

    # Purge slot locks for past dates — safe because past slots can't be booked
    from app.services.calendar.locks import slot_locks
    purged = slot_locks.purge_before(now.date())
    if purged:
        logger.info(f"[CONV] Purged {purged} past slot locks")

    # Purge fetch-locks (single-flight cache-fill locks) for past dates.
    # Only removes locks not currently held by an in-flight fetch.
    from app.services.calendar import service as cal_service
    cutoff_str = now.date().isoformat()
    fetch_snapshot = list(cal_service._fetch_locks.items())
    fetch_purged = 0
    for key, flock in fetch_snapshot:
        # key is "YYYY-MM-DD_...", "evt_YYYY-MM-DD_..." or
        # "range_YYYY-MM-DD_YYYY-MM-DD_..."; a lock is safe to drop once its
        # (first) date portion is entirely in the past.
        if key.startswith("range_"):
            date_part = key[len("range_"):]
        elif key.startswith("evt_"):
            date_part = key[len("evt_"):]
        else:
            date_part = key
        if date_part[:10] >= cutoff_str:
            continue
        if flock.acquire(blocking=False):
            try:
                with cal_service._fetch_guard:
                    cal_service._fetch_locks.pop(key, None)
            finally:
                flock.release()
            fetch_purged += 1
    if fetch_purged:
        logger.info(f"[CONV] Purged {fetch_purged} past fetch locks")

    # Purge stale citas cache entries
    now_ts = _time.time()
    with cal._citas_cache_lock:
        stale_phones = [
            phone for phone, (_, ts) in list(cal._citas_cache.items())
            if now_ts - ts >= CITAS_CACHE_TTL_SEC
        ]
        for phone in stale_phones:
            cal._citas_cache.pop(phone, None)

    # Purge inactive rate limiter buckets
    from app.handlers.webhook import ip_rate_limiter, phone_rate_limiter
    ip_rate_limiter.purge_inactive()
    phone_rate_limiter.purge_inactive()


# ── Entry point ────────────────────────────────────────────────────────────

def handle_message(identifier: str, phone: Optional[str], text: Optional[str],
                   interactive_id: Optional[str]):
    """
    Main entry point called by webhook handler.
    text: set for text messages or unknown types (__unknown__)
    interactive_id: set for button_reply / list_reply

    Acquires a per-identifier lock so that concurrent deliveries for the same
    user (e.g. WhatsApp retries) are serialised and don't corrupt state.
    """
    lock = _get_phone_lock(identifier)
    if not lock.acquire(timeout=45):
        logger.warning("[CONV] Phone lock timeout para %s", mask_phone(identifier))
        metrics.inc("phone_lock_timeout")
        wa.send_text_message(identifier, msg_reintentar())
        return
    try:
        wa.begin_delivery_tracking()
        _ctx.committed = False
        try:
            _process_message(identifier, phone, text, interactive_id)
        except Exception:
            logger.exception("[CONV] Error procesando mensaje de %s", identifier)
            metrics.inc("handler_errors")
            _safe_fallback(identifier)
            return
        if not wa.reply_was_delivered():
            logger.warning("[CONV] Respuesta no entregada a %s; fallback", identifier)
            metrics.inc("reply_delivery_failed")
            _safe_fallback(identifier)
    finally:
        lock.release()


def _process_message(identifier: str, phone: Optional[str], text: Optional[str],
                     interactive_id: Optional[str]):
    """Inner handler — called inside the per-identifier lock."""
    state = _get(identifier)
    state.touch()
    if phone is not None:
        state.phone = phone

    # Admin command intercept — runs before any other routing
    effective_phone = phone or state.phone
    if (text is not None and ADMIN_PHONE and effective_phone == ADMIN_PHONE
            and text.strip().lower() in ADMIN_COMANDOS):
        _handle_admin_command(identifier, text.strip().lower())
        return

    # Global: back_to_menu from any state
    if interactive_id == "back_to_menu":
        _to_menu(identifier)
        return

    # Reminder template responses handled regardless of current state
    if interactive_id and interactive_id.startswith("reminder_"):
        _handle_reminder_response(identifier, phone, interactive_id)
        return

    # Text input outside MENU → menu, EXCEPT BOOK_ENTER_NAME which expects text
    if text is not None and state.step not in (MENU, BOOK_ENTER_NAME):
        logger.info(f"[CONV] Text input in state {state.step} for {identifier} → menu")
        _to_menu(identifier)
        return

    # BOOK_ENTER_NAME expects only text — any button press → menu
    if interactive_id is not None and state.step == BOOK_ENTER_NAME:
        _to_menu(identifier)
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
        MOVE_SELECT_CITA:    _handle_move_select_cita,
    }
    handler = dispatch.get(state.step)
    if handler:
        handler(identifier, state, interactive_id or text or "")
    else:
        _to_menu(identifier)


# ── Admin command dispatcher ───────────────────────────────────────────────

def _handle_admin_command(identifier: str, cmd: str) -> None:
    """Dispatch an admin command to the appropriate handler."""
    if cmd == "/status":
        wa.send_text_message(identifier, build_status_report())
    elif cmd == "/help":
        wa.send_text_message(identifier, build_help_message())
    elif cmd == "/logs":
        wa.send_text_message(identifier, read_log_tail())
    elif cmd == "/restart":
        wa.send_text_message(identifier, "Reiniciando...")
        schedule_restart()
    else:
        _to_menu(identifier)


# ── Navigation helpers ─────────────────────────────────────────────────────

def _to_menu(identifier: str):
    """Reset state and show main menu. Used for fallback and normal navigation."""
    _clear(identifier)
    wa.send_interactive(identifier, build_main_menu())


def _go_to_hour_select(identifier: str, state: ConversationState, d: date, slots: list):
    """
    Navigate to hour selection from any booking step.
    Splits slots into morning/afternoon and shows period picker when both
    are available, so build_hours_list never receives more than 9 slots
    (WhatsApp limit: 9 content rows + 1 nav row = 10 max).
    """
    state.all_day_slots = slots
    morning, afternoon = _split_periods(slots)
    if morning and afternoon:
        base_morning, base_afternoon = _base_period_ranges(d)
        state.step = BOOK_SELECT_PERIOD
        wa.send_interactive(identifier, build_period_select(
            d,
            base_morning or f"{morning[0]}-{morning[-1]}",
            base_afternoon or f"{afternoon[0]}-{afternoon[-1]}",
        ))
    elif morning:
        state.available_slots = morning
        state.step = BOOK_SELECT_HOUR
        wa.send_interactive(identifier, build_hours_list(d, morning))
    else:
        state.available_slots = afternoon
        state.step = BOOK_SELECT_HOUR
        wa.send_interactive(identifier, build_hours_list(d, afternoon))


# ── MENU ───────────────────────────────────────────────────────────────────

def _handle_menu(identifier: str, state: ConversationState, value: str):
    if value == "menu_book":
        # get_citas_futuras returns [] on Calendar API failure, so the limit
        # fails open by design (do not "fix" into fail-closed).
        citas = cal.get_citas_futuras(identifier, phone=state.phone)
        if len(citas) >= MAX_CITAS_ACTIVAS:
            wa.send_text_message(identifier, msg_limite_citas())
            _to_menu(identifier)
            return
        state.step = BOOK_SELECT_SERVICE
        wa.send_interactive(identifier, build_service_select())
        return

    elif value == "menu_book_event":
        # No-op when event is not active (guard against stale/replayed messages)
        if not EVENTO_ACTIVO:
            wa.send_interactive(identifier, build_main_menu())
            return
        # get_citas_futuras returns [] on Calendar API failure, so the limit
        # fails open by design (do not "fix" into fail-closed).
        citas = cal.get_citas_futuras(identifier, phone=state.phone)
        if len(citas) >= MAX_CITAS_ACTIVAS:
            wa.send_text_message(identifier, msg_limite_citas())
            _to_menu(identifier)
            return
        state.mode = 'evento'
        state.step = BOOK_SELECT_SERVICE
        wa.send_interactive(identifier, build_service_select())
        return

    elif value == "menu_view":
        citas = cal.get_citas_futuras(identifier, phone=state.phone)
        state.step = VIEW_APPOINTMENTS
        wa.send_interactive(identifier, build_appointments_view(citas))

    elif value == "menu_cancel":
        citas = cal.get_citas_futuras(identifier, phone=state.phone)
        if not citas:
            wa.send_text_message(identifier, msg_sin_citas())
            _to_menu(identifier)
            return
        state.cancel_citas = citas
        state.step = CANCEL_SELECT
        wa.send_interactive(identifier, build_cancel_select(citas))

    elif value == "menu_move":
        citas = cal.get_citas_futuras(identifier, phone=state.phone)
        if not citas:
            wa.send_text_message(identifier, msg_sin_citas())
            _to_menu(identifier)
            return
        state.move_citas = citas
        state.step = MOVE_SELECT_CITA
        wa.send_interactive(identifier, build_move_select(citas))

    else:
        # First contact or unrecognized → show menu
        wa.send_interactive(identifier, build_main_menu())


# ── BOOK: SELECT SERVICE ───────────────────────────────────────────────────

def _handle_book_select_service(identifier: str, state: ConversationState, value: str):
    if not value.startswith("service_"):
        _to_menu(identifier)
        return
    key = value.removeprefix("service_")
    if key not in SERVICIOS:
        _to_menu(identifier)
        return
    state.selected_service = SERVICIOS[key]

    if state.mode == 'evento':
        # Event flow: use event days from EVENTO_DIAS
        days = get_event_days()
        if not days:
            wa.send_text_message(identifier, msg_evento_sin_dias())
            _to_menu(identifier)
            return
    else:
        days = get_next_days(BOOKING_WINDOW_DAYS)

    if not days:
        available_days = []
    else:
        slots_by_day = cal.get_slots_disponibles_for_days(
            days,
            mode=state.mode,
            duracion_min=state.selected_service['duracion_min'],
            presencia_cliente_min=state.selected_service['presencia_cliente_min'],
        )
        available_days = [d for d in days if slots_by_day.get(d)]

    if not available_days:
        wa.send_text_message(identifier, msg_sin_slots())
        _to_menu(identifier)
        return
    state.available_days = available_days
    state.step = BOOK_SELECT_DAY
    wa.send_interactive(identifier, build_days_list(available_days))


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


def _handle_book_select_day(identifier: str, state: ConversationState, value: str):
    if not state.selected_service:
        _to_menu(identifier)
        return

    if not value.startswith("day_"):
        _to_menu(identifier)
        return

    try:
        selected_date = date.fromisoformat(value.removeprefix("day_"))
    except ValueError:
        _to_menu(identifier)
        return

    if selected_date not in state.available_days:
        _to_menu(identifier)
        return

    slots = cal.get_slots_disponibles(
        selected_date,
        mode=state.mode,
        duracion_min=state.selected_service['duracion_min'],
        presencia_cliente_min=state.selected_service['presencia_cliente_min'],
    )
    if not slots:
        wa.send_text_message(identifier, msg_sin_slots())
        wa.send_interactive(identifier, build_days_list(state.available_days))
        return

    state.selected_date = selected_date
    _go_to_hour_select(identifier, state, selected_date, slots)


# ── BOOK: SELECT PERIOD ────────────────────────────────────────────────────

def _handle_book_select_period(identifier: str, state: ConversationState, value: str):
    morning, afternoon = _split_periods(state.all_day_slots)

    if value == "period_morning":
        slots = morning
    elif value == "period_afternoon":
        slots = afternoon
    elif value == "back_to_day":
        state.step = BOOK_SELECT_DAY
        wa.send_interactive(identifier, build_days_list(state.available_days))
        return
    else:
        _to_menu(identifier)
        return

    if not slots:
        wa.send_text_message(identifier, msg_sin_slots())
        wa.send_interactive(identifier, build_days_list(state.available_days))
        state.step = BOOK_SELECT_DAY
        return

    state.available_slots = slots
    if state.selected_date is None:
        _to_menu(identifier)
        return
    state.step = BOOK_SELECT_HOUR
    wa.send_interactive(
        identifier, build_hours_list(state.selected_date, slots, came_from_period=True)
    )


# ── BOOK: SELECT HOUR ──────────────────────────────────────────────────────

def _handle_book_select_hour(identifier: str, state: ConversationState, value: str):
    if value == "back_to_day":
        state.step = BOOK_SELECT_DAY
        wa.send_interactive(identifier, build_days_list(state.available_days))
        return

    if value == "back_to_period":
        morning, afternoon = _split_periods(state.all_day_slots)
        if morning and afternoon:
            if state.selected_date is None:
                _to_menu(identifier)
                return
            base_morning, base_afternoon = _base_period_ranges(state.selected_date)
            state.step = BOOK_SELECT_PERIOD
            wa.send_interactive(identifier, build_period_select(
                state.selected_date,
                base_morning or f"{morning[0]}-{morning[-1]}",
                base_afternoon or f"{afternoon[0]}-{afternoon[-1]}",
            ))
        else:
            _to_menu(identifier)
        return

    if not value.startswith("hour_"):
        _to_menu(identifier)
        return

    # Parse: hour_{YYYY-MM-DD}_{HHMM}
    try:
        parts = value.removeprefix("hour_").split("_")  # ['2026-03-25', '1030']
        selected_date = date.fromisoformat(parts[0])
        raw_time = parts[1]  # '1030'
        slot = f"{raw_time[:2]}:{raw_time[2:]}"  # '10:30'
    except (ValueError, IndexError):
        _to_menu(identifier)
        return

    if selected_date != state.selected_date or slot not in state.available_slots:
        _to_menu(identifier)
        return

    state.selected_slot = slot
    if state.move_source_event_id:
        _execute_mover_cita(identifier, state)
    else:
        state.step = BOOK_ENTER_NAME
        wa.send_text_message(identifier, "¿Cuál es tu nombre y apellidos?")


# ── BOOK: ENTER NAME ──────────────────────────────────────────────────────

_NOMBRE_MAX_LEN = 100  # Calendar summary field is 1024 bytes; keep it reasonable

def _handle_book_enter_name(identifier: str, state: ConversationState, value: str):
    if value == UNKNOWN_INPUT:
        wa.send_text_message(identifier, msg_nombre_por_texto())
        return
    nombre = value.strip().replace('\n', ' ').replace('\r', '')
    if len(nombre) < 2:
        wa.send_text_message(
            identifier, "Por favor, escribe tu nombre (mínimo 2 letras)."
        )
        return
    if len(nombre) > _NOMBRE_MAX_LEN:
        wa.send_text_message(
            identifier, "El nombre es demasiado largo. Por favor, escribe tu nombre."
        )
        return

    if (
        not state.selected_date
        or not state.selected_slot
        or state.selected_service is None
    ):
        logger.error("[CONV] _handle_book_enter_name: incomplete state for %s",
                     identifier)
        _to_menu(identifier)
        return

    state.nombre = nombre
    d = state.selected_date
    hora = state.selected_slot

    event_id, reason = cal.reservar_cita(
        d, hora, nombre, identifier, state.selected_service,
        telefono=state.phone, mode=state.mode,
    )

    if reason == 'slot_taken':
        logger.warning(f"[CONV] Slot {d} {hora} taken for {identifier}")
        slots = cal.get_slots_disponibles(
            d,
            mode=state.mode,
            duracion_min=state.selected_service['duracion_min'],
            presencia_cliente_min=state.selected_service['presencia_cliente_min'],
        )
        if slots:
            wa.send_text_message(identifier, msg_slot_no_disponible())
            _go_to_hour_select(identifier, state, d, slots)
        else:
            wa.send_text_message(identifier, msg_sin_slots())
            state.step = BOOK_SELECT_DAY
            wa.send_interactive(identifier, build_days_list(state.available_days))

    elif reason == 'error':
        wa.send_text_message(identifier, msg_error_creando_cita())
        _to_menu(identifier)

    else:
        _ctx.committed = True
        wa.send_interactive(
            identifier,
            build_back_to_menu_message(
                msg_cita_confirmada(d, hora, state.selected_service)
            ),
        )
        _clear(identifier)


# ── MOVE: SELECT CITA ─────────────────────────────────────────────────────

def _handle_move_select_cita(identifier: str, state: ConversationState, value: str):
    if not value.startswith("move_appt_"):
        _to_menu(identifier)
        return

    event_id = value.removeprefix("move_appt_")
    cita = next((c for c in state.move_citas if c['id'] == event_id), None)
    if cita is None:
        wa.send_text_message(identifier, msg_cita_no_encontrada())
        _to_menu(identifier)
        return

    nombre = parse_nombre(cita.get('description', '') or '')
    if nombre is None:
        nombre = "Cliente"
    state.move_source_nombre = nombre
    state.move_source_event_id = event_id
    cita_fecha = cita['start'].date().isoformat()
    state.mode = 'evento' if cita_fecha in EVENTO_DIAS else 'normal'
    state.step = BOOK_SELECT_SERVICE
    wa.send_interactive(identifier, build_service_select())


def _execute_mover_cita(identifier: str, state: ConversationState):
    if (
        not state.selected_date
        or not state.selected_slot
        or state.selected_service is None
        or not state.move_source_event_id
    ):
        logger.error("[CONV] _execute_mover_cita: incomplete state for %s", identifier)
        _to_menu(identifier)
        return

    d = state.selected_date
    hora = state.selected_slot

    new_event_id, reason = cal.mover_cita(
        state.move_source_event_id, d, hora,
        state.move_source_nombre or "Cliente",
        identifier, state.selected_service,
        telefono=state.phone, mode=state.mode,
    )

    if reason == 'slot_taken':
        logger.warning(f"[CONV] Move slot {d} {hora} taken for {identifier}")
        slots = cal.get_slots_disponibles(
            d,
            mode=state.mode,
            duracion_min=state.selected_service['duracion_min'],
            presencia_cliente_min=state.selected_service['presencia_cliente_min'],
        )
        if slots:
            wa.send_text_message(identifier, msg_slot_no_disponible())
            _go_to_hour_select(identifier, state, d, slots)
        else:
            wa.send_text_message(identifier, msg_sin_slots())
            state.step = BOOK_SELECT_DAY
            wa.send_interactive(identifier, build_days_list(state.available_days))

    elif reason == 'error':
        wa.send_text_message(identifier, msg_error_creando_cita())
        _to_menu(identifier)

    else:
        _ctx.committed = True
        wa.send_interactive(
            identifier,
            build_back_to_menu_message(
                msg_cita_movida(d, hora, state.selected_service)
            ),
        )
        _clear(identifier)


# ── VIEW APPOINTMENTS ──────────────────────────────────────────────────────

def _handle_view_appointments(identifier: str, state: ConversationState, value: str):
    # Any interaction (tap on a cita row or back_to_menu) → go to menu
    _to_menu(identifier)


# ── CANCEL: SELECT ─────────────────────────────────────────────────────────

def _handle_cancel_select(identifier: str, state: ConversationState, value: str):
    if not value.startswith("cancel_appt_"):
        _to_menu(identifier)
        return

    event_id = value.removeprefix("cancel_appt_")
    if not event_id:
        _to_menu(identifier)
        return

    # Look up event in cached citas
    citas = state.cancel_citas
    cita = next((c for c in citas if c['id'] == event_id), None)
    if not cita:
        wa.send_text_message(identifier, "No se encontró esa cita.")
        _to_menu(identifier)
        return

    if cal.cancelar_cita(event_id):
        _ctx.committed = True
        wa.send_interactive(
            identifier, build_back_to_menu_message(msg_cancelacion_ok())
        )
        _clear(identifier)
    else:
        wa.send_text_message(
            identifier, "No se pudo cancelar la cita. Por favor, contáctanos."
        )
        _to_menu(identifier)


# ── REMINDER RESPONSES ─────────────────────────────────────────────────────

def _handle_reminder_response(identifier: str, phone: Optional[str],
                               interactive_id: str):
    """
    Handle quick reply buttons from reminder template.
    reminder_confirm_{event_id} → confirm appointment
    reminder_cancel_{event_id}  → start cancellation flow
    """
    if interactive_id.startswith("reminder_confirm_"):
        event_id = interactive_id.removeprefix("reminder_confirm_")
        cita = cal.get_event_by_id(event_id, identifier, phone=phone)
        if not cita:
            wa.send_text_message(identifier, "No se encontró esa cita.")
            _to_menu(identifier)
            return
        if cal.confirmar_cita(event_id):
            _ctx.committed = True
            wa.send_text_message(identifier, "¡Tu cita está confirmada! ✅")
        else:
            wa.send_text_message(
                identifier, "No se pudo confirmar la cita. Por favor, contáctanos."
            )
        _to_menu(identifier)

    elif interactive_id.startswith("reminder_cancel_"):
        event_id = interactive_id.removeprefix("reminder_cancel_")
        cita = cal.get_event_by_id(event_id, identifier, phone=phone)
        if not cita:
            wa.send_text_message(identifier, "No se encontró esa cita.")
            _to_menu(identifier)
            return
        if cal.cancelar_cita(event_id):
            _ctx.committed = True
            wa.send_interactive(identifier,
                                 build_back_to_menu_message(msg_cancelacion_ok()))
            _clear(identifier)
        else:
            wa.send_text_message(
                identifier, "No se pudo cancelar la cita. Por favor, contáctanos."
            )
            _to_menu(identifier)

    else:
        _to_menu(identifier)
