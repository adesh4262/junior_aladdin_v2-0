"""Tests for Side C read model builder (read_model_builder.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope, ReadModelSummary
from junior_aladdin.side_c_memory.event_store import clear as clear_events, append_event
from junior_aladdin.side_c_memory.journal_store import clear as clear_journals, append_journal
from junior_aladdin.side_c_memory.read_model_builder import (
    build_blocked_actions_summary,
    build_decision_review_summary,
    build_health_timeline_summary,
    build_override_history_summary,
    build_trade_history_summary,
)


@pytest.fixture(autouse=True)
def reset_stores():
    clear_events()
    clear_journals()
    yield
    clear_events()
    clear_journals()


class TestBuildTradeHistorySummary:
    def test_empty_trade(self):
        summary = build_trade_history_summary("NONEXISTENT")
        assert isinstance(summary, ReadModelSummary)
        assert summary.family == MemoryEventFamily.TRADE_JOURNAL
        assert summary.event_count == 0

    def test_trade_with_journal(self):
        append_journal(MemoryEnvelope(
            family=MemoryEventFamily.TRADE_JOURNAL,
            event_type="trade_completed",
            source="side_a",
            emitter="side_a",
            timestamp=datetime(2026, 6, 9, tzinfo=timezone.utc),
            severity=Severity.INFO,
            refs={"trade_id": "T123"},
        ))
        summary = build_trade_history_summary("T123")
        assert summary.event_count >= 1
        assert "related_records" in summary.summary_data


class TestBuildDecisionReviewSummary:
    def test_empty_decision(self):
        summary = build_decision_review_summary("NONEXISTENT")
        assert isinstance(summary, ReadModelSummary)
        assert summary.family == MemoryEventFamily.DECISION_JOURNAL
        assert summary.event_count == 0

    def test_decision_with_journal(self):
        append_journal(MemoryEnvelope(
            family=MemoryEventFamily.DECISION_JOURNAL,
            event_type="decision_made",
            source="floor_5",
            emitter="floor_5",
            timestamp=datetime(2026, 6, 9, tzinfo=timezone.utc),
            severity=Severity.INFO,
            refs={"decision_id": "D456"},
        ))
        summary = build_decision_review_summary("D456")
        assert summary.event_count >= 1


class TestBuildHealthTimelineSummary:
    def test_empty_timeline(self):
        summary = build_health_timeline_summary()
        assert isinstance(summary, ReadModelSummary)
        assert summary.family == MemoryEventFamily.HEALTH_EVENT
        assert summary.event_count == 0

    def test_health_events(self):
        append_event(MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            event_type="connection_degraded",
            source="floor_1",
            emitter="floor_1",
            timestamp=datetime(2026, 6, 9, tzinfo=timezone.utc),
            severity=Severity.CAUTION,
        ))
        summary = build_health_timeline_summary()
        assert summary.event_count >= 1
        assert "severity_counts" in summary.summary_data
        assert "transitions" in summary.summary_data

    def test_health_with_timerange(self):
        append_event(MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            event_type="test",
            source="floor_1",
            emitter="floor_1",
            timestamp=datetime(2026, 6, 9, tzinfo=timezone.utc),
            severity=Severity.INFO,
        ))
        summary = build_health_timeline_summary(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        assert summary.event_count >= 1


class TestBuildOverrideHistorySummary:
    def test_empty_overrides(self):
        summary = build_override_history_summary()
        assert isinstance(summary, ReadModelSummary)
        assert summary.family == MemoryEventFamily.OVERRIDE
        assert summary.event_count == 0

    def test_override_events(self):
        append_event(MemoryEnvelope(
            family=MemoryEventFamily.OVERRIDE,
            event_type="parameter_override",
            source="side_a",
            emitter="side_a",
            timestamp=datetime(2026, 6, 9, tzinfo=timezone.utc),
            severity=Severity.SEVERE,
        ))
        summary = build_override_history_summary()
        assert summary.event_count >= 1
        assert "override_count" in summary.summary_data
        assert "reasons" in summary.summary_data


class TestBuildBlockedActionsSummary:
    def test_empty_blocked(self):
        summary = build_blocked_actions_summary()
        assert isinstance(summary, ReadModelSummary)
        assert summary.family == MemoryEventFamily.BLOCKED_ACTION
        assert summary.event_count == 0

    def test_blocked_events(self):
        append_event(MemoryEnvelope(
            family=MemoryEventFamily.BLOCKED_ACTION,
            event_type="order_blocked",
            source="side_a",
            emitter="side_a",
            timestamp=datetime(2026, 6, 9, tzinfo=timezone.utc),
            severity=Severity.CAUTION,
        ))
        summary = build_blocked_actions_summary()
        assert summary.event_count >= 1
        assert "block_count" in summary.summary_data
        assert "severity_breakdown" in summary.summary_data
