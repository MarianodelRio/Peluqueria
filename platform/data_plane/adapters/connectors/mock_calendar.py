"""MockCalendarAdapter — configurable test double for CalendarConnector."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data_plane.connectors.categories.calendar import CalendarConnector
from data_plane.connectors.errors import PermanentConnectorError, TransientConnectorError


class MockCalendarAdapter(CalendarConnector):
    """
    Configurable mock for CalendarConnector.

    :param transient_failures: number of initial calls that raise TransientConnectorError
    :param permanent_failure: if True, every call raises PermanentConnectorError
    :param preset_slots: list of slot strings returned by list_slots
    :param preset_event_id: event ID string returned by create_event
    """

    def __init__(
        self,
        *,
        transient_failures: int = 0,
        permanent_failure: bool = False,
        preset_slots: list[str] | None = None,
        preset_event_id: str = "evt_mock",
        preset_available_days: list[dict] | None = None,
        preset_slots_for_day: list[dict] | None = None,
        preset_book_result: dict | None = None,
        preset_appointments: list[dict] | None = None,
    ) -> None:
        self._transient_failures = transient_failures
        self._permanent_failure = permanent_failure
        self._preset_slots = preset_slots
        self._preset_event_id = preset_event_id
        self.preset_available_days = preset_available_days
        self.preset_slots_for_day = preset_slots_for_day
        self.preset_book_result = preset_book_result
        self.preset_appointments = preset_appointments
        self.calls: list[dict[str, Any]] = []
        self._call_count = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_and_check(self, method_name: str, **kwargs: Any) -> None:
        self._call_count += 1
        self.calls.append({"method": method_name, **kwargs})
        if self._permanent_failure:
            raise PermanentConnectorError(
                f"[MOCK_CALENDAR] Permanent failure on {method_name}"
            )
        if self._call_count <= self._transient_failures:
            raise TransientConnectorError(
                f"[MOCK_CALENDAR] Transient failure #{self._call_count} on {method_name}"
            )

    # ------------------------------------------------------------------
    # CalendarConnector implementation
    # ------------------------------------------------------------------

    def list_slots(
        self,
        date: date = None,  # type: ignore[assignment]
        service_duration_min: int = 0,
        presence_min: int = 0,
        **kwargs: Any,
    ) -> list[str]:
        self._record_and_check(
            "list_slots",
            date=date,
            service_duration_min=service_duration_min,
            presence_min=presence_min,
            **kwargs,
        )
        return self._preset_slots or ["09:00", "10:00"]

    def create_event(
        self,
        slot_dt: datetime = None,  # type: ignore[assignment]
        contact_id: str = "",
        service_key: str = "",
        contact_name: str = "",
        duration_min: int = 30,
        **kwargs: Any,
    ) -> str:
        self._record_and_check(
            "create_event",
            slot_dt=slot_dt,
            contact_id=contact_id,
            service_key=service_key,
            contact_name=contact_name,
            duration_min=duration_min,
            **kwargs,
        )
        return self._preset_event_id

    def cancel_event(self, event_id: str = "", **kwargs: Any) -> None:  # type: ignore[override]
        self._record_and_check("cancel_event", event_id=event_id, **kwargs)

    def get_event(self, event_id: str = "", **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        self._record_and_check("get_event", event_id=event_id, **kwargs)
        return {"event_id": event_id, "status": "confirmed"}

    def list_for_range(
        self,
        start: datetime = None,  # type: ignore[assignment]
        end: datetime = None,  # type: ignore[assignment]
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self._record_and_check("list_for_range", start=start, end=end, **kwargs)
        return []

    def mark_reminder_sent(self, event_id: str = "", **kwargs: Any) -> None:
        self._record_and_check("mark_reminder_sent", event_id=event_id)

    def mark_manual_confirmed(self, event_id: str = "", **kwargs: Any) -> None:
        self._record_and_check("mark_manual_confirmed", event_id=event_id)

    def get_pending_manual_events(self, lookahead_days: int = 60, **kwargs: Any) -> list[dict]:
        self._record_and_check("get_pending_manual_events", lookahead_days=lookahead_days)
        return []

    def get_available_days(
        self,
        from_date: str = "",
        service_duration_min: int = 0,
        presence_min: int = 0,
        lookahead_days: int = 14,
        **kwargs: Any,
    ) -> list[dict]:
        self._record_and_check(
            "get_available_days",
            from_date=from_date,
            service_duration_min=service_duration_min,
            presence_min=presence_min,
            lookahead_days=lookahead_days,
        )
        return self.preset_available_days if self.preset_available_days is not None else []

    def get_slots_for_day(
        self,
        date_str: str = "",
        period: str = "all",
        service_duration_min: int = 0,
        presence_min: int = 0,
        **kwargs: Any,
    ) -> list[dict]:
        self._record_and_check(
            "get_slots_for_day",
            date_str=date_str,
            period=period,
            service_duration_min=service_duration_min,
            presence_min=presence_min,
        )
        return self.preset_slots_for_day if self.preset_slots_for_day is not None else []

    def book_appointment(
        self,
        slot: str = "",
        contact_id: str = "",
        service_key: str = "",
        contact_name: str = "",
        duration_min: int = 30,
        **kwargs: Any,
    ) -> dict:
        self._record_and_check(
            "book_appointment",
            slot=slot,
            contact_id=contact_id,
            service_key=service_key,
            contact_name=contact_name,
            duration_min=duration_min,
        )
        return self.preset_book_result if self.preset_book_result is not None else {
            "success": True,
            "event_id": "evt_mock_booked",
            "message": "Cita reservada",
        }

    def get_future_appointments(
        self,
        contact_id: str = "",
        **kwargs: Any,
    ) -> list[dict]:
        self._record_and_check("get_future_appointments", contact_id=contact_id)
        return self.preset_appointments if self.preset_appointments is not None else []
