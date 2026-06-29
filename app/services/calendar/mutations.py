# services/calendar/mutations.py
"""
Calendar event write operations: create, cancel, confirm, mark.
All functions invalidate relevant cache entries after modifying Calendar.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pytz

from app.config import GOOGLE_CALENDAR_ID, TIMEZONE, SERVICIOS
from app.utils import metrics
from app.utils.security import mask_phone
from app.utils.parser import parse_tel, set_field
from app.utils.slots import slot_to_datetime

from .client import client
from .caches import slot_cache, citas_cache

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)


def _invalidate_slot_cache(d: date) -> None:
    """Remove all cache entries for a given date (all durations),
    including evt_* keys."""
    date_str = d.isoformat()
    slot_cache.invalidate_matching(
        lambda k: k.startswith(date_str) or k.startswith(f"evt_{date_str}")
    )


def _invalidate_citas_cache(phone: Optional[str]) -> None:
    citas_cache.invalidate(phone)


def crear_cita(
    d: date, hora: str, nombre: str, telefono: str, servicio: dict,
) -> Optional[str]:
    """
    Create appointment event in Google Calendar.
    Returns event ID on success, None on failure.
    """
    svc = client.get_service()
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
        created = svc.events().insert(
            calendarId=GOOGLE_CALENDAR_ID, body=event
        ).execute(num_retries=0)
        logger.info(
            f"[CAL] Created appointment (confirmed): {nombre} {mask_phone(telefono)} "
            f"{d} {hora} event_id={created['id']}"
        )
        _invalidate_slot_cache(d)
        metrics.inc('bookings_created')
        _invalidate_citas_cache(telefono)
        return created['id']
    except Exception as e:
        logger.error(f"[CAL] Error creating appointment: {e}")
        return None


def confirmar_cita(event_id: str) -> bool:
    """Update appointment status to 'confirmada'."""
    svc = client.get_service()
    try:
        event = svc.events().get(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute(num_retries=0)
        desc = event.get('description', '') or ''
        desc = set_field(desc, 'Estado', 'confirmada')
        event['description'] = desc
        svc.events().update(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event
        ).execute(num_retries=0)
        logger.info(f"[CAL] Confirmed appointment event_id={event_id}")
        _invalidate_citas_cache(parse_tel(desc))
        return True
    except Exception as e:
        logger.error(f"[CAL] Error confirming appointment {event_id}: {e}")
        return False


def cancelar_cita(event_id: str) -> bool:
    """Delete appointment event from Google Calendar."""
    svc = client.get_service()
    try:
        event = svc.events().get(
            calendarId=GOOGLE_CALENDAR_ID,
            eventId=event_id
        ).execute(num_retries=0)
        start_raw = event.get('start', {})
        start_str = start_raw.get('dateTime') or start_raw.get('date')
        try:
            event_date = datetime.fromisoformat(start_str).astimezone(TZ).date()
        except Exception:
            event_date = None

        svc.events().delete(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute(num_retries=0)
        logger.info(f"[CAL] Deleted appointment event_id={event_id}")
        metrics.inc('bookings_cancelled')
        if event_date:
            _invalidate_slot_cache(event_date)
        _invalidate_citas_cache(parse_tel(event.get('description', '') or ''))
        return True
    except Exception as e:
        logger.error(f"[CAL] Error deleting appointment {event_id}: {e}")
        return False


def marcar_manual_confirmado(event_id: str) -> bool:
    """
    After sending WhatsApp confirmation for a manual appointment,
    update Estado: confirmada and ensure Recordatorio: no is set.
    """
    svc = client.get_service()
    try:
        event = svc.events().get(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute(num_retries=0)
        desc = event.get('description', '') or ''
        desc = set_field(desc, 'Estado', 'confirmada')
        desc = set_field(desc, 'Recordatorio', 'no')
        event['description'] = desc
        svc.events().update(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event
        ).execute(num_retries=0)
        logger.info(f"[CAL] Marked manual event confirmed: {event_id}")
        _invalidate_citas_cache(parse_tel(desc))
        return True
    except Exception as e:
        logger.error(f"[CAL] Error marking manual confirmed {event_id}: {e}")
        return False


def marcar_recordatorio_enviado(event_id: str) -> bool:
    """Mark event Recordatorio: sí after sending reminder."""
    svc = client.get_service()
    try:
        event = svc.events().get(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute(num_retries=0)
        desc = event.get('description', '') or ''
        desc = set_field(desc, 'Recordatorio', 'sí')
        event['description'] = desc
        svc.events().update(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event
        ).execute(num_retries=0)
        logger.info(f"[CAL] Marked reminder sent: {event_id}")
        return True
    except Exception as e:
        logger.error(f"[CAL] Error marking reminder {event_id}: {e}")
        return False
