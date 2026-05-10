# config.py
import logging
import os
import re
import yaml
from datetime import date as _date
from dotenv import load_dotenv

load_dotenv()

# ── Day name → weekday index mapping (Monday=0 … Sunday=6) ────────────────
_DAY_NAMES = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _ranges_overlap(ranges: list) -> bool:
    """Return True if any two ranges in the list overlap."""
    # Convert HH:MM to minutes for comparison
    def to_min(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    parsed = [(to_min(r[0]), to_min(r[1])) for r in ranges]
    parsed.sort()
    for i in range(len(parsed) - 1):
        if parsed[i][1] > parsed[i + 1][0]:
            return True
    return False


def _load_and_validate_yaml(path: str) -> dict:
    """
    Load and validate the business config YAML.
    Raises RuntimeError with a descriptive message on any failure.
    Returns the validated dict on success.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
    except FileNotFoundError:
        raise RuntimeError(f"[CONFIG] Cannot load config.yaml: file not found at '{path}'")
    except yaml.YAMLError as exc:
        raise RuntimeError(f"[CONFIG] Cannot load config.yaml: invalid YAML — {exc}")
    except Exception as exc:
        raise RuntimeError(f"[CONFIG] Cannot load config.yaml: {exc}")

    if not isinstance(cfg, dict):
        raise RuntimeError("[CONFIG] config.yaml must be a YAML mapping at the top level")

    # Rule 2: negocio.nombre and negocio.telefono_contacto are non-empty strings
    negocio = cfg.get("negocio")
    if not isinstance(negocio, dict):
        raise RuntimeError("[CONFIG] Rule 2: 'negocio' must be a mapping")
    if not isinstance(negocio.get("nombre"), str) or not negocio["nombre"].strip():
        raise RuntimeError("[CONFIG] Rule 2: 'negocio.nombre' must be a non-empty string")
    if not isinstance(negocio.get("telefono_contacto"), str) or not negocio["telefono_contacto"].strip():
        raise RuntimeError("[CONFIG] Rule 2: 'negocio.telefono_contacto' must be a non-empty string")

    # Rule 3: horario keys, ranges, fin > inicio, no overlap, at least one day
    horario = cfg.get("horario")
    if not isinstance(horario, dict) or len(horario) == 0:
        raise RuntimeError("[CONFIG] Rule 3: 'horario' must be a non-empty mapping")
    for day_name, ranges in horario.items():
        if day_name not in _DAY_NAMES:
            raise RuntimeError(
                f"[CONFIG] Rule 3: invalid day name '{day_name}' in 'horario'. "
                f"Valid names: {list(_DAY_NAMES.keys())}"
            )
        if not isinstance(ranges, list) or len(ranges) == 0:
            raise RuntimeError(
                f"[CONFIG] Rule 3: 'horario.{day_name}' must be a non-empty list of ranges"
            )
        for rng in ranges:
            if not (isinstance(rng, list) and len(rng) == 2):
                raise RuntimeError(
                    f"[CONFIG] Rule 3: each range in 'horario.{day_name}' must be a 2-element list [inicio, fin]"
                )
            inicio, fin = rng
            if not (_TIME_RE.match(str(inicio)) and _TIME_RE.match(str(fin))):
                raise RuntimeError(
                    f"[CONFIG] Rule 3: range values in 'horario.{day_name}' must be 'HH:MM' strings"
                )
            if fin <= inicio:
                raise RuntimeError(
                    f"[CONFIG] Rule 3: 'horario.{day_name}' has range where fin ('{fin}') <= inicio ('{inicio}')"
                )
        if len(ranges) > 1 and _ranges_overlap(ranges):
            raise RuntimeError(
                f"[CONFIG] Rule 3: 'horario.{day_name}' has overlapping time ranges"
            )

    # Rule 4: ventana_busqueda_dias is int >= 1
    vbd = cfg.get("ventana_busqueda_dias")
    if not isinstance(vbd, int) or isinstance(vbd, bool) or vbd < 1:
        raise RuntimeError("[CONFIG] Rule 4: 'ventana_busqueda_dias' must be an integer >= 1")

    # Rule 5: servicios is non-empty dict; each entry valid; max 9
    servicios = cfg.get("servicios")
    if not isinstance(servicios, dict) or len(servicios) == 0:
        raise RuntimeError("[CONFIG] Rule 5: 'servicios' must be a non-empty mapping")
    if len(servicios) > 9:
        raise RuntimeError(
            f"[CONFIG] Rule 5: 'servicios' has {len(servicios)} entries; maximum is 9 "
            "(WhatsApp list row limit: 9 service rows + 1 navigation row = 10 total)"
        )
    for svc_key, svc in servicios.items():
        if not isinstance(svc, dict):
            raise RuntimeError(f"[CONFIG] Rule 5: 'servicios.{svc_key}' must be a mapping")
        if not isinstance(svc.get("nombre"), str) or not svc["nombre"].strip():
            raise RuntimeError(f"[CONFIG] Rule 5: 'servicios.{svc_key}.nombre' must be a non-empty string")
        precio = svc.get("precio")
        if not isinstance(precio, (int, float)) or isinstance(precio, bool) or precio < 0:
            raise RuntimeError(f"[CONFIG] Rule 5: 'servicios.{svc_key}.precio' must be a number >= 0")
        dur = svc.get("duracion_min")
        if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
            raise RuntimeError(f"[CONFIG] Rule 5: 'servicios.{svc_key}.duracion_min' must be an integer > 0")
        pres = svc.get("presencia_cliente_min")
        if not isinstance(pres, int) or isinstance(pres, bool) or pres < dur:
            raise RuntimeError(
                f"[CONFIG] Rule 5: 'servicios.{svc_key}.presencia_cliente_min' must be an integer >= duracion_min ({dur})"
            )

    # Rule 6: lookaheads_dias.citas_cliente and .citas_manuales are int >= 1
    lookaheads = cfg.get("lookaheads_dias")
    if not isinstance(lookaheads, dict):
        raise RuntimeError("[CONFIG] Rule 6: 'lookaheads_dias' must be a mapping")
    for field in ("citas_cliente", "citas_manuales"):
        val = lookaheads.get(field)
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            raise RuntimeError(
                f"[CONFIG] Rule 6: 'lookaheads_dias.{field}' must be an integer >= 1"
            )

    # Rule 7: recordatorio_horas_antes.desde >= 1 and hasta > desde
    rah = cfg.get("recordatorio_horas_antes")
    if not isinstance(rah, dict):
        raise RuntimeError("[CONFIG] Rule 7: 'recordatorio_horas_antes' must be a mapping")
    desde = rah.get("desde")
    hasta = rah.get("hasta")
    if not isinstance(desde, int) or isinstance(desde, bool) or desde < 1:
        raise RuntimeError("[CONFIG] Rule 7: 'recordatorio_horas_antes.desde' must be an integer >= 1")
    if not isinstance(hasta, int) or isinstance(hasta, bool) or hasta <= desde:
        raise RuntimeError(
            f"[CONFIG] Rule 7: 'recordatorio_horas_antes.hasta' must be an integer > desde ({desde})"
        )

    # Rule 8: envios.recordatorios and envios.confirmaciones are exactly bool
    envios = cfg.get("envios")
    if not isinstance(envios, dict):
        raise RuntimeError("[CONFIG] Rule 8: 'envios' must be a mapping")
    for field in ("recordatorios", "confirmaciones"):
        if field not in envios:
            raise RuntimeError(f"[CONFIG] Rule 8: 'envios.{field}' is required")
        val = envios[field]
        if not isinstance(val, bool):
            raise RuntimeError(
                f"[CONFIG] Rule 8: 'envios.{field}' must be a boolean (true/false), got {type(val).__name__!r}"
            )

    # Rule 9: evento block (optional — absent or activo not True is always OK)
    _evento_block = cfg.get("evento")
    if isinstance(_evento_block, dict) and _evento_block.get("activo") is True:
        # Deep validation only when activo is exactly True
        _ev_nombre = _evento_block.get("nombre")
        if not isinstance(_ev_nombre, str) or not _ev_nombre.strip():
            raise RuntimeError("[CONFIG] Rule 9: 'evento.nombre' must be a non-empty string when activo is true")
        _ev_dias = _evento_block.get("dias")
        if not isinstance(_ev_dias, dict) or len(_ev_dias) == 0:
            raise RuntimeError("[CONFIG] Rule 9: 'evento.dias' must be a non-empty mapping when activo is true")
        for iso_key, ranges in _ev_dias.items():
            try:
                _date.fromisoformat(str(iso_key))
            except ValueError:
                raise RuntimeError(
                    f"[CONFIG] Rule 9: 'evento.dias' key '{iso_key}' is not a valid ISO date (YYYY-MM-DD)"
                )
            if not isinstance(ranges, list) or len(ranges) == 0:
                raise RuntimeError(
                    f"[CONFIG] Rule 9: 'evento.dias.{iso_key}' must be a non-empty list of ranges"
                )
            for rng in ranges:
                if not (isinstance(rng, list) and len(rng) == 2):
                    raise RuntimeError(
                        f"[CONFIG] Rule 9: each range in 'evento.dias.{iso_key}' must be a 2-element list [inicio, fin]"
                    )
                inicio, fin = rng
                if not (_TIME_RE.match(str(inicio)) and _TIME_RE.match(str(fin))):
                    raise RuntimeError(
                        f"[CONFIG] Rule 9: range values in 'evento.dias.{iso_key}' must be 'HH:MM' strings"
                    )
                if fin <= inicio:
                    raise RuntimeError(
                        f"[CONFIG] Rule 9: 'evento.dias.{iso_key}' has range where fin ('{fin}') <= inicio ('{inicio}')"
                    )
            if len(ranges) > 1 and _ranges_overlap(ranges):
                raise RuntimeError(
                    f"[CONFIG] Rule 9: 'evento.dias.{iso_key}' has overlapping time ranges"
                )
        if len(_ev_dias) > 9:
            logging.getLogger(__name__).warning(
                f"[CONFIG] Rule 9: 'evento.dias' has {len(_ev_dias)} dates; "
                "more than 9 may not display well in the WhatsApp day picker (max 9 rows)."
            )

    # Rule 10: negocio.admin_phone, if present, must be a string of 7-15 digits (no '+', no spaces)
    _admin_phone_raw = negocio.get("admin_phone")
    if _admin_phone_raw is not None:
        if not isinstance(_admin_phone_raw, str) or not re.fullmatch(r"\d{7,15}", _admin_phone_raw):
            raise RuntimeError(
                "[CONFIG] Rule 10: 'negocio.admin_phone' must be a string of 7-15 digits "
                "(no '+', no spaces, no dashes) — e.g. '34612345678'"
            )

    return cfg


# ── Load YAML config ───────────────────────────────────────────────────────
_CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")
_cfg = _load_and_validate_yaml(_CONFIG_PATH)

# ── Business constants from YAML ───────────────────────────────────────────
HORARIO_BASE = {
    _DAY_NAMES[k]: [tuple(r) for r in v]
    for k, v in _cfg["horario"].items()
}

SERVICIOS: dict = dict(_cfg["servicios"])

BOOKING_WINDOW_DAYS: int = _cfg["ventana_busqueda_dias"]

BUSINESS_NAME: str = _cfg["negocio"]["nombre"]
CONTACT_PHONE: str = _cfg["negocio"]["telefono_contacto"]

LOOKAHEAD_CITAS_CLIENTE_DIAS: int = _cfg["lookaheads_dias"]["citas_cliente"]
LOOKAHEAD_CITAS_MANUALES_DIAS: int = _cfg["lookaheads_dias"]["citas_manuales"]

RECORDATORIO_DESDE_H: int = _cfg["recordatorio_horas_antes"]["desde"]
RECORDATORIO_HASTA_H: int = _cfg["recordatorio_horas_antes"]["hasta"]

ENVIAR_RECORDATORIOS: bool = _cfg["envios"]["recordatorios"]
ENVIAR_CONFIRMACIONES: bool = _cfg["envios"]["confirmaciones"]

# ── Special event (optional) ───────────────────────────────────────────────
_evento_cfg = _cfg.get("evento") or {}
EVENTO_ACTIVO: bool = _evento_cfg.get("activo") is True
EVENTO_NOMBRE: str = _evento_cfg.get("nombre", "") if EVENTO_ACTIVO else ""
# EVENTO_DIAS: dict[str, list] — keys are ISO date strings e.g. "2026-12-20"
EVENTO_DIAS: dict = dict(_evento_cfg.get("dias") or {}) if EVENTO_ACTIVO else {}

# ── Admin command ─────────────────────────────────────────────────────────
# ADMIN_PHONE: digits-only WhatsApp number that may trigger admin commands.
# Empty string means admin commands are disabled.
ADMIN_PHONE: str = os.getenv("ADMIN_PHONE") or _cfg["negocio"].get("admin_phone") or ""
# The text command that triggers the status report (case-insensitive match).
ADMIN_COMANDO: str = "/estado"

# ── WhatsApp credentials ───────────────────────────────────────────────────
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN    = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_VERIFY_TOKEN    = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
# App Secret (Meta -> App Settings -> Basic -> App Secret).
# Used to verify X-Hub-Signature-256 on every incoming webhook POST.
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")

# ── Google Calendar ────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")

# ── Timezone ───────────────────────────────────────────────────────────────
TIMEZONE = "Europe/Madrid"

# ── Appointment settings ───────────────────────────────────────────────────
CITA_DURACION_MIN = 30
ESTADO_EXPIRACION_MIN = 30

# ── Scheduler intervals (minutes) ─────────────────────────────────────────
SYNC_MANUAL_INTERVAL_MIN = 60
RECORDATORIO_INTERVAL_MIN = 60
LIMPIAR_ESTADOS_INTERVAL_MIN = 10

# ── WhatsApp templates ─────────────────────────────────────────────────────
WHATSAPP_REMINDER_TEMPLATE = "recordatorio_cita"
WHATSAPP_CONFIRMATION_TEMPLATE = "confirmacion_cita"
WHATSAPP_TEMPLATE_LANG = "es"
INTERACTIVE_FOOTER = "_Cualquier texto te llevará de vuelta al menú principal_"

# ── HTTP / API timeouts ────────────────────────────────────────────────────
GOOGLE_API_TIMEOUT_SEC = 30
HTTP_TIMEOUT_SEC = 10

# ── Slot availability cache ────────────────────────────────────────────────
SLOT_CACHE_TTL_SEC = 30

# ── Per-phone appointments cache ───────────────────────────────────────────
CITAS_CACHE_TTL_SEC = 60

# ── Concurrency ────────────────────────────────────────────────────────────
MAX_CONCURRENT_HANDLERS = 40


def validate_config() -> None:
    """
    Validate required environment variables at startup.
    Raises RuntimeError if any critical variable is missing.
    Logs a warning if WHATSAPP_APP_SECRET is absent (HMAC verification disabled).
    YAML validation runs first at import time; this runs at lifespan startup.
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
