from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .parser import parse_cfg

OVERLAP_TOLERANCE_SECONDS = 60

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_time(t_str: str) -> time:
    h, m = t_str.strip().split(":")
    return time(int(h), int(m))


def _parse_range(range_str: str) -> tuple[time, time]:
    start_s, end_s = range_str.split("-")
    return _parse_time(start_s), _parse_time(end_s)


def resolve_day_schedule(
    d: date,
    events: list[dict],
    base_schedule: dict[str, list[str]],
    timezone: str,
) -> list[tuple[time, time]] | None:
    """
    Returns list of (open_time, close_time) ranges for day d.
    Returns None if the day is closed (no schedule or closed by CFG event).
    Priority: [CFG] CERRADO/VACACIONES > [CFG] HORARIO HH:MM-HH:MM > base_schedule.
    """
    import re

    cfg_override: list[tuple[time, time]] | None = None
    has_cfg_override = False

    for event in events:
        directive = parse_cfg(event)
        if directive is None:
            continue

        directive_upper = directive.upper()

        if directive_upper == "CERRADO":
            start_str = event.get("start", {}).get("date", "")
            end_str = event.get("end", {}).get("date", "")
            if start_str and end_str:
                start_d = date.fromisoformat(start_str)
                end_d = date.fromisoformat(end_str)
                if start_d <= d < end_d:
                    return None

        if directive_upper.startswith("VACACIONES"):
            # Multi-day all-day event: end date is exclusive per Google convention
            start_str = event.get("start", {}).get("date", "")
            end_str = event.get("end", {}).get("date", "")
            if start_str and end_str:
                start_d = date.fromisoformat(start_str)
                end_d = date.fromisoformat(end_str)
                if start_d <= d < end_d:
                    return None

        horario_m = re.match(r"HORARIO\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", directive_upper)
        if horario_m:
            cfg_override = [(_parse_time(horario_m.group(1)), _parse_time(horario_m.group(2)))]
            has_cfg_override = True

    if has_cfg_override:
        return cfg_override

    weekday_key = WEEKDAY_KEYS[d.weekday()]
    ranges_strs = base_schedule.get(weekday_key) if base_schedule else None
    if not ranges_strs:
        return None

    return [_parse_range(r) for r in ranges_strs]


def compute_slots(
    d: date,
    events: list[dict],
    base_schedule: dict[str, list[str]],
    timezone: str,
    slot_duration_min: int,
    service_duration_min: int,
    presence_min: int,
) -> list[str]:
    """
    Returns list of available slot start times as 'HH:MM' strings.
    presence_min: minimum minutes the client must be present (can exceed service_duration_min).
    """
    if base_schedule is None:
        base_schedule = {}

    ranges = resolve_day_schedule(d, events, base_schedule, timezone)
    if ranges is None:
        return []

    tz = ZoneInfo(timezone)
    tolerance = timedelta(seconds=OVERLAP_TOLERANCE_SECONDS)
    slot_td = timedelta(minutes=slot_duration_min)
    service_td = timedelta(minutes=service_duration_min)
    presence_td = timedelta(minutes=presence_min)

    # Build list of timed events (not all-day config events)
    timed_events = []
    for ev in events:
        start_info = ev.get("start", {})
        end_info = ev.get("end", {})
        if "dateTime" not in start_info:
            continue  # skip all-day events for blocking
        ev_start = datetime.fromisoformat(start_info["dateTime"])
        ev_end = datetime.fromisoformat(end_info["dateTime"])
        timed_events.append((ev_start, ev_end))

    available = []
    for open_t, close_t in ranges:
        open_dt = datetime(d.year, d.month, d.day, open_t.hour, open_t.minute, tzinfo=tz)
        close_dt = datetime(d.year, d.month, d.day, close_t.hour, close_t.minute, tzinfo=tz)

        slot_start = open_dt
        while True:
            # The client must finish their presence before closing time
            if slot_start + presence_td > close_dt:
                break

            slot_end = slot_start + service_td

            # Check overlap with any timed event
            blocked = False
            for ev_start, ev_end in timed_events:
                # Normalize to aware datetimes if needed
                if ev_start.tzinfo is None:
                    ev_start = ev_start.replace(tzinfo=tz)
                if ev_end.tzinfo is None:
                    ev_end = ev_end.replace(tzinfo=tz)

                # Overlap: event_start < slot_end - tolerance AND event_end > slot_start + tolerance
                if ev_start < slot_end - tolerance and ev_end > slot_start + tolerance:
                    blocked = True
                    break

            if not blocked:
                available.append(slot_start.strftime("%H:%M"))

            slot_start += slot_td

    return available
