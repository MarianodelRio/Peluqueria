"""MockNotificationAdapter — configurable test double for NotificationConnector."""

from __future__ import annotations

from typing import Any

from data_plane.connectors.categories.notification import NotificationConnector
from data_plane.connectors.errors import PermanentConnectorError, TransientConnectorError


class MockNotificationAdapter(NotificationConnector):
    """
    Configurable mock for NotificationConnector.

    :param transient_failures: number of initial calls that raise TransientConnectorError
    :param permanent_failure: if True, every call raises PermanentConnectorError
    """

    def __init__(
        self,
        *,
        transient_failures: int = 0,
        permanent_failure: bool = False,
    ) -> None:
        self._transient_failures = transient_failures
        self._permanent_failure = permanent_failure
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
                f"[MOCK_NOTIFICATION] Permanent failure on {method_name}"
            )
        if self._call_count <= self._transient_failures:
            raise TransientConnectorError(
                f"[MOCK_NOTIFICATION] Transient failure #{self._call_count} on {method_name}"
            )

    # ------------------------------------------------------------------
    # NotificationConnector implementation
    # ------------------------------------------------------------------

    def send_text(
        self, contact_id: str = "", text: str = "", **kwargs: Any  # type: ignore[override]
    ) -> None:
        self._record_and_check("send_text", contact_id=contact_id, text=text, **kwargs)

    def send_template(
        self,
        contact_id: str = "",
        template_name: str = "",
        params: dict[str, str] = None,  # type: ignore[assignment]
        **kwargs: Any,
    ) -> None:
        self._record_and_check(
            "send_template",
            contact_id=contact_id,
            template_name=template_name,
            params=params or {},
            **kwargs,
        )

    def send_interactive_buttons(
        self,
        contact_id: str = "",
        body: str = "",
        buttons: list[dict[str, Any]] = None,  # type: ignore[assignment]
        **kwargs: Any,
    ) -> None:
        self._record_and_check(
            "send_interactive_buttons",
            contact_id=contact_id,
            body=body,
            buttons=buttons or [],
            **kwargs,
        )
