# services/whatsapp.py
"""WhatsApp Cloud API integration."""
import logging
import time
import httpx
from app.config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN

logger = logging.getLogger(__name__)

_BASE_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
_HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

# Persistent client with connection pooling — reuses TCP connections across calls
_client = httpx.Client(timeout=10)

_MAX_RETRIES = 2
_RETRY_DELAY = 1.0


def _post(body: dict) -> bool:
    """
    Internal helper: POST to WhatsApp API.
    Retries up to _MAX_RETRIES times on 5xx/network errors.
    4xx errors (bad payload, auth) are not retried.
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = _client.post(_BASE_URL, json=body, headers=_HEADERS)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                logger.error(f"[WA] HTTP {e.response.status_code} → {e.response.text}")
                return False
            if attempt < _MAX_RETRIES:
                logger.warning(f"[WA] HTTP {e.response.status_code}, retry {attempt + 1}/{_MAX_RETRIES}")
                time.sleep(_RETRY_DELAY)
            else:
                logger.error(f"[WA] HTTP {e.response.status_code} → {e.response.text}")
                return False
        except Exception as e:
            if attempt < _MAX_RETRIES:
                logger.warning(f"[WA] Request error (retry {attempt + 1}/{_MAX_RETRIES}): {e}")
                time.sleep(_RETRY_DELAY)
            else:
                logger.error(f"[WA] Request error: {e}")
                return False
    return False


def send_text_message(to: str, text: str) -> bool:
    """Send a plain text WhatsApp message."""
    ok = _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    })
    if ok:
        logger.info(f"[WA] text → {to}: {text[:60]}")
    return ok


def send_interactive(to: str, payload: dict) -> bool:
    """
    Send an interactive message (buttons or list).
    payload: dict returned by utils/interactive.py builders.
    """
    ok = _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        **payload,
    })
    if ok:
        logger.info(f"[WA] interactive({payload.get('interactive', {}).get('type')}) → {to}")
    return ok


def send_template(to: str, template_name: str, lang: str, components: list) -> bool:
    """Send a template message (for proactive messages outside 24h window)."""
    ok = _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": components,
        },
    })
    if ok:
        logger.info(f"[WA] template({template_name}) → {to}")
    return ok
