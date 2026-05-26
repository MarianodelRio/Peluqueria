"""Unit tests for engine.compute_slots and engine.resolve_day_schedule (pure functions)."""

from __future__ import annotations

from datetime import date, timedelta

from data_plane.adapters.connectors.google_calendar.engine import (
    compute_slots,
)

# Fixed test date: 2024-01-08 is a Monday
TEST_DATE = date(2024, 1, 8)
TZ = "Europe/Madrid"

SCHEDULE_MON_10_14 = {"mon": ["10:00-14:00"]}
SCHEDULE_MON_SPLIT = {"mon": ["10:00-12:00", "15:00-17:00"]}


def make_timed_event(start_str: str, end_str: str, tz: str = "Europe/Madrid") -> dict:
    """start_str and end_str as 'HH:MM', creates event for a fixed test date."""
    base = "2024-01-08"
    return {
        "start": {"dateTime": f"{base}T{start_str}:00+01:00"},
        "end": {"dateTime": f"{base}T{end_str}:00+01:00"},
        "summary": "Test event",
    }


def make_allday_event(title: str, start_date: str, end_date: str | None = None) -> dict:
    """start_date and end_date as 'YYYY-MM-DD'. end_date is exclusive."""
    if end_date is None:
        d = date.fromisoformat(start_date)
        end_date = (d + timedelta(days=1)).isoformat()
    return {
        "start": {"date": start_date},
        "end": {"date": end_date},
        "summary": title,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_closed_day_no_schedule() -> None:
    """Schedule has no entry for Monday → empty slot list."""
    schedule = {"tue": ["10:00-14:00"]}  # no 'mon' key
    result = compute_slots(
        TEST_DATE,
        events=[],
        base_schedule=schedule,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    assert result == []


def test_empty_schedule() -> None:
    """Empty schedule dict → no ranges for any day → empty slot list."""
    result = compute_slots(
        TEST_DATE,
        events=[],
        base_schedule={},
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    assert result == []


def test_cfg_cerrado_closes_day() -> None:
    """[CFG] CERRADO all-day event → day is closed regardless of base schedule."""
    events = [make_allday_event("[CFG] CERRADO", "2024-01-08")]
    result = compute_slots(
        TEST_DATE,
        events=events,
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    assert result == []


def test_cfg_vacaciones_closes_day() -> None:
    """[CFG] VACACIONES multi-day event covering the test date → day is closed."""
    # end date is exclusive: 2024-01-09 means up to and including 2024-01-08
    events = [make_allday_event("[CFG] VACACIONES", "2024-01-06", "2024-01-10")]
    result = compute_slots(
        TEST_DATE,
        events=events,
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    assert result == []


def test_cfg_horario_overrides_schedule() -> None:
    """[CFG] HORARIO 11:00-13:00 overrides base schedule → slots only in 11:00-13:00."""
    events = [make_allday_event("[CFG] HORARIO 11:00-13:00", "2024-01-08")]
    result = compute_slots(
        TEST_DATE,
        events=events,
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    # 11:00 and 11:30 fit (both need 30 min presence before 13:00)
    # 12:00 → 12:00 + 30min = 12:30 presence, fits before 13:00
    # 12:30 → 12:30 + 30min = 13:00, does NOT exceed 13:00 so it fits too
    assert "10:00" not in result
    assert "11:00" in result
    assert "11:30" in result
    assert "14:00" not in result
    # All returned slots must be within 11:00-13:00
    for slot in result:
        h, m = slot.split(":")
        slot_minutes = int(h) * 60 + int(m)
        assert 11 * 60 <= slot_minutes < 13 * 60


def test_open_day_no_events() -> None:
    """Day with schedule 10:00-14:00, no events, 30-min slots → returns all expected slots."""
    result = compute_slots(
        TEST_DATE,
        events=[],
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    # Slots: 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00, 13:30
    expected = ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"]
    assert result == expected


def test_event_blocks_slot() -> None:
    """A timed event overlapping 10:00-10:30 removes that slot."""
    events = [make_timed_event("10:00", "10:30")]
    result = compute_slots(
        TEST_DATE,
        events=events,
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    assert "10:00" not in result
    assert "10:30" in result


def test_overlap_tolerance() -> None:
    """Event ending exactly at slot start (within OVERLAP_TOLERANCE_SECONDS) → slot NOT blocked."""
    # Event ends at 10:00, slot starts at 10:00 — they touch but the overlap check uses tolerance
    # ev_end (10:00) > slot_start + tolerance (10:00 + 60s = 10:01) is FALSE → not blocked
    events = [make_timed_event("09:00", "10:00")]
    result = compute_slots(
        TEST_DATE,
        events=events,
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    # 10:00 slot: ev_end (10:00) > slot_start + tolerance (10:01) → False → not blocked
    assert "10:00" in result


def test_presence_min_filters_last_slots() -> None:
    """presence_min=180 in 10:00-14:00 → only slots that leave 3h before close allowed."""
    # close = 14:00 (840 min), need slot_start + 180 min <= 840 → slot_start <= 11:00
    result = compute_slots(
        TEST_DATE,
        events=[],
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=180,
    )
    # 10:00 + 180min = 13:00 <= 14:00 ✓
    # 10:30 + 180min = 13:30 <= 14:00 ✓
    # 11:00 + 180min = 14:00 <= 14:00 ✓  (not strictly greater)
    # 11:30 + 180min = 14:30 > 14:00 ✗
    assert "10:00" in result
    assert "10:30" in result
    assert "11:00" in result
    assert "11:30" not in result
    assert "13:00" not in result


def test_split_schedule_morning_afternoon() -> None:
    """Schedule with two ranges → slots come from both, with a gap in between."""
    result = compute_slots(
        TEST_DATE,
        events=[],
        base_schedule=SCHEDULE_MON_SPLIT,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    # Morning: 10:00-12:00 → 10:00, 10:30, 11:00, 11:30
    assert "10:00" in result
    assert "10:30" in result
    assert "11:00" in result
    assert "11:30" in result
    # Gap between 12:00 and 15:00 — no slots
    assert "12:00" not in result
    assert "13:00" not in result
    assert "14:00" not in result
    # Afternoon: 15:00-17:00 → 15:00, 15:30, 16:00, 16:30
    assert "15:00" in result
    assert "15:30" in result
    assert "16:00" in result
    assert "16:30" in result
    # Nothing beyond 17:00
    assert "17:00" not in result


def test_cfg_cerrado_previous_day_does_not_close_current_day() -> None:
    """[CFG] CERRADO for D-1 must not close D.

    Google Calendar returns end.date = D (exclusive) for an event on D-1.
    The date-range guard must filter it out.
    """
    events = [make_allday_event("[CFG] CERRADO", "2024-01-07", "2024-01-08")]
    result = compute_slots(
        TEST_DATE,
        events=events,
        base_schedule=SCHEDULE_MON_10_14,
        timezone=TZ,
        slot_duration_min=30,
        service_duration_min=30,
        presence_min=30,
    )
    assert result != [], "CERRADO on D-1 must not close D"
    assert "10:00" in result
