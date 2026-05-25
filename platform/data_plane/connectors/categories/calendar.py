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
