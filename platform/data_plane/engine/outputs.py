"""Output types produced by the Bot Engine — no framework imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class SendTextOutput:
    text: str


@dataclass(frozen=True)
class ButtonDef:
    id: str
    title: str


@dataclass(frozen=True)
class SendInteractiveButtonsOutput:
    body: str
    buttons: tuple[ButtonDef, ...]


@dataclass(frozen=True)
class ListRowDef:
    id: str
    title: str
    description: str = ""


@dataclass(frozen=True)
class ListSectionDef:
    title: str
    rows: tuple[ListRowDef, ...]


@dataclass(frozen=True)
class SendInteractiveListOutput:
    body: str
    button_label: str
    sections: tuple[ListSectionDef, ...]


@dataclass(frozen=True)
class OptionDef:
    id: str
    title: str


@dataclass(frozen=True)
class SendOptionsOutput:
    body: str
    button_label: str
    options: tuple[OptionDef, ...]


Output = Union[
    SendTextOutput,
    SendInteractiveButtonsOutput,
    SendInteractiveListOutput,
    SendOptionsOutput,
]
