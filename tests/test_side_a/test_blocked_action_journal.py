"""Tests for blocked_action_journal.py — BlockedActionJournal."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from junior_aladdin.shared.types import ExecutionMode, Severity
from junior_aladdin.side_a_execution.blocked_action_journal import (
    BlockedActionJournal,
)
from junior_aladdin.side_a_execution.side_a_types import BlockedActionRecord


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def journal() -> BlockedActionJournal:
    """Empty BlockedActionJournal."""
    return BlockedActionJournal()


@pytest.fixture
def sample_record() -> BlockedActionRecord:
    """Standard blocked action record."""
    return BlockedActionRecord(
        trade_id="T001",
        block_reason="Insufficient capital",
        mode=ExecutionMode.REAL,
        severity=Severity.CAUTION,
        details={"available": 10000, "required": 20000},
    )


@pytest.fixture
def journal_with_records(journal: BlockedActionJournal) -> BlockedActionJournal:
    """Journal with several test records."""
    records = [
        BlockedActionRecord(trade_id="T001", block_reason="Capital", severity=Severity.CAUTION),
        BlockedActionRecord(trade_id="T001", block_reason="Duplicate", severity=Severity.INFO),
        BlockedActionRecord(trade_id="T002", block_reason="Lock", severity=Severity.SEVERE),
        BlockedActionRecord(trade_id="T003", block_reason="Emergency", severity=Severity.CRITICAL),
    ]
    for r in records:
        journal.record(r)
    return journal


# =============================================================================
# Record Tests
# =============================================================================


class TestRecord:
    """Verify recording blocked actions."""

    def test_record_returns_record(self, journal: BlockedActionJournal, sample_record: BlockedActionRecord):
        """record() returns the stored record."""
        result = journal.record(sample_record)
        assert result.trade_id == "T001"
        assert result.block_reason == "Insufficient capital"

    def test_record_stored_in_journal(self, journal: BlockedActionJournal, sample_record: BlockedActionRecord):
        """Record is stored and retrievable."""
        journal.record(sample_record)
        blocks = journal.get_session_blocks()
        assert len(blocks) == 1
        assert blocks[0].trade_id == "T001"

    def test_record_sets_timestamp(self, journal: BlockedActionJournal):
        """Record gets a timestamp if not provided."""
        record = BlockedActionRecord(trade_id="T1", block_reason="Test")
        journal.record(record)
        assert record.timestamp is not None

    def test_record_block_convenience(self, journal: BlockedActionJournal):
        """record_block convenience method works."""
        result = journal.record_block(
            trade_id="T001",
            block_reason="Test block",
            mode=ExecutionMode.PAPER,
            severity=Severity.SEVERE,
            details={"key": "value"},
        )
        assert result.trade_id == "T001"
        assert result.severity == Severity.SEVERE
        assert result.details == {"key": "value"}

    def test_max_records_enforced(self):
        """Max records cap is enforced."""
        j = BlockedActionJournal(max_records=3)
        for i in range(5):
            j.record(BlockedActionRecord(trade_id=f"T{i}", block_reason=f"Reason {i}"))
        assert len(j.get_session_blocks()) == 3
        # Oldest should be T2 (dropped T0, T1)
        assert j.get_session_blocks()[0].trade_id == "T2"


# =============================================================================
# Query by Trade Tests
# =============================================================================


class TestGetByTrade:
    """Verify trade-level queries."""

    def test_get_by_trade_found(self, journal_with_records: BlockedActionJournal):
        """Records for a trade are returned."""
        blocks = journal_with_records.get_by_trade("T001")
        assert len(blocks) == 2
        assert all(b.trade_id == "T001" for b in blocks)

    def test_get_by_trade_not_found(self, journal_with_records: BlockedActionJournal):
        """No records for unknown trade returns empty."""
        blocks = journal_with_records.get_by_trade("UNKNOWN")
        assert blocks == []

    def test_get_by_trade_order(self, journal_with_records: BlockedActionJournal):
        """Results are in insertion order (oldest first)."""
        blocks = journal_with_records.get_by_trade("T001")
        assert blocks[0].block_reason == "Capital"
        assert blocks[1].block_reason == "Duplicate"


# =============================================================================
# Query by Severity Tests
# =============================================================================


class TestGetBySeverity:
    """Verify severity-based queries."""

    def test_get_by_severity_caution(self, journal_with_records: BlockedActionJournal):
        """CAUTION+ returns CAUTION, SEVERE, CRITICAL."""
        blocks = journal_with_records.get_by_severity(min_severity=Severity.CAUTION)
        severities = {b.severity for b in blocks}
        assert Severity.CAUTION in severities
        assert Severity.SEVERE in severities
        assert Severity.CRITICAL in severities
        assert Severity.INFO not in severities

    def test_get_by_severity_severe(self, journal_with_records: BlockedActionJournal):
        """SEVERE+ returns SEVERE, CRITICAL only."""
        blocks = journal_with_records.get_by_severity(min_severity=Severity.SEVERE)
        assert len(blocks) == 2
        assert all(b.severity in (Severity.SEVERE, Severity.CRITICAL) for b in blocks)

    def test_get_by_severity_newest_first(self, journal_with_records: BlockedActionJournal):
        """Results are newest first."""
        blocks = journal_with_records.get_by_severity()
        assert blocks[0].block_reason == "Emergency"


# =============================================================================
# Recent Blocks Tests
# =============================================================================


class TestGetRecent:
    """Verify recent blocks queries."""

    def test_get_recent_default(self, journal_with_records: BlockedActionJournal):
        """get_recent returns newest first by default."""
        recent = journal_with_records.get_recent()
        assert recent[0].block_reason == "Emergency"

    def test_get_recent_count(self, journal_with_records: BlockedActionJournal):
        """get_recent respects count limit."""
        recent = journal_with_records.get_recent(count=2)
        assert len(recent) == 2

    def test_get_recent_empty(self, journal: BlockedActionJournal):
        """get_recent on empty journal returns empty list."""
        assert journal.get_recent() == []


# =============================================================================
# Metrics Tests
# =============================================================================


class TestMetrics:
    """Verify metrics and summaries."""

    def test_count_by_severity(self, journal_with_records: BlockedActionJournal):
        """count_by_severity returns correct counts."""
        counts = journal_with_records.count_by_severity()
        assert counts.get("INFO", 0) == 1
        assert counts.get("CAUTION", 0) == 1
        assert counts.get("SEVERE", 0) == 1
        assert counts.get("CRITICAL", 0) == 1

    def test_count_by_trade(self, journal_with_records: BlockedActionJournal):
        """count_by_trade returns correct counts."""
        counts = journal_with_records.count_by_trade()
        assert counts.get("T001", 0) == 2
        assert counts.get("T002", 0) == 1

    def test_metrics_summary_structure(self, journal_with_records: BlockedActionJournal):
        """get_metrics_summary returns expected keys."""
        summary = journal_with_records.get_metrics_summary()
        assert "total_blocks" in summary
        assert "severity_counts" in summary
        assert "recent_reasons" in summary

    def test_metrics_summary_values(self, journal_with_records: BlockedActionJournal):
        """get_metrics_summary returns correct values."""
        summary = journal_with_records.get_metrics_summary()
        assert summary["total_blocks"] == 4
        assert "CAUTION" in summary["severity_counts"]

    def test_empty_journal_metrics(self, journal: BlockedActionJournal):
        """Empty journal returns zeros."""
        summary = journal.get_metrics_summary()
        assert summary["total_blocks"] == 0


# =============================================================================
# Log Callback Tests
# =============================================================================


class TestLogCallback:
    """Verify log callback is invoked."""

    def test_record_triggers_log(self):
        """record() triggers log callback."""
        log_mock = MagicMock()
        j = BlockedActionJournal(on_log_callback=log_mock)
        j.record(BlockedActionRecord(trade_id="T1", block_reason="Test"))
        log_mock.assert_called_once()
        assert log_mock.call_args[0][0] == "BLOCKED_ACTION_RECORDED"

    def test_record_block_triggers_log(self):
        """record_block() triggers log callback."""
        log_mock = MagicMock()
        j = BlockedActionJournal(on_log_callback=log_mock)
        j.record_block(trade_id="T1", block_reason="Test")
        log_mock.assert_called_once()


# =============================================================================
# Clear Tests
# =============================================================================


class TestClear:
    """Verify clear functionality."""

    def test_clear_empties_journal(self, journal_with_records: BlockedActionJournal):
        """Clear removes all records."""
        journal_with_records.clear()
        assert journal_with_records.get_session_blocks() == []

    def test_clear_resets_counts(self, journal_with_records: BlockedActionJournal):
        """Clear resets severity counts."""
        journal_with_records.clear()
        assert journal_with_records.count_by_severity() == {}
