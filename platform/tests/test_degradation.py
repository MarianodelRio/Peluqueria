"""Unit tests for data_plane.engine.degradation.degrade_output."""

from __future__ import annotations

from data_plane.engine.degradation import degrade_output
from data_plane.engine.outputs import (
    ButtonDef,
    ListRowDef,
    ListSectionDef,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendTextOutput,
)
from data_plane.ports.channel_adapter import ChannelCapabilities

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_CAPS = ChannelCapabilities(
    supports_interactive_buttons=True,
    supports_interactive_lists=True,
    max_buttons=3,
    max_list_rows=10,
)

_NO_INTERACTIVE_CAPS = ChannelCapabilities(
    supports_interactive_buttons=False,
    supports_interactive_lists=False,
    max_buttons=0,
    max_list_rows=0,
)


def _make_buttons_output(n: int) -> SendInteractiveButtonsOutput:
    return SendInteractiveButtonsOutput(
        body="Choose:",
        buttons=tuple(ButtonDef(id=f"btn_{i}", title=f"Button {i}") for i in range(1, n + 1)),
    )


def _make_list_output(*section_sizes: int) -> SendInteractiveListOutput:
    sections = tuple(
        ListSectionDef(
            title=f"Section {s}",
            rows=tuple(
                ListRowDef(id=f"row_{s}_{r}", title=f"Row {s}/{r}")
                for r in range(1, size + 1)
            ),
        )
        for s, size in enumerate(section_sizes, 1)
    )
    return SendInteractiveListOutput(
        body="Pick one:",
        button_label="Open list",
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_text_output_returned_unchanged() -> None:
    """SendTextOutput is identity regardless of caps."""
    output = SendTextOutput(text="Hello")
    result = degrade_output(output, _FULL_CAPS)
    assert result is output


def test_buttons_within_limit_returned_unchanged() -> None:
    """Buttons output within max_buttons on a supporting channel → unchanged."""
    output = _make_buttons_output(3)  # exactly at max_buttons=3
    result = degrade_output(output, _FULL_CAPS)
    assert result is output


def test_list_within_limit_returned_unchanged() -> None:
    """List output within max_list_rows on a supporting channel → unchanged."""
    output = _make_list_output(5, 4)  # total 9, max_list_rows=10
    result = degrade_output(output, _FULL_CAPS)
    assert result is output


def test_buttons_truncated_when_exceeds_max() -> None:
    """Buttons output with len > max_buttons → truncated to first max_buttons."""
    output = _make_buttons_output(5)
    caps = ChannelCapabilities(
        supports_interactive_buttons=True,
        supports_interactive_lists=True,
        max_buttons=3,
        max_list_rows=10,
    )
    result = degrade_output(output, caps)
    assert isinstance(result, SendInteractiveButtonsOutput)
    assert len(result.buttons) == 3
    assert result.buttons[0].id == "btn_1"
    assert result.buttons[2].id == "btn_3"
    assert result.body == output.body


def test_buttons_degraded_to_text_when_not_supported() -> None:
    """Buttons output on non-supporting channel → SendTextOutput with numbered titles."""
    output = _make_buttons_output(3)
    result = degrade_output(output, _NO_INTERACTIVE_CAPS)
    assert isinstance(result, SendTextOutput)
    lines = result.text.split("\n")
    assert lines[0] == output.body
    assert lines[1] == "1. Button 1"
    assert lines[2] == "2. Button 2"
    assert lines[3] == "3. Button 3"


def test_list_degraded_to_text_when_not_supported() -> None:
    """List output on non-supporting channel → SendTextOutput with numbered row titles."""
    output = _make_list_output(2, 2)
    result = degrade_output(output, _NO_INTERACTIVE_CAPS)
    assert isinstance(result, SendTextOutput)
    lines = result.text.split("\n")
    assert lines[0] == output.body
    assert lines[1] == "1. Row 1/1"
    assert lines[2] == "2. Row 1/2"
    assert lines[3] == "3. Row 2/1"
    assert lines[4] == "4. Row 2/2"


def test_list_truncated_when_total_rows_exceed_max() -> None:
    """List with total rows > max_list_rows truncated correctly across sections."""
    output = _make_list_output(4, 4, 4)  # 12 total rows
    caps = ChannelCapabilities(
        supports_interactive_buttons=True,
        supports_interactive_lists=True,
        max_buttons=3,
        max_list_rows=7,
    )
    result = degrade_output(output, caps)
    assert isinstance(result, SendInteractiveListOutput)
    total_rows = sum(len(s.rows) for s in result.sections)
    assert total_rows == 7
    # First section fully kept (4 rows), second section truncated to 3
    assert len(result.sections[0].rows) == 4
    assert len(result.sections[1].rows) == 3
    # Third section entirely dropped
    assert len(result.sections) == 2
    assert result.body == output.body
    assert result.button_label == output.button_label
