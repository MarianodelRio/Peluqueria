"""CalendarConnector ABC — defines the boundary for calendar operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any


class CalendarConnector(ABC):
    """Abstract base class for calendar connector implementations."""

    @abstractmethod
    def list_slots(
        self,
        date: date,
        service_duration_min: int,
        presence_min: int,
    ) -> list[str]:
        """Return available time slots for the given date and service."""

    @abstractmethod
    def create_event(
        self,
        slot_dt: datetime,
        contact_id: str,
        service_key: str,
        contact_name: str,
        duration_min: int,
    ) -> str:
        """Create a calendar event and return the event ID."""

    @abstractmethod
    def cancel_event(self, event_id: str) -> None:
        """Cancel an existing calendar event."""

    @abstractmethod
    def get_event(self, event_id: str) -> dict[str, Any]:
        """Retrieve details of a calendar event."""

    @abstractmethod
    def list_for_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """List all events in the given datetime range."""

    @abstractmethod
    def mark_reminder_sent(self, event_id: str) -> None:
        """Mark a calendar event as having had its reminder sent."""

    @abstractmethod
    def mark_manual_confirmed(self, event_id: str) -> None:
        """Mark a calendar event as manually confirmed by staff."""

    @abstractmethod
    def get_pending_manual_events(self, lookahead_days: int) -> list[dict[str, Any]]:
        """Return events pending manual confirmation within the next lookahead_days days."""

    @abstractmethod
    def get_available_days(
        self,
        from_date: str,
        service_duration_min: int,
        presence_min: int,
        lookahead_days: int,
    ) -> list[dict]:
        """Return days with ≥1 available slot. Each dict: {id: "day_YYYY-MM-DD", title: "..."}."""

    @abstractmethod
    def get_slots_for_day(
        self,
        date_str: str,
        period: str,
        service_duration_min: int,
        presence_min: int,
    ) -> list[dict]:
        """Return available slots for a day/period. Each dict: {id: "hour_YYYY-MM-DD_HHMM", ...}."""

    @abstractmethod
    def book_appointment(
        self,
        slot: str,
        contact_id: str,
        service_key: str,
        contact_name: str,
        duration_min: int,
    ) -> dict:
        """Book a slot. Returns {success: bool, event_id: str|None, message: str}."""

    @abstractmethod
    def get_future_appointments(
        self,
        contact_id: str,
    ) -> list[dict]:
        """Return future appointments for a contact. Each dict: {id: "cancel_appt_{eid}", ...}."""
