from __future__ import annotations

from datetime import datetime, timedelta

from .parser import set_field, strip_html
from .repository import EventsRepository


def create_event(
    repo: EventsRepository,
    slot_dt: datetime,
    contact_id: str,
    service_key: str,
    contact_name: str,
    duration_min: int,
    timezone: str,
) -> str:
    end_dt = slot_dt + timedelta(minutes=duration_min)
    description = (
        f"Nombre: {contact_name}\n"
        f"Telefono: {contact_id}\n"
        f"Servicio: {service_key}\n"
        f"Estado: pendiente\n"
        f"Recordatorio: no"
    )
    body = {
        "summary": f"{service_key} - {contact_name}",
        "description": description,
        "start": {"dateTime": slot_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
    }
    created = repo.create_event(body)
    return created["id"]


def cancel_event(repo: EventsRepository, event_id: str) -> None:
    repo.delete_event(event_id)


def mark_reminder_sent(repo: EventsRepository, event_id: str) -> None:
    event = repo.get_event(event_id)
    desc = strip_html(event.get("description", ""))
    desc = set_field(desc, "Recordatorio", "sí")
    event["description"] = desc
    repo.update_event(event_id, event)


def mark_manual_confirmed(repo: EventsRepository, event_id: str) -> None:
    event = repo.get_event(event_id)
    desc = strip_html(event.get("description", ""))
    desc = set_field(desc, "Estado", "confirmada")
    desc = set_field(desc, "Recordatorio", "no")
    event["description"] = desc
    repo.update_event(event_id, event)
