# services/scheduler.py
"""
APScheduler background jobs.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import (
    SYNC_MANUAL_INTERVAL_MIN,
    RECORDATORIO_INTERVAL_MIN,
    LIMPIAR_ESTADOS_INTERVAL_MIN,
    TIMEZONE,
    GOOGLE_CALENDAR_ID,
    WHATSAPP_REMINDER_TEMPLATE,
    WHATSAPP_CONFIRMATION_TEMPLATE,
    WHATSAPP_TEMPLATE_LANG,
)
from app.services import calendar as cal_service
from app.services.calendar import _get_service
from app.services import whatsapp as wa_service
from app.utils.parser import parse_estado
from app.utils.slots import format_date_es
from app.handlers.conversation import clean_expired_states

logger = logging.getLogger(__name__)


def job_sync_citas_manuales():
    """
    Find manual calendar events with Telefono: and Estado: pendiente.
    Send confirmation and mark Estado: confirmada (idempotent).
    """
    logger.info("[JOB] Running: sync_citas_manuales")
    try:
        events = cal_service.get_eventos_manuales_sin_confirmar()
        for ev in events:
            # Re-check idempotency against live data before sending
            service = _get_service()
            fresh = service.events().get(
                calendarId=GOOGLE_CALENDAR_ID,
                eventId=ev['id']
            ).execute()
            fresh_desc = fresh.get('description', '') or ''
            if parse_estado(fresh_desc) == 'confirmada':
                logger.info(f"[JOB] Manual event {ev['id']} already confirmed, skipping")
                continue

            nombre = ev['nombre']
            start_dt = ev['start']
            d = start_dt.date()
            hora = start_dt.strftime("%H:%M")
            event_id = ev['id']

            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": nombre},
                        {"type": "text", "text": format_date_es(d).capitalize()},
                        {"type": "text", "text": hora},
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": f"reminder_cancel_{event_id}"}],
                },
            ]

            sent = wa_service.send_template(
                ev['telefono'],
                WHATSAPP_CONFIRMATION_TEMPLATE,
                WHATSAPP_TEMPLATE_LANG,
                components,
            )
            if sent:
                cal_service.marcar_manual_confirmado(ev['id'])
                logger.info(f"[JOB] Manual confirmation sent: {ev['id']} tel={ev['telefono']}")
            else:
                logger.warning(f"[JOB] Failed to send manual confirmation: {ev['id']}")
    except Exception as e:
        logger.error(f"[JOB] Error in sync_citas_manuales: {e}")


def job_enviar_recordatorios():
    """
    Find appointments in 23-25h window with Reminder24h: no.
    Send template reminder with confirm/cancel buttons.
    """
    logger.info("[JOB] Running: enviar_recordatorios")
    try:
        citas = cal_service.get_citas_para_recordatorio()
        for cita in citas:
            start_dt = cita['start']
            d = start_dt.date()
            hora = start_dt.strftime("%H:%M")
            event_id = cita['id']

            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": format_date_es(d).capitalize()},
                        {"type": "text", "text": hora},
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": f"reminder_confirm_{event_id}"}],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [{"type": "payload", "payload": f"reminder_cancel_{event_id}"}],
                },
            ]

            sent = wa_service.send_template(
                cita['telefono'],
                WHATSAPP_REMINDER_TEMPLATE,
                WHATSAPP_TEMPLATE_LANG,
                components,
            )
            if sent:
                cal_service.marcar_recordatorio_enviado(cita['id'])
                logger.info(f"[JOB] Reminder sent: {cita['id']} tel={cita['telefono']}")
            else:
                logger.warning(f"[JOB] Failed to send reminder: {cita['id']}")
    except Exception as e:
        logger.error(f"[JOB] Error in enviar_recordatorios: {e}")


def job_limpiar_estados_conversacion():
    """Remove expired conversation states (> 30 min inactive)."""
    logger.info("[JOB] Running: limpiar_estados_conversacion")
    try:
        clean_expired_states()
    except Exception as e:
        logger.error(f"[JOB] Error in limpiar_estados_conversacion: {e}")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=TIMEZONE)

    _jobs = [
        (job_sync_citas_manuales,          SYNC_MANUAL_INTERVAL_MIN),
        (job_enviar_recordatorios,         RECORDATORIO_INTERVAL_MIN),
        (job_limpiar_estados_conversacion, LIMPIAR_ESTADOS_INTERVAL_MIN),
    ]
    for fn, interval in _jobs:
        scheduler.add_job(
            fn,
            trigger=IntervalTrigger(minutes=interval),
            id=fn.__name__,
            name=fn.__name__,
            max_instances=1,
            coalesce=True,
        )

    return scheduler
