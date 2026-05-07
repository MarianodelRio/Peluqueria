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

from app.config import (
    GOOGLE_CREDENTIALS_PATH, GOOGLE_CALENDAR_ID, TIMEZONE, CITA_DURACION_MIN,
    GOOGLE_API_TIMEOUT_SEC, SLOT_CACHE_TTL_SEC, CITAS_CACHE_TTL_SEC, SERVICIOS,
    LOOKAHEAD_CITAS_CLIENTE_DIAS, LOOKAHEAD_CITAS_MANUALES_DIAS,
    RECORDATORIO_DESDE_H, RECORDATORIO_HASTA_H, EVENTO_DIAS,
)
from app.utils import metrics
from app.utils.security import mask_phone
from app.utils.parser import (
    parse_nombre, parse_tel, parse_estado, parse_reminder,
    parse_cfg, set_field, remove_field, parse_servicio_from_title
)
from app.utils.slots import (
    get_base_slots_for_day, generate_slots, filter_available_slots, slot_to_datetime,
    get_event_slots_for_day,
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


def _compute_slots(
    d: date,
    events: List[dict],
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
    event_horario: Optional[List[tuple]] = None,
) -> List[str]:
    """
    Pure function: compute available slots for a day given pre-fetched events.
    Does NOT include the today-filter (caller handles that).
    events: list of dicts in the same format as _get_day_events returns.

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


def _get_slots_disponibles_uncached(d: date, duracion_min: int = 30, presencia_cliente_min: int = 30) -> List[str]:
    """Internal: fetch slots from Google Calendar without cache. Today-filter applied by caller."""
    service = _get_service()
    events = _get_day_events(service, d)
    return _compute_slots(d, events, duracion_min, presencia_cliente_min)


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


# ── Citas-per-phone cache ──────────────────────────────────────────────────
_citas_cache: dict[str, tuple[list, float]] = {}
_citas_cache_lock = threading.Lock()


def _invalidate_citas_cache(phone: Optional[str]) -> None:
    """
    Remove the cached citas entry for `phone`.
    No-op if phone is None or not in cache.
    Safe to call from any thread.
    """
    if phone is None:
        return
    with _citas_cache_lock:
        _citas_cache.pop(phone, None)


def _slot_cache_key(d: date, duracion_min: int = 30, presencia_cliente_min: int = 30) -> str:
    return f"{d.isoformat()}_{duracion_min}_{presencia_cliente_min}"


def _invalidate_slot_cache(d: date) -> None:
    """Remove all cache entries for a given date (all durations), including evt_* prefixed keys."""
    date_str = d.isoformat()
    # Normal keys: "YYYY-MM-DD_30_30", "YYYY-MM-DD_60_180", ...
    # Event keys:  "evt_YYYY-MM-DD_30_30", ...
    prefix_normal = date_str
    prefix_event = f"evt_{date_str}"
    with _slot_cache_lock:
        keys_to_delete = [
            k for k in _slot_cache
            if k.startswith(prefix_normal) or k.startswith(prefix_event)
        ]
        for k in keys_to_delete:
            _slot_cache.pop(k, None)


def get_slots_disponibles(d: date, bypass_cache: bool = False, duracion_min: int = 30, presencia_cliente_min: int = 30) -> List[str]:
    """
    Returns available slots for a given date.
    bypass_cache=True skips cache and always fetches live data (used during booking).
    duracion_min: calendar event duration in minutes (used for collision detection).
    presencia_cliente_min: client presence window in minutes (used for slot generation).
    Cache stores the UNFILTERED list; today-filter is applied on every read.
    """
    today = datetime.now(TZ).date()
    now_time = datetime.now(TZ).strftime("%H:%M")

    if not bypass_cache:
        key = _slot_cache_key(d, duracion_min, presencia_cliente_min)
        now_ts = time.time()
        with _slot_cache_lock:
            if key in _slot_cache:
                result, ts = _slot_cache[key]
                if now_ts - ts < SLOT_CACHE_TTL_SEC:
                    result = list(result)
                    if d == today:
                        result = [s for s in result if s > now_time]
                    return result

    try:
        result = _get_slots_disponibles_uncached(d, duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min)
    except Exception as e:
        logger.error(f"[CAL] Error fetching slots for {d}: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return []

    if not bypass_cache:
        with _slot_cache_lock:
            # Store unfiltered — today-filter is applied on read
            _slot_cache[_slot_cache_key(d, duracion_min, presencia_cliente_min)] = (list(result), time.time())

    if d == today:
        result = [s for s in result if s > now_time]
    return result


def _get_events_in_range(service, start: date, end: date) -> dict:
    """
    Fetch all events for every date in [start, end] inclusive via a single API call.
    Returns dict[date, List[dict]] where each value uses the same format as _get_day_events.
    Paginates automatically, capped at 5 pages to prevent runaway loops.
    """
    range_start = TZ.localize(datetime(start.year, start.month, start.day, 0, 0, 0))
    range_end = TZ.localize(datetime(end.year, end.month, end.day, 23, 59, 59))

    # Initialise a bucket for every date in the range (days with no events get [])
    buckets: dict = {}
    current = start
    while current <= end:
        buckets[current] = []
        current += timedelta(days=1)

    page_token = None
    pages_fetched = 0
    max_pages = 5

    while pages_fetched < max_pages:
        kwargs = dict(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=range_start.isoformat(),
            timeMax=range_end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
        )
        if page_token:
            kwargs['pageToken'] = page_token

        result = service.events().list(**kwargs).execute(num_retries=2)
        pages_fetched += 1

        for item in result.get('items', []):
            start_raw = item.get('start', {})
            end_raw = item.get('end', {})
            title = item.get('summary', '')
            description = item.get('description', '') or ''
            event_id = item['id']

            if 'date' in start_raw:
                # All-day event — end.date is EXCLUSIVE, expand with while d < end_d
                start_d = date.fromisoformat(start_raw['date'])
                end_d = date.fromisoformat(end_raw['date'])
                d = start_d
                while d < end_d:
                    if d in buckets:
                        day_start = TZ.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
                        day_end = TZ.localize(datetime(d.year, d.month, d.day, 23, 59, 59))
                        buckets[d].append({
                            'id': event_id,
                            'title': title,
                            'description': description,
                            'start': day_start,
                            'end': day_end,
                            'all_day': True,
                        })
                    d += timedelta(days=1)
            else:
                # Timed event — bucket by start date
                start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
                end_dt = datetime.fromisoformat(end_raw['dateTime']).astimezone(TZ)
                d = start_dt.date()
                if d in buckets:
                    buckets[d].append({
                        'id': event_id,
                        'title': title,
                        'description': description,
                        'start': start_dt,
                        'end': end_dt,
                        'all_day': False,
                    })

        page_token = result.get('nextPageToken')
        if not page_token:
            break

    return buckets


def get_slots_disponibles_range(
    start: date,
    end: date,
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> dict:
    """
    Fetch and compute available slots for every date in [start, end] inclusive
    using a single batched Google Calendar API call.

    Populates the per-day slot cache (unfiltered) as a side-effect so that
    subsequent single-day get_slots_disponibles() calls are cache hits.

    Returns dict[date, List[str]] with today-filter applied on today's value.
    Returns {} on any error.
    """
    try:
        service = _get_service()
        events_by_day = _get_events_in_range(service, start, end)

        today = datetime.now(TZ).date()
        now_time = datetime.now(TZ).strftime("%H:%M")
        now_ts = time.time()

        result: dict = {}
        current = start
        while current <= end:
            slots = _compute_slots(current, events_by_day.get(current, []), duracion_min, presencia_cliente_min)

            # Write unfiltered slots to cache
            key = _slot_cache_key(current, duracion_min, presencia_cliente_min)
            with _slot_cache_lock:
                _slot_cache[key] = (list(slots), now_ts)

            # Apply today-filter only to the returned value
            if current == today:
                result[current] = [s for s in slots if s > now_time]
            else:
                result[current] = list(slots)

            current += timedelta(days=1)

        return result
    except Exception as e:
        logger.error(f"[CAL] Error in get_slots_disponibles_range({start}, {end}): {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return {}


def _get_slots_evento_uncached(d: date, duracion_min: int = 30, presencia_cliente_min: int = 30) -> List[str]:
    """
    Internal: fetch slots for a special-event day without cache.
    Uses event_horario from EVENTO_DIAS for base slot generation.
    Today-filter applied by caller.
    """
    # Build event_horario from EVENTO_DIAS
    key = d.isoformat()
    raw_ranges = EVENTO_DIAS.get(key, [])
    event_horario = [(r[0], r[1]) for r in raw_ranges] if raw_ranges else []
    if not event_horario:
        return []
    service = _get_service()
    events = _get_day_events(service, d)
    return _compute_slots(d, events, duracion_min, presencia_cliente_min, event_horario=event_horario)


def get_slots_disponibles_evento(
    d: date,
    bypass_cache: bool = False,
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> List[str]:
    """
    Returns available slots for a special-event day.
    Uses 'evt_{d}_{duracion}_{presencia}' cache keys to avoid colliding with normal flow.
    bypass_cache=True skips cache (used during booking confirmation).
    Today-filter applied on every read, same as get_slots_disponibles.
    """
    today = datetime.now(TZ).date()
    now_time = datetime.now(TZ).strftime("%H:%M")

    if not bypass_cache:
        key = f"evt_{_slot_cache_key(d, duracion_min, presencia_cliente_min)}"
        now_ts = time.time()
        with _slot_cache_lock:
            if key in _slot_cache:
                result, ts = _slot_cache[key]
                if now_ts - ts < SLOT_CACHE_TTL_SEC:
                    result = list(result)
                    if d == today:
                        result = [s for s in result if s > now_time]
                    return result

    try:
        result = _get_slots_evento_uncached(d, duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min)
    except Exception as e:
        logger.error(f"[CAL] Error fetching evento slots for {d}: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return []

    if not bypass_cache:
        evt_key = f"evt_{_slot_cache_key(d, duracion_min, presencia_cliente_min)}"
        with _slot_cache_lock:
            _slot_cache[evt_key] = (list(result), time.time())

    if d == today:
        result = [s for s in result if s > now_time]
    return result


def get_slots_disponibles_evento_range(
    days: List[date],
    duracion_min: int = 30,
    presencia_cliente_min: int = 30,
) -> dict:
    """
    Fetch and compute available slots for every date in `days` using a single
    batched Google Calendar API call for [min(days), max(days)].

    Populates the per-day 'evt_*' slot cache as a side-effect so that
    subsequent single-day get_slots_disponibles_evento() calls are cache hits.

    Returns dict[date, List[str]] with today-filter applied on today's value.
    Returns {} on any error or if `days` is empty.
    """
    if not days:
        return {}
    try:
        start = min(days)
        end = max(days)
        service = _get_service()
        events_by_day = _get_events_in_range(service, start, end)

        today = datetime.now(TZ).date()
        now_time = datetime.now(TZ).strftime("%H:%M")
        now_ts = time.time()

        result: dict = {}
        for d in days:
            key = d.isoformat()
            raw_ranges = EVENTO_DIAS.get(key, [])
            event_horario = [(r[0], r[1]) for r in raw_ranges] if raw_ranges else []
            if not event_horario:
                slots: List[str] = []
            else:
                slots = _compute_slots(
                    d, events_by_day.get(d, []), duracion_min, presencia_cliente_min,
                    event_horario=event_horario,
                )

            # Write unfiltered slots to evt_* cache
            evt_key = f"evt_{_slot_cache_key(d, duracion_min, presencia_cliente_min)}"
            with _slot_cache_lock:
                _slot_cache[evt_key] = (list(slots), now_ts)

            # Apply today-filter only to the returned value
            if d == today:
                result[d] = [s for s in slots if s > now_time]
            else:
                result[d] = list(slots)

        return result
    except Exception as e:
        logger.error(f"[CAL] Error in get_slots_disponibles_evento_range: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return {}


def slot_sigue_libre(d: date, hora: str, duracion_min: int = 30, presencia_cliente_min: int = 30) -> bool:
    """
    Re-check if a specific slot is still available.
    Always bypasses cache — called inside the booking lock for anti-race guarantee.
    """
    available = get_slots_disponibles(d, bypass_cache=True, duracion_min=duracion_min, presencia_cliente_min=presencia_cliente_min)
    return hora in available


def reservar_cita(d: date, hora: str, nombre: str, telefono: str, servicio: dict) -> tuple:
    """
    Atomic booking: acquire per-slot lock → re-validate → create.
    Prevents race conditions between concurrent booking attempts.

    Returns:
        (event_id, None)          — success
        (None, 'slot_taken')      — slot no longer available
        (None, 'error')           — Calendar API failure
    """
    lock = _get_slot_lock(d, hora)
    presencia = servicio['presencia_cliente_min']
    with lock:
        if not slot_sigue_libre(d, hora, duracion_min=servicio['duracion_min'], presencia_cliente_min=presencia):
            return None, 'slot_taken'
        event_id = crear_cita(d, hora, nombre, telefono, servicio=servicio)
        if not event_id:
            return None, 'error'
        return event_id, None


def crear_cita(d: date, hora: str, nombre: str, telefono: str, servicio: dict) -> Optional[str]:
    """
    Create appointment event in Google Calendar.
    Returns event ID on success, None on failure.
    """
    service = _get_service()
    start_dt = slot_to_datetime(d, hora)
    end_dt = start_dt + timedelta(minutes=servicio['duracion_min'])

    key = next((k for k, v in SERVICIOS.items() if v is servicio), "desconocido")

    description = (
        f"Nombre: {nombre}\n"
        f"Telefono: {telefono}\n"
        f"Servicio: {key}\n"
        f"Estado: confirmada\n"
        f"Recordatorio: no"
    )

    event = {
        'summary': f"{servicio['nombre']} - {nombre}",
        'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': TIMEZONE},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': TIMEZONE},
    }

    try:
        created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute(num_retries=2)
        logger.info(f"[CAL] Created appointment (confirmed): {nombre} {mask_phone(telefono)} {d} {hora} event_id={created['id']}")
        _invalidate_slot_cache(d)
        metrics.inc('bookings_created')
        _invalidate_citas_cache(telefono)
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
        _invalidate_citas_cache(parse_tel(desc))
        return True
    except Exception as e:
        logger.error(f"[CAL] Error confirming appointment {event_id}: {e}")
        return False


def cancelar_cita(event_id: str) -> bool:
    """Delete appointment event from Google Calendar."""
    service = _get_service()
    try:
        # Fetch the event to get its date for cache invalidation
        event = service.events().get(
            calendarId=GOOGLE_CALENDAR_ID,
            eventId=event_id
        ).execute(num_retries=2)
        start_str = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        try:
            event_date = datetime.fromisoformat(start_str).astimezone(TZ).date()
        except Exception:
            event_date = None

        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute(num_retries=2)
        logger.info(f"[CAL] Deleted appointment event_id={event_id}")
        metrics.inc('bookings_cancelled')
        if event_date:
            _invalidate_slot_cache(event_date)
        _invalidate_citas_cache(parse_tel(event.get('description', '') or ''))
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
    time_max = (now + timedelta(days=LOOKAHEAD_CITAS_MANUALES_DIAS)).isoformat()

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
        service_key, nombre_from_title = parse_servicio_from_title(title)
        nombre = parse_nombre(desc) or nombre_from_title or "Cliente"
        manual_events.append({
            'id': item['id'],
            'title': title,
            'nombre': nombre,
            'description': desc,
            'telefono': tel,
            'start': start_dt,
            'service_key': service_key,
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
        _invalidate_citas_cache(parse_tel(desc))
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
    window_start = now + timedelta(hours=RECORDATORIO_DESDE_H)
    window_end = now + timedelta(hours=RECORDATORIO_HASTA_H)

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
    Results are cached per phone for CITAS_CACHE_TTL_SEC seconds.
    """
    try:
        # Cache read
        now_ts = time.time()
        with _citas_cache_lock:
            if telefono in _citas_cache:
                cached, ts = _citas_cache[telefono]
                if now_ts - ts < CITAS_CACHE_TTL_SEC:
                    return list(cached)

        service = _get_service()
        now = datetime.now(TZ)
        time_max = (now + timedelta(days=LOOKAHEAD_CITAS_CLIENTE_DIAS)).isoformat()

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

        # Cache write
        with _citas_cache_lock:
            _citas_cache[telefono] = (list(citas), time.time())

        return citas
    except Exception as e:
        logger.error(f"[CAL] Error fetching citas for {mask_phone(telefono)}: {e}", exc_info=True)
        metrics.inc('calendar_errors')
        return []


def get_event_by_id(event_id: str, phone: str) -> Optional[dict]:
    """
    Fetch a single appointment event by ID and verify ownership.

    Security: returns None if the event's Telefono field does not match `phone`,
    making phone-mismatch indistinguishable from a missing event to the caller.

    Returns a dict with keys {id, title, description, start, end} matching the
    entries returned by get_citas_futuras, or None on any error / ownership failure.
    """
    try:
        service = _get_service()
        event = service.events().get(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute(num_retries=2)
    except Exception as e:
        logger.debug(f"[CAL] get_event_by_id not found or error event_id={event_id}: {e}")
        return None

    title = event.get('summary', '') or ''
    if parse_cfg(title):
        return None

    start_raw = event.get('start', {})
    if 'dateTime' not in start_raw:
        return None

    desc = event.get('description', '') or ''
    if parse_tel(desc) != phone:
        return None

    start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
    end_dt = datetime.fromisoformat(event.get('end', {})['dateTime']).astimezone(TZ)

    return {
        'id': event['id'],
        'title': title,
        'description': desc,
        'start': start_dt,
        'end': end_dt,
    }


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
