# tests/test_interactive.py
"""
Unit tests for utils/interactive.py.
Validates payload structure, WhatsApp limits and edge cases.
"""
from datetime import date
from unittest.mock import patch
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
from app.config import SERVICIOS
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
        assert ids == {"menu_book", "menu_move", "menu_cancel"}

    def test_button_titles_under_20_chars(self):
        for b in _buttons(build_main_menu()):
            assert len(b["reply"]["title"]) <= 20

    def test_footer_present(self):
        msg = build_main_menu()
        assert "footer" in msg["interactive"]

    def test_evento_activo_false_still_three_buttons(self):
        """With EVENTO_ACTIVO=False, menu is unchanged (3 buttons)."""
        with patch("app.utils.interactive.EVENTO_ACTIVO", False):
            msg = build_main_menu()
        assert msg["interactive"]["type"] == "button"
        assert len(_buttons(msg)) == 3


# ── build_main_menu with event active ──────────────────────────────────────────

class TestBuildMainMenuWithEvento:
    def test_evento_activo_true_produces_list(self):
        """When EVENTO_ACTIVO=True, menu is a list with 4 rows."""
        with patch("app.utils.interactive.EVENTO_ACTIVO", True), \
             patch("app.utils.interactive.EVENTO_NOMBRE", "Navidad"):
            msg = build_main_menu()
        assert msg["interactive"]["type"] == "list"

    def test_evento_activo_true_has_four_rows(self):
        with patch("app.utils.interactive.EVENTO_ACTIVO", True), \
             patch("app.utils.interactive.EVENTO_NOMBRE", "Navidad"):
            msg = build_main_menu()
        rows = _all_rows(msg)
        assert len(rows) == 4

    def test_menu_book_event_row_present(self):
        with patch("app.utils.interactive.EVENTO_ACTIVO", True), \
             patch("app.utils.interactive.EVENTO_NOMBRE", "Navidad"):
            msg = build_main_menu()
        ids = [r["id"] for r in _all_rows(msg)]
        assert "menu_book_event" in ids

    def test_event_row_title_includes_nombre(self):
        with patch("app.utils.interactive.EVENTO_ACTIVO", True), \
             patch("app.utils.interactive.EVENTO_NOMBRE", "Navidad"):
            msg = build_main_menu()
        rows = {r["id"]: r for r in _all_rows(msg)}
        assert "Navidad" in rows["menu_book_event"]["title"]

    def test_event_row_title_truncated_to_24_chars(self):
        long_name = "A" * 30
        with patch("app.utils.interactive.EVENTO_ACTIVO", True), \
             patch("app.utils.interactive.EVENTO_NOMBRE", long_name):
            msg = build_main_menu()
        rows = {r["id"]: r for r in _all_rows(msg)}
        assert len(rows["menu_book_event"]["title"]) <= 24

    def test_list_button_label_is_ver_opciones(self):
        with patch("app.utils.interactive.EVENTO_ACTIVO", True), \
             patch("app.utils.interactive.EVENTO_NOMBRE", "Navidad"):
            msg = build_main_menu()
        assert msg["interactive"]["action"]["button"] == "Ver opciones"


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
        assert "back_to_day" in ids


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
        from datetime import timedelta
        days = [
            date(2026, 3, 23) + timedelta(days=i) for i in range(9)
        ]
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
        assert len(rows) == 4   # 3 slots + back_to_day

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
    def test_type_is_list(self):
        msg = build_service_select()
        assert msg["type"] == "interactive"
        assert msg["interactive"]["type"] == "list"

    def test_all_service_row_ids_start_with_service(self):
        rows = _all_rows(build_service_select())
        service_rows = [r for r in rows if r["id"] != "back_to_menu"]
        for r in service_rows:
            assert r["id"].startswith("service_"), r["id"]

    def test_back_to_menu_row_exists(self):
        rows = _all_rows(build_service_select())
        ids = [r["id"] for r in rows]
        assert "back_to_menu" in ids

    def test_total_rows_under_or_equal_10(self):
        rows = _all_rows(build_service_select())
        assert len(rows) <= 10

    def test_row_titles_under_24_chars(self):
        rows = _all_rows(build_service_select())
        for r in rows:
            assert len(r["title"]) <= 24, r["title"]

    def test_service_rows_have_euro_description(self):
        rows = _all_rows(build_service_select())
        service_rows = [r for r in rows if r["id"] != "back_to_menu"]
        for r in service_rows:
            assert "description" in r, f"Row {r['id']} has no description"
            assert "€" in r["description"], f"Row {r['id']} description missing €"

    def test_service_row_count_matches_servicios(self):
        rows = _all_rows(build_service_select())
        service_rows = [r for r in rows if r["id"] != "back_to_menu"]
        assert len(service_rows) == len(SERVICIOS)

    def test_specific_service_ids_present(self):
        rows = _all_rows(build_service_select())
        ids = {r["id"] for r in rows}
        assert "service_corte" in ids
        assert "service_corte_barba" in ids
        assert "service_mechas" in ids


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
        lines_with_date = [line for line in body.splitlines() if "📅" in line]
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


# ── build_hours_list with came_from_period ──────────────────────────────────────

class TestBuildHoursListCameFromPeriod:
    def test_9_slots_came_from_period_true_yields_10_rows(self):
        slots = [f"10:{m:02d}" for m in range(0, 270, 30)][:9]  # 9 slots
        rows = _all_rows(
            build_hours_list(date(2026, 3, 23), slots, came_from_period=True)
        )
        assert len(rows) == 10

    def test_came_from_period_true_includes_back_to_period(self):
        slots = ["10:00", "10:30", "11:00"]
        rows = _all_rows(
            build_hours_list(date(2026, 3, 23), slots, came_from_period=True)
        )
        row_ids = [r["id"] for r in rows]
        assert "back_to_period" in row_ids
        assert "change_period" not in row_ids
        assert "change_day" not in row_ids
        assert "back_to_menu" not in row_ids

    def test_came_from_period_false_includes_back_to_day(self):
        slots = ["10:00", "10:30", "11:00"]
        rows = _all_rows(
            build_hours_list(date(2026, 3, 23), slots, came_from_period=False)
        )
        row_ids = [r["id"] for r in rows]
        assert "back_to_day" in row_ids
        assert "back_to_period" not in row_ids
