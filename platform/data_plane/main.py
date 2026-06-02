import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from data_plane.adapters.channel.factory import channel_factory
from data_plane.adapters.connectors.mock import MockConnector
from data_plane.adapters.connectors.mock_calendar import MockCalendarAdapter
from data_plane.adapters.state_store.sqlite import SQLiteStateStore
from data_plane.config import load_tenant_config
from data_plane.engine.bot import Bot
from data_plane.engine.flow import load_flow
from data_plane.ports.connector import ConnectorPort

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        config = load_tenant_config(os.environ["TENANT_CONFIG_PATH"])
        adapter, router = channel_factory(config.channel, config.tenant_id)
        app.include_router(router)

        flow = load_flow(Path(config.flow_path).read_text())
        state_store = SQLiteStateStore(db_path=os.environ.get("STATE_DB_PATH", "/data/state.db"))

        calendar_type = config.connectors.calendar.type
        connector: ConnectorPort
        if calendar_type == "mock":
            connector = MockConnector()
        elif calendar_type == "google_calendar":
            from data_plane.adapters.connectors.google_calendar.adapter import (
                GoogleCalendarAdapter,
            )
            from data_plane.connectors.registry import ConnectorRegistry

            cal_cfg = config.connectors.calendar
            if cal_cfg.credentials_path is None:
                raise ValueError(
                    "[MAIN] google_calendar connector requires 'credentials_path' in tenant config"
                )
            if cal_cfg.calendar_id is None:
                raise ValueError(
                    "[MAIN] google_calendar connector requires 'calendar_id' in tenant config"
                )
            google_adapter = GoogleCalendarAdapter(
                credentials_path=cal_cfg.credentials_path,
                calendar_id=cal_cfg.calendar_id,
                schedule=cal_cfg.schedule or {},
                timezone=cal_cfg.timezone,
                slot_duration_min=cal_cfg.slot_duration_min,
                lookahead_days_client=cal_cfg.lookahead_days_client,
                lookahead_days_manual=cal_cfg.lookahead_days_manual,
            )
            connector = ConnectorRegistry(
                config={"calendar": {"adapter": "google_calendar"}},
                adapter_factories={"google_calendar": lambda _creds: google_adapter},
            )
        elif calendar_type == "mock_calendar":
            from data_plane.connectors.registry import ConnectorRegistry

            mock_adapter = MockCalendarAdapter()
            connector = ConnectorRegistry(
                config={"calendar": {"adapter": "mock_calendar"}},
                adapter_factories={"mock_calendar": lambda _creds: mock_adapter},
            )
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
