# services/calendar/queries.py
"""
Read-only Calendar queries: events for scheduler jobs and client-facing lookups.
These functions do not modify any Calendar event and have no side-effects on cache.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import pytz

from app.config import (
    GOOGLE_CALENDAR_ID, TIMEZONE,
    LOOKAHEAD_CITAS_CLIENTE_DIAS, LOOKAHEAD_CITAS_MANUALES_DIAS,
    RECORDATORIO_DESDE_H, RECORDATORIO_HASTA_H,
)
from app.utils import metrics
from app.utils.security import mask_phone
from app.utils.parser import (
    parse_nombre, parse_tel, parse_wa_id, parse_estado, parse_reminder,
    parse_cfg, parse_servicio_from_title,
)
from app.utils.slots import get_event_days

from .client import client
from .caches import citas_cache

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)


def _event_matches(desc: str, identifier: str, phone: Optional[str]) -> bool:
    wa_id = parse_wa_id(desc)
    tel   = parse_tel(desc)
    return (wa_id == identifier) or (phone is not None and tel == phone)


def get_eventos_manuales_sin_confirmar() -> List[dict]:
    """
    Return manual calendar events with Telefono: and Estado: pendiente.
    These are appointments created by the barber that need WhatsApp confirmation.
    Idempotent: once Estado is set to confirmada, they are skipped.
    """
    service = client.get_service()
    now = datetime.now(TZ)
    time_max = (now + timedelta(days=LOOKAHEAD_CITAS_MANUALES_DIAS)).isoformat()

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=now.isoformat(),
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
        fields='items(id,summary,description,start,end)',
    ).execute(num_retries=0)

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


def get_citas_para_recordatorio() -> List[dict]:
    """
    Return appointments in 23h-25h window with Recordatorio: no (or unset).
    Must have Telefono: and Estado: pendiente or confirmada.
    """
    service = client.get_service()
    now = datetime.now(TZ)
    window_start = now + timedelta(hours=RECORDATORIO_DESDE_H)
    window_end = now + timedelta(hours=RECORDATORIO_HASTA_H)

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=window_start.isoformat(),
        timeMax=window_end.isoformat(),
        singleEvents=True,
        orderBy='startTime',
        fields='items(id,summary,description,start,end)',
    ).execute(num_retries=0)

    reminders = []
    for item in result.get('items', []):
        desc = item.get('description', '') or ''
        title = item.get('summary', '') or ''

        if parse_cfg(title):
            continue

        tel = parse_tel(desc)
        wa_id = parse_wa_id(desc)
        contacto = tel or wa_id
        if not contacto:
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
            'contacto': contacto,
            'start': start_dt,
        })

    return reminders


def get_citas_futuras(identifier: str, phone: Optional[str] = None) -> list:
    """
    Return ALL future appointments for an identifier (BSUID or phone), ordered by date.
    Returns [] on Google Calendar API failure (graceful degradation).
    Results are cached per identifier for CITAS_CACHE_TTL_SEC seconds.
    """
    try:
        # Cache read
        cached = citas_cache.get(identifier)
        if cached is not None:
            return list(cached)

        service = client.get_service()
        now = datetime.now(TZ)
        lookahead_dias = LOOKAHEAD_CITAS_CLIENTE_DIAS
        event_days = get_event_days()
        if event_days:
            lookahead_dias = max(lookahead_dias, (event_days[-1] - now.date()).days + 1)
        time_max = (now + timedelta(days=lookahead_dias)).isoformat()

        result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime',
            fields='items(id,summary,description,start,end)',
        ).execute(num_retries=0)

        citas = []
        for item in result.get('items', []):
            desc = item.get('description', '') or ''
            title = item.get('summary', '') or ''

            if parse_cfg(title):
                continue

            if not _event_matches(desc, identifier, phone):
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
        citas_cache.set(identifier, list(citas))

        return citas
    except Exception as e:
        logger.error(
            f"[CAL] Error fetching citas for {mask_phone(identifier)}: {e}",
            exc_info=True,
        )
        metrics.inc('calendar_errors')
        return []


def get_event_by_id(event_id: str, identifier: str,
                    phone: Optional[str] = None) -> Optional[dict]:
    """
    Fetch a single appointment event by ID and verify ownership.

    Security: returns None if neither the WaId nor Telefono field matches,
    making identifier-mismatch indistinguishable from a missing event to the caller.

    Returns a dict with keys {id, title, description, start, end} matching the
    entries returned by get_citas_futuras, or None on any error / ownership failure.
    """
    try:
        service = client.get_service()
        event = service.events().get(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id,
            fields='id,summary,description,start,end',
        ).execute(num_retries=0)
    except Exception as e:
        logger.debug(
            f"[CAL] get_event_by_id not found or error event_id={event_id}: {e}"
        )
        return None

    title = event.get('summary', '') or ''
    if parse_cfg(title):
        return None

    start_raw = event.get('start', {})
    if 'dateTime' not in start_raw:
        return None

    desc = event.get('description', '') or ''
    if not _event_matches(desc, identifier, phone):
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
