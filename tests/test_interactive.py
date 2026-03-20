# tests/test_interactive.py
"""
Unit tests for utils/interactive.py.
Validates payload structure, WhatsApp limits and edge cases.
"""
import pytest
from datetime import date
from app.utils.interactive import (
    _trunc,
    build_main_menu,
    build_period_select,
    build_days_list,
    build_hours_list,
    build_booking_confirm,
    build_appointments_view,
    build_cancel_select,
    build_cancel_confirm,
)
import pytz
from datetime import datetime

TZ = pytz.timezone("Europe/Madrid")


def _all_rows(payload):
    """Collect all list rows from a list-type interactive payload."""
    sections = payload["interactive"]["action"].get("sections", [])
    rows = []
    for s in sections:
        rows.extend(s.get("rows", []))
    return rows


def _buttons(payload):
    return payload["interactive"]["action"].get("buttons", [])


def make_cita(event_id, year, month, day, hour, minute):
    start = TZ.localize(datetime(year, month, day, hour, minute))
    return {"id": event_id, "start": start}


# ── _trunc ─────────────────────────────────────────────────────────────────────

class TestTrunc:
    def test_short_text_unchanged(self):
        assert _trunc("Hola", 20) == "Hola"

    def test_long_text_truncated(self):
        assert len(_trunc("A" * 30, 20)) == 20

    def test_exact_length_unchanged(self):
        assert _trunc("A" * 20, 20) == "A" * 20


# ── build_main_menu ─────────────────────────────────────────────────────────────

class TestBuildMainMenu:
    def test_structure(self):
        msg = build_main_menu()
        assert msg["type"] == "interactive"
        assert msg["interactive"]["type"] == "button"

    def test_three_buttons(self):
        msg = build_main_menu()
        assert len(_buttons(msg)) == 3

    def test_button_ids(self):
        ids = {b["reply"]["id"] for b in _buttons(build_main_menu())}
        assert ids == {"menu_book", "menu_view", "menu_cancel"}

    def test_button_titles_under_20_chars(self):
        for b in _buttons(build_main_menu()):
            assert len(b["reply"]["title"]) <= 20

    def test_footer_present(self):
        msg = build_main_menu()
        assert "footer" in msg["interactive"]


# ── build_period_select ─────────────────────────────────────────────────────────

class TestBuildPeriodSelect:
    def test_structure(self):
        msg = build_period_select(date(2026, 3, 23), "10:00-14:00", "16:00-20:00")
        assert msg["type"] == "interactive"
        assert msg["interactive"]["type"] == "button"

    def test_three_buttons(self):
        msg = build_period_select(date(2026, 3, 23), "10:00-14:00", "16:00-20:00")
        assert len(_buttons(msg)) == 3

    def test_button_titles_under_20_chars(self):
        msg = build_period_select(date(2026, 3, 23), "10:00-14:00", "16:00-20:00")
        for b in _buttons(msg):
            assert len(b["reply"]["title"]) <= 20, b["reply"]["title"]

    def test_period_button_ids(self):
        msg = build_period_select(date(2026, 3, 23), "10:00-14:00", "16:00-20:00")
        ids = {b["reply"]["id"] for b in _buttons(msg)}
        assert "period_morning" in ids
        assert "period_afternoon" in ids
        assert "back_to_menu" in ids


# ── build_days_list ─────────────────────────────────────────────────────────────

class TestBuildDaysList:
    def test_structure(self):
        days = [date(2026, 3, 23), date(2026, 3, 24)]
        msg = build_days_list(days)
        assert msg["interactive"]["type"] == "list"

    def test_rows_include_days_plus_back(self):
        days = [date(2026, 3, 23), date(2026, 3, 24)]
        rows = _all_rows(build_days_list(days))
        assert len(rows) == 3   # 2 days + back

    def test_back_to_menu_row_present(self):
        rows = _all_rows(build_days_list([date(2026, 3, 23)]))
        ids = [r["id"] for r in rows]
        assert "back_to_menu" in ids

    def test_day_row_id_format(self):
        rows = _all_rows(build_days_list([date(2026, 3, 23)]))
        assert any(r["id"] == "day_2026-03-23" for r in rows)

    def test_row_titles_under_24_chars(self):
        days = [date(2026, 3, d) for d in range(23, 28)]
        for row in _all_rows(build_days_list(days)):
            assert len(row["title"]) <= 24

    def test_total_rows_under_10(self):
        # WhatsApp limit: 10 rows total
        days = [date(2026, 3, 23) + __import__("datetime").timedelta(days=i) for i in range(9)]
        rows = _all_rows(build_days_list(days))
        assert len(rows) <= 10


# ── build_hours_list ────────────────────────────────────────────────────────────

class TestBuildHoursList:
    def test_structure(self):
        msg = build_hours_list(date(2026, 3, 23), ["10:00", "10:30"])
        assert msg["interactive"]["type"] == "list"

    def test_rows_include_slots_plus_nav(self):
        slots = ["10:00", "10:30", "11:00"]
        rows = _all_rows(build_hours_list(date(2026, 3, 23), slots))
        assert len(rows) == 5   # 3 slots + change_day + back

    def test_slot_row_id_format(self):
        rows = _all_rows(build_hours_list(date(2026, 3, 23), ["10:00"]))
        assert any(r["id"] == "hour_2026-03-23_1000" for r in rows)

    def test_total_rows_under_10_with_8_slots(self):
        # 8 content slots + 2 nav = 10 (WhatsApp max)
        slots = [f"{h}:{m:02d}" for h in range(10, 14) for m in (0, 30)]
        rows = _all_rows(build_hours_list(date(2026, 3, 23), slots))
        assert len(rows) <= 10


# ── build_booking_confirm ───────────────────────────────────────────────────────

class TestBuildBookingConfirm:
    def test_structure(self):
        msg = build_booking_confirm(date(2026, 3, 23), "10:00")
        assert msg["interactive"]["type"] == "button"

    def test_three_buttons(self):
        assert len(_buttons(build_booking_confirm(date(2026, 3, 23), "10:00"))) == 3

    def test_confirm_button_present(self):
        ids = {b["reply"]["id"] for b in _buttons(build_booking_confirm(date(2026, 3, 23), "10:00"))}
        assert "book_confirm" in ids

    def test_body_contains_date_and_slot(self):
        msg = build_booking_confirm(date(2026, 3, 23), "10:00")
        body = msg["interactive"]["body"]["text"]
        assert "10:00" in body


# ── build_appointments_view ─────────────────────────────────────────────────────

class TestBuildAppointmentsView:
    def test_empty_shows_buttons(self):
        msg = build_appointments_view([])
        assert msg["interactive"]["type"] == "button"

    def test_with_citas_shows_list(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        msg = build_appointments_view(citas)
        assert msg["interactive"]["type"] == "list"

    def test_max_10_rows(self):
        citas = [make_cita(f"evt{i}", 2026, 3, 23 + i // 24, 10, 0) for i in range(12)]
        rows = _all_rows(build_appointments_view(citas))
        assert len(rows) <= 10

    def test_back_button_always_present(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        rows = _all_rows(build_appointments_view(citas))
        assert any(r["id"] == "back_to_menu" for r in rows)

    def test_overflow_message_shown(self):
        citas = [make_cita(f"evt{i}", 2026, 3, 23, 10, 0) for i in range(10)]
        msg = build_appointments_view(citas)
        body = msg["interactive"]["body"]["text"]
        assert "9" in body or "primeras" in body


# ── build_cancel_select ─────────────────────────────────────────────────────────

class TestBuildCancelSelect:
    def test_empty_shows_buttons(self):
        msg = build_cancel_select([])
        assert msg["interactive"]["type"] == "button"

    def test_cancel_row_id_format(self):
        citas = [make_cita("evt_abc", 2026, 3, 23, 10, 0)]
        rows = _all_rows(build_cancel_select(citas))
        assert any(r["id"] == "cancel_appt_evt_abc" for r in rows)

    def test_max_10_rows(self):
        citas = [make_cita(f"evt{i}", 2026, 3, 23, 10, 0) for i in range(12)]
        rows = _all_rows(build_cancel_select(citas))
        assert len(rows) <= 10


# ── build_cancel_confirm ────────────────────────────────────────────────────────

class TestBuildCancelConfirm:
    def test_structure(self):
        msg = build_cancel_confirm(date(2026, 3, 23), "10:00", "evt_xyz")
        assert msg["interactive"]["type"] == "button"

    def test_confirm_button_id_contains_event_id(self):
        msg = build_cancel_confirm(date(2026, 3, 23), "10:00", "evt_xyz")
        ids = {b["reply"]["id"] for b in _buttons(msg)}
        assert "cancel_confirm_evt_xyz" in ids

    def test_keep_button_present(self):
        msg = build_cancel_confirm(date(2026, 3, 23), "10:00", "evt_xyz")
        ids = {b["reply"]["id"] for b in _buttons(msg)}
        assert "cancel_keep" in ids

    def test_three_buttons(self):
        msg = build_cancel_confirm(date(2026, 3, 23), "10:00", "evt_xyz")
        assert len(_buttons(msg)) == 3
