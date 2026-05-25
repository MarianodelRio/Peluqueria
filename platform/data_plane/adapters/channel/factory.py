"""Channel factory — maps ChannelConfig to a concrete adapter + router pair."""

from __future__ import annotations

from fastapi import APIRouter

from data_plane.adapters.channel.http_dev import HttpDevChannelAdapter
from data_plane.adapters.channel.http_dev import make_router as make_http_dev_router
from data_plane.adapters.channel.whatsapp import WhatsAppAdapter
from data_plane.adapters.channel.whatsapp import make_router as make_whatsapp_router
from data_plane.config import ChannelConfig
from data_plane.ports.channel_adapter import ChannelAdapter


def channel_factory(
    channel_config: ChannelConfig, tenant_id: str
) -> tuple[ChannelAdapter, APIRouter]:
    """Return a (adapter, router) pair for the given channel configuration."""
    if channel_config.type == "whatsapp":
        wa_adapter = WhatsAppAdapter(
            tenant_id=tenant_id,
            phone_number_id=channel_config.phone_number_id or "",
            access_token=channel_config.access_token or "",
            app_secret=channel_config.app_secret or "",
            verify_token=channel_config.verify_token or "",
        )
        return wa_adapter, make_whatsapp_router(wa_adapter)

    if channel_config.type == "http_dev":
        dev_adapter = HttpDevChannelAdapter(tenant_id=tenant_id)
        return dev_adapter, make_http_dev_router(dev_adapter)

    raise ValueError(f"Unknown channel type: {channel_config.type!r}")
