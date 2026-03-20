# utils/slots.py
"""
Slot generation and availability calculation.
All times in Europe/Madrid timezone.
"""
from datetime import date, datetime, timedelta
from typing import List
import pytz
import logging

from app.config import HORARIO_BASE, CITA_DURACION_MIN, TIMEZONE

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

OVERLAP_TOLERANCE_SECONDS = 60  # ±1 minute tolerance


def generate_slots(start_str: str, end_str: str) -> List[str]:
    """
    Generate 30-min slots between start and end.
    start_str, end_str: 'HH:MM' format.
    Returns list of 'HH:MM' strings. Last slot starts at end - 30min.
    """
    slots = []
    start_h, start_m = map(int, start_str.split(':'))
    end_h, end_m = map(int, end_str.split(':'))
    current = start_h * 60 + start_m
    end = end_h * 60 + end_m
    while current + CITA_DURACION_MIN <= end:
        h = current // 60
        m = current % 60
        slots.append(f"{h:02d}:{m:02d}")
        current += CITA_DURACION_MIN
    return slots


def get_base_slots_for_day(d: date) -> List[str]:
    """Returns base slots for a given date based on HORARIO_BASE."""
    weekday = d.weekday()  # 0=Monday, 6=Sunday
    if weekday not in HORARIO_BASE:
        return []
    slots = []
    for start_str, end_str in HORARIO_BASE[weekday]:
        slots.extend(generate_slots(start_str, end_str))
    return slots


def slot_to_datetime(d: date, slot: str) -> datetime:
    """Convert date + 'HH:MM' slot to aware datetime in Madrid timezone."""
    h, m = map(int, slot.split(':'))
    naive = datetime(d.year, d.month, d.day, h, m, 0)
    return TZ.localize(naive)


def events_overlap_slot(event_start: datetime, event_end: datetime,
                        slot_start: datetime, slot_end: datetime) -> bool:
    """
    Returns True if event overlaps with slot.
    Applies ±1 minute tolerance to avoid false positives on boundary slots.
    """
    tolerance = timedelta(seconds=OVERLAP_TOLERANCE_SECONDS)
    effective_event_start = event_start + tolerance
    effective_event_end = event_end - tolerance
    # Overlap: event starts before slot ends AND event ends after slot starts
    return effective_event_start < slot_end and effective_event_end > slot_start


def filter_available_slots(all_slots: List[str], d: date, events: List[dict]) -> List[str]:
    """
    Given all possible slots and a list of Google Calendar events for that day,
    return only the free slots.

    events: list of dicts with keys 'start', 'end' as aware datetimes.
    """
    available = []
    for slot in all_slots:
        slot_start = slot_to_datetime(d, slot)
        slot_end = slot_start + timedelta(minutes=CITA_DURACION_MIN)
        occupied = False
        for event in events:
            ev_start = event['start']
            ev_end = event['end']
            if events_overlap_slot(ev_start, ev_end, slot_start, slot_end):
                occupied = True
                break
        if not occupied:
            available.append(slot)
    return available


def get_next_days(n_calendar_days: int = 10) -> List[date]:
    """
    Returns working days (Mon-Fri) within the next n_calendar_days from today.
    Includes today if it's a working day.
    """
    today = datetime.now(TZ).date()
    return [
        today + timedelta(days=i)
        for i in range(n_calendar_days + 1)
        if (today + timedelta(days=i)).weekday() < 6
    ]


def format_date_es(d: date) -> str:
    """Format date in Spanish: 'lunes 24 de marzo'"""
    dias = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
             'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]}"
