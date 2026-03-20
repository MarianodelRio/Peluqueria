# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# WhatsApp
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

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

# WhatsApp templates
WHATSAPP_REMINDER_TEMPLATE = "recordatorio_cita"
WHATSAPP_CONFIRMATION_TEMPLATE = "confirmacion_cita"
WHATSAPP_TEMPLATE_LANG = "es"
INTERACTIVE_FOOTER = "_Cualquier texto te llevará de vuelta al menú principal_"
