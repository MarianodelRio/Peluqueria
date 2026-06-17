# tests/stress/payloads.py
"""
Pre-built WhatsApp webhook payload builders for stress testing.
Each builder returns a full Meta webhook envelope matching the format
parsed by app/handlers/webhook.py.

Phone comes from msg["from"].
Interactive messages use msg["type"]="interactive" with
msg["interactive"]["type"] either "button_reply" or "list_reply".
"""
from datetime import date, timedelta
from uuid import uuid4

from app.config import SERVICIOS


def _stress_date() -> date:
    """Working day ~7 days out. Within the 14-day window, with buffer from today."""
    d = date.today() + timedelta(days=7)
    while d.weekday() == 6:   # skip Sunday only (Saturday is open)
        d += timedelta(days=1)
    return d


STRESS_DATE = _stress_date().isoformat()
STRESS_SLOT = "10:00"


def _wrap(phone: str, msg: dict) -> dict:
    """Wrap a single message dict in a full Meta webhook envelope."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [msg],
                            "contacts": [
                                {
                                    "wa_id": phone,
                                    "profile": {"name": "Stress Test"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def step_hola(phone: str) -> dict:
    """Send 'hola' text message — triggers menu display."""
    msg = {
        "from": phone,
        "id": str(uuid4()),
        "type": "text",
        "text": {"body": "hola"},
    }
    return _wrap(phone, msg)


def step_menu_book(phone: str) -> dict:
    """Tap 'Reservar cita' button from main menu."""
    msg = {
        "from": phone,
        "id": str(uuid4()),
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "menu_book", "title": "Reservar cita"},
        },
    }
    return _wrap(phone, msg)


def step_service_corte(phone: str) -> dict:
    """Select the first available service from the list."""
    key = next(iter(SERVICIOS))
    service_id = f"service_{key}"
    msg = {
        "from": phone,
        "id": str(uuid4()),
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {
                "id": service_id,
                "title": SERVICIOS[key].get("nombre", key),
            },
        },
    }
    return _wrap(phone, msg)


def step_select_day(phone: str) -> dict:
    """Select the stress-test date from the day picker."""
    day_id = f"day_{STRESS_DATE}"
    msg = {
        "from": phone,
        "id": str(uuid4()),
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {"id": day_id, "title": STRESS_DATE},
        },
    }
    return _wrap(phone, msg)


def step_select_hour(phone: str) -> dict:
    """Select the stress-test time slot from the hour picker."""
    # Format: hour_{YYYY-MM-DD}_{HHMM}  e.g. hour_2027-08-15_1000
    slot_compact = STRESS_SLOT.replace(":", "")
    hour_id = f"hour_{STRESS_DATE}_{slot_compact}"
    msg = {
        "from": phone,
        "id": str(uuid4()),
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {"id": hour_id, "title": STRESS_SLOT},
        },
    }
    return _wrap(phone, msg)


def step_enter_name(phone: str) -> dict:
    """Enter client name as a text message."""
    msg = {
        "from": phone,
        "id": str(uuid4()),
        "type": "text",
        "text": {"body": "Stress Test"},
    }
    return _wrap(phone, msg)
