from data_plane.engine.outputs import (
    ListSectionDef,
    Output,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendOptionsOutput,
    SendTextOutput,
)
from data_plane.ports.channel_adapter import ChannelCapabilities


def degrade_output(output: Output, caps: ChannelCapabilities) -> Output:
    if isinstance(output, SendInteractiveButtonsOutput):
        if not caps.supports_interactive_buttons:
            lines = [output.body]
            for i, btn in enumerate(output.buttons, 1):
                lines.append(f"{i}. {btn.title}")
            return SendTextOutput(text="\n".join(lines))
        if len(output.buttons) > caps.max_buttons:
            return SendInteractiveButtonsOutput(
                body=output.body,
                buttons=output.buttons[: caps.max_buttons],
            )

    if isinstance(output, SendInteractiveListOutput):
        if not caps.supports_interactive_lists:
            lines = [output.body]
            n = 1
            for section in output.sections:
                for row in section.rows:
                    lines.append(f"{n}. {row.title}")
                    n += 1
            return SendTextOutput(text="\n".join(lines))
        total = sum(len(s.rows) for s in output.sections)
        if total > caps.max_list_rows:
            remaining = caps.max_list_rows
            new_sections: list[ListSectionDef] = []
            for section in output.sections:
                if remaining <= 0:
                    break
                kept_rows = section.rows[:remaining]
                remaining -= len(kept_rows)
                new_sections.append(
                    ListSectionDef(title=section.title, rows=kept_rows)
                )
            return SendInteractiveListOutput(
                body=output.body,
                button_label=output.button_label,
                sections=tuple(new_sections),
            )

    if isinstance(output, SendOptionsOutput):
        if not caps.supports_interactive_lists:
            text = output.body + "\n" + "\n".join(
                f"{i + 1}. {opt.title}" for i, opt in enumerate(output.options)
            )
            return SendTextOutput(text=text)
        # Channel supports lists — pass through for the adapter to convert
        return output

    return output
