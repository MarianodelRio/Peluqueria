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
    build_service_select,
    build_appointments_view,
    build_cancel_select,
    build_back_to_menu_message,
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


# ── build_service_select ────────────────────────────────────────────────────────

class TestBuildServiceSelect:
    def test_type_is_button(self):
        msg = build_service_select()
        assert msg["type"] == "interactive"
        assert msg["interactive"]["type"] == "button"

    def test_exactly_three_buttons(self):
        assert len(_buttons(build_service_select())) == 3

    def test_all_button_ids_start_with_service(self):
        for b in _buttons(build_service_select()):
            assert b["reply"]["id"].startswith("service_"), b["reply"]["id"]

    def test_all_button_titles_under_20_chars(self):
        for b in _buttons(build_service_select()):
            assert len(b["reply"]["title"]) <= 20, b["reply"]["title"]

    def test_specific_button_ids(self):
        ids = {b["reply"]["id"] for b in _buttons(build_service_select())}
        assert ids == {"service_corte", "service_corte_barba", "service_mechas"}

    def test_price_in_button_titles(self):
        titles = [b["reply"]["title"] for b in _buttons(build_service_select())]
        assert any("€" in title for title in titles)


# ── build_appointments_view ─────────────────────────────────────────────────────

class TestBuildAppointmentsView:
    def test_empty_shows_buttons(self):
        msg = build_appointments_view([])
        assert msg["interactive"]["type"] == "button"

    def test_with_citas_shows_button(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        msg = build_appointments_view(citas)
        assert msg["interactive"]["type"] == "button"

    def test_back_button_always_present(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        buttons = _buttons(build_appointments_view(citas))
        assert any(b["reply"]["id"] == "back_to_menu" for b in buttons)

    def test_single_back_button(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        buttons = _buttons(build_appointments_view(citas))
        assert len(buttons) == 1

    def test_body_contains_appointment_lines(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        msg = build_appointments_view(citas)
        body = msg["interactive"]["body"]["text"]
        assert "📅" in body
        assert "🕒" in body

    def test_body_contains_closing_message(self):
        citas = [make_cita("evt1", 2026, 3, 23, 10, 0)]
        msg = build_appointments_view(citas)
        body = msg["interactive"]["body"]["text"]
        assert "escríbenos" in body

    def test_capped_at_8_appointments(self):
        citas = [make_cita(f"evt{i}", 2026, 3, 23, 10, 0) for i in range(12)]
        msg = build_appointments_view(citas)
        body = msg["interactive"]["body"]["text"]
        # Only 8 lines starting with 📅 should appear
        lines_with_date = [l for l in body.splitlines() if "📅" in l]
        assert len(lines_with_date) == 8


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


# ── build_back_to_menu_message ──────────────────────────────────────────────────

class TestBuildBackToMenuMessage:
    def test_type_is_button(self):
        msg = build_back_to_menu_message("Tu cita está confirmada.")
        assert msg["type"] == "interactive"
        assert msg["interactive"]["type"] == "button"

    def test_exactly_one_button(self):
        msg = build_back_to_menu_message("Tu cita está confirmada.")
        assert len(_buttons(msg)) == 1

    def test_button_id_is_back_to_menu(self):
        msg = build_back_to_menu_message("Tu cita está confirmada.")
        assert _buttons(msg)[0]["reply"]["id"] == "back_to_menu"

    def test_body_matches_passed_string(self):
        body_text = "Cita cancelada correctamente."
        msg = build_back_to_menu_message(body_text)
        assert msg["interactive"]["body"]["text"] == body_text


# ── build_hours_list with show_change_period ────────────────────────────────────

class TestBuildHoursListShowChangePeriod:
    def test_7_slots_show_change_period_true_yields_10_rows(self):
        slots = [f"10:{m:02d}" for m in range(0, 210, 30)][:7]  # 7 slots
        rows = _all_rows(build_hours_list(date(2026, 3, 23), slots, show_change_period=True))
        assert len(rows) == 10

    def test_show_change_period_true_row_ids_include_all_nav(self):
        slots = ["10:00", "10:30", "11:00"]
        rows = _all_rows(build_hours_list(date(2026, 3, 23), slots, show_change_period=True))
        row_ids = [r["id"] for r in rows]
        assert "change_period" in row_ids
        assert "change_day" in row_ids
        assert "back_to_menu" in row_ids

    def test_show_change_period_false_does_not_include_change_period(self):
        slots = ["10:00", "10:30", "11:00"]
        rows = _all_rows(build_hours_list(date(2026, 3, 23), slots, show_change_period=False))
        row_ids = [r["id"] for r in rows]
        assert "change_period" not in row_ids


