"""Domain model for internal messages — no framework imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    BUTTON_REPLY = "button_reply"
    LIST_REPLY = "list_reply"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    LOCATION = "location"
    REACTION = "reaction"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InternalMessage:
    tenant_id: str
    contact_id: str
    message_type: MessageType
    text: str | None
    payload: str | None
    timestamp: datetime
