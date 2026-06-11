# services/calendar/service.py
"""
Slot availability functions and atomic booking.
Mutations (crear/cancelar/confirmar/marcar) live in mutations.py.
Read-only queries live in queries.py.
All datetimes are timezone-aware (Europe/Madrid).
"""
import logging
from datetime import date, datetime, timedelta
from typing import List

import pytz

from app.config import TIMEZONE, EVENTO_DIAS
from app.utils import metrics

from .caches import slot_cache
from .locks import slot_locks
from .engine import slot_cache_key, compute_slots
from .repository import events_repo
from .mutations import crear_cita, cancelar_cita

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _filter_past_hours_today(d: date, slots: List[str]) -> List[str]:
    """Strip slots already past when d is today. No-op for future dates."""
    today = datetime.now(TZ).date()
    if d == today:
        now_time = datetime.now(TZ).strftime("%H:%M")
        return [s for s in slots if s > now_time]
    return list(slots)


def _invalidate_slot_cache(d: date) -> None:
    """Remove all cache entries for a given date (all durations),
    including evt_* keys."""
    date_str = d.isoformat()
    slot_cache.invalidate_matching(
        lambda k: k.startswith(date_str) or k.startswith(f"evt_{date_str}")
    )


# ── Unified slot availability ──────────────────────────────────────────────────

def get_slots_disponibles(
    d: date,
    *,
    mode: str = 'normal',
    bypass_cache: bool = False,
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> List[str]:
    """
    Returns available slots for a given date.

    mode='normal'  — uses HORARIO_BASE (standard booking flow).
    mode='evento'  — uses EVENTO_DIAS[d] as base slot ranges (event booking flow).

    bypass_cache=True skips cache and always fetches live data (used during booking).
    Cache stores the UNFILTERED list; today-filter is applied on every read.
    """
    event_horario = None
    if mode == 'evento':
        raw_ranges = EVENTO_DIAS.get(d.isoformat(), [])
        if not raw_ranges:
            return []
        event_horario = [(r[0], r[1]) for r in raw_ranges]

    key = slot_cache_key(d, mode, duracion_min, presencia_cliente_min)
    if not bypass_cache:
        cached = slot_cache.get(key)
        if cached is not None:
            return _filter_past_hours_today(d, cached)

    try:
        events = events_repo.list_for_day(d)
        result = compute_slots(
            d, events, duracion_min, presencia_cliente_min,
            event_horario=event_horario,
        )
    except Exception as e:
        logger.error(f"[CAL] Error fetching slots for {d}: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return []

    if not bypass_cache:
        # Store unfiltered — today-filter is applied on read
        slot_cache.set(key, list(result))

    return _filter_past_hours_today(d, result)


def get_slots_disponibles_for_days(
    days: List[date],
    *,
    mode: str = 'normal',
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> dict:
    """
    Fetch and compute available slots for every date in `days` using a single
    batched Google Calendar API call for [min(days), max(days)].

    Populates the per-day slot cache (unfiltered) as a side-effect so that
    subsequent single-day get_slots_disponibles() calls are cache hits.

    Returns dict[date, List[str]] with today-filter applied on today's value.
    Returns {} on any error or if `days` is empty.
    """
    if not days:
        return {}
    try:
        start = min(days)
        end = max(days)
        events_by_day = events_repo.list_for_range(start, end)

        result: dict = {}

        for d in days:
            event_horario = None
            if mode == 'evento':
                raw_ranges = EVENTO_DIAS.get(d.isoformat(), [])
                event_horario = [(r[0], r[1]) for r in raw_ranges] if raw_ranges else []
                if not event_horario:
                    key = slot_cache_key(d, mode, duracion_min, presencia_cliente_min)
                    slot_cache.set(key, [])
                    result[d] = []
                    continue

            slots = compute_slots(
                d, events_by_day.get(d, []), duracion_min, presencia_cliente_min,
                event_horario=event_horario,
            )

            # Write unfiltered slots to cache
            key = slot_cache_key(d, mode, duracion_min, presencia_cliente_min)
            slot_cache.set(key, list(slots))

            # Apply today-filter only to the returned value
            result[d] = _filter_past_hours_today(d, slots)

        return result
    except Exception as e:
        logger.error(
            f"[CAL] Error in get_slots_disponibles_for_days: {e}",
            exc_info=True,
        )
        metrics.inc('calendar_errors')
        return {}


# ── Compatibility wrappers ────────────────────────────────────────────────────

def get_slots_disponibles_evento(
    d: date,
    bypass_cache: bool = False,
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> List[str]:
    """Compatibility wrapper — delegates to get_slots_disponibles with mode='evento'."""
    return get_slots_disponibles(
        d, mode='evento', bypass_cache=bypass_cache,
        duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min,
    )


def get_slots_disponibles_evento_range(
    days: List[date],
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> dict:
    """Compatibility wrapper — delegates to get_slots_disponibles_for_days
    with mode='evento'."""
    return get_slots_disponibles_for_days(
        days, mode='evento',
        duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min,
    )


def get_slots_disponibles_range(
    start: date,
    end: date,
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> dict:
    """
    Fetch and compute available slots for every date in [start, end] inclusive
    using a single batched Google Calendar API call.

    Populates the per-day slot cache as a side-effect so that subsequent
    single-day get_slots_disponibles() calls are cache hits.

    Returns dict[date, List[str]] with today-filter applied on today's value.
    Returns {} on any error.
    """
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return get_slots_disponibles_for_days(
        days, mode='normal',
        duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min,
    )


def slot_sigue_libre(
    d: date,
    hora: str,
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> bool:
    """
    Re-check if a specific slot is still available.
    Always bypasses cache — called inside the booking lock for anti-race guarantee.
    """
    available = get_slots_disponibles(
        d, mode='normal', bypass_cache=True,
        duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min,
    )
    return hora in available


# ── Atomic booking ────────────────────────────────────────────────────────────

def reservar_cita(
    d: date, hora: str, nombre: str, telefono: str, servicio: dict,
) -> tuple:
    """
    Atomic booking: acquire per-slot lock → re-validate → create.
    Prevents race conditions between concurrent booking attempts.

    Returns:
        (event_id, None)          — success
        (None, 'slot_taken')      — slot no longer available
        (None, 'error')           — Calendar API failure
    """
    lock = slot_locks.get(d, hora)
    presencia = servicio['presencia_cliente_min']
    with lock:
        if not slot_sigue_libre(
            d, hora,
            duracion_min=servicio['duracion_min'],
            presencia_cliente_min=presencia,
        ):
            return None, 'slot_taken'
        event_id = crear_cita(d, hora, nombre, telefono, servicio=servicio)
        if not event_id:
            return None, 'error'
        return event_id, None


def mover_cita(
    source_event_id: str, d: date, hora: str, nombre: str, telefono: str,
    servicio: dict,
) -> tuple:
    """
    Atomic move: acquire per-slot lock → re-validate → create new → delete old.

    Returns:
        (new_event_id, None)     — success
        (None, 'slot_taken')     — slot no longer available
        (None, 'error')          — Calendar API failure on create
    """
    lock = slot_locks.get(d, hora)
    presencia = servicio['presencia_cliente_min']
    with lock:
        if not slot_sigue_libre(
            d, hora,
            duracion_min=servicio['duracion_min'],
            presencia_cliente_min=presencia,
        ):
            return None, 'slot_taken'
        new_event_id = crear_cita(d, hora, nombre, telefono, servicio=servicio)
        if not new_event_id:
            return None, 'error'

    if not cancelar_cita(source_event_id):
        logger.warning(
            f"[CAL] mover_cita: failed to delete source event {source_event_id}"
        )

    return new_event_id, None
