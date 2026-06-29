# services/scheduler.py
"""
APScheduler background jobs.
"""
import logging
import time
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import (
    SYNC_MANUAL_INTERVAL_MIN,
    RECORDATORIO_INTERVAL_MIN,
    LIMPIAR_ESTADOS_INTERVAL_MIN,
    TIMEZONE,
    WHATSAPP_REMINDER_TEMPLATE,
    WHATSAPP_CONFIRMATION_TEMPLATE,
    WHATSAPP_TEMPLATE_LANG,
    ENVIAR_RECORDATORIOS,
    ENVIAR_CONFIRMACIONES,
)
from app.services import calendar as cal_service
from app.services import whatsapp as wa_service
from app.utils import metrics
from app.utils.security import mask_phone
from app.utils.slots import format_date_es
from app.handlers.conversation import clean_expired_states

logger = logging.getLogger(__name__)


def job_sync_citas_manuales():
    """
    Find manual calendar events with Telefono: and Estado: pendiente.
    Send confirmation and mark Estado: confirmada (idempotent).
    """
    t0 = time.time()
    logger.info("[JOB] START sync_citas_manuales")
    if not ENVIAR_CONFIRMACIONES:
        logger.info("[JOB] sync_citas_manuales disabled by config, skipping")
        return
    metrics.inc('scheduler_sync_manual_runs')
    try:
        events = cal_service.get_eventos_manuales_sin_confirmar()
        for ev in events:
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
                    "parameters": [
                        {"type": "payload", "payload": f"reminder_cancel_{event_id}"}
                    ],
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
                logger.info(
                    f"[JOB] Manual confirmation sent: {ev['id']} "
                    f"tel={mask_phone(ev['telefono'])}"
                )
            else:
                logger.warning(f"[JOB] Failed to send manual confirmation: {ev['id']}")
    except Exception as e:
        logger.error(f"[JOB] ERROR sync_citas_manuales: {e}", exc_info=True)
    finally:
        logger.info(f"[JOB] END sync_citas_manuales ({time.time() - t0:.1f}s)")


def job_enviar_recordatorios():
    """
    Find appointments in 23-25h window with Reminder24h: no.
    Send template reminder with confirm/cancel buttons.
    """
    t0 = time.time()
    logger.info("[JOB] START enviar_recordatorios")
    if not ENVIAR_RECORDATORIOS:
        logger.info("[JOB] enviar_recordatorios disabled by config, skipping")
        return
    metrics.inc('scheduler_recordatorios_runs')
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
                    "parameters": [
                        {"type": "payload", "payload": f"reminder_confirm_{event_id}"}
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [
                        {"type": "payload", "payload": f"reminder_cancel_{event_id}"}
                    ],
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
                logger.info(
                    f"[JOB] Reminder sent: {cita['id']} "
                    f"tel={mask_phone(cita['telefono'])}"
                )
            else:
                logger.warning(f"[JOB] Failed to send reminder: {cita['id']}")
    except Exception as e:
        logger.error(f"[JOB] ERROR enviar_recordatorios: {e}", exc_info=True)
    finally:
        logger.info(f"[JOB] END enviar_recordatorios ({time.time() - t0:.1f}s)")


def job_limpiar_estados_conversacion():
    """Remove expired conversation states (> 30 min inactive)."""
    t0 = time.time()
    logger.info("[JOB] START limpiar_estados_conversacion")
    metrics.inc('scheduler_limpiar_runs')
    try:
        clean_expired_states()
    except Exception as e:
        logger.error(f"[JOB] ERROR limpiar_estados_conversacion: {e}", exc_info=True)
    finally:
        logger.info(f"[JOB] END limpiar_estados_conversacion ({time.time() - t0:.1f}s)")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        executors={'default': ThreadPoolExecutor(20)},
        timezone=TIMEZONE,
    )

    _jobs = []
    if ENVIAR_CONFIRMACIONES:
        _jobs.append((job_sync_citas_manuales, SYNC_MANUAL_INTERVAL_MIN))
    else:
        logger.info("[SCHEDULER] job_sync_citas_manuales not registered (ENVIAR_CONFIRMACIONES=False)")
    if ENVIAR_RECORDATORIOS:
        _jobs.append((job_enviar_recordatorios, RECORDATORIO_INTERVAL_MIN))
    else:
        logger.info("[SCHEDULER] job_enviar_recordatorios not registered (ENVIAR_RECORDATORIOS=False)")
    _jobs.append((job_limpiar_estados_conversacion, LIMPIAR_ESTADOS_INTERVAL_MIN))

    for fn, interval in _jobs:
        scheduler.add_job(
            fn,
            trigger=IntervalTrigger(minutes=interval),
            id=fn.__name__,
            name=fn.__name__,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

    return scheduler
