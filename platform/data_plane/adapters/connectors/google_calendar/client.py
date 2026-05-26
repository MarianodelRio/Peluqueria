from __future__ import annotations

import threading

import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarClient:
    def __init__(self, credentials_path: str, timeout_sec: int = 30) -> None:
        self._credentials_path = credentials_path
        self._timeout_sec = timeout_sec
        self._local = threading.local()

    def _build_credentials(self):
        return service_account.Credentials.from_service_account_file(
            self._credentials_path, scopes=SCOPES
        )

    def service(self):
        if not hasattr(self._local, "service"):
            creds = self._build_credentials()
            http = google_auth_httplib2.AuthorizedHttp(
                creds, http=httplib2.Http(timeout=self._timeout_sec)
            )
            self._local.service = build(
                "calendar", "v3", http=http, cache_discovery=False
            )
        return self._local.service
