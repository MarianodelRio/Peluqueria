# services/calendar/engine.py
"""
Pure slot-computation functions — no IO, no cache.
All external dependencies are passed in as arguments.
"""
import logging
from datetime import date
from typing import List, Optional

from app.config import CITA_DURACION_MIN
from app.utils.parser import parse_cfg
from app.utils.slots import (
    get_base_slots_for_day, generate_slots, filter_available_slots,
)

logger = logging.getLogger(__name__)


def slot_cache_key(
    d: date,
    mode: str = 'normal',
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> str:
    """
    Return the cache key for a (date, mode, duracion, presencia) combination.
    Event-mode keys are prefixed with 'evt_' to avoid colliding with normal keys.
    """
    if mode == 'evento':
        return f"evt_{d.isoformat()}_{duracion_min}_{presencia_cliente_min}"
    return f"{d.isoformat()}_{duracion_min}_{presencia_cliente_min}"


def compute_slots(
    d: date,
    events: List[dict],
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
    event_horario: Optional[List[tuple]] = None,
) -> List[str]:
    """
    Pure function: compute available slots for a day given pre-fetched events.
    Does NOT include the today-filter (caller handles that).
    events: list of dicts in the same format as EventsRepository.list_for_day returns.

    Priority chain for base slots:
      [CFG] CERRADO / VACACIONES  → []  (hard close, highest priority)
      [CFG] HORARIO HH:MM-HH:MM  → special_schedule overrides everything
      event_horario               → event-specific ranges (only if no special_schedule)
      HORARIO_BASE / weekday      → normal fallback
    """
    is_closed = False
    special_schedule = None
    blocking_events = []

    for ev in events:
        cfg = parse_cfg(ev['title'])
        if cfg:
            if cfg['type'] in ('cerrado', 'vacaciones'):
                logger.info(f"[CAL] Day {d} is closed: {ev['title']}")
                is_closed = True
                break
            elif cfg['type'] == 'horario' and special_schedule is None:
                special_schedule = cfg
                logger.info(f"[CAL] Special schedule on {d}: {cfg['start']}-{cfg['end']}")
        else:
            blocking_events.append({'start': ev['start'], 'end': ev['end']})

    if is_closed:
        return []

    if special_schedule:
        base_slots = generate_slots(
            special_schedule['start'], special_schedule['end'],
            presencia_cliente_min, step_min=CITA_DURACION_MIN,
        )
    elif event_horario is not None:
        # event_horario is a list of (start_str, end_str) tuples
        base_slots = []
        for start_str, end_str in event_horario:
            base_slots.extend(
                generate_slots(start_str, end_str, presencia_cliente_min, step_min=CITA_DURACION_MIN)
            )
    else:
        base_slots = get_base_slots_for_day(d, presencia_cliente_min)

    if not base_slots:
        return []

    return filter_available_slots(base_slots, d, blocking_events, duracion_min)
