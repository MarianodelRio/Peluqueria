# services/calendar.py
"""
Google Calendar service. Single source of truth for all appointment data.
All datetimes are timezone-aware (Europe/Madrid).
"""
import logging
import threading
import time
import httplib2
import google_auth_httplib2
from datetime import date, datetime, timedelta
from typing import List, Optional
import pytz
from googleapiclient.discovery import build
from google.oauth2 import service_account

from app.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_CALENDAR_ID, TIMEZONE, CITA_DURACION_MIN, GOOGLE_API_TIMEOUT_SEC, SLOT_CACHE_TTL_SEC
from app.utils import metrics
from app.utils.parser import (
    parse_nombre, parse_tel, parse_estado, parse_reminder,
    parse_cfg, set_field, remove_field
)
from app.utils.slots import (
    get_base_slots_for_day, generate_slots, filter_available_slots, slot_to_datetime,
)

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)
# calendar.events: full read/write on events only (no calendar metadata access).
# This is the minimum scope required for all operations in this service.
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# ── Service singleton (one per thread, thread-safe) ────────────────────────
_thread_local = threading.local()


def _get_service():
    """
    Return a cached Google Calendar service per thread.
    Avoids rebuilding credentials on every call while remaining thread-safe.
    The google-auth library handles token refresh transparently.
    """
    if not hasattr(_thread_local, 'service'):
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
        )
        authorized_http = google_auth_httplib2.AuthorizedHttp(
            creds, http=httplib2.Http(timeout=GOOGLE_API_TIMEOUT_SEC)
        )
        _thread_local.service = build('calendar', 'v3', http=authorized_http, cache_discovery=False)
    return _thread_local.service


def _get_day_events(service, d: date) -> List[dict]:
    """
    Fetch all events for a given day from Google Calendar.
    Returns list of dicts: {id, title, description, start, end, all_day}
    """
    day_start = TZ.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
    day_end = TZ.localize(datetime(d.year, d.month, d.day, 23, 59, 59))

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy='startTime',
    ).execute(num_retries=2)

    events = []
    for item in result.get('items', []):
        start_raw = item.get('start', {})
        end_raw = item.get('end', {})

        # All-day events
        if 'date' in start_raw:
            events.append({
                'id': item['id'],
                'title': item.get('summary', ''),
                'description': item.get('description', '') or '',
                'start': day_start,
                'end': day_end,
                'all_day': True,
            })
            continue

        # Timed events
        start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
        end_dt = datetime.fromisoformat(end_raw['dateTime']).astimezone(TZ)
        events.append({
            'id': item['id'],
            'title': item.get('summary', ''),
            'description': item.get('description', '') or '',
            'start': start_dt,
            'end': end_dt,
            'all_day': False,
        })
    return events


def _get_slots_disponibles_uncached(d: date) -> List[str]:
    """Internal: fetch slots from Google Calendar without cache."""
    service = _get_service()
    events = _get_day_events(service, d)

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

    base_slots = (
        generate_slots(special_schedule['start'], special_schedule['end'])
        if special_schedule else get_base_slots_for_day(d)
    )

    if not base_slots:
        return []

    available = filter_available_slots(base_slots, d, blocking_events)

    if d == datetime.now(TZ).date():
        now_time = datetime.now(TZ).strftime("%H:%M")
        available = [s for s in available if s > now_time]

    return available


# ── Per-slot locks (prevent race conditions during booking) ────────────────
_slot_locks: dict[str, threading.Lock] = {}
_slot_locks_guard = threading.Lock()


def _get_slot_lock(d: date, hora: str) -> threading.Lock:
    """One Lock per (date, slot). Created on demand, never deleted (bounded set)."""
    key = f"{d.isoformat()}_{hora}"
    with _slot_locks_guard:
        if key not in _slot_locks:
            _slot_locks[key] = threading.Lock()
        return _slot_locks[key]


# ── Slot availability cache ────────────────────────────────────────────────
_slot_cache: dict[str, tuple[list, float]] = {}
_slot_cache_lock = threading.Lock()


def _slot_cache_key(d: date) -> str:
    return d.isoformat()


def _invalidate_slot_cache(d: date) -> None:
    with _slot_cache_lock:
        _slot_cache.pop(_slot_cache_key(d), None)


def get_slots_disponibles(d: date, bypass_cache: bool = False) -> List[str]:
    """
    Returns available slots for a given date.
    bypass_cache=True skips cache and always fetches live data (used during booking).
    """
    if not bypass_cache:
        key = _slot_cache_key(d)
        now_ts = time.time()
        with _slot_cache_lock:
            if key in _slot_cache:
                result, ts = _slot_cache[key]
                if now_ts - ts < SLOT_CACHE_TTL_SEC:
                    return list(result)

    try:
        result = _get_slots_disponibles_uncached(d)
    except Exception as e:
        logger.error(f"[CAL] Error fetching slots for {d}: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return []

    if not bypass_cache:
        with _slot_cache_lock:
            _slot_cache[_slot_cache_key(d)] = (list(result), time.time())

    return result


def slot_sigue_libre(d: date, hora: str) -> bool:
    """
    Re-check if a specific slot is still available.
    Always bypasses cache — called inside the booking lock for anti-race guarantee.
    """
    available = get_slots_disponibles(d, bypass_cache=True)
    return hora in available


def reservar_cita(d: date, hora: str, nombre: str, telefono: str) -> tuple:
    """
    Atomic booking: acquire per-slot lock → re-validate → create.
    Prevents race conditions between concurrent booking attempts.

    Returns:
        (event_id, None)          — success
        (None, 'slot_taken')      — slot no longer available
        (None, 'double_booking')  — client already has appointment that day
        (None, 'error')           — Calendar API failure
    """
    lock = _get_slot_lock(d, hora)
    with lock:
        if not slot_sigue_libre(d, hora):
            return None, 'slot_taken'
        if tiene_cita_ese_dia(telefono, d):
            return None, 'double_booking'
        event_id = crear_cita(d, hora, nombre, telefono)
        if not event_id:
            return None, 'error'
        return event_id, None


def tiene_cita_ese_dia(telefono: str, d: date) -> bool:
    """
    Check if phone number already has an appointment on given date.
    Rule: max 1 appointment per day per client.
    """
    service = _get_service()
    events = _get_day_events(service, d)
    for ev in events:
        tel = parse_tel(ev['description'])
        if tel and tel == telefono:
            return True
    return False


def crear_cita(d: date, hora: str, nombre: str, telefono: str) -> Optional[str]:
    """
    Create appointment event in Google Calendar.
    Returns event ID on success, None on failure.
    """
    service = _get_service()
    start_dt = slot_to_datetime(d, hora)
    end_dt = start_dt + timedelta(minutes=CITA_DURACION_MIN)

    description = (
        f"Nombre: {nombre}\n"
        f"Telefono: {telefono}\n"
        f"Estado: confirmada\n"
        f"Recordatorio: no"
    )

    event = {
        'summary': f"Cita - {nombre}",
        'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': TIMEZONE},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': TIMEZONE},
    }

    try:
        created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute(num_retries=2)
        logger.info(f"[CAL] Created appointment (confirmed): {nombre} {telefono} {d} {hora} event_id={created['id']}")
        _invalidate_slot_cache(d)
        metrics.inc('bookings_created')
        return created['id']
    except Exception as e:
        logger.error(f"[CAL] Error creating appointment: {e}")
        return None


def confirmar_cita(event_id: str) -> bool:
    """Update appointment status to 'confirmada'."""
    service = _get_service()
    try:
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute(num_retries=2)
        desc = event.get('description', '') or ''
        desc = set_field(desc, 'Estado', 'confirmada')
        event['description'] = desc
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute(num_retries=2)
        logger.info(f"[CAL] Confirmed appointment event_id={event_id}")
        return True
    except Exception as e:
        logger.error(f"[CAL] Error confirming appointment {event_id}: {e}")
        return False


def cancelar_cita(event_id: str) -> bool:
    """Delete appointment event from Google Calendar."""
    service = _get_service()
    try:
        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute(num_retries=2)
        logger.info(f"[CAL] Deleted appointment event_id={event_id}")
        metrics.inc('bookings_cancelled')
        return True
    except Exception as e:
        logger.error(f"[CAL] Error deleting appointment {event_id}: {e}")
        return False


def get_eventos_manuales_sin_confirmar() -> List[dict]:
    """
    Return manual calendar events with Telefono: and Estado: pendiente.
    These are appointments created by the barber that need WhatsApp confirmation.
    Idempotent: once Estado is set to confirmada, they are skipped.
    """
    service = _get_service()
    now = datetime.now(TZ)
    time_max = (now + timedelta(days=60)).isoformat()

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=now.isoformat(),
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
    ).execute(num_retries=2)

    manual_events = []
    for item in result.get('items', []):
        desc = item.get('description', '') or ''
        title = item.get('summary', '') or ''

        # Skip [CFG] events
        if parse_cfg(title):
            continue

        # Must have Telefono: (new format) or Tel: (legacy)
        tel = parse_tel(desc)
        if not tel:
            continue

        # Must be Estado: pendiente (idempotency — confirmada means already processed)
        estado = parse_estado(desc)
        if estado != 'pendiente':
            continue

        start_raw = item.get('start', {})
        if 'dateTime' not in start_raw:
            continue

        start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
        nombre = parse_nombre(desc) or title or "Cliente"
        manual_events.append({
            'id': item['id'],
            'title': title,
            'nombre': nombre,
            'description': desc,
            'telefono': tel,
            'start': start_dt,
        })

    return manual_events


def marcar_manual_confirmado(event_id: str) -> bool:
    """
    After sending WhatsApp confirmation for a manual appointment,
    update Estado: confirmada and ensure Recordatorio: no is set.
    """
    service = _get_service()
    try:
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute(num_retries=2)
        desc = event.get('description', '') or ''
        desc = set_field(desc, 'Estado', 'confirmada')
        desc = set_field(desc, 'Recordatorio', 'no')
        event['description'] = desc
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute(num_retries=2)
        logger.info(f"[CAL] Marked manual event confirmed: {event_id}")
        return True
    except Exception as e:
        logger.error(f"[CAL] Error marking manual confirmed {event_id}: {e}")
        return False


def get_citas_para_recordatorio() -> List[dict]:
    """
    Return appointments in 23h-25h window with Recordatorio: no (or unset).
    Must have Telefono: and Estado: pendiente or confirmada.
    """
    service = _get_service()
    now = datetime.now(TZ)
    window_start = now + timedelta(hours=23)
    window_end = now + timedelta(hours=25)

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=window_start.isoformat(),
        timeMax=window_end.isoformat(),
        singleEvents=True,
        orderBy='startTime',
    ).execute(num_retries=2)

    reminders = []
    for item in result.get('items', []):
        desc = item.get('description', '') or ''
        title = item.get('summary', '') or ''

        if parse_cfg(title):
            continue

        tel = parse_tel(desc)
        if not tel:
            continue

        # Skip if reminder already sent
        if parse_reminder(desc) == 'si':
            continue

        # Only send for pending or confirmed appointments
        estado = parse_estado(desc)
        if estado not in ('pendiente', 'confirmada', None):
            continue

        start_raw = item.get('start', {})
        if 'dateTime' not in start_raw:
            continue

        start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
        reminders.append({
            'id': item['id'],
            'title': title,
            'description': desc,
            'telefono': tel,
            'start': start_dt,
        })

    return reminders


def marcar_recordatorio_enviado(event_id: str) -> bool:
    """Mark event Recordatorio: sí after sending reminder."""
    service = _get_service()
    try:
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute(num_retries=2)
        desc = event.get('description', '') or ''
        desc = set_field(desc, 'Recordatorio', 'sí')
        event['description'] = desc
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute(num_retries=2)
        logger.info(f"[CAL] Marked reminder sent: {event_id}")
        return True
    except Exception as e:
        logger.error(f"[CAL] Error marking reminder {event_id}: {e}")
        return False


def get_citas_futuras(telefono: str) -> list:
    """
    Return ALL future appointments for a phone number, ordered by date.
    Returns [] on Google Calendar API failure (graceful degradation).
    """
    try:
        service = _get_service()
        now = datetime.now(TZ)
        time_max = (now + timedelta(days=30)).isoformat()

        result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime',
        ).execute(num_retries=2)

        citas = []
        for item in result.get('items', []):
            desc = item.get('description', '') or ''
            title = item.get('summary', '') or ''

            if parse_cfg(title):
                continue

            tel = parse_tel(desc)
            if not tel or tel != telefono:
                continue

            start_raw = item.get('start', {})
            if 'dateTime' not in start_raw:
                continue

            start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
            end_raw = item.get('end', {})
            end_dt = datetime.fromisoformat(end_raw['dateTime']).astimezone(TZ)

            citas.append({
                'id': item['id'],
                'title': title,
                'description': desc,
                'start': start_dt,
                'end': end_dt,
            })

        return citas
    except Exception as e:
        logger.error(f"[CAL] Error fetching citas for {telefono}: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return []


def check_calendar_health() -> bool:
    """
    Verify Google Calendar connectivity by listing at most 1 event.
    Uses events().list() instead of calendars().get() so we only need
    the calendar.events scope (no calendar metadata access required).
    Returns True if the API responds successfully, False otherwise.
    """
    try:
        service = _get_service()
        service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            maxResults=1,
            singleEvents=True,
        ).execute(num_retries=2)
        return True
    except Exception as e:
        logger.error(f"[CAL] Health check failed: {e}")
        return False
