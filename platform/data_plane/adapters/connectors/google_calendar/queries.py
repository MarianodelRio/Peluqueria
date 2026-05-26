from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .parser import get_field, strip_html
from .repository import EventsRepository


def get_pending_manual_events(
    repo: EventsRepository,
    timezone: str,
    lookahead_days: int,
) -> list[dict]:
    tz = ZoneInfo(timezone)
    start = datetime.now(tz)
    end = start + timedelta(days=lookahead_days)
    events = repo.list_for_range(start, end)

    result = []
    for ev in events:
        raw_desc = ev.get("description") or ""
        desc = strip_html(raw_desc)
        telefono = get_field(desc, "Telefono")
        if telefono is None:
            continue
        estado = get_field(desc, "Estado") or "pendiente"
        if estado.lower() == "confirmada":
            continue
        result.append(
            {
                "event_id": ev["id"],
                "summary": ev.get("summary", ""),
                "start": ev.get("start", {}),
                "end": ev.get("end", {}),
                "telefono": telefono,
                "nombre": get_field(desc, "Nombre"),
                "servicio": get_field(desc, "Servicio"),
                "estado": estado,
                "recordatorio": get_field(desc, "Recordatorio"),
            }
        )
    return result
