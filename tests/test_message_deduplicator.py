# tests/test_message_deduplicator.py
"""Unit tests for app/utils/dedup.py."""
from datetime import datetime, timedelta
from unittest.mock import patch

from app.utils.dedup import MessageDeduplicator


class TestMessageDeduplicator:
    def test_first_seen_returns_false(self):
        dedup = MessageDeduplicator(ttl_minutes=10)
        assert dedup.seen("id_1") is False

    def test_second_seen_returns_true(self):
        dedup = MessageDeduplicator(ttl_minutes=10)
        dedup.seen("id_1")
        assert dedup.seen("id_1") is True

    def test_seen_returns_false_after_ttl_expiry(self):
        dedup = MessageDeduplicator(ttl_minutes=10)
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)

        with patch("app.utils.dedup.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            # First call — registers the ID at fixed_now
            assert dedup.seen("id_1") is False

        # Advance time past TTL (11 minutes later)
        advanced_now = fixed_now + timedelta(minutes=11)
        with patch("app.utils.dedup.datetime") as mock_dt:
            mock_dt.now.return_value = advanced_now
            # The entry is expired, so it should be treated as new
            assert dedup.seen("id_1") is False

    def test_different_ids_are_independent(self):
        dedup = MessageDeduplicator(ttl_minutes=10)
        assert dedup.seen("a") is False
        assert dedup.seen("b") is False

    def test_forget_allows_id_to_be_seen_again(self):
        dedup = MessageDeduplicator(ttl_minutes=10)
        assert dedup.seen("id_1") is False
        assert dedup.seen("id_1") is True
        dedup.forget("id_1")
        assert dedup.seen("id_1") is False
