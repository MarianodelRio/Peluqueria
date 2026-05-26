from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from data_plane.connectors.errors import PermanentConnectorError, TransientConnectorError

from .client import CalendarClient


class EventsRepository:
    def __init__(self, client: CalendarClient, calendar_id: str, timezone: str) -> None:
        self._client = client
        self._calendar_id = calendar_id
        self._tz = ZoneInfo(timezone)

    def _svc(self):
        return self._client.service()

    def _handle_http_error(self, e: HttpError) -> NoReturn:
        code = e.resp.status
        if code >= 500:
            raise TransientConnectorError(f"Google Calendar API error {code}: {e}") from e
        raise PermanentConnectorError(f"Google Calendar API error {code}: {e}") from e

    def list_for_day(self, d: date) -> list[dict[str, Any]]:
        try:
            tz = self._tz
            start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
            end = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(days=1)
            result = (
                self._svc()
                .events()
                .list(
                    calendarId=self._calendar_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    fields="items(id,summary,description,start,end)",
                )
                .execute(num_retries=2)
            )
            return result.get("items", [])
        except HttpError as e:
            self._handle_http_error(e)

    def list_for_range(
        self, start: datetime, end: datetime, max_pages: int = 5
    ) -> list[dict[str, Any]]:
        try:
            items: list[dict] = []
            page_token = None
            for _ in range(max_pages):
                params = dict(
                    calendarId=self._calendar_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                if page_token:
                    params["pageToken"] = page_token
                result = self._svc().events().list(**params).execute(num_retries=2)
                items.extend(result.get("items", []))
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            return items
        except HttpError as e:
            self._handle_http_error(e)

    def get_event(self, event_id: str) -> dict[str, Any]:
        try:
            return (
                self._svc()
                .events()
                .get(calendarId=self._calendar_id, eventId=event_id)
                .execute(num_retries=2)
            )
        except HttpError as e:
            self._handle_http_error(e)

    def create_event(self, body: dict) -> dict[str, Any]:
        try:
            return (
                self._svc()
                .events()
                .insert(calendarId=self._calendar_id, body=body)
                .execute(num_retries=2)
            )
        except HttpError as e:
            self._handle_http_error(e)

    def update_event(self, event_id: str, body: dict) -> dict[str, Any]:
        try:
            return (
                self._svc()
                .events()
                .update(calendarId=self._calendar_id, eventId=event_id, body=body)
                .execute(num_retries=2)
            )
        except HttpError as e:
            self._handle_http_error(e)

    def delete_event(self, event_id: str) -> None:
        try:
            (
                self._svc()
                .events()
                .delete(calendarId=self._calendar_id, eventId=event_id)
                .execute(num_retries=2)
            )
        except HttpError as e:
            self._handle_http_error(e)
