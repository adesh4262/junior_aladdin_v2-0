"""Tests for Side C types (c_types.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import (
    DEFAULT_RETENTION_POLICIES,
    MemoryEnvelope,
    MemoryQuery,
    ReadModelSummary,
    RetentionPolicy,
)


class TestEventFamily:
    """Verify the 8 locked event families."""

    def test_all_families_present(self):
        families = list(MemoryEventFamily)
        assert len(families) == 8

    def test_trade_journal(self):
        assert MemoryEventFamily.TRADE_JOURNAL.value == "TRADE_JOURNAL"

    def test_decision_journal(self):
        assert MemoryEventFamily.DECISION_JOURNAL.value == "DECISION_JOURNAL"

    def test_execution_event(self):
        assert MemoryEventFamily.EXECUTION_EVENT.value == "EXECUTION_EVENT"

    def test_health_event(self):
        assert MemoryEventFamily.HEALTH_EVENT.value == "HEALTH_EVENT"

    def test_override(self):
        assert MemoryEventFamily.OVERRIDE.value == "OVERRIDE"

    def test_blocked_action(self):
        assert MemoryEventFamily.BLOCKED_ACTION.value == "BLOCKED_ACTION"

    def test_replay_ref(self):
        assert MemoryEventFamily.REPLAY_REF.value == "REPLAY_REF"

    def test_review_ref(self):
        assert MemoryEventFamily.REVIEW_REF.value == "REVIEW_REF"


class TestMemoryEnvelope:
    """Verify MemoryEnvelope dataclass and auto-ID generation."""

    def test_default_creation(self):
        env = MemoryEnvelope()
        assert env.envelope_id.startswith("env_")
        assert env.family == MemoryEventFamily.HEALTH_EVENT
        assert env.severity == Severity.INFO

    def test_custom_creation(self):
        ts = datetime.now(timezone.utc)
        env = MemoryEnvelope(
            family=MemoryEventFamily.TRADE_JOURNAL,
            event_type="trade_completed",
            source="side_a",
            emitter="side_a",
            timestamp=ts,
            severity=Severity.SEVERE,
            refs={"trade_id": "T123"},
        )
        assert env.envelope_id.startswith("env_")
        assert env.family == MemoryEventFamily.TRADE_JOURNAL
        assert env.event_type == "trade_completed"
        assert env.source == "side_a"
        assert env.emitter == "side_a"
        assert env.timestamp == ts
        assert env.severity == Severity.SEVERE
        assert env.refs == {"trade_id": "T123"}

    def test_explicit_envelope_id(self):
        env = MemoryEnvelope(envelope_id="custom_id_123")
        assert env.envelope_id == "custom_id_123"

    def test_payload_ref_default_empty(self):
        env = MemoryEnvelope()
        assert env.payload_ref == ""

    def test_refs_default_empty(self):
        env = MemoryEnvelope()
        assert env.refs == {}


class TestMemoryQuery:
    """Verify MemoryQuery dataclass."""

    def test_default_creation(self):
        q = MemoryQuery()
        assert q.families == []
        assert q.start_time is None
        assert q.end_time is None
        assert q.refs_filter is None
        assert q.limit == 100
        assert q.offset == 0

    def test_custom_creation(self):
        ts = datetime.now(timezone.utc)
        q = MemoryQuery(
            families=[MemoryEventFamily.HEALTH_EVENT],
            start_time=ts,
            end_time=ts,
            refs_filter={"trade_id": "T123"},
            limit=50,
            offset=10,
        )
        assert q.families == [MemoryEventFamily.HEALTH_EVENT]
        assert q.start_time == ts
        assert q.end_time == ts
        assert q.refs_filter == {"trade_id": "T123"}
        assert q.limit == 50
        assert q.offset == 10


class TestRetentionPolicy:
    """Verify RetentionPolicy dataclass."""

    def test_default_creation(self):
        p = RetentionPolicy()
        assert p.family == MemoryEventFamily.HEALTH_EVENT
        assert p.max_age_days == 90
        assert p.archive_after_days == 30

    def test_custom_creation(self):
        p = RetentionPolicy(
            family=MemoryEventFamily.TRADE_JOURNAL,
            max_age_days=365,
            archive_after_days=90,
        )
        assert p.family == MemoryEventFamily.TRADE_JOURNAL
        assert p.max_age_days == 365
        assert p.archive_after_days == 90

    def test_no_archive(self):
        p = RetentionPolicy(
            family=MemoryEventFamily.REPLAY_REF,
            max_age_days=30,
            archive_after_days=None,
        )
        assert p.archive_after_days is None


class TestReadModelSummary:
    """Verify ReadModelSummary dataclass."""

    def test_default_creation(self):
        s = ReadModelSummary()
        assert s.family == MemoryEventFamily.HEALTH_EVENT
        assert s.event_count == 0
        assert s.summary_data == {}

    def test_custom_creation(self):
        s = ReadModelSummary(
            family=MemoryEventFamily.TRADE_JOURNAL,
            timerange=(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc)),
            event_count=5,
            summary_data={"trade_id": "T123", "pnl": 1500},
        )
        assert s.family == MemoryEventFamily.TRADE_JOURNAL
        assert s.event_count == 5
        assert s.summary_data["trade_id"] == "T123"
        assert s.summary_data["pnl"] == 1500


class TestDefaultRetentionPolicies:
    """Verify default retention policies match roadmap specs."""

    def test_eight_policies(self):
        assert len(DEFAULT_RETENTION_POLICIES) == 8

    def test_trade_journal_365(self):
        p = [x for x in DEFAULT_RETENTION_POLICIES if x.family == MemoryEventFamily.TRADE_JOURNAL][0]
        assert p.max_age_days == 365
        assert p.archive_after_days == 90

    def test_health_event_90(self):
        p = [x for x in DEFAULT_RETENTION_POLICIES if x.family == MemoryEventFamily.HEALTH_EVENT][0]
        assert p.max_age_days == 90
        assert p.archive_after_days == 30

    def test_replay_ref_30_no_archive(self):
        p = [x for x in DEFAULT_RETENTION_POLICIES if x.family == MemoryEventFamily.REPLAY_REF][0]
        assert p.max_age_days == 30
        assert p.archive_after_days is None
