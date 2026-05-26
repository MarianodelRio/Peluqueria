"""TenantConfig dataclass and YAML loader for data-plane boot-time configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ChannelConfig:
    type: str
    phone_number_id: str | None = None
    access_token: str | None = None
    app_secret: str | None = None
    verify_token: str | None = None


@dataclass
class CalendarConnectorConfig:
    type: str
    credentials_path: str | None = None
    calendar_id: str | None = None
    timezone: str = "Europe/Madrid"
    slot_duration_min: int = 30
    lookahead_days_client: int = 14
    lookahead_days_manual: int = 60
    schedule: dict[str, list[str]] | None = None


@dataclass
class ConnectorsConfig:
    calendar: CalendarConnectorConfig = field(
        default_factory=lambda: CalendarConnectorConfig(type="mock")
    )


@dataclass
class TenantConfig:
    tenant_id: str
    flow_path: str
    channel: ChannelConfig
    connectors: ConnectorsConfig = field(default_factory=ConnectorsConfig)


def load_tenant_config(path: str) -> TenantConfig:
    """Load TenantConfig from a YAML file.

    Relative ``flow_path`` values are resolved relative to the directory
    containing the YAML file.
    """
    yaml_path = Path(path)
    raw = yaml.safe_load(yaml_path.read_text())

    # Resolve flow_path relative to the YAML file's directory
    flow_path_raw: str = raw["flow_path"]
    if not Path(flow_path_raw).is_absolute():
        flow_path = str((yaml_path.parent / flow_path_raw).resolve())
    else:
        flow_path = flow_path_raw

    channel_raw: dict = raw["channel"]
    channel = ChannelConfig(
        type=channel_raw["type"],
        phone_number_id=channel_raw.get("phone_number_id"),
        access_token=channel_raw.get("access_token"),
        app_secret=channel_raw.get("app_secret"),
        verify_token=channel_raw.get("verify_token"),
    )

    connectors_raw: dict = raw.get("connectors", {})
    calendar_raw: dict = connectors_raw.get("calendar", {"type": "mock"})
    calendar = CalendarConnectorConfig(
        type=calendar_raw.get("type", "mock"),
        credentials_path=calendar_raw.get("credentials_path"),
        calendar_id=calendar_raw.get("calendar_id"),
        timezone=calendar_raw.get("timezone", "Europe/Madrid"),
        slot_duration_min=calendar_raw.get("slot_duration_min", 30),
        lookahead_days_client=calendar_raw.get("lookahead_days_client", 14),
        lookahead_days_manual=calendar_raw.get("lookahead_days_manual", 60),
        schedule=calendar_raw.get("schedule"),
    )
    connectors = ConnectorsConfig(calendar=calendar)

    return TenantConfig(
        tenant_id=raw["tenant_id"],
        flow_path=flow_path,
        channel=channel,
        connectors=connectors,
    )
