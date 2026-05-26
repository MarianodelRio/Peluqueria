from __future__ import annotations

import html
import re


def strip_html(text: str) -> str:
    """Remove HTML tags and unescape HTML entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text).strip()


def get_field(description: str, field_name: str) -> str | None:
    """Extract value of 'Field: value' from description text."""
    # Apply strip_html first in case description has HTML
    clean = strip_html(description)
    pattern = rf"(?i){re.escape(field_name)}\s*:\s*(.+)"
    m = re.search(pattern, clean)
    return m.group(1).strip() if m else None


def set_field(description: str, field_name: str, value: str) -> str:
    """Set 'field_name: value' line. Update if exists, append if not."""
    pattern = rf"(?i)({re.escape(field_name)}\s*:).+"
    replacement = rf"{field_name}: {value}"
    new_desc, count = re.subn(pattern, replacement, description)
    if count == 0:
        new_desc = description.rstrip("\n") + f"\n{field_name}: {value}"
    return new_desc


def remove_field(description: str, field_name: str) -> str:
    """Remove the line containing 'field_name: ...'"""
    lines = description.split("\n")
    pattern = re.compile(rf"(?i){re.escape(field_name)}\s*:.+")
    return "\n".join(line for line in lines if not pattern.match(line.strip()))


def parse_cfg(event: dict) -> str | None:
    """Extract [CFG] directive from all-day event summary. Returns directive string or None."""
    if "dateTime" in event.get("start", {}):
        return None  # Not an all-day event
    summary = event.get("summary", "")
    m = re.match(r"\[CFG\]\s*(.+)", summary, re.IGNORECASE)
    return m.group(1).strip() if m else None
