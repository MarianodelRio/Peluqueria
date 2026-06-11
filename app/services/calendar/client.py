# services/calendar/client.py
"""Google Calendar API client — thread-local service singleton."""
import logging
import threading

import httplib2
import google_auth_httplib2
from googleapiclient.discovery import build
from google.oauth2 import service_account

from app.config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_API_TIMEOUT_SEC,
    GOOGLE_CALENDAR_ID,
)

logger = logging.getLogger(__name__)

# calendar.events: full read/write on events only (no calendar metadata access).
# This is the minimum scope required for all operations in this service.
SCOPES = ['https://www.googleapis.com/auth/calendar.events']


class CalendarClient:
    """
    Wraps the Google Calendar API service with per-thread lazy construction.
    Thread-safe: each OS thread gets its own service instance via threading.local.
    """

    def __init__(self, credentials_path: str, timeout_sec: int, calendar_id: str):
        self._credentials_path = credentials_path
        self._timeout_sec = timeout_sec
        self._calendar_id = calendar_id
        self._thread_local = threading.local()

    @property
    def calendar_id(self) -> str:
        return self._calendar_id

    def get_service(self):
        """
        Return a cached Google Calendar service per thread.
        Avoids rebuilding credentials on every call while remaining thread-safe.
        The google-auth library handles token refresh transparently.
        """
        if not hasattr(self._thread_local, 'service'):
            creds = service_account.Credentials.from_service_account_file(
                self._credentials_path, scopes=SCOPES
            )
            authorized_http = google_auth_httplib2.AuthorizedHttp(
                creds, http=httplib2.Http(timeout=self._timeout_sec)
            )
            self._thread_local.service = build(
                'calendar', 'v3', http=authorized_http, cache_discovery=False
            )
        return self._thread_local.service

    def health_check(self) -> bool:
        """
        Verify Google Calendar connectivity by listing at most 1 event.
        Uses events().list() instead of calendars().get() so we only need
        the calendar.events scope (no calendar metadata access required).
        Returns True if the API responds successfully, False otherwise.
        """
        try:
            service = self.get_service()
            service.events().list(
                calendarId=self._calendar_id,
                maxResults=1,
                singleEvents=True,
                fields='items(id)',
            ).execute(num_retries=2)
            return True
        except Exception as e:
            logger.error(f"[CAL] Health check failed: {e}")
            return False

    def warmup(self) -> None:
        """Pre-build the thread-local service; log success or failure."""
        try:
            self.get_service()
            logger.info("[CAL] Calendar client warmed up successfully")
        except Exception as e:
            logger.warning(f"[CAL] Calendar client warmup failed: {e}")


# Module-level singleton
client = CalendarClient(
    GOOGLE_CREDENTIALS_PATH, GOOGLE_API_TIMEOUT_SEC, GOOGLE_CALENDAR_ID
)


def check_calendar_health() -> bool:
    """Module-level wrapper so existing imports keep working."""
    return client.health_check()
