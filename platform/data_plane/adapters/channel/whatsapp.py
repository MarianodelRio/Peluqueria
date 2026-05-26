import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.responses import PlainTextResponse

from data_plane.engine.outputs import (
    ListRowDef,
    ListSectionDef,
    Output,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendOptionsOutput,
    SendTextOutput,
)
from data_plane.ports.channel_adapter import ChannelAdapter, ChannelCapabilities
from shared.domain.messages import InternalMessage, MessageType

log = logging.getLogger(__name__)

_WHATSAPP_CAPABILITIES = ChannelCapabilities(
    supports_interactive_buttons=True,
    supports_interactive_lists=True,
    max_buttons=3,
    max_list_rows=10,
)


class WhatsAppAdapter(ChannelAdapter):
    def __init__(
        self,
        tenant_id: str,
        phone_number_id: str,
        access_token: str,
        app_secret: str,
        verify_token: str,
    ) -> None:
        self._tenant_id = tenant_id
        self._phone_number_id = phone_number_id
        self._access_token = access_token
        self._app_secret = app_secret
        self.verify_token = verify_token
        self._client = httpx.Client()

    def receive(self, raw_payload: dict) -> InternalMessage | None:
        try:
            value = raw_payload["entry"][0]["changes"][0]["value"]
            messages = value.get("messages")
            if not messages:
                return None
            msg = messages[0]
            contact_id = msg["from"]
            timestamp = datetime.fromtimestamp(int(msg["timestamp"]), tz=timezone.utc)
            msg_type_str = msg["type"]

            if msg_type_str == "text":
                message_type = MessageType.TEXT
                text = msg["text"]["body"]
                payload = None
            elif msg_type_str == "interactive":
                interactive = msg["interactive"]
                itype = interactive["type"]
                if itype == "button_reply":
                    message_type = MessageType.BUTTON_REPLY
                    text = None
                    payload = interactive["button_reply"]["id"]
                elif itype == "list_reply":
                    message_type = MessageType.LIST_REPLY
                    text = None
                    payload = interactive["list_reply"]["id"]
                else:
                    message_type = MessageType.UNKNOWN
                    text = None
                    payload = None
            else:
                message_type = MessageType.UNKNOWN
                text = None
                payload = None

            return InternalMessage(
                tenant_id=self._tenant_id,
                contact_id=contact_id,
                message_type=message_type,
                text=text,
                payload=payload,
                timestamp=timestamp,
            )
        except (KeyError, IndexError, ValueError):
            return None

    def send(self, contact_id: str, output: Output) -> None:
        url = f"https://graph.facebook.com/v19.0/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        if isinstance(output, SendTextOutput):
            body = {
                "messaging_product": "whatsapp",
                "to": contact_id,
                "type": "text",
                "text": {"body": output.text, "preview_url": False},
            }
        elif isinstance(output, SendInteractiveButtonsOutput):
            body = {
                "messaging_product": "whatsapp",
                "to": contact_id,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": output.body},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b.id, "title": b.title}}
                            for b in output.buttons
                        ]
                    },
                },
            }
        elif isinstance(output, SendOptionsOutput):
            list_output = SendInteractiveListOutput(
                body=output.body,
                button_label=output.button_label,
                sections=(
                    ListSectionDef(
                        title="",
                        rows=tuple(
                            ListRowDef(id=opt.id, title=opt.title)
                            for opt in output.options
                        ),
                    ),
                ),
            )
            body = {
                "messaging_product": "whatsapp",
                "to": contact_id,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": list_output.body},
                    "action": {
                        "button": list_output.button_label,
                        "sections": [
                            {
                                "title": s.title,
                                "rows": [
                                    {
                                        "id": r.id,
                                        "title": r.title,
                                        "description": r.description,
                                    }
                                    for r in s.rows
                                ],
                            }
                            for s in list_output.sections
                        ],
                    },
                },
            }
        elif isinstance(output, SendInteractiveListOutput):
            body = {
                "messaging_product": "whatsapp",
                "to": contact_id,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": output.body},
                    "action": {
                        "button": output.button_label,
                        "sections": [
                            {
                                "title": s.title,
                                "rows": [
                                    {
                                        "id": r.id,
                                        "title": r.title,
                                        "description": r.description,
                                    }
                                    for r in s.rows
                                ],
                            }
                            for s in output.sections
                        ],
                    },
                },
            }
        else:
            log.error("WhatsAppAdapter.send: unknown output type %s", type(output))
            return

        try:
            response = self._client.post(url, json=body, headers=headers)
            if response.status_code >= 400:
                log.error(
                    "WhatsApp API error %s: %s", response.status_code, response.text
                )
        except Exception:
            log.exception("WhatsAppAdapter.send: HTTP request failed")

    def verify_signature(self, body: bytes, signature_header: str) -> bool:
        if not self._app_secret or not signature_header:
            return False
        expected = "sha256=" + hmac.new(
            self._app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    @property
    def capabilities(self) -> ChannelCapabilities:
        return _WHATSAPP_CAPABILITIES

    def close(self) -> None:
        self._client.close()


def make_router(adapter: WhatsAppAdapter) -> APIRouter:
    """Return an APIRouter with the two WhatsApp webhook handlers."""
    from data_plane._process import _process_message  # avoid circular at module load

    router = APIRouter()

    @router.get("/webhook/whatsapp")
    def whatsapp_verify(request: Request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and token == adapter.verify_token:
            return PlainTextResponse(challenge)
        raise HTTPException(status_code=403)

    @router.post("/webhook/whatsapp")
    async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
        body_bytes = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not adapter.verify_signature(body_bytes, signature):
            raise HTTPException(status_code=401)
        raw_payload = json.loads(body_bytes)
        background_tasks.add_task(
            _process_message, raw_payload, adapter, request.app.state.bot
        )
        return {"status": "ok"}

    return router
