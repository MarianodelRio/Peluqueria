# utils/parser.py
"""
Robust parser for Google Calendar event descriptions.
All functions: case insensitive, tolerant of spaces, never raise exceptions.
"""
import re
import html
import unicodedata
from typing import Optional

# E.164: 7–15 digits after stripping formatting
_PHONE_MIN_DIGITS = 7
_PHONE_MAX_DIGITS = 15


def _norm(text: str) -> str:
    """
    Central normalisation for all value comparisons:
      1. NFC — collapse multi-codepoint characters (e.g. NFD accents) into one
      2. Lowercase — case-insensitive comparison without relying on regex flags
      3. Strip accents — remove combining marks so 'sí','si','Sí','SÍ' all → 'si'
      4. Strip whitespace
    Only applied to VALUES being compared, never to user-visible output.
    """
    if not text:
        return ""
    text = unicodedata.normalize('NFC', text)
    text = text.lower()
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'   # Mn = non-spacing mark (accents)
    )
    return text.strip()


def _strip_html(text: str) -> str:
    """
    Remove HTML markup that Google Calendar may inject into description fields.
      1. Replace block-level tags with newlines to preserve line structure
      2. Strip remaining tags
      3. Decode HTML entities (&amp; → &, &nbsp; → space, etc.)
    """
    if not text:
        return text
    # Block tags → newline so field lines stay separate
    text = re.sub(r'<(?:br\s*/?>|/p>|/div>|/li>)', '\n', text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode entities
    text = html.unescape(text)
    return text


def parse_nombre(text: str) -> Optional[str]:
    """Extract name from 'Nombre: ...' field."""
    if not text:
        return None
    text = _strip_html(text)
    match = re.search(r'nombre\s*:\s*(.+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def parse_tel(text: str) -> Optional[str]:
    """
    Extract phone number from 'Telefono:' field.
    Falls back to 'Tel:' for backwards compatibility.
    Returns None if the stripped digit count is outside 7–15 (E.164 range).
    """
    if not text:
        return None
    text = _strip_html(text)
    match = re.search(r'telefono\s*:\s*(\+?[\d\s\-]{6,})', text, re.IGNORECASE)
    if not match:
        match = re.search(r'tel\s*:\s*(\+?[\d\s\-]{6,})', text, re.IGNORECASE)
    if match:
        # Strip formatting, then remove leading '+' to normalise to digits-only
        # (WhatsApp sends numbers without '+'; this avoids mismatches with
        # manually created events that may have '+34...' in the description)
        stripped = re.sub(r'[\s\-]', '', match.group(1)).lstrip('+')
        digits = re.sub(r'\D', '', stripped)
        if _PHONE_MIN_DIGITS <= len(digits) <= _PHONE_MAX_DIGITS:
            # Normalise Spanish numbers written without country code:
            # 9-digit numbers (e.g. '600000001') → '34600000001'
            if len(digits) == 9:
                stripped = '34' + stripped
            return stripped
    return None


def parse_estado(text: str) -> Optional[str]:
    """Returns 'pendiente', 'confirmada', or None."""
    if not text:
        return None
    text = _strip_html(text)
    match = re.search(r'estado\s*:\s*(\w+)', text, re.IGNORECASE)
    if match:
        val = _norm(match.group(1))
        if val in ('pendiente', 'confirmada'):
            return val
    return None


def parse_reminder(text: str) -> Optional[str]:
    """
    Returns 'si', 'no', or None.
    Checks 'Recordatorio:' field, falls back to legacy 'Reminder24h:'.
    """
    if not text:
        return None
    text = _strip_html(text)
    match = re.search(r'recordatorio\s*:\s*(\w+)', text, re.IGNORECASE)
    if not match:
        match = re.search(r'reminder24h\s*:\s*(\w+)', text, re.IGNORECASE)
    if match:
        val = _norm(match.group(1))
        if val in ('si', 'no'):
            return val
    return None


def parse_cfg(title: str) -> Optional[dict]:
    """
    Parse [CFG] event titles.
    Returns dict with key 'type' and optional 'start'/'end' strings.
    Types: 'cerrado', 'vacaciones', 'horario'
    Example: {'type': 'horario', 'start': '10:00', 'end': '13:00'}
    Tolerant of: accents, extra spaces, en-dash vs hyphen, no space before time.
    """
    if not title:
        return None
    title_norm = _norm(title)
    if '[cfg]' not in title_norm:
        return None

    if 'cerrado' in title_norm:
        return {'type': 'cerrado'}
    if 'vacaciones' in title_norm:
        return {'type': 'vacaciones'}

    # [CFG] HORARIO HH:MM-HH:MM  (space optional, separator: hyphen or en-dash)
    match = re.search(r'horario\s*(\d{1,2}:\d{2})\s*[-\u2013]\s*(\d{1,2}:\d{2})', title_norm)
    if match:
        return {'type': 'horario', 'start': match.group(1), 'end': match.group(2)}

    return None


def set_field(description: str, key: str, value: str) -> str:
    """
    Set or update a field in event description.
    Removes ALL existing occurrences of the key (handles accidental duplicates),
    then appends the new key: value line.
    key should be like 'Estado', 'Recordatorio', etc.
    """
    if not description:
        description = ""
    # Strip every existing line for this key (case-insensitive, incl. trailing newline)
    pattern = re.compile(rf'^{re.escape(key)}\s*:.*\n?', re.IGNORECASE | re.MULTILINE)
    cleaned = pattern.sub('', description).rstrip('\n')
    new_line = f"{key}: {value}"
    return (cleaned + '\n' + new_line) if cleaned else new_line


def remove_field(description: str, key: str) -> str:
    """Remove a field line from description."""
    if not description:
        return ""
    pattern = re.compile(rf'^{re.escape(key)}\s*:.*\n?', re.IGNORECASE | re.MULTILINE)
    return pattern.sub('', description)
