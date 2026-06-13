"""Tests for execution_logging_layer.py — ExecutionLoggingLayer.

Tests cover:
- Family resolution for each event type
- Severity resolution for each event type
- Side C ingestion (mock ingest_event)
- Dashboard callback invocation
- Recent events buffer and query API
- Edge cases (unknown events, missing data, ingest failures)
- Integration with orchestrator-style data
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from junior_aladdin.shared.types import Severity
from junior_aladdin.side_a_execution.execution_logging_layer import (
    ExecutionLoggingLayer,
    _BLOCKED_ACTION_TYPES,
    _CAUTION_EVENT_TYPES,
    _EXECUTION_EVENT_TYPES,
    _KNOWN_EVENT_TYPES,
    _OVERRIDE_TYPES,
    _SEVERE_EVENT_TYPES,
    _TRADE_JOURNAL_TYPES,
)
from junior_aladdin.side_c_memory.c_types import EventFamily


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_side_c_ingest() -> MagicMock:
    """Mock Side C ingest_event function."""
    return MagicMock()


@pytest.fixture
def mock_dashboard() -> MagicMock:
    """Mock dashboard callback."""
    return MagicMock()


@pytest.fixture
def logging_layer(mock_side_c_ingest, mock_dashboard) -> ExecutionLoggingLayer:
    """ExecutionLoggingLayer with mocked dependencies."""
    return ExecutionLoggingLayer(
        side_c_ingest=mock_side_c_ingest,
        on_dashboard_event=mock_dashboard,
        max_recent_events=50,
    )


@pytest.fixture
def logging_layer_no_side_c(mock_dashboard) -> ExecutionLoggingLayer:
    """ExecutionLoggingLayer without Side C connection."""
    return ExecutionLoggingLayer(
        side_c_ingest=None,
        on_dashboard_event=mock_dashboard,
    )


@pytest.fixture
def standard_data() -> dict[str, object]:
    """Standard event data dict."""
    return {
        "trade_id": "TRADE-001",
        "order_id": "ORD-001",
        "mode": "PAPER",
        "status": "active",
    }


# =============================================================================
# Family Resolution Tests
# =============================================================================


class TestResolveFamily:
    """Verify event_type → EventFamily mapping."""

    def test_execution_event_types(self, logging_layer: ExecutionLoggingLayer):
        """All EXECUTION_EVENT types resolve correctly."""
        for et in _EXECUTION_EVENT_TYPES:
            assert logging_layer._resolve_family(et) == EventFamily.EXECUTION_EVENT, \
                f"{et} should map to EXECUTION_EVENT"

    def test_blocked_action_types(self, logging_layer: ExecutionLoggingLayer):
        """All BLOCKED_ACTION types resolve correctly."""
        for et in _BLOCKED_ACTION_TYPES:
            assert logging_layer._resolve_family(et) == EventFamily.BLOCKED_ACTION, \
                f"{et} should map to BLOCKED_ACTION"

    def test_trade_journal_types(self, logging_layer: ExecutionLoggingLayer):
        """All TRADE_JOURNAL types resolve correctly."""
        for et in _TRADE_JOURNAL_TYPES:
            assert logging_layer._resolve_family(et) == EventFamily.TRADE_JOURNAL, \
                f"{et} should map to TRADE_JOURNAL"

    def test_override_types(self, logging_layer: ExecutionLoggingLayer):
        """All OVERRIDE types resolve correctly."""
        for et in _OVERRIDE_TYPES:
            assert logging_layer._resolve_family(et) == EventFamily.OVERRIDE, \
                f"{et} should map to OVERRIDE"

    def test_unknown_event_type_defaults_to_execution(self, logging_layer: ExecutionLoggingLayer):
        """Unknown event types default to EXECUTION_EVENT."""
        assert logging_layer._resolve_family("UNKNOWN_EVENT") == EventFamily.EXECUTION_EVENT
        assert logging_layer._resolve_family("CUSTOM_EVENT_TYPE") == EventFamily.EXECUTION_EVENT
        assert logging_layer._resolve_family("") == EventFamily.EXECUTION_EVENT


# =============================================================================
# Severity Resolution Tests
# =============================================================================


class TestResolveSeverity:
    """Verify event_type → Severity mapping."""

    def test_severe_event_types(self, logging_layer: ExecutionLoggingLayer):
        """All SEVERE event types resolve correctly."""
        for et in _SEVERE_EVENT_TYPES:
            assert logging_layer._resolve_severity(et) == Severity.SEVERE, \
                f"{et} should map to SEVERE"

    def test_caution_event_types(self, logging_layer: ExecutionLoggingLayer):
        """All CAUTION event types resolve correctly."""
        for et in _CAUTION_EVENT_TYPES:
            assert logging_layer._resolve_severity(et) == Severity.CAUTION, \
                f"{et} should map to CAUTION"

    def test_info_event_types(self, logging_layer: ExecutionLoggingLayer):
        """All other event types resolve to INFO."""
        for et in _EXECUTION_EVENT_TYPES:
            if et not in _SEVERE_EVENT_TYPES and et not in _CAUTION_EVENT_TYPES:
                assert logging_layer._resolve_severity(et) == Severity.INFO, \
                    f"{et} should map to INFO"

    def test_unknown_event_type_info(self, logging_layer: ExecutionLoggingLayer):
        """Unknown event types default to INFO."""
        assert logging_layer._resolve_severity("UNKNOWN_EVENT") == Severity.INFO


# =============================================================================
# Build Payload Tests
# =============================================================================


class TestBuildPayload:
    """Verify payload construction strips reserved fields."""

    def test_strips_reserved_fields(self, logging_layer: ExecutionLoggingLayer):
        """Reserved MemoryEvent fields are removed from payload."""
        data = {
            "family": "EXECUTION_EVENT",
            "source": "side_a",
            "emitter": "side_a",
            "timestamp": "2025-01-01T00:00:00Z",
            "severity": "INFO",
            "refs": {"trade_id": "T001"},
            "trade_id": "T001",
            "order_id": "ORD001",
        }
        payload = logging_layer._build_payload("DECISION_ACCEPTED", data)
        assert "family" not in payload
        assert "source" not in payload
        assert "emitter" not in payload
        assert "timestamp" not in payload
        assert "severity" not in payload
        assert "refs" not in payload

    def test_preserves_other_fields(self, logging_layer: ExecutionLoggingLayer):
        """Non-reserved fields are preserved in payload."""
        data = {
            "trade_id": "T001",
            "order_id": "ORD001",
            "mode": "PAPER",
            "execution_path": "REAL",
        }
        payload = logging_layer._build_payload("DECISION_ACCEPTED", data)
        assert payload["trade_id"] == "T001"
        assert payload["order_id"] == "ORD001"
        assert payload["mode"] == "PAPER"
        assert payload["execution_path"] == "REAL"

    def test_includes_event_type(self, logging_layer: ExecutionLoggingLayer):
        """Event type is always included in payload."""
        payload = logging_layer._build_payload("FILL_PROCESSED", {})
        assert payload["event_type"] == "FILL_PROCESSED"

    def test_empty_data(self, logging_layer: ExecutionLoggingLayer):
        """Empty data dict produces payload with just event_type."""
        payload = logging_layer._build_payload("EXIT_COMPLETE", {})
        assert payload == {"event_type": "EXIT_COMPLETE"}


# =============================================================================
# Log Method — Core Tests
# =============================================================================


class TestLog:
    """Verify the main log() method end-to-end."""

    def test_side_c_ingest_called_execution_event(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
        standard_data: dict[str, object],
    ):
        """DECISION_ACCEPTED → ingest_event called with EXECUTION_EVENT family."""
        logging_layer.log("DECISION_ACCEPTED", standard_data)
        mock_side_c_ingest.assert_called_once()
        call_kwargs = mock_side_c_ingest.call_args[1]
        assert call_kwargs["emitter_id"] == "side_a"
        event_data = call_kwargs["event_data"]
        assert event_data["family"] == "EXECUTION_EVENT"
        assert event_data["event_type"] == "DECISION_ACCEPTED"
        assert event_data["severity"] == "INFO"
        assert event_data["refs"] == {"trade_id": "TRADE-001", "order_id": "ORD-001"}

    def test_side_c_ingest_blocked_action(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """DECISION_BLOCKED → ingest_event called with BLOCKED_ACTION family."""
        logging_layer.log("DECISION_BLOCKED", {"trade_id": "T001", "reason": "Risk gate"})
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["family"] == "BLOCKED_ACTION"
        assert event_data["severity"] == "CAUTION"

    def test_side_c_ingest_trade_journal(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """TRADE_COMPLETE → ingest_event called with TRADE_JOURNAL family."""
        logging_layer.log("TRADE_COMPLETE", {
            "trade_id": "T001",
            "entry": 150.0,
            "exit": 155.0,
            "pnl": 5.0,
        })
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["family"] == "TRADE_JOURNAL"
        assert event_data["severity"] == "INFO"

    def test_side_c_ingest_override(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """OVERRIDE_APPLIED → ingest_event called with OVERRIDE family."""
        logging_layer.log("OVERRIDE_APPLIED", {
            "trade_id": "T001",
            "override_type": "PARAMETER",
            "reason": "Manual adjustment",
        })
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["family"] == "OVERRIDE"
        assert event_data["severity"] == "INFO"

    def test_dashboard_callback_called(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_dashboard: MagicMock,
        standard_data: dict[str, object],
    ):
        """Dashboard callback receives structured event data."""
        logging_layer.log("FILL_PROCESSED", standard_data)
        mock_dashboard.assert_called_once()
        call_type, call_data = mock_dashboard.call_args[0]
        assert call_type == "FILL_PROCESSED"
        assert call_data["family"] == "EXECUTION_EVENT"
        assert call_data["severity"] == "INFO"
        assert call_data["payload"]["trade_id"] == "TRADE-001"
        assert "timestamp" in call_data

    def test_severe_event_dashboard(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_dashboard: MagicMock,
    ):
        """Severe events include SEVERE severity in dashboard data."""
        logging_layer.log("EMERGENCY_FLATTEN", {"trade_id": "T001"})
        call_data = mock_dashboard.call_args[0][1]
        assert call_data["severity"] == "SEVERE"

    def test_buffer_updated(
        self,
        logging_layer: ExecutionLoggingLayer,
        standard_data: dict[str, object],
    ):
        """Recent events buffer is updated after each log."""
        assert len(logging_layer._recent_events) == 0
        logging_layer.log("DECISION_ACCEPTED", standard_data)
        assert len(logging_layer._recent_events) == 1
        logging_layer.log("FILL_PROCESSED", standard_data)
        assert len(logging_layer._recent_events) == 2

    def test_buffer_max_size(
        self,
        mock_side_c_ingest: MagicMock,
        mock_dashboard: MagicMock,
    ):
        """Buffer respects max_recent_events limit."""
        layer = ExecutionLoggingLayer(
            side_c_ingest=mock_side_c_ingest,
            on_dashboard_event=mock_dashboard,
            max_recent_events=5,
        )
        for i in range(10):
            layer.log("DECISION_ACCEPTED", {"trade_id": f"T{i:03d}"})
        assert len(layer._recent_events) == 5

    def test_emitter_id_used(
        self,
        mock_side_c_ingest: MagicMock,
        mock_dashboard: MagicMock,
    ):
        """Custom emitter ID is used in ingest calls."""
        layer = ExecutionLoggingLayer(
            side_c_ingest=mock_side_c_ingest,
            on_dashboard_event=mock_dashboard,
            emitter_id="custom_emitter",
        )
        layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        assert mock_side_c_ingest.call_args[1]["emitter_id"] == "custom_emitter"

    def test_side_c_ingest_not_configured(
        self,
        logging_layer_no_side_c: ExecutionLoggingLayer,
        mock_dashboard: MagicMock,
    ):
        """No crash when Side C ingest is None."""
        logging_layer_no_side_c.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        # Dashboard still called
        mock_dashboard.assert_called_once()


# =============================================================================
# Log Method — Error Handling Tests
# =============================================================================


class TestLogErrorHandling:
    """Verify the log() method handles errors gracefully."""

    def test_side_c_ingest_raises_value_error(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
        mock_dashboard: MagicMock,
    ):
        """ValueError from Side C ingest does not propagate."""
        mock_side_c_ingest.side_effect = ValueError("Invalid family")
        # Should not raise
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        # Dashboard still called
        mock_dashboard.assert_called_once()

    def test_dashboard_callback_raises(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_dashboard: MagicMock,
    ):
        """Exception from dashboard callback does not propagate."""
        mock_dashboard.side_effect = RuntimeError("Dashboard down")
        # Should not raise
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})

    def test_no_crash_on_empty_data(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """Empty data dict does not cause crash."""
        # Should not raise
        logging_layer.log("DECISION_ACCEPTED", {})

    def test_no_crash_on_none_data(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """None event type is handled without crash."""
        logging_layer.log("", {"trade_id": "T001"})


# =============================================================================
# Query API Tests
# =============================================================================


class TestGetRecentEvents:
    """Verify get_recent_events query method."""

    def test_returns_newest_first(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """Events are returned newest first."""
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        logging_layer.log("FILL_PROCESSED", {"trade_id": "T001"})
        results = logging_layer.get_recent_events()
        assert len(results) == 2
        assert results[0]["event_type"] == "FILL_PROCESSED"  # newest
        assert results[1]["event_type"] == "DECISION_ACCEPTED"  # oldest

    def test_filter_by_event_type(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """Can filter by event type."""
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        logging_layer.log("FILL_PROCESSED", {"trade_id": "T001"})
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T002"})
        results = logging_layer.get_recent_events(event_type_filter="DECISION_ACCEPTED")
        assert len(results) == 2
        assert all(r["event_type"] == "DECISION_ACCEPTED" for r in results)

    def test_filter_by_family(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """Can filter by family."""
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        logging_layer.log("DECISION_BLOCKED", {"trade_id": "T001"})
        results = logging_layer.get_recent_events(family_filter="BLOCKED_ACTION")
        assert len(results) == 1
        assert results[0]["event_type"] == "DECISION_BLOCKED"

    def test_limit(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """Limit parameter caps results."""
        for i in range(10):
            logging_layer.log("DECISION_ACCEPTED", {"trade_id": f"T{i:03d}"})
        results = logging_layer.get_recent_events(limit=3)
        assert len(results) == 3

    def test_empty_buffer(self, logging_layer: ExecutionLoggingLayer):
        """Empty buffer returns empty list."""
        assert logging_layer.get_recent_events() == []


class TestCountEvents:
    """Verify count_events method."""

    def test_counts_all(self, logging_layer: ExecutionLoggingLayer):
        """Counts all events when no filter."""
        logging_layer.log("DECISION_ACCEPTED", {})
        logging_layer.log("FILL_PROCESSED", {})
        assert logging_layer.count_events() == 2

    def test_counts_by_type(self, logging_layer: ExecutionLoggingLayer):
        """Counts events of specific type."""
        logging_layer.log("DECISION_ACCEPTED", {})
        logging_layer.log("DECISION_ACCEPTED", {})
        logging_layer.log("FILL_PROCESSED", {})
        assert logging_layer.count_events(event_type="DECISION_ACCEPTED") == 2

    def test_counts_by_family(self, logging_layer: ExecutionLoggingLayer):
        """Counts events of specific family."""
        logging_layer.log("DECISION_ACCEPTED", {})
        logging_layer.log("DECISION_BLOCKED", {})
        assert logging_layer.count_events(family="EXECUTION_EVENT") == 1
        assert logging_layer.count_events(family="BLOCKED_ACTION") == 1

    def test_empty_buffer(self, logging_layer: ExecutionLoggingLayer):
        """Empty buffer returns 0."""
        assert logging_layer.count_events() == 0


class TestGetMetricsSummary:
    """Verify get_metrics_summary method."""

    def test_summary_structure(self, logging_layer: ExecutionLoggingLayer):
        """Metrics summary contains expected keys."""
        summary = logging_layer.get_metrics_summary()
        assert "total_events" in summary
        assert "by_event_type" in summary
        assert "by_severity" in summary
        assert "by_family" in summary

    def test_aggregates_correctly(
        self,
        logging_layer: ExecutionLoggingLayer,
    ):
        """Metrics aggregate events by type, severity, family."""
        logging_layer.log("DECISION_ACCEPTED", {"trade_id": "T001"})
        logging_layer.log("FILL_PROCESSED", {"trade_id": "T001"})
        logging_layer.log("DECISION_BLOCKED", {"trade_id": "T001"})

        summary = logging_layer.get_metrics_summary()
        assert summary["total_events"] == 3
        assert summary["by_event_type"]["DECISION_ACCEPTED"] == 1
        assert summary["by_event_type"]["FILL_PROCESSED"] == 1
        assert summary["by_event_type"]["DECISION_BLOCKED"] == 1
        assert summary["by_severity"]["INFO"] == 2
        assert summary["by_severity"]["CAUTION"] == 1
        assert summary["by_family"]["EXECUTION_EVENT"] == 2
        assert summary["by_family"]["BLOCKED_ACTION"] == 1

    def test_empty_buffer_returns_zeros(self, logging_layer: ExecutionLoggingLayer):
        """Empty buffer returns zero counts."""
        summary = logging_layer.get_metrics_summary()
        assert summary["total_events"] == 0
        assert summary["by_event_type"] == {}
        assert summary["by_severity"] == {}
        assert summary["by_family"] == {}


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Verify edge cases and boundary conditions."""

    def test_known_event_types_are_complete(self):
        """All known event types are in at least one family set."""
        # Verify the union of all family sets matches KNOWN_EVENT_TYPES
        all_types = (
            _EXECUTION_EVENT_TYPES
            | _BLOCKED_ACTION_TYPES
            | _TRADE_JOURNAL_TYPES
            | _OVERRIDE_TYPES
        )
        assert all_types == _KNOWN_EVENT_TYPES

    def test_no_overlap_between_family_sets(self):
        """No event type belongs to more than one family."""
        all_pairs = [
            ("EXECUTION", _EXECUTION_EVENT_TYPES),
            ("BLOCKED", _BLOCKED_ACTION_TYPES),
            ("JOURNAL", _TRADE_JOURNAL_TYPES),
            ("OVERRIDE", _OVERRIDE_TYPES),
        ]
        for i, (name_a, set_a) in enumerate(all_pairs):
            for j, (name_b, set_b) in enumerate(all_pairs):
                if i < j:
                    overlap = set_a & set_b
                    assert not overlap, \
                        f"Overlap between {name_a} and {name_b}: {overlap}"

    def test_no_duplicate_across_severity_sets(self):
        """No event type is in both SEVERE and CAUTION severity sets."""
        overlap = _SEVERE_EVENT_TYPES & _CAUTION_EVENT_TYPES
        assert not overlap, f"Event types in both severity sets: {overlap}"

    def test_log_without_trade_id(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """Events without trade_id still work."""
        logging_layer.log("MODE_CHANGED", {"new_mode": "PAPER"})
        mock_side_c_ingest.assert_called_once()
        # No trade_id in refs
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["refs"] == {}

    def test_log_with_only_order_id(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """Events with only order_id still work."""
        logging_layer.log("ACKNOWLEDGEMENT_PROCESSED", {"order_id": "ORD-001"})
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["refs"] == {"order_id": "ORD-001"}


# =============================================================================
# Integration-Style Tests
# =============================================================================


class TestIntegrationScenarios:
    """Verify end-to-end scenarios with realistic event sequences."""

    def test_decision_accepted_flow(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
        mock_dashboard: MagicMock,
    ):
        """Simulate a decision accepted flow end-to-end."""
        # DECISION_ACCEPTED
        logging_layer.log("DECISION_ACCEPTED", {
            "trade_id": "T001",
            "order_id": "ORD001",
            "execution_path": "PAPER",
        })
        assert mock_side_c_ingest.call_count == 1
        assert mock_dashboard.call_count == 1
        assert mock_dashboard.call_args[0][0] == "DECISION_ACCEPTED"

    def test_fill_then_reconcile_flow(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """Simulate a fill followed by reconciliation."""
        # FILL_PROCESSED
        logging_layer.log("FILL_PROCESSED", {
            "trade_id": "T001",
            "order_id": "ORD001",
            "filled_qty": 25,
            "price": 150.0,
            "is_partial": False,
        })
        # PROTECTION_STAGED
        logging_layer.log("PROTECTION_STAGED", {
            "trade_id": "T001",
            "sl_order_id": "SL001",
            "tgt_order_id": "TGT001",
        })
        # RECONCILE_COMPLETE
        logging_layer.log("RECONCILE_COMPLETE", {
            "trade_id": "T001",
            "outcome": "MATCH",
        })
        assert mock_side_c_ingest.call_count == 3

        # Check event buffer
        events = logging_layer.get_recent_events()
        assert len(events) == 3

    def test_blocked_action_recording(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """Blocked actions record correctly to Side C."""
        logging_layer.log("DECISION_BLOCKED", {
            "trade_id": "T001",
            "reason": "Risk gate: insufficient capital",
            "mode": "REAL",
        })
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["family"] == "BLOCKED_ACTION"
        assert event_data["severity"] == "CAUTION"
        assert event_data["payload"]["reason"] == "Risk gate: insufficient capital"

    def test_emergency_flow(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
        mock_dashboard: MagicMock,
    ):
        """Emergency events propagate with SEVERE severity."""
        logging_layer.log("EMERGENCY_FLATTEN", {
            "trade_id": "T001",
            "new_state": "FLATTENED",
        })
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["severity"] == "SEVERE"
        # Dashboard gets severe too
        assert mock_dashboard.call_args[0][1]["severity"] == "SEVERE"

    def test_trade_complete_journal(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """Trade completion creates TRADE_JOURNAL entry."""
        logging_layer.log("TRADE_COMPLETE", {
            "trade_id": "T001",
            "entry": 150.0,
            "exit": 155.0,
            "pnl": 5.0,
            "mode": "PAPER",
            "duration_seconds": 3600,
        })
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["family"] == "TRADE_JOURNAL"
        payload = event_data["payload"]
        assert payload["entry"] == 150.0
        assert payload["exit"] == 155.0
        assert payload["pnl"] == 5.0

    def test_orchestrator_rejection(
        self,
        logging_layer: ExecutionLoggingLayer,
        mock_side_c_ingest: MagicMock,
    ):
        """Rejection events from orchestrator flow correctly."""
        logging_layer.log("REJECTION_PROCESSED", {
            "order_id": "ORD001",
            "trade_id": "T001",
            "reason": "INSUFFICIENT_MARGIN",
        })
        mock_side_c_ingest.assert_called_once()
        event_data = mock_side_c_ingest.call_args[1]["event_data"]
        assert event_data["severity"] == "CAUTION"
        assert event_data["payload"]["reason"] == "INSUFFICIENT_MARGIN"
