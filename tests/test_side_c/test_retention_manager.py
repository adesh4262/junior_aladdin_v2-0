"""Tests for Side C retention manager (retention_manager.py)."""

import pytest
from datetime import datetime, timedelta, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope, RetentionPolicy
from junior_aladdin.side_c_memory.event_store import clear as clear_events, append_event
from junior_aladdin.side_c_memory.journal_store import clear as clear_journals, append_journal
from junior_aladdin.side_c_memory.retention_manager import (
    apply_retention_policy,
    get_retention_status,
    set_retention_policy,
)


@pytest.fixture(autouse=True)
def reset_stores():
    clear_events()
    clear_journals()
    yield
    clear_events()
    clear_journals()


def old_event(days_ago=400):
    """Create a health event with a timestamp far in the past."""
    return MemoryEnvelope(
        family=MemoryEventFamily.HEALTH_EVENT,
        event_type="test",
        source="floor_1",
        emitter="floor_1",
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        severity=Severity.INFO,
    )


def recent_event():
    return MemoryEnvelope(
        family=MemoryEventFamily.HEALTH_EVENT,
        event_type="test",
        source="floor_1",
        emitter="floor_1",
        timestamp=datetime.now(timezone.utc),
        severity=Severity.INFO,
    )


def old_journal(days_ago=400):
    return MemoryEnvelope(
        family=MemoryEventFamily.TRADE_JOURNAL,
        event_type="test",
        source="side_a",
        emitter="side_a",
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        severity=Severity.INFO,
        refs={"trade_id": "T1"},
    )


class TestSetRetentionPolicy:
    def test_set_valid_policy(self):
        policy = RetentionPolicy(
            family=MemoryEventFamily.HEALTH_EVENT,
            max_age_days=1,
            archive_after_days=1,
        )
        set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)
        # Should not raise

    def test_set_invalid_policy_raises(self):
        policy = RetentionPolicy(
            family=MemoryEventFamily.HEALTH_EVENT,
            max_age_days=0,  # Invalid
        )
        with pytest.raises(ValueError, match=">= 1"):
            set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)

    def test_set_negative_policy_raises(self):
        policy = RetentionPolicy(family=MemoryEventFamily.HEALTH_EVENT, max_age_days=-1)
        with pytest.raises(ValueError, match=">= 1"):
            set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)


class TestGetRetentionStatus:
    def test_status_returns_per_family(self):
        append_event(recent_event())
        status = get_retention_status()
        assert "HEALTH_EVENT" in status
        assert status["HEALTH_EVENT"]["total_count"] == 1

    def test_status_shows_age(self):
        append_event(old_event(days_ago=50))
        status = get_retention_status()
        assert status["HEALTH_EVENT"]["oldest_event_age_days"] is not None


class TestApplyRetentionPolicy:
    def test_archive_old_events(self):
        # Set retention: max_age=1, archive_after=30 → events aged 1-31 days archive
        # events older than 31 days expire
        policy = RetentionPolicy(
            family=MemoryEventFamily.HEALTH_EVENT,
            max_age_days=1,
            archive_after_days=30,
        )
        set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)

        append_event(old_event(days_ago=5))   # 5 days old → archive (1 <= 5 < 31)
        append_event(recent_event())            # recent → stay

        result = apply_retention_policy()
        assert result["events_archived"] >= 1
        assert MemoryEventFamily.HEALTH_EVENT.value in result["families_affected"]

    def test_expire_very_old_events(self):
        # Retention: max_age=1, archive_after=1, so events older than 2 days expire
        policy = RetentionPolicy(
            family=MemoryEventFamily.HEALTH_EVENT,
            max_age_days=1,
            archive_after_days=1,
        )
        set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)

        append_event(old_event(days_ago=50))  # older than 2 → expire

        result = apply_retention_policy()
        assert result["events_expired"] >= 1

    def test_no_archive_direct_expiry(self):
        """archive_after_days=None means direct expiry after max_age_days."""
        policy = RetentionPolicy(
            family=MemoryEventFamily.HEALTH_EVENT,
            max_age_days=1,
            archive_after_days=None,
        )
        set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)

        append_event(old_event(days_ago=50))
        result = apply_retention_policy()
        assert result["events_expired"] >= 1
        assert result["events_archived"] == 0

    def test_recent_events_not_affected(self):
        policy = RetentionPolicy(
            family=MemoryEventFamily.HEALTH_EVENT,
            max_age_days=365,
            archive_after_days=90,
        )
        set_retention_policy(MemoryEventFamily.HEALTH_EVENT, policy)

        append_event(recent_event())
        result = apply_retention_policy()
        assert result["events_archived"] == 0
        assert result["events_expired"] == 0

    def test_archives_journals_separately(self):
        policy = RetentionPolicy(
            family=MemoryEventFamily.TRADE_JOURNAL,
            max_age_days=1,
            archive_after_days=30,
        )
        set_retention_policy(MemoryEventFamily.TRADE_JOURNAL, policy)

        append_journal(old_journal(days_ago=5))  # 5 days old → archive (1 <= 5 < 31)
        result = apply_retention_policy()
        assert result["events_archived"] >= 1

    def test_apply_does_not_crash_on_empty_store(self):
        result = apply_retention_policy()
        assert result["events_archived"] == 0
        assert result["events_expired"] == 0
        assert result["errors"] == []
