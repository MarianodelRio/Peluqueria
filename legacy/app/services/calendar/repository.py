# services/calendar/repository.py
"""
Google Calendar event fetchers.
Thin wrappers around the API that return normalised dicts.
"""
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

import pytz

from app.config import GOOGLE_CALENDAR_ID, TIMEZONE
from .client import client, CalendarClient

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)


class EventsRepository:
    """Fetches raw Calendar events and normalises them into dicts."""

    def __init__(self, cal_client: CalendarClient):
        self._client = cal_client

    def list_for_day(self, d: date, service=None) -> List[dict]:
        """
        Fetch all events for a given day from Google Calendar.
        Returns list of dicts: {id, title, description, start, end, all_day}
        Uses the provided service object if given, else builds one via the client.
        """
        svc = service if service is not None else self._client.get_service()

        day_start = TZ.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
        day_end = TZ.localize(datetime(d.year, d.month, d.day, 23, 59, 59))

        result = svc.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            fields='items(id,summary,description,start,end)',
        ).execute(num_retries=2)

        events = []
        for item in result.get('items', []):
            start_raw = item.get('start', {})
            end_raw = item.get('end', {})

            # All-day events
            if 'date' in start_raw:
                events.append({
                    'id': item['id'],
                    'title': item.get('summary', ''),
                    'description': item.get('description', '') or '',
                    'start': day_start,
                    'end': day_end,
                    'all_day': True,
                })
                continue

            # Timed events
            start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
            end_dt = datetime.fromisoformat(end_raw['dateTime']).astimezone(TZ)
            events.append({
                'id': item['id'],
                'title': item.get('summary', ''),
                'description': item.get('description', '') or '',
                'start': start_dt,
                'end': end_dt,
                'all_day': False,
            })
        return events

    def list_for_range(self, start: date, end: date, service=None) -> dict:
        """
        Fetch all events for every date in [start, end] inclusive via a single API call.
        Returns dict[date, List[dict]] where each value uses the same format as list_for_day.
        Paginates automatically, capped at 5 pages to prevent runaway loops.
        The optional `service` parameter exists for the legacy _get_events_in_range shim.
        """
        svc = service if service is not None else self._client.get_service()

        range_start = TZ.localize(datetime(start.year, start.month, start.day, 0, 0, 0))
        range_end = TZ.localize(datetime(end.year, end.month, end.day, 23, 59, 59))

        # Initialise a bucket for every date in the range (days with no events get [])
        buckets: dict = {}
        current = start
        while current <= end:
            buckets[current] = []
            current += timedelta(days=1)

        page_token = None
        pages_fetched = 0
        max_pages = 5

        while pages_fetched < max_pages:
            kwargs = dict(
                calendarId=GOOGLE_CALENDAR_ID,
                timeMin=range_start.isoformat(),
                timeMax=range_end.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                fields='items(id,summary,description,start,end),nextPageToken',
            )
            if page_token:
                kwargs['pageToken'] = page_token

            result = svc.events().list(**kwargs).execute(num_retries=2)
            pages_fetched += 1

            for item in result.get('items', []):
                start_raw = item.get('start', {})
                end_raw = item.get('end', {})
                title = item.get('summary', '')
                description = item.get('description', '') or ''
                event_id = item['id']

                if 'date' in start_raw:
                    # All-day event — end.date is EXCLUSIVE, expand with while d < end_d
                    start_d = date.fromisoformat(start_raw['date'])
                    end_d = date.fromisoformat(end_raw['date'])
                    d = start_d
                    while d < end_d:
                        if d in buckets:
                            day_start = TZ.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
                            day_end = TZ.localize(datetime(d.year, d.month, d.day, 23, 59, 59))
                            buckets[d].append({
                                'id': event_id,
                                'title': title,
                                'description': description,
                                'start': day_start,
                                'end': day_end,
                                'all_day': True,
                            })
                        d += timedelta(days=1)
                else:
                    # Timed event — bucket by start date
                    start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(TZ)
                    end_dt = datetime.fromisoformat(end_raw['dateTime']).astimezone(TZ)
                    d = start_dt.date()
                    if d in buckets:
                        buckets[d].append({
                            'id': event_id,
                            'title': title,
                            'description': description,
                            'start': start_dt,
                            'end': end_dt,
                            'all_day': False,
                        })

            page_token = result.get('nextPageToken')
            if not page_token:
                break

        return buckets


# Module-level singleton
events_repo = EventsRepository(client)
