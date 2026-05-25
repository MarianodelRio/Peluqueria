"""Shared message-processing helper for channel adapter handlers."""

from __future__ import annotations

import logging

from data_plane.engine.bot import Bot
from data_plane.engine.degradation import degrade_output
from data_plane.ports.channel_adapter import ChannelAdapter

log = logging.getLogger(__name__)


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
        log.exception("[PROCESS] Unhandled error in message processing")
