"""Flow interpreter — pure domain logic, no I/O, no framework imports."""

from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Any

from shared.domain.conversation import ConversationState
from shared.domain.messages import InternalMessage

from .flow import ActionDef, Flow, TransitionDef
from .outputs import (
    ButtonDef,
    ListRowDef,
    ListSectionDef,
    OptionDef,
    Output,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendOptionsOutput,
    SendTextOutput,
)

if TYPE_CHECKING:
    from data_plane.ports.connector import ConnectorPort

MAX_TRANSITION_DEPTH = 10

_TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")


class DataProxy:
    """Wraps a dict; attribute access returns None for missing keys, DataProxy for nested dicts."""

    def __init__(self, data: dict) -> None:
        object.__setattr__(self, "_data", data)

    def __getattr__(self, key: str) -> Any:
        data = object.__getattribute__(self, "_data")
        val = data.get(key)
        if isinstance(val, dict):
            return DataProxy(val)
        return val


def _resolve(template: str, message: InternalMessage, data: dict[str, Any]) -> str:
    """Replace {{message.text}}, {{data.key}}, {{data.a.b.c}} etc. in a template string."""

    def replacer(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        parts = expr.split(".")
        if not parts:
            return match.group(0)
        namespace = parts[0]
        if namespace == "message" and len(parts) >= 2:
            # Single-level message attribute
            return str(getattr(message, parts[1], "") or "")
        if namespace == "data" and len(parts) >= 2:
            # Navigate potentially nested path
            current: Any = data
            for segment in parts[1:]:
                if isinstance(current, dict):
                    current = current.get(segment)
                else:
                    current = None
                if current is None:
                    return ""
            return str(current) if current is not None else ""
        return match.group(0)

    return _TEMPLATE_RE.sub(replacer, template)


def _resolve_params(
    params: dict[str, Any], message: InternalMessage, data: dict[str, Any]
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for k, v in params.items():
        resolved[k] = _resolve(str(v), message, data) if isinstance(v, str) else v
    return resolved


def _transition_matches(
    transition: TransitionDef, message: InternalMessage, data: dict[str, Any]
) -> bool:
    # Determine payload match
    if transition.on_payload_prefix is not None:
        payload_match = (
            message.payload is not None
            and message.payload.startswith(transition.on_payload_prefix)
        )
    elif transition.on_payload is not None:
        payload_match = message.payload == transition.on_payload
    elif transition.on_type is not None:
        payload_match = message.message_type.value == transition.on_type
    else:
        return False

    if not payload_match:
        return False

    # Evaluate optional condition
    if transition.condition is not None:
        try:
            result = eval(  # noqa: S307
                transition.condition,
                {"__builtins__": {}},
                {"data": DataProxy(data)},
            )
        except Exception:
            return False
        if not result:
            return False

    return True


def _run_on_enter(
    actions: tuple[ActionDef, ...],
    state: ConversationState,
    message: InternalMessage,
    connector: "ConnectorPort",
) -> list[Output]:
    outputs: list[Output] = []
    for action in actions:
        if action.action == "send_text":
            text = _resolve(action.text or "", message, state.data)
            outputs.append(SendTextOutput(text=text))

        elif action.action == "send_interactive_buttons":
            body = _resolve(action.body or "", message, state.data)
            buttons = tuple(
                ButtonDef(id=b["id"], title=b["title"]) for b in action.buttons
            )
            outputs.append(SendInteractiveButtonsOutput(body=body, buttons=buttons))

        elif action.action == "send_interactive_list":
            body = _resolve(action.body or "", message, state.data)
            button_label = _resolve(action.button_label or "", message, state.data)
            sections = tuple(
                ListSectionDef(
                    title=s.get("title", ""),
                    rows=tuple(
                        ListRowDef(
                            id=r["id"],
                            title=r["title"],
                            description=r.get("description", ""),
                        )
                        for r in s.get("rows", [])
                    ),
                )
                for s in action.sections
            )
            outputs.append(
                SendInteractiveListOutput(
                    body=body,
                    button_label=button_label,
                    sections=sections,
                )
            )

        elif action.action == "send_dynamic_options":
            items = state.data.get(action.source_key or "", []) if action.source_key else []
            if items:
                options_tuple = tuple(
                    OptionDef(id=item["id"], title=item["title"]) for item in items
                )
                outputs.append(
                    SendOptionsOutput(
                        body=action.text or "",
                        button_label=action.button_label or "Seleccionar",
                        options=options_tuple,
                    )
                )
            elif action.empty_text:
                outputs.append(SendTextOutput(text=action.empty_text))

        elif action.action == "invoke_connector":
            params = _resolve_params(action.params, message, state.data)
            result = connector.invoke(
                connector=action.connector or "",
                operation=action.operation or "",
                params=params,
            )
            # Unwrap {"items": [...]} registry normalization for list-returning connectors
            if action.result_key and isinstance(result, dict) and list(result.keys()) == ["items"]:
                state.data[action.result_key] = result["items"]
            elif action.result_key:
                state.data[action.result_key] = result

    return outputs


class FlowInterpreter:
    """Pure stateless interpreter: process(message, state) → (new_state, outputs)."""

    def __init__(self, flow: Flow) -> None:
        self._flow = flow

    def process(
        self,
        message: InternalMessage,
        state: ConversationState,
        connector: "ConnectorPort",
    ) -> tuple[ConversationState, list[Output]]:
        new_state = copy.deepcopy(state)
        flow = self._flow
        outputs: list[Output] = []

        depth = 0
        while True:
            if depth >= MAX_TRANSITION_DEPTH:
                raise RuntimeError(
                    f"MAX_TRANSITION_DEPTH ({MAX_TRANSITION_DEPTH}) exceeded"
                    f" — possible cycle in flow '{new_state.current_state}'"
                )

            matched_transition: TransitionDef | None = None

            # Check global transitions first
            for gt in flow.global_transitions:
                if _transition_matches(gt, message, new_state.data):
                    matched_transition = gt
                    break

            # Check state-level transitions
            if matched_transition is None:
                current_state_def = flow.states.get(new_state.current_state)
                if current_state_def:
                    for t in current_state_def.transitions:
                        if _transition_matches(t, message, new_state.data):
                            matched_transition = t
                            break

            if matched_transition is not None:
                # Apply set_data interpolations
                for key, template in matched_transition.set_data.items():
                    new_state.data[key] = _resolve(template, message, new_state.data)

                # Apply prefix extraction and optional service expansion
                if (
                    matched_transition.on_payload_prefix is not None
                    and matched_transition.extract_suffix_as is not None
                    and message.payload is not None
                ):
                    suffix = message.payload[len(matched_transition.on_payload_prefix):]
                    new_state.data[matched_transition.extract_suffix_as] = suffix
                    # Expand service properties if suffix matches a service key
                    service = flow.services.get(suffix)
                    if service is not None:
                        for prop_key, prop_val in service.items():
                            new_state.data[f"service_{prop_key}"] = prop_val

                new_state.current_state = matched_transition.target
                target_def = flow.states.get(new_state.current_state)
                if target_def:
                    outputs = _run_on_enter(
                        target_def.on_enter, new_state, message, connector
                    )
                else:
                    outputs = []
                depth += 1
                # One user message fires at most one transition; break here.
                # The depth counter + guard above protect against future
                # epsilon-transition loops if the schema ever supports them.
                break

            # No transition matched — stop the loop
            break

        # If at least one transition fired, return immediately (no fallback)
        if depth > 0:
            return new_state, outputs

        # No transition matched at all — apply fallback
        current_state_def = flow.states.get(new_state.current_state)
        if current_state_def is None:
            return new_state, outputs

        fallback_name = current_state_def.fallback
        if fallback_name is None:
            return new_state, outputs

        if fallback_name == new_state.current_state:
            # Same-state fallback: re-execute on_enter without changing state
            outputs = _run_on_enter(
                current_state_def.on_enter, new_state, message, connector
            )
            return new_state, outputs

        # Different-state fallback
        new_state.current_state = fallback_name
        fallback_def = flow.states.get(fallback_name)
        if fallback_def:
            outputs = _run_on_enter(
                fallback_def.on_enter, new_state, message, connector
            )
        else:
            outputs = []
        return new_state, outputs
