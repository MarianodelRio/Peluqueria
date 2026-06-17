"""
watchdog.py — Standalone health-check script for the Peluqueria bot.

Run every 60 minutes via cron. Performs five checks:
  1. Bot /health endpoint (bot_down, bot_degraded)
  2. RAM usage (ram_critical)
  3. Disk usage (disk_critical)
  4. Error spike in /metrics (errors_spike)
  5. Ngrok tunnel reachability (ngrok_down)

Sends a WhatsApp template alert (alerta_sistema) to the admin when any check
fails. Per-alert cooldowns are persisted in a JSON state file.

No imports from app/. Fully standalone.
"""

import json
import logging
import os
import time
from datetime import datetime

import httpx
import psutil
import yaml
from dotenv import load_dotenv

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────
_LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FMT)
logger = logging.getLogger(__name__)

# ── Constants with env overrides ───────────────────────────────────────────
BOT_URL = os.getenv("WATCHDOG_BOT_URL", "http://localhost:8000")
TEMPLATE_NAME = os.getenv("WATCHDOG_TEMPLATE_NAME", "alerta_sistema")
STATE_FILE = os.getenv("WATCHDOG_STATE_FILE", "/var/log/peluqueria/watchdog_state.json")
RAM_PCT_THRESHOLD = int(os.getenv("WATCHDOG_RAM_CRITICAL_PCT", "90"))
DISK_PCT_THRESHOLD = int(os.getenv("WATCHDOG_DISK_CRITICAL_PCT", "90"))
ERROR_SPIKE_THRESHOLD = int(os.getenv("WATCHDOG_ERROR_SPIKE_THRESHOLD", "3"))

COOLDOWN_STANDARD_SEC = 30 * 60       # 30 minutes
COOLDOWN_ERRORS_SEC = 2 * 60 * 60     # 2 hours
HEALTH_TIMEOUT_SEC = 5
NGROK_DOMAIN = os.getenv("NGROK_DOMAIN", "")


# ── State management ───────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "last_alerts": {
            k: 0 for k in [
                "bot_down", "bot_degraded", "ram_critical",
                "disk_critical", "errors_spike", "ngrok_down",
            ]
        },
        "prev_metrics": {"calendar_errors": 0, "whatsapp_errors": 0},
    }


def load_state() -> dict:
    """Read STATE_FILE; return default state on missing file or JSON decode error."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Ensure all expected keys exist (forward-compatibility)
        default = _default_state()
        for key in default["last_alerts"]:
            alerts = data.setdefault("last_alerts", {})
            alerts[key] = data.get("last_alerts", {}).get(key, 0)
        data.setdefault("prev_metrics", default["prev_metrics"])
        return data
    except FileNotFoundError:
        return _default_state()
    except json.JSONDecodeError:
        logger.warning("[WATCHDOG] State file corrupt — using defaults")
        return _default_state()
    except Exception as exc:
        logger.warning("[WATCHDOG] Could not read state file: %s — using defaults", exc)
        return _default_state()


def save_state(state: dict) -> None:
    """Atomic write: write to .tmp then os.replace to avoid partial writes."""
    tmp_path = STATE_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception as exc:
        logger.error("[WATCHDOG] Could not save state: %s", exc)


def is_in_cooldown(state: dict, key: str, cooldown_sec: int) -> bool:
    """Return True if the last alert for key was sent within cooldown_sec seconds."""
    last = state.get("last_alerts", {}).get(key, 0)
    return (time.time() - last) < cooldown_sec


# ── WhatsApp alert ─────────────────────────────────────────────────────────

def send_alert(
        phone_number_id: str, token: str, admin_phone: str,
        label: str, detail: str) -> bool:
    """
    Send a WhatsApp template alert (alerta_sistema) to admin_phone.
    Returns True on HTTP 200/201. Never raises — catches all exceptions.
    """
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    url = f"https://graph.facebook.com/v23.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": admin_phone,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": "es_ES"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": label},
                        {"type": "text", "text": timestamp},
                        {"type": "text", "text": detail},
                    ],
                }
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in (200, 201):
            return True
        logger.error(
            "[WATCHDOG] Alert HTTP %s: %s", response.status_code, response.text[:200]
        )
        return False
    except Exception as exc:
        logger.error("[WATCHDOG] Exception sending alert: %s", exc)
        return False


# ── Main check logic ───────────────────────────────────────────────────────

def run_checks() -> None:
    # 1. Read credentials
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    admin_phone = os.getenv("ADMIN_PHONE", "")

    if not admin_phone:
        # Fall back to config.yaml
        config_yaml_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.yaml"
        )
        try:
            with open(config_yaml_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            admin_phone = (cfg or {}).get("negocio", {}).get("admin_phone", "") or ""
        except Exception as exc:
            logger.warning(
                "[WATCHDOG] Could not read config.yaml"
                " for admin_phone: %s",
                exc,
            )

    if not admin_phone:
        logger.warning(
            "[WATCHDOG] ADMIN_PHONE not set"
            " — checks will run but no alerts will be sent"
        )

    # 2. Load state
    state = load_state()

    # 3. Collect alerts: list of (key, cooldown_sec, label, detail)
    alerts_fired: list = []

    # Check 1 — Bot health
    try:
        resp = httpx.get(f"{BOT_URL}/health", timeout=HEALTH_TIMEOUT_SEC)
        # /health returns 503 when calendar is degraded — still parse the body
        # before raising so we can emit bot_degraded instead of bot_down.
        try:
            health = resp.json()
        except Exception:
            health = {}
        if health.get("calendar") == "error":
            alerts_fired.append((
                "bot_degraded",
                COOLDOWN_STANDARD_SEC,
                "CALENDAR CAIDO",
                "calendar: error en /health",
            ))
        else:
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        alerts_fired.append(("bot_down", COOLDOWN_STANDARD_SEC, "BOT CAIDO", str(exc)))
    except Exception as exc:
        alerts_fired.append(("bot_down", COOLDOWN_STANDARD_SEC, "BOT CAIDO", str(exc)))

    # Check 2 — RAM
    mem = psutil.virtual_memory()
    if mem.percent >= RAM_PCT_THRESHOLD:
        used_mb = mem.used // 1024 // 1024
        total_mb = mem.total // 1024 // 1024
        alerts_fired.append((
            "ram_critical",
            COOLDOWN_STANDARD_SEC,
            f"RAM CRITICA {int(mem.percent)}%",
            f"{used_mb} MB / {total_mb} MB",
        ))

    # Check 3 — Disk
    disk = psutil.disk_usage("/")
    if disk.percent >= DISK_PCT_THRESHOLD:
        used_gb = disk.used // 1024 // 1024 // 1024
        total_gb = disk.total // 1024 // 1024 // 1024
        alerts_fired.append((
            "disk_critical",
            COOLDOWN_STANDARD_SEC,
            f"DISCO CRITICO {int(disk.percent)}%",
            f"{used_gb} GB / {total_gb} GB",
        ))

    # Check 4 — Error spike (only when bot is reachable)
    bot_is_down = any(key == "bot_down" for key, _, _, _ in alerts_fired)
    if not bot_is_down:
        try:
            metrics_resp = httpx.get(f"{BOT_URL}/metrics", timeout=HEALTH_TIMEOUT_SEC)
            current_metrics = metrics_resp.json()
            cal_current = current_metrics.get("calendar_errors", 0)
            wa_current = current_metrics.get("whatsapp_errors", 0)
            cal_prev = state["prev_metrics"].get("calendar_errors", 0)
            wa_prev = state["prev_metrics"].get("whatsapp_errors", 0)
            cal_delta = cal_current - cal_prev
            wa_delta = wa_current - wa_prev
            if cal_delta >= ERROR_SPIKE_THRESHOLD or wa_delta >= ERROR_SPIKE_THRESHOLD:
                alerts_fired.append((
                    "errors_spike",
                    COOLDOWN_ERRORS_SEC,
                    "ERRORES ACUMULADOS",
                    f"calendar_errors +{cal_delta}, whatsapp_errors +{wa_delta}",
                ))
            # Update prev_metrics only on successful fetch
            state["prev_metrics"]["calendar_errors"] = cal_current
            state["prev_metrics"]["whatsapp_errors"] = wa_current
        except Exception as exc:
            logger.warning("[WATCHDOG] Could not fetch /metrics: %s", exc)
            # Do NOT update prev_metrics on failure

    # Check 5 — ngrok tunnel (only when bot is reachable and NGROK_DOMAIN is set)
    if not bot_is_down and NGROK_DOMAIN:
        try:
            r = httpx.get(
                f"https://{NGROK_DOMAIN}/health",
                timeout=HEALTH_TIMEOUT_SEC,
            )
            r.raise_for_status()
        except Exception as exc:
            alerts_fired.append((
                "ngrok_down", COOLDOWN_STANDARD_SEC,
                "NGROK CAIDO", str(exc),
            ))

    # 4. Process fired alerts
    for key, cooldown_sec, label, detail in alerts_fired:
        if is_in_cooldown(state, key, cooldown_sec):
            logger.info("[WATCHDOG] Cooldown activo para %s, omitiendo alerta", key)
            continue
        if not admin_phone:
            logger.warning("[WATCHDOG] ADMIN_PHONE vacio, no se envia alerta %s", key)
            continue
        ok = send_alert(phone_number_id, token, admin_phone, label, detail)
        if ok:
            state["last_alerts"][key] = time.time()
            logger.info("[WATCHDOG] Alerta enviada: %s", key)
        else:
            logger.error(
                "[WATCHDOG] Error enviando alerta %s"
                " — cooldown no marcado",
                key,
            )

    # 5. All-OK message
    if not alerts_fired:
        print("[WATCHDOG] All checks OK")

    # 6. Persist state
    save_state(state)


if __name__ == "__main__":
    run_checks()
