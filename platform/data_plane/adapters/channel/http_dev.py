"""HTTP Dev Channel Adapter — in-process channel for local/testing use."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from data_plane.engine.outputs import (
    Output,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendOptionsOutput,
    SendTextOutput,
)
from data_plane.ports.channel_adapter import ChannelAdapter, ChannelCapabilities
from shared.domain.messages import InternalMessage, MessageType

log = logging.getLogger(__name__)

_HTTP_DEV_CAPABILITIES = ChannelCapabilities(
    supports_interactive_buttons=True,
    supports_interactive_lists=True,
    max_buttons=10,
    max_list_rows=20,
)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _output_to_dict(output: Output) -> dict[str, Any]:
    if isinstance(output, SendTextOutput):
        return {"type": "text", "text": output.text}
    if isinstance(output, SendInteractiveButtonsOutput):
        return {
            "type": "interactive_buttons",
            "body": output.body,
            "buttons": [{"id": b.id, "title": b.title} for b in output.buttons],
        }
    if isinstance(output, SendInteractiveListOutput):
        return {
            "type": "interactive_list",
            "body": output.body,
            "button_label": output.button_label,
            "sections": [
                {
                    "title": s.title,
                    "rows": [
                        {"id": r.id, "title": r.title, "description": r.description}
                        for r in s.rows
                    ],
                }
                for s in output.sections
            ],
        }
    if isinstance(output, SendOptionsOutput):
        return {
            "type": "options",
            "body": output.body,
            "button_label": output.button_label,
            "options": [{"id": opt.id, "title": opt.title} for opt in output.options],
        }
    log.error("[HTTP_DEV] Unknown output type: %s", type(output))
    return {"type": "unknown"}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class HttpDevChannelAdapter(ChannelAdapter):
    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id
        self._queue: deque[dict[str, Any]] = deque(maxlen=200)

    def receive(self, raw_payload: dict) -> InternalMessage | None:
        try:
            contact_id: str | None = raw_payload.get("contact_id")
            if not contact_id:
                return None

            msg_type_str: str = raw_payload.get("type", "text")

            if msg_type_str == "text":
                text = raw_payload.get("text")
                if text is None:
                    return None
                message_type = MessageType.TEXT
                payload = None
            elif msg_type_str == "button_reply":
                payload = raw_payload.get("payload")
                if payload is None:
                    return None
                message_type = MessageType.BUTTON_REPLY
                text = None
            elif msg_type_str == "list_reply":
                payload = raw_payload.get("payload")
                if payload is None:
                    return None
                message_type = MessageType.LIST_REPLY
                text = None
            else:
                message_type = MessageType.UNKNOWN
                text = raw_payload.get("text")
                payload = raw_payload.get("payload")

            return InternalMessage(
                tenant_id=self._tenant_id,
                contact_id=contact_id,
                message_type=message_type,
                text=text,
                payload=payload,
                timestamp=datetime.now(timezone.utc),
            )
        except Exception:
            log.exception("[HTTP_DEV] Error parsing inbound payload")
            return None

    def send(self, contact_id: str, output: Output) -> None:
        serialized = {
            "contact_id": contact_id,
            **_output_to_dict(output),
        }
        self._queue.append(serialized)

    def verify_signature(self, body: bytes, sig_header: str) -> bool:
        return True

    @property
    def capabilities(self) -> ChannelCapabilities:
        return _HTTP_DEV_CAPABILITIES

    def drain(self) -> list[dict[str, Any]]:
        """Pop and return all enqueued messages, clearing the queue."""
        items = list(self._queue)
        self._queue.clear()
        return items


# ---------------------------------------------------------------------------
# Pydantic request model
# ---------------------------------------------------------------------------


class InboundPayload(BaseModel):
    contact_id: str
    type: str = "text"
    text: str | None = None
    payload: str | None = None


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def make_router(adapter: HttpDevChannelAdapter) -> APIRouter:
    from data_plane._process import _process_message  # avoid circular at module load

    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def chat_ui() -> str:
        return (Path(__file__).resolve().parent / "chat_ui.html").read_text()

    @router.post("/inbound")
    def inbound(body: InboundPayload, request: Request) -> dict:
        raw = body.model_dump()
        _process_message(raw, adapter, request.app.state.bot)
        return {"status": "ok"}

    @router.get("/messages")
    def messages() -> dict:
        return {"messages": adapter.drain()}

    return router
