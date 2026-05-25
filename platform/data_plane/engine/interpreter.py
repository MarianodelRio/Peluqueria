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
    Output,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendTextOutput,
)

if TYPE_CHECKING:
    from data_plane.ports.connector import ConnectorPort

MAX_TRANSITION_DEPTH = 10

_TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")


def _resolve(template: str, message: InternalMessage, data: dict[str, Any]) -> str:
    """Replace {{message.text}}, {{data.key}} etc. in a template string."""

    def replacer(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        parts = expr.split(".", 1)
        if parts[0] == "message" and len(parts) == 2:
            return str(getattr(message, parts[1], "") or "")
        if parts[0] == "data" and len(parts) == 2:
            return str(data.get(parts[1], ""))
        return match.group(0)

    return _TEMPLATE_RE.sub(replacer, template)


def _resolve_params(
    params: dict[str, Any], message: InternalMessage, data: dict[str, Any]
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for k, v in params.items():
        resolved[k] = _resolve(str(v), message, data) if isinstance(v, str) else v
    return resolved


def _transition_matches(transition: TransitionDef, message: InternalMessage) -> bool:
    if transition.on_payload is not None:
        return message.payload == transition.on_payload
    if transition.on_type is not None:
        return message.message_type.value == transition.on_type
    return False


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

        elif action.action == "invoke_connector":
            params = _resolve_params(action.params, message, state.data)
            result = connector.invoke(
                connector=action.connector or "",
                operation=action.operation or "",
                params=params,
            )
            if action.result_key:
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
                if _transition_matches(gt, message):
                    matched_transition = gt
                    break

            # Check state-level transitions
            if matched_transition is None:
                current_state_def = flow.states.get(new_state.current_state)
                if current_state_def:
                    for t in current_state_def.transitions:
                        if _transition_matches(t, message):
                            matched_transition = t
                            break

            if matched_transition is not None:
                # Apply set_data interpolations
                for key, template in matched_transition.set_data.items():
                    new_state.data[key] = _resolve(template, message, new_state.data)

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
