"""Tests for GoogleCalendarAdapter using FakeRepository injected via _repo=."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data_plane.adapters.connectors.google_calendar.adapter import GoogleCalendarAdapter

TZ = "Europe/Madrid"
TEST_DATE_STR = "2024-01-08"  # Monday


# ---------------------------------------------------------------------------
# FakeRepository
# ---------------------------------------------------------------------------


class FakeRepository:
    """In-memory fake for EventsRepository. All attributes are public for test assertions."""

    def __init__(self):
        self.day_events: dict = {}  # date → list[dict]
        self.range_events: list[dict] = []
        self.events: dict[str, dict] = {}  # event_id → dict
        self.created: list[dict] = []
        self.updated: dict[str, dict] = {}  # event_id → last body
        self.deleted: set[str] = set()

    def list_for_day(self, d) -> list[dict]:
        return self.day_events.get(str(d), [])

    def list_for_range(self, start, end, max_pages=5) -> list[dict]:
        return self.range_events

    def get_event(self, event_id: str) -> dict:
        return self.events[event_id]

    def create_event(self, body: dict) -> dict:
        created = {"id": "evt_new_123", **body}
        self.created.append(created)
        return created

    def update_event(self, event_id: str, body: dict) -> dict:
        self.updated[event_id] = body
        return body

    def delete_event(self, event_id: str) -> None:
        self.deleted.add(event_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_adapter(fake_repo: FakeRepository, schedule=None) -> GoogleCalendarAdapter:
    return GoogleCalendarAdapter(
        credentials_path="fake",
        calendar_id="fake@cal",
        schedule=schedule or {"mon": ["10:00-14:00"]},
        timezone=TZ,
        slot_duration_min=30,
        lookahead_days_client=14,
        lookahead_days_manual=60,
        _repo=fake_repo,
    )


def make_timed_event(start_str: str, end_str: str) -> dict:
    base = TEST_DATE_STR
    return {
        "start": {"dateTime": f"{base}T{start_str}:00+01:00"},
        "end": {"dateTime": f"{base}T{end_str}:00+01:00"},
        "summary": "Existing booking",
    }


def make_description(**fields: str) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fields.items())


# ---------------------------------------------------------------------------
# list_slots tests
# ---------------------------------------------------------------------------


def test_list_slots_open_day_no_events() -> None:
    """Monday with 10:00-14:00 schedule and no events → expected slots returned."""
    fake = FakeRepository()
    import datetime as dt
    d = dt.date(2024, 1, 8)
    fake.day_events[str(d)] = []
    adapter = build_adapter(fake)

    result = adapter.list_slots(d, service_duration_min=30, presence_min=30)

    assert "10:00" in result
    assert "13:30" in result
    assert len(result) == 8  # 10:00 through 13:30 every 30 min


def test_list_slots_closed_day() -> None:
    """Schedule with no Monday entry → empty list."""
    fake = FakeRepository()
    import datetime as dt
    d = dt.date(2024, 1, 8)
    adapter = build_adapter(fake, schedule={"tue": ["10:00-14:00"]})

    result = adapter.list_slots(d, service_duration_min=30, presence_min=30)

    assert result == []


def test_list_slots_event_blocks_slot() -> None:
    """One timed event at 10:00-10:30 → 10:00 slot excluded."""
    fake = FakeRepository()
    import datetime as dt
    d = dt.date(2024, 1, 8)
    fake.day_events[str(d)] = [make_timed_event("10:00", "10:30")]
    adapter = build_adapter(fake)

    result = adapter.list_slots(d, service_duration_min=30, presence_min=30)

    assert "10:00" not in result
    assert "10:30" in result


def test_list_slots_cfg_cerrado() -> None:
    """[CFG] CERRADO all-day event → no slots."""
    fake = FakeRepository()
    import datetime as dt
    d = dt.date(2024, 1, 8)
    fake.day_events[str(d)] = [
        {
            "start": {"date": "2024-01-08"},
            "end": {"date": "2024-01-09"},
            "summary": "[CFG] CERRADO",
        }
    ]
    adapter = build_adapter(fake)

    result = adapter.list_slots(d, service_duration_min=30, presence_min=30)

    assert result == []


# ---------------------------------------------------------------------------
# create_event tests
# ---------------------------------------------------------------------------


def test_create_event_returns_event_id() -> None:
    """create_event returns the id from the fake repository response."""
    fake = FakeRepository()
    adapter = build_adapter(fake)
    tz = ZoneInfo(TZ)
    slot_dt = datetime(2024, 1, 8, 10, 0, tzinfo=tz)

    event_id = adapter.create_event(
        slot_dt=slot_dt,
        contact_id="+34600000000",
        service_key="test_svc",
        contact_name="Ana",
        duration_min=30,
    )

    assert event_id == "evt_new_123"


def test_create_event_body_has_canonical_fields() -> None:
    """The event body passed to repository contains required description fields."""
    fake = FakeRepository()
    adapter = build_adapter(fake)
    tz = ZoneInfo(TZ)
    slot_dt = datetime(2024, 1, 8, 10, 0, tzinfo=tz)

    adapter.create_event(
        slot_dt=slot_dt,
        contact_id="+34600000000",
        service_key="test_svc",
        contact_name="Ana",
        duration_min=30,
    )

    assert len(fake.created) == 1
    body = fake.created[0]
    description = body["description"]
    assert "Nombre: Ana" in description
    assert "Telefono: +34600000000" in description
    assert "Servicio: test_svc" in description
    assert "Estado: pendiente" in description
    assert "Recordatorio: no" in description


def test_create_event_end_time_uses_duration() -> None:
    """The event body end time equals start + duration_min."""
    fake = FakeRepository()
    adapter = build_adapter(fake)
    tz = ZoneInfo(TZ)
    slot_dt = datetime(2024, 1, 8, 10, 0, tzinfo=tz)

    adapter.create_event(
        slot_dt=slot_dt,
        contact_id="+34600000000",
        service_key="test_svc",
        contact_name="Ana",
        duration_min=45,
    )

    body = fake.created[0]
    end_dt = datetime.fromisoformat(body["end"]["dateTime"])
    expected_end = slot_dt + timedelta(minutes=45)
    # Compare as isoformat strings to avoid tz offset differences
    assert end_dt.isoformat() == expected_end.isoformat()


# ---------------------------------------------------------------------------
# cancel_event tests
# ---------------------------------------------------------------------------


def test_cancel_event_calls_delete() -> None:
    """cancel_event delegates to repo.delete_event with the correct event_id."""
    fake = FakeRepository()
    adapter = build_adapter(fake)

    adapter.cancel_event("evt_abc")

    assert "evt_abc" in fake.deleted


# ---------------------------------------------------------------------------
# get_event tests
# ---------------------------------------------------------------------------


def test_get_event_normalizes_fields() -> None:
    """get_event returns dict with 'telefono', 'nombre', 'servicio', 'estado', 'recordatorio'."""
    fake = FakeRepository()
    fake.events["evt_001"] = {
        "id": "evt_001",
        "summary": "test_svc - Ana",
        "description": make_description(
            Nombre="Ana",
            Telefono="+34600000000",
            Servicio="test_svc",
            Estado="pendiente",
            Recordatorio="no",
        ),
        "start": {"dateTime": "2024-01-08T10:00:00+01:00"},
        "end": {"dateTime": "2024-01-08T10:30:00+01:00"},
    }
    adapter = build_adapter(fake)

    result = adapter.get_event("evt_001")

    assert result["event_id"] == "evt_001"
    assert result["telefono"] == "+34600000000"
    assert result["nombre"] == "Ana"
    assert result["servicio"] == "test_svc"
    assert result["estado"] == "pendiente"
    assert result["recordatorio"] == "no"


def test_get_event_strips_html() -> None:
    """HTML tags in description are removed before field extraction."""
    fake = FakeRepository()
    # Google Calendar wraps descriptions in HTML; each field is on its own line
    # separated by <br> which strip_html converts to a space, preserving line
    # integrity as long as fields are on separate source lines.
    fake.events["evt_002"] = {
        "id": "evt_002",
        "summary": "test_svc - Bob",
        "description": "<b>Nombre: Bob</b>\nTelefono: +34611111111",
        "start": {"dateTime": "2024-01-08T11:00:00+01:00"},
        "end": {"dateTime": "2024-01-08T11:30:00+01:00"},
    }
    adapter = build_adapter(fake)

    result = adapter.get_event("evt_002")

    assert result["nombre"] == "Bob"
    assert result["telefono"] == "+34611111111"


# ---------------------------------------------------------------------------
# mark_reminder_sent tests
# ---------------------------------------------------------------------------


def test_mark_reminder_sent() -> None:
    """After mark_reminder_sent, updated description contains 'Recordatorio: sí'."""
    fake = FakeRepository()
    fake.events["evt_003"] = {
        "id": "evt_003",
        "summary": "test_svc - Ana",
        "description": make_description(
            Nombre="Ana",
            Telefono="+34600000000",
            Servicio="test_svc",
            Estado="pendiente",
            Recordatorio="no",
        ),
        "start": {},
        "end": {},
    }
    adapter = build_adapter(fake)

    adapter.mark_reminder_sent("evt_003")

    assert "evt_003" in fake.updated
    updated_desc = fake.updated["evt_003"]["description"]
    assert "Recordatorio: sí" in updated_desc


def test_mark_reminder_sent_preserves_other_fields() -> None:
    """mark_reminder_sent does not alter Nombre, Telefono, Servicio, or Estado fields."""
    fake = FakeRepository()
    fake.events["evt_004"] = {
        "id": "evt_004",
        "summary": "test_svc - Carlos",
        "description": make_description(
            Nombre="Carlos",
            Telefono="+34622222222",
            Servicio="test_svc",
            Estado="pendiente",
            Recordatorio="no",
        ),
        "start": {},
        "end": {},
    }
    adapter = build_adapter(fake)

    adapter.mark_reminder_sent("evt_004")

    updated_desc = fake.updated["evt_004"]["description"]
    assert "Nombre: Carlos" in updated_desc
    assert "Telefono: +34622222222" in updated_desc
    assert "Servicio: test_svc" in updated_desc
    assert "Estado: pendiente" in updated_desc


# ---------------------------------------------------------------------------
# mark_manual_confirmed tests
# ---------------------------------------------------------------------------


def test_mark_manual_confirmed() -> None:
    """After mark_manual_confirmed, Estado becomes 'confirmada' and Recordatorio 'no'."""
    fake = FakeRepository()
    fake.events["evt_005"] = {
        "id": "evt_005",
        "summary": "test_svc - Diana",
        "description": make_description(
            Nombre="Diana",
            Telefono="+34633333333",
            Servicio="test_svc",
            Estado="pendiente",
            Recordatorio="sí",
        ),
        "start": {},
        "end": {},
    }
    adapter = build_adapter(fake)

    adapter.mark_manual_confirmed("evt_005")

    updated_desc = fake.updated["evt_005"]["description"]
    assert "Estado: confirmada" in updated_desc
    assert "Recordatorio: no" in updated_desc


# ---------------------------------------------------------------------------
# get_pending_manual_events tests
# ---------------------------------------------------------------------------


def test_get_pending_manual_events_returns_pending() -> None:
    """Event with Telefono and Estado != confirmada is included in pending list."""
    fake = FakeRepository()
    fake.range_events = [
        {
            "id": "evt_p1",
            "summary": "test_svc - Eve",
            "description": make_description(
                Nombre="Eve",
                Telefono="+34644444444",
                Servicio="test_svc",
                Estado="pendiente",
                Recordatorio="no",
            ),
            "start": {"dateTime": "2024-01-10T10:00:00+01:00"},
            "end": {"dateTime": "2024-01-10T10:30:00+01:00"},
        }
    ]
    adapter = build_adapter(fake)

    result = adapter.get_pending_manual_events(lookahead_days=60)

    assert len(result) == 1
    assert result[0]["event_id"] == "evt_p1"
    assert result[0]["telefono"] == "+34644444444"
    assert result[0]["estado"] == "pendiente"


def test_get_pending_manual_events_excludes_confirmed() -> None:
    """Event with Estado: confirmada is excluded from pending list."""
    fake = FakeRepository()
    fake.range_events = [
        {
            "id": "evt_c1",
            "summary": "test_svc - Frank",
            "description": make_description(
                Nombre="Frank",
                Telefono="+34655555555",
                Servicio="test_svc",
                Estado="confirmada",
                Recordatorio="no",
            ),
            "start": {"dateTime": "2024-01-10T11:00:00+01:00"},
            "end": {"dateTime": "2024-01-10T11:30:00+01:00"},
        }
    ]
    adapter = build_adapter(fake)

    result = adapter.get_pending_manual_events(lookahead_days=60)

    assert result == []


def test_get_pending_manual_events_excludes_no_telefono() -> None:
    """Event without a Telefono field is excluded from pending list."""
    fake = FakeRepository()
    fake.range_events = [
        {
            "id": "evt_nt1",
            "summary": "[CFG] CERRADO",
            "description": "No hay telefono aqui",
            "start": {"date": "2024-01-10"},
            "end": {"date": "2024-01-11"},
        }
    ]
    adapter = build_adapter(fake)

    result = adapter.get_pending_manual_events(lookahead_days=60)

    assert result == []
