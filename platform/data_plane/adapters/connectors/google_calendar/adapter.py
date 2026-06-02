from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from data_plane.connectors.categories.calendar import CalendarConnector

from . import engine, mutations, queries
from .client import CalendarClient
from .parser import get_field, strip_html
from .repository import EventsRepository

# ---------------------------------------------------------------------------
# Spanish date constants
# ---------------------------------------------------------------------------

_ES_WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
_ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


class GoogleCalendarAdapter(CalendarConnector):
    # Per-slot threading locks (shared across all instances, keyed by calendar_id:slot)
    _slot_locks: ClassVar[dict[str, threading.Lock]] = {}
    _slot_locks_mutex: ClassVar[threading.Lock] = threading.Lock()

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
        self._calendar_id = calendar_id
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lock_for_slot(self, slot_key: str) -> threading.Lock:
        """Retrieve or create a lock keyed by calendar_id:slot_key."""
        full_key = f"{self._calendar_id}:{slot_key}"
        with self._slot_locks_mutex:
            if full_key not in self._slot_locks:
                self._slot_locks[full_key] = threading.Lock()
            return self._slot_locks[full_key]

    # ------------------------------------------------------------------
    # Existing CalendarConnector methods
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # New flow-facing methods
    # ------------------------------------------------------------------

    def get_available_days(
        self,
        from_date: str,
        service_duration_min: int,
        presence_min: int,
        lookahead_days: int,
    ) -> list[dict]:
        """Return days with >=1 available slot. Each dict: {id: 'day_YYYY-MM-DD', title: '...'}."""
        service_duration_min = int(service_duration_min)
        presence_min = int(presence_min)
        lookahead_days = int(lookahead_days)

        tz = ZoneInfo(self._timezone)
        start_date = date.fromisoformat(from_date)
        end_date = start_date + timedelta(days=lookahead_days)

        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=tz)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 0, 0, 0, tzinfo=tz)

        all_events = self._repo.list_for_range(start_dt, end_dt)

        # Partition events by date
        events_by_date: dict[date, list[dict]] = {}
        for event in all_events:
            start_info = event.get("start", {})
            if "dateTime" in start_info:
                ev_dt = datetime.fromisoformat(start_info["dateTime"])
                ev_date = ev_dt.date()
            elif "date" in start_info:
                ev_date = date.fromisoformat(start_info["date"])
            else:
                continue
            events_by_date.setdefault(ev_date, []).append(event)

        result: list[dict] = []
        current = start_date
        while current < end_date:
            day_events = events_by_date.get(current, [])
            slots = engine.compute_slots(
                current,
                day_events,
                self._schedule,
                self._timezone,
                self._slot_duration_min,
                service_duration_min,
                presence_min,
            )
            if slots:
                result.append({
                    "id": f"day_{current.isoformat()}",
                    "title": (
                        f"{_ES_WEEKDAYS[current.weekday()]}"
                        f" {current.day}"
                        f" {_ES_MONTHS[current.month - 1]}"
                    ),
                })
            current += timedelta(days=1)

        return result

    def get_slots_for_day(
        self,
        date_str: str,
        period: str,
        service_duration_min: int,
        presence_min: int,
    ) -> list[dict]:
        """Return available slots for a day/period. Each dict: {id: 'hour_YYYY-MM-DD_HHMM', ...}."""
        service_duration_min = int(service_duration_min)
        presence_min = int(presence_min)

        d = date.fromisoformat(date_str)
        events = self._repo.list_for_day(d)
        slots = engine.compute_slots(
            d,
            events,
            self._schedule,
            self._timezone,
            self._slot_duration_min,
            service_duration_min,
            presence_min,
        )

        result: list[dict] = []
        for slot_str in slots:
            hh, mm = slot_str.split(":")
            slot_hour = int(hh)
            if period == "morning" and slot_hour >= 14:
                continue
            if period == "afternoon" and slot_hour < 14:
                continue
            result.append({
                "id": f"hour_{date_str}_{hh}{mm}",
                "title": slot_str,
            })

        return result

    def book_appointment(
        self,
        slot: str,
        contact_id: str,
        service_key: str,
        contact_name: str,
        duration_min: int,
    ) -> dict:
        """Book a slot. Returns {success: bool, event_id: str|None, message: str}."""
        duration_min = int(duration_min)

        # Parse slot format: "YYYY-MM-DD_HHMM"
        date_part, time_part = slot.split("_", 1)
        hh = int(time_part[:2])
        mm = int(time_part[2:])
        d = date.fromisoformat(date_part)

        tz = ZoneInfo(self._timezone)
        slot_dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)

        lock = self._lock_for_slot(slot)
        lock.acquire()
        try:
            # Re-check availability under the lock
            events = self._repo.list_for_day(slot_dt.date())
            available_slots = engine.compute_slots(
                slot_dt.date(),
                events,
                self._schedule,
                self._timezone,
                self._slot_duration_min,
                duration_min,
                duration_min,
            )
            slot_time_str = f"{slot_dt.hour:02d}:{slot_dt.minute:02d}"
            if slot_time_str not in available_slots:
                return {
                    "success": False,
                    "event_id": None,
                    "message": "Ese horario ya no está disponible",
                }

            event_id = mutations.create_event(
                self._repo,
                slot_dt,
                contact_id,
                service_key,
                contact_name,
                duration_min,
                self._timezone,
            )
            message = (
                f"Cita reservada el {_ES_WEEKDAYS[slot_dt.weekday()].lower()} "
                f"{slot_dt.day} {_ES_MONTHS[slot_dt.month - 1]} "
                f"a las {slot_dt.hour:02d}:{slot_dt.minute:02d}"
            )
            return {"success": True, "event_id": event_id, "message": message}
        finally:
            lock.release()

    def get_future_appointments(
        self,
        contact_id: str,
    ) -> list[dict]:
        """Return future appointments for a contact. Each dict: {id: 'cancel_appt_{eid}', ...}."""
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz=tz)
        end = now + timedelta(days=30)

        events = self._repo.list_for_range(now, end)

        result: list[dict] = []
        for event in events:
            desc_raw = event.get("description", "")
            desc = strip_html(desc_raw)
            telefono = get_field(desc, "Telefono")
            if telefono != contact_id:
                continue

            event_id = event.get("id", "")
            service_name = get_field(desc, "Servicio") or ""

            start_info = event.get("start", {})
            if "dateTime" not in start_info:
                continue
            start = datetime.fromisoformat(start_info["dateTime"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)

            title = (
                f"{_ES_WEEKDAYS[start.weekday()]} {start.day} {_ES_MONTHS[start.month - 1]}"
                f" · {start.hour:02d}:{start.minute:02d}"
                f" · {service_name}"
            )
            result.append({"id": f"cancel_appt_{event_id}", "title": title})

        return result
