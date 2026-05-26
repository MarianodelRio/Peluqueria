"""Flow definition dataclasses and YAML loader — no framework imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass(frozen=True)
class ActionDef:
    action: str
    # send_text
    text: str | None = None
    # send_interactive_buttons
    body: str | None = None
    buttons: tuple[dict[str, str], ...] = field(default_factory=tuple)
    # send_interactive_list
    button_label: str | None = None
    sections: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    # invoke_connector
    connector: str | None = None
    operation: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    result_key: str | None = None
    # send_dynamic_options
    source_key: str | None = None
    empty_text: str | None = None


@dataclass(frozen=True)
class TransitionDef:
    target: str
    on_payload: str | None = None
    on_type: str | None = None
    set_data: dict[str, str] = field(default_factory=dict)
    on_payload_prefix: str | None = None
    extract_suffix_as: str | None = None
    condition: str | None = None


@dataclass(frozen=True)
class StateDef:
    name: str
    on_enter: tuple[ActionDef, ...]
    transitions: tuple[TransitionDef, ...]
    fallback: str | None


@dataclass(frozen=True)
class Flow:
    id: str
    initial_state: str
    global_transitions: tuple[TransitionDef, ...]
    states: dict[str, StateDef]
    services: dict[str, dict[str, Any]] = field(default_factory=dict)


def _parse_action(raw: dict[str, Any]) -> ActionDef:
    buttons_raw = raw.get("buttons", [])
    sections_raw = raw.get("sections", [])
    params_raw = raw.get("params", {})
    return ActionDef(
        action=raw["action"],
        text=raw.get("text"),
        body=raw.get("body"),
        buttons=tuple(buttons_raw),
        button_label=raw.get("button_label"),
        sections=tuple(sections_raw),
        connector=raw.get("connector"),
        operation=raw.get("operation"),
        params=dict(params_raw) if params_raw else {},
        result_key=raw.get("result_key"),
        source_key=raw.get("source_key"),
        empty_text=raw.get("empty_text"),
    )


def _parse_transition(raw: dict[str, Any]) -> TransitionDef:
    set_data_raw = raw.get("set_data", {})
    return TransitionDef(
        target=raw["target"],
        on_payload=raw.get("on_payload"),
        on_type=raw.get("on_type"),
        set_data=dict(set_data_raw) if set_data_raw else {},
        on_payload_prefix=raw.get("on_payload_prefix"),
        extract_suffix_as=raw.get("extract_suffix_as"),
        condition=raw.get("condition"),
    )


def _parse_state(name: str, raw: dict[str, Any]) -> StateDef:
    on_enter_raw = raw.get("on_enter", [])
    transitions_raw = raw.get("transitions", [])
    return StateDef(
        name=name,
        on_enter=tuple(_parse_action(a) for a in on_enter_raw),
        transitions=tuple(_parse_transition(t) for t in transitions_raw),
        fallback=raw.get("fallback"),
    )


def load_flow(yaml_text: str) -> Flow:
    """Parse a YAML flow definition into a frozen Flow dataclass."""
    raw: dict[str, Any] = yaml.safe_load(yaml_text)

    global_transitions_raw = raw.get("global_transitions", [])
    states_raw = raw.get("states", {})
    services_raw = raw.get("services", {})

    return Flow(
        id=raw["id"],
        initial_state=raw["initial_state"],
        global_transitions=tuple(_parse_transition(t) for t in global_transitions_raw),
        states={name: _parse_state(name, state) for name, state in states_raw.items()},
        services=dict(services_raw) if services_raw else {},
    )
