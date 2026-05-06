# tests/test_slots.py
"""
Unit tests for utils/slots.py.
Covers slot generation, availability filtering, date helpers and edge cases.
"""
import pytest
from datetime import date, timedelta
from unittest.mock import patch
import pytz

from app.utils.slots import (
    generate_slots,
    get_base_slots_for_day,
    slot_to_datetime,
    events_overlap_slot,
    filter_available_slots,
    get_next_days,
    format_date_es,
)
from app.config import HORARIO_BASE, CITA_DURACION_MIN

TZ = pytz.timezone("Europe/Madrid")


def _slots_for_weekday(weekday: int) -> list:
    """Compute expected slots from HORARIO_BASE for a given weekday."""
    return [
        slot
        for start, end in HORARIO_BASE.get(weekday, [])
        for slot in generate_slots(start, end)
    ]


def aware(y, m, d, h, mi=0):
    return TZ.localize(__import__("datetime").datetime(y, m, d, h, mi))


# ── generate_slots ────────────────────────────────────────────────────────────

class TestGenerateSlots:
    def test_morning_block(self):
        # Uses HORARIO_BASE morning period to stay config-aligned
        start, end = HORARIO_BASE[1][0]
        slots = generate_slots(start, end)
        minutes = (int(end[:2]) * 60 + int(end[3:])) - (int(start[:2]) * 60 + int(start[3:]))
        assert len(slots) == minutes // CITA_DURACION_MIN
        assert slots[0] == start

    def test_afternoon_block(self):
        start, end = HORARIO_BASE[1][1]
        slots = generate_slots(start, end)
        minutes = (int(end[:2]) * 60 + int(end[3:])) - (int(start[:2]) * 60 + int(start[3:]))
        assert len(slots) == minutes // CITA_DURACION_MIN
        assert slots[0] == start

    def test_single_slot(self):
        assert generate_slots("10:00", "10:30") == ["10:00"]

    def test_no_slots_when_range_too_small(self):
        # Only 20 minutes — no 30-min slot fits
        assert generate_slots("10:00", "10:20") == []

    def test_exact_boundary(self):
        # Last slot starts at end - 30min, never AT end
        slots = generate_slots("10:00", "11:00")
        assert len(slots) == 60 // CITA_DURACION_MIN
        assert "11:00" not in slots

    def test_duracion_120_produces_correct_slots(self):
        # 10:00-14:00 with 120-min window, 30-min step → slots at 10:00, 10:30, 11:00, 11:30, 12:00
        slots = generate_slots("10:00", "14:00", duracion_min=120)
        assert slots == ["10:00", "10:30", "11:00", "11:30", "12:00"]

    def test_default_duracion_backward_compat(self):
        # No third arg → same as before (30-min slots)
        slots_default = generate_slots("10:00", "14:00")
        slots_explicit = generate_slots("10:00", "14:00", duracion_min=30)
        assert slots_default == slots_explicit


# ── get_base_slots_for_day ────────────────────────────────────────────────────

class TestGetBaseSlotsForDay:
    def test_tuesday_has_slots(self):
        tuesday = date(2026, 3, 24)   # Tuesday
        slots = get_base_slots_for_day(tuesday)
        assert slots == _slots_for_weekday(1)

    def test_saturday_has_slots(self):
        saturday = date(2026, 3, 28)
        slots = get_base_slots_for_day(saturday)
        assert slots == _slots_for_weekday(5)

    def test_sunday_has_no_slots(self):
        sunday = date(2026, 3, 29)
        assert get_base_slots_for_day(sunday) == []

    def test_friday_has_slots(self):
        friday = date(2026, 3, 27)
        slots = get_base_slots_for_day(friday)
        assert slots == _slots_for_weekday(4)

    def test_duracion_120_returns_fewer_slots_than_default(self):
        tuesday = date(2026, 3, 24)
        slots_30 = get_base_slots_for_day(tuesday)
        slots_120 = get_base_slots_for_day(tuesday, duracion_min=120)
        assert len(slots_120) < len(slots_30)
        assert len(slots_120) > 0

    def test_duracion_120_base_slots_have_30min_step(self):
        tuesday = date(2026, 3, 24)
        slots = get_base_slots_for_day(tuesday, duracion_min=120)
        assert len(slots) == 10
        assert slots[0] == "10:00"
        assert slots[1] == "10:30"
        assert slots[5] == "17:00"
        assert slots[6] == "17:30"


# ── slot_to_datetime ──────────────────────────────────────────────────────────

class TestSlotToDatetime:
    def test_returns_aware_datetime(self):
        d = date(2026, 3, 23)
        dt = slot_to_datetime(d, "10:30")
        assert dt.tzinfo is not None

    def test_correct_hour_minute(self):
        d = date(2026, 3, 23)
        dt = slot_to_datetime(d, "16:00")
        assert dt.hour == 16 and dt.minute == 0


# ── events_overlap_slot ───────────────────────────────────────────────────────

class TestEventsOverlapSlot:
    def setup_method(self):
        self.slot_start = aware(2026, 3, 23, 10, 0)
        self.slot_end   = aware(2026, 3, 23, 10, 30)

    def test_full_overlap(self):
        # Event exactly matches slot
        assert events_overlap_slot(self.slot_start, self.slot_end,
                                   self.slot_start, self.slot_end)

    def test_event_before_slot(self):
        ev_start = aware(2026, 3, 23, 9, 0)
        ev_end   = aware(2026, 3, 23, 9, 30)
        assert not events_overlap_slot(ev_start, ev_end, self.slot_start, self.slot_end)

    def test_event_after_slot(self):
        ev_start = aware(2026, 3, 23, 11, 0)
        ev_end   = aware(2026, 3, 23, 11, 30)
        assert not events_overlap_slot(ev_start, ev_end, self.slot_start, self.slot_end)

    def test_event_partially_overlaps_start(self):
        ev_start = aware(2026, 3, 23, 9, 30)
        ev_end   = aware(2026, 3, 23, 10, 15)
        assert events_overlap_slot(ev_start, ev_end, self.slot_start, self.slot_end)

    def test_event_partially_overlaps_end(self):
        ev_start = aware(2026, 3, 23, 10, 15)
        ev_end   = aware(2026, 3, 23, 11, 0)
        assert events_overlap_slot(ev_start, ev_end, self.slot_start, self.slot_end)

    def test_tolerance_boundary_adjacent_slot_no_overlap(self):
        # Event ends exactly at slot start (10:00) → within ±1min tolerance → no overlap
        ev_start = aware(2026, 3, 23, 9, 30)
        ev_end   = aware(2026, 3, 23, 10, 0)   # ends exactly at slot start
        assert not events_overlap_slot(ev_start, ev_end, self.slot_start, self.slot_end)

    def test_tolerance_boundary_adjacent_slot_end_no_overlap(self):
        # Event starts exactly at slot end (10:30) → no overlap
        ev_start = aware(2026, 3, 23, 10, 30)
        ev_end   = aware(2026, 3, 23, 11, 0)
        assert not events_overlap_slot(ev_start, ev_end, self.slot_start, self.slot_end)


# ── filter_available_slots ────────────────────────────────────────────────────

class TestFilterAvailableSlots:
    def test_no_events_all_available(self):
        d = date(2026, 3, 23)
        slots = ["10:00", "10:30", "11:00"]
        assert filter_available_slots(slots, d, []) == slots

    def test_occupied_slot_removed(self):
        d = date(2026, 3, 23)
        slots = ["10:00", "10:30", "11:00"]
        events = [{"start": aware(2026, 3, 23, 10, 0),
                   "end":   aware(2026, 3, 23, 10, 30)}]
        available = filter_available_slots(slots, d, events)
        assert "10:00" not in available
        assert "10:30" in available
        assert "11:00" in available

    def test_all_day_event_blocks_all(self):
        d = date(2026, 3, 23)
        slots = ["10:00", "10:30"]
        events = [{"start": aware(2026, 3, 23, 0, 0),
                   "end":   aware(2026, 3, 23, 23, 59)}]
        assert filter_available_slots(slots, d, events) == []

    def test_empty_slots(self):
        d = date(2026, 3, 23)
        assert filter_available_slots([], d, []) == []

    def test_duracion_120_blocks_wider_window(self):
        # Slot at 10:00 with 120-min window; event at 11:30 overlaps → 10:00 blocked
        d = date(2026, 3, 23)
        slots = ["10:00"]
        events = [{"start": aware(2026, 3, 23, 11, 30),
                   "end":   aware(2026, 3, 23, 12, 0)}]
        available = filter_available_slots(slots, d, events, duracion_min=120)
        assert "10:00" not in available

    def test_duracion_120_slot_free_when_event_outside_window(self):
        # Event at 12:30 is outside the 10:00–12:00 window → slot is free
        d = date(2026, 3, 23)
        slots = ["10:00"]
        events = [{"start": aware(2026, 3, 23, 12, 30),
                   "end":   aware(2026, 3, 23, 13, 0)}]
        available = filter_available_slots(slots, d, events, duracion_min=120)
        assert "10:00" in available


# ── get_next_days ─────────────────────────────────────────────────────────────

class TestGetNextDays:
    def test_returns_only_working_days(self):
        days = get_next_days(14)
        for d in days:
            assert d.weekday() < 6, f"{d} is a Sunday"

    def test_includes_today_if_weekday(self):
        # Freeze "today" to a known Monday
        monday = TZ.localize(__import__("datetime").datetime(2026, 3, 23))
        with patch("app.utils.slots.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            days = get_next_days(7)
        assert days[0] == date(2026, 3, 23)

    def test_skips_today_if_sunday(self):
        sunday = TZ.localize(__import__("datetime").datetime(2026, 3, 29))
        with patch("app.utils.slots.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            days = get_next_days(7)
        # First day must be Monday 30 March
        assert days[0] == date(2026, 3, 30)

    def test_count_within_window(self):
        monday = TZ.localize(__import__("datetime").datetime(2026, 3, 23))
        with patch("app.utils.slots.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            days = get_next_days(7)
        # range(8): Mon23, Tue24, Wed25, Thu26, Fri27, Sat28, Sun29(skip), Mon30 → 7 working days
        assert len(days) == 7


# ── format_date_es ────────────────────────────────────────────────────────────

class TestFormatDateEs:
    def test_monday(self):
        assert format_date_es(date(2026, 3, 23)) == "lunes 23 de marzo"

    def test_friday(self):
        assert format_date_es(date(2026, 3, 27)) == "viernes 27 de marzo"

    def test_december(self):
        assert format_date_es(date(2026, 12, 25)) == "viernes 25 de diciembre"

    def test_capitalise_helper(self):
        # The callers use .capitalize() on the result
        result = format_date_es(date(2026, 3, 23)).capitalize()
        assert result[0].isupper()
