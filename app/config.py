# config.py
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# WhatsApp
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN    = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_VERIFY_TOKEN    = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
# App Secret (Meta → App Settings → Basic → App Secret).
# Used to verify X-Hub-Signature-256 on every incoming webhook POST.
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")

# Google Calendar
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")

# Timezone
TIMEZONE = "Europe/Madrid"

# Schedule
HORARIO_BASE = {
    1: [("10:00", "14:00"), ("17:00", "21:00")],
    2: [("10:00", "14:00"), ("17:00", "21:00")],
    3: [("10:00", "14:00"), ("17:00", "21:00")],
    4: [("10:00", "14:00"), ("17:00", "21:00")],  # Friday
    5: [("10:00", "14:00")],                       # Saturday
}

# Services offered (key → display name, price in EUR, calendar event duration, client presence window)
SERVICIOS = {
    "corte":       {"nombre": "Corte de pelo",        "precio": 10,  "duracion_min": 30, "presencia_cliente_min": 30},
    "corte_barba": {"nombre": "Corte de pelo + barba", "precio": 12,  "duracion_min": 30, "presencia_cliente_min": 30},
    "mechas":      {"nombre": "Mechas",                "precio": 30,  "duracion_min": 60, "presencia_cliente_min": 180},
}

# Appointment settings
CITA_DURACION_MIN = 30
ESTADO_EXPIRACION_MIN = 30
BOOKING_WINDOW_DAYS = 14  # Calendar days to look ahead when offering available days

# Scheduler intervals (minutes)
SYNC_MANUAL_INTERVAL_MIN = 60
RECORDATORIO_INTERVAL_MIN = 60
LIMPIAR_ESTADOS_INTERVAL_MIN = 10


def validate_config() -> None:
    """
    Validate required environment variables at startup.
    Raises RuntimeError if any critical variable is missing.
    Logs a warning if WHATSAPP_APP_SECRET is absent (HMAC verification disabled).
    """
    _log = logging.getLogger(__name__)
    critical = {
        "WHATSAPP_PHONE_NUMBER_ID": WHATSAPP_PHONE_NUMBER_ID,
        "WHATSAPP_ACCESS_TOKEN":    WHATSAPP_ACCESS_TOKEN,
        "WHATSAPP_VERIFY_TOKEN":    WHATSAPP_VERIFY_TOKEN,
        "GOOGLE_CALENDAR_ID":       GOOGLE_CALENDAR_ID,
    }
    missing = [name for name, val in critical.items() if not val]
    if missing:
        raise RuntimeError(f"[CONFIG] Missing required env vars: {', '.join(missing)}")
    for svc_key, svc in SERVICIOS.items():
        if svc['duracion_min'] <= 0:
            raise RuntimeError(f"[CONFIG] SERVICIOS['{svc_key}']['duracion_min'] must be > 0")
        if svc['presencia_cliente_min'] <= 0:
            raise RuntimeError(f"[CONFIG] SERVICIOS['{svc_key}']['presencia_cliente_min'] must be > 0")
        if svc['presencia_cliente_min'] < svc['duracion_min']:
            raise RuntimeError(
                f"[CONFIG] SERVICIOS['{svc_key}']: presencia_cliente_min ({svc['presencia_cliente_min']}) "
                f"must be >= duracion_min ({svc['duracion_min']})"
            )
    if not WHATSAPP_APP_SECRET:
        _log.warning(
            "[CONFIG] WHATSAPP_APP_SECRET not set — "
            "webhook HMAC signature verification is DISABLED. "
            "Set it in .env for production."
        )


# WhatsApp templates
WHATSAPP_REMINDER_TEMPLATE = "recordatorio_cita"
WHATSAPP_CONFIRMATION_TEMPLATE = "confirmacion_cita"
WHATSAPP_TEMPLATE_LANG = "es"
INTERACTIVE_FOOTER = "_Cualquier texto te llevará de vuelta al menú principal_"
CONTACT_PHONE = "+34 676 27 38 00"

# HTTP / API timeouts
GOOGLE_API_TIMEOUT_SEC = 30
HTTP_TIMEOUT_SEC = 10

# Slot availability cache
SLOT_CACHE_TTL_SEC = 30

# Concurrency
MAX_CONCURRENT_HANDLERS = 40
