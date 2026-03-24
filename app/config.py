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
    0: [("10:00", "14:00"), ("16:00", "20:00")],  # Monday
    1: [("10:00", "14:00"), ("16:00", "20:00")],
    2: [("10:00", "14:00"), ("16:00", "20:00")],
    3: [("10:00", "14:00"), ("16:00", "20:00")],
    4: [("10:00", "14:00"), ("16:00", "20:00")],  # Friday
    5: [("10:00", "14:00")],                       # Saturday
}

# Appointment settings
CITA_DURACION_MIN = 30
ESTADO_EXPIRACION_MIN = 30
BOOKING_WINDOW_DAYS = 7  # Calendar days to look ahead when offering available days

# Scheduler intervals (minutes)
SYNC_MANUAL_INTERVAL_MIN = 5
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

# HTTP / API timeouts
GOOGLE_API_TIMEOUT_SEC = 30
HTTP_TIMEOUT_SEC = 10

# Slot availability cache
SLOT_CACHE_TTL_SEC = 30

# Concurrency
MAX_CONCURRENT_HANDLERS = 20
