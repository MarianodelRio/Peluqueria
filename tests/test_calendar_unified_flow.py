# tests/test_calendar_unified_flow.py
"""
Integration tests for the unified get_slots_disponibles(mode=) API.
Mocks events_repo.list_for_day / list_for_range — no real credentials needed.
"""
import pytest
from datetime import date
from unittest.mock import patch

import pytz

TZ = pytz.timezone("Europe/Madrid")

# A Sunday far in the future — no HORARIO_BASE entry → only valid via evento mode
_EVENT_DAY = date(2099, 12, 25)
_NORMAL_DAY = date(2026, 3, 24)  # Tuesday with HORARIO_BASE slots


@pytest.fixture(autouse=True)
def clear_slot_cache():
    """Clear the slot cache before and after each test."""
    from app.services.calendar.caches import slot_cache
    slot_cache.invalidate_matching(lambda k: True)
    yield
    slot_cache.invalidate_matching(lambda k: True)


class TestUnifiedGetSlotsDisponibles:

    def test_mode_normal_returns_slots(self):
        """get_slots_disponibles(mode='normal') returns slots from compute_slots."""
        from app.services.calendar.service import get_slots_disponibles

        with patch("app.services.calendar.service.events_repo") as mock_repo:
            mock_repo.list_for_day.return_value = []  # no blocking events
            slots = get_slots_disponibles(_NORMAL_DAY, mode='normal')

        # Tuesday has HORARIO_BASE entries — slots should be non-empty
        assert isinstance(slots, list)
        assert len(slots) > 0
        # 10:00 is a typical Tuesday morning slot
        assert "10:00" in slots

    def test_mode_evento_returns_event_slots(self):
        """When mode='evento' and day is in EVENTO_DIAS, slots come from event
        horario."""
        from app.services.calendar.service import get_slots_disponibles

        event_horario_cfg = {_EVENT_DAY.isoformat(): [["10:00", "12:00"]]}

        with patch("app.services.calendar.service.EVENTO_DIAS", event_horario_cfg), \
             patch("app.services.calendar.service.events_repo") as mock_repo:
            mock_repo.list_for_day.return_value = []
            slots = get_slots_disponibles(_EVENT_DAY, mode='evento')

        assert "10:00" in slots
        assert "11:30" in slots
        assert "12:00" not in slots  # last slot must finish before closing

    def test_mode_evento_returns_empty_for_unknown_day(self):
        """get_slots_disponibles(mode='evento') returns [] when day not in
        EVENTO_DIAS."""
        from app.services.calendar.service import get_slots_disponibles

        with patch("app.services.calendar.service.EVENTO_DIAS", {}):
            slots = get_slots_disponibles(_EVENT_DAY, mode='evento')

        assert slots == []

    def test_get_slots_disponibles_for_days_populates_cache_for_both_modes(self):
        """
        Cache keys use mode-based prefix:
          normal → 'YYYY-MM-DD_dur_pres'
          evento → 'evt_YYYY-MM-DD_dur_pres'
        After get_slots_disponibles_for_days, both key patterns must be present.
        """
        from app.services.calendar.service import get_slots_disponibles_for_days
        from app.services.calendar.caches import slot_cache
        from app.services.calendar.engine import slot_cache_key

        d = _NORMAL_DAY
        event_horario_cfg = {d.isoformat(): [["10:00", "12:00"]]}

        # Test normal mode — cache key has no prefix
        with patch("app.services.calendar.service.events_repo") as mock_repo:
            mock_repo.list_for_range.return_value = {d: []}
            get_slots_disponibles_for_days(
                [d], mode='normal', duracion_min=30, presencia_cliente_min=30
            )

        normal_key = slot_cache_key(d, 'normal', 30, 30)
        assert not normal_key.startswith("evt_"), "Normal key must not have evt_ prefix"
        assert slot_cache.get(normal_key) is not None

        # Test evento mode — cache key has evt_ prefix
        with patch("app.services.calendar.service.EVENTO_DIAS", event_horario_cfg), \
             patch("app.services.calendar.service.events_repo") as mock_repo:
            mock_repo.list_for_range.return_value = {d: []}
            get_slots_disponibles_for_days(
                [d], mode='evento', duracion_min=30, presencia_cliente_min=30
            )

        evt_key = slot_cache_key(d, 'evento', 30, 30)
        assert evt_key.startswith("evt_"), "Evento key must have evt_ prefix"
        assert slot_cache.get(evt_key) is not None
