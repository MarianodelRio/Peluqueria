import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from data_plane.adapters.channel.factory import channel_factory
from data_plane.adapters.connectors.mock import MockConnector
from data_plane.adapters.state_store.in_memory import InMemoryStateStore
from data_plane.config import load_tenant_config
from data_plane.engine.bot import Bot
from data_plane.engine.flow import load_flow

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        config = load_tenant_config(os.environ["TENANT_CONFIG_PATH"])
        adapter, router = channel_factory(config.channel, config.tenant_id)
        app.include_router(router)

        flow = load_flow(Path(config.flow_path).read_text())
        state_store = InMemoryStateStore()

        calendar_type = config.connectors.calendar.type
        if calendar_type == "mock":
            connector = MockConnector()
        else:
            raise ValueError(f"[MAIN] Unsupported calendar connector type: {calendar_type!r}")

        bot = Bot(flow=flow, state_store=state_store, connector=connector)
        app.state.adapter = adapter
        app.state.bot = bot
        yield
        adapter.close()

    _app = FastAPI(lifespan=_lifespan)

    @_app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return _app


app = create_app()
