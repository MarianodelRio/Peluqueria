from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data_plane.connectors.categories.calendar import CalendarConnector

from . import engine, mutations, queries
from .client import CalendarClient
from .parser import get_field, strip_html
from .repository import EventsRepository


class GoogleCalendarAdapter(CalendarConnector):
    def __init__(
        self,
        credentials_path: str,
        calendar_id: str,
        schedule: dict[str, list[str]],
        timezone: str = "Europe/Madrid",
        slot_duration_min: int = 30,
        lookahead_days_client: int = 14,
        lookahead_days_manual: int = 60,
        *,
        _repo: EventsRepository | None = None,
    ) -> None:
        self._schedule = schedule
        self._timezone = timezone
        self._slot_duration_min = slot_duration_min
        self._lookahead_days_client = lookahead_days_client
        self._lookahead_days_manual = lookahead_days_manual

        if _repo is not None:
            self._repo = _repo
        else:
            client = CalendarClient(credentials_path=credentials_path)
            self._repo = EventsRepository(client, calendar_id, timezone)

    def list_slots(
        self,
        date: date,
        service_duration_min: int,
        presence_min: int,
    ) -> list[str]:
        events = self._repo.list_for_day(date)
        return engine.compute_slots(
            date,
            events,
            self._schedule,
            self._timezone,
            self._slot_duration_min,
            service_duration_min,
            presence_min,
        )

    def create_event(
        self,
        slot_dt: datetime,
        contact_id: str,
        service_key: str,
        contact_name: str,
        duration_min: int,
    ) -> str:
        return mutations.create_event(
            self._repo,
            slot_dt,
            contact_id,
            service_key,
            contact_name,
            duration_min,
            self._timezone,
        )

    def cancel_event(self, event_id: str) -> None:
        mutations.cancel_event(self._repo, event_id)

    def get_event(self, event_id: str) -> dict[str, Any]:
        raw = self._repo.get_event(event_id)
        desc = strip_html(raw.get("description", ""))
        return {
            "event_id": raw["id"],
            "summary": raw.get("summary", ""),
            "start": raw.get("start", {}),
            "end": raw.get("end", {}),
            "telefono": get_field(desc, "Telefono"),
            "nombre": get_field(desc, "Nombre"),
            "servicio": get_field(desc, "Servicio"),
            "estado": get_field(desc, "Estado"),
            "recordatorio": get_field(desc, "Recordatorio"),
        }

    def list_for_range(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._repo.list_for_range(start, end)

    def mark_reminder_sent(self, event_id: str) -> None:
        mutations.mark_reminder_sent(self._repo, event_id)

    def mark_manual_confirmed(self, event_id: str) -> None:
        mutations.mark_manual_confirmed(self._repo, event_id)

    def get_pending_manual_events(self, lookahead_days: int) -> list[dict[str, Any]]:
        return queries.get_pending_manual_events(
            self._repo, self._timezone, lookahead_days
        )
