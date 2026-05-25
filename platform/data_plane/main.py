import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from starlette.responses import PlainTextResponse

from data_plane.adapters.channel.whatsapp import WhatsAppAdapter
from data_plane.adapters.connectors.mock import MockConnector
from data_plane.adapters.state_store.in_memory import InMemoryStateStore
from data_plane.engine.bot import Bot
from data_plane.engine.degradation import degrade_output
from data_plane.engine.flow import load_flow
from data_plane.ports.channel_adapter import ChannelAdapter

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    tenant_id = os.environ["TENANT_ID"]
    phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    access_token = os.environ["WHATSAPP_ACCESS_TOKEN"]
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    verify_token = os.environ["WHATSAPP_VERIFY_TOKEN"]
    flow_path = os.environ["FLOW_PATH"]

    flow = load_flow(Path(flow_path).read_text())
    state_store = InMemoryStateStore()
    connector = MockConnector()
    bot = Bot(flow=flow, state_store=state_store, connector=connector)

    adapter = WhatsAppAdapter(
        tenant_id=tenant_id,
        phone_number_id=phone_number_id,
        access_token=access_token,
        app_secret=app_secret,
        verify_token=verify_token,
    )

    app.state.bot = bot
    app.state.adapter = adapter
    yield
    adapter.close()


app = FastAPI(lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/webhook/whatsapp")
def whatsapp_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    adapter: WhatsAppAdapter = request.app.state.adapter
    if mode == "subscribe" and token == adapter.verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    body_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    adapter: WhatsAppAdapter = request.app.state.adapter
    if not adapter.verify_signature(body_bytes, signature):
        raise HTTPException(status_code=401)
    raw_payload = json.loads(body_bytes)
    background_tasks.add_task(
        _process_message, raw_payload, request.app.state.adapter, request.app.state.bot
    )
    return {"status": "ok"}


def _process_message(raw_payload: dict, adapter: ChannelAdapter, bot: Bot) -> None:
    try:
        message = adapter.receive(raw_payload)
        if message is None:
            return
        outputs = bot.handle_message(message)
        for output in outputs:
            degraded = degrade_output(output, adapter.capabilities)
            adapter.send(message.contact_id, degraded)
    except Exception:
        log.exception("[WEBHOOK] Unhandled error in background message processing")
