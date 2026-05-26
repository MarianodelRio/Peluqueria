"""Unit tests for the SQLite state store adapter."""

from __future__ import annotations

from datetime import datetime

from data_plane.adapters.state_store.sqlite import SQLiteStateStore
from shared.domain.conversation import ConversationState


def _make_store(tmp_path) -> SQLiteStateStore:
    db_path = str(tmp_path / "test_state.db")
    return SQLiteStateStore(db_path=db_path)


def _state(
    tenant_id: str = "t1",
    contact_id: str = "c1",
    current_state: str = "MENU",
    data: dict | None = None,
) -> ConversationState:
    now = datetime.utcnow()
    return ConversationState(
        tenant_id=tenant_id,
        contact_id=contact_id,
        current_state=current_state,
        data=data or {},
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Test 1 — save + get round-trip
# ---------------------------------------------------------------------------


def test_save_and_get_round_trip(tmp_path) -> None:
    store = _make_store(tmp_path)
    state = _state(current_state="CONFIRM", data={"name": "Alice"})
    store.save(state)

    retrieved = store.get("t1", "c1")
    assert retrieved is not None
    assert retrieved.current_state == "CONFIRM"
    assert retrieved.data == {"name": "Alice"}
    assert retrieved.tenant_id == "t1"
    assert retrieved.contact_id == "c1"
    # Datetime round-trip
    assert isinstance(retrieved.created_at, datetime)
    assert isinstance(retrieved.updated_at, datetime)


# ---------------------------------------------------------------------------
# Test 2 — delete removes row; subsequent get returns None
# ---------------------------------------------------------------------------


def test_delete_removes_row(tmp_path) -> None:
    store = _make_store(tmp_path)
    store.save(_state())
    assert store.get("t1", "c1") is not None

    store.delete("t1", "c1")
    assert store.get("t1", "c1") is None


# ---------------------------------------------------------------------------
# Test 3 — get returns None for non-existent key
# ---------------------------------------------------------------------------


def test_get_nonexistent_returns_none(tmp_path) -> None:
    store = _make_store(tmp_path)
    assert store.get("no_tenant", "no_contact") is None


# ---------------------------------------------------------------------------
# Test 4 — save is idempotent: second save with different current_state overwrites
# ---------------------------------------------------------------------------


def test_save_overwrites_existing(tmp_path) -> None:
    store = _make_store(tmp_path)
    store.save(_state(current_state="MENU"))
    store.save(_state(current_state="CONFIRM"))

    retrieved = store.get("t1", "c1")
    assert retrieved is not None
    assert retrieved.current_state == "CONFIRM"


# ---------------------------------------------------------------------------
# Test 5 — nested data dict survives JSON round-trip
# ---------------------------------------------------------------------------


def test_nested_data_survives_json_round_trip(tmp_path) -> None:
    nested = {"booking": {"slot": "09:00", "confirmed": True}, "count": 3}
    store = _make_store(tmp_path)
    store.save(_state(data=nested))

    retrieved = store.get("t1", "c1")
    assert retrieved is not None
    assert retrieved.data["booking"]["slot"] == "09:00"
    assert retrieved.data["booking"]["confirmed"] is True
    assert retrieved.data["count"] == 3


# ---------------------------------------------------------------------------
# Test 6 — two different contact_id rows are independent
# ---------------------------------------------------------------------------


def test_two_contacts_are_independent(tmp_path) -> None:
    store = _make_store(tmp_path)
    store.save(_state(contact_id="c1", current_state="MENU", data={"k": "v1"}))
    store.save(_state(contact_id="c2", current_state="CONFIRM", data={"k": "v2"}))

    r1 = store.get("t1", "c1")
    r2 = store.get("t1", "c2")

    assert r1 is not None
    assert r2 is not None
    assert r1.current_state == "MENU"
    assert r2.current_state == "CONFIRM"
    assert r1.data["k"] == "v1"
    assert r2.data["k"] == "v2"


# ---------------------------------------------------------------------------
# Test 7 — delete is a no-op if row absent
# ---------------------------------------------------------------------------


def test_delete_nonexistent_is_noop(tmp_path) -> None:
    store = _make_store(tmp_path)
    # Should not raise
    store.delete("no_tenant", "no_contact")
