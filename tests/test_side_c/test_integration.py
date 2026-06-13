"""Integration tests for Side C — full end-to-end chain.

Tests the complete flow:
  Approved Emitter → ingest_layer → event_router → store → query_layer → read_model_builder

Also tests rejection paths:
  - Unknown emitter rejection
  - Unauthorized family rejection
  - Append-only verification
"""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory import (
    EventFamily,
    MemoryQuery,
    build_blocked_actions_summary,
    build_decision_review_summary,
    build_health_timeline_summary,
    build_override_history_summary,
    build_trade_history_summary,
    clear_event_store,
    clear_journal_store,
    clear_reference_store,
    get_event,
    get_journal,
    get_reference,
    get_trade_history,
    query_cross_store,
    ingest_event,
    route_event,
    set_event_router,
    set_store_callback,
)
from junior_aladdin.side_c_memory.event_store import append_event as es_append
from junior_aladdin.side_c_memory.journal_store import append_journal as js_append
from junior_aladdin.side_c_memory.reference_store import store_reference as rs_store


@pytest.fixture(autouse=True)
def reset_all():
    """Reset all stores and disconnect router/callbacks before each test."""
    clear_event_store()
    clear_journal_store()
    clear_reference_store()
    set_event_router(None)
    set_store_callback("event_store", None)
    set_store_callback("journal_store", None)
    set_store_callback("reference_store", None)
    yield
    clear_event_store()
    clear_journal_store()
    clear_reference_store()
    set_event_router(None)
    set_store_callback("event_store", None)
    set_store_callback("journal_store", None)
    set_store_callback("reference_store", None)


def _connect_pipeline():
    """Connect the full ingest → router → store pipeline."""
    set_store_callback("event_store", es_append)
    set_store_callback("journal_store", js_append)
    set_store_callback("reference_store", rs_store)
    set_event_router(route_event)


# =============================================================================
# Full integration tests
# =============================================================================

class TestFullPipeline:
    """Test full end-to-end chain for each emitter."""

    def test_floor_1_health_event_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "connection_degraded",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "CAUTION",
            "payload": {"state": "DEGRADED", "source_name": "angel_one_ws"},
            "refs": {"connection_id": "conn_123"},
        }, "floor_1")

        # Verify event was stored
        assert event.envelope_id is not None
        assert event.envelope_id.startswith("env_")

        # Query back
        results = query_cross_store(
            MemoryQuery(
                families=[EventFamily.HEALTH_EVENT],
                start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        assert len(results) >= 1
        assert results[0].family == MemoryEventFamily.HEALTH_EVENT
        assert results[0].source == "floor_1"

        # Read model works
        summary = build_health_timeline_summary(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert summary.event_count >= 1
        assert summary.family == MemoryEventFamily.HEALTH_EVENT

    def test_side_a_trade_journal_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "trade_completed",
            "source": "side_a",
            "emitter": "side_a",
            "family": "TRADE_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "trade_id": "T123",
                "entry": 18500.0,
                "exit": 18650.0,
                "pnl": 1500.0,
                "mode": "PAPER",
            },
            "refs": {"trade_id": "T123", "decision_id": "D456"},
        }, "side_a")

        assert event is not None
        assert event.family == MemoryEventFamily.TRADE_JOURNAL

        # Query trade history
        history = get_trade_history("T123")
        assert len(history) >= 1

        # Read model
        summary = build_trade_history_summary("T123")
        assert summary.event_count >= 1
        assert summary.family == MemoryEventFamily.TRADE_JOURNAL

    def test_floor_5_decision_journal_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "decision_made",
            "source": "floor_5",
            "emitter": "floor_5",
            "family": "DECISION_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "decision": "TRADE",
                "conviction_band": "STRONG",
                "reason": "4/5 heads aligned",
            },
            "refs": {"decision_id": "D456"},
        }, "floor_5")

        assert event is not None
        assert event.family == MemoryEventFamily.DECISION_JOURNAL

        # Read model
        summary = build_decision_review_summary("D456")
        assert summary.event_count >= 1

    def test_side_a_execution_event_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "order_placed",
            "source": "side_a",
            "emitter": "side_a",
            "family": "EXECUTION_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "order_id": "O789",
                "action": "BUY",
                "status": "PLACED",
            },
            "refs": {"trade_id": "T123"},
        }, "side_a")

        assert event is not None
        assert event.family == MemoryEventFamily.EXECUTION_EVENT

    def test_side_a_override_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "parameter_override",
            "source": "side_a",
            "emitter": "side_a",
            "family": "OVERRIDE",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "SEVERE",
            "payload": {
                "reason": "Manual intervention",
                "override_type": "PARAMETER",
            },
        }, "side_a")

        assert event is not None
        summary = build_override_history_summary()
        assert summary.event_count >= 1

    def test_side_a_blocked_action_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "order_blocked",
            "source": "side_a",
            "emitter": "side_a",
            "family": "BLOCKED_ACTION",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "CAUTION",
            "payload": {
                "reason": "Risk limit exceeded",
                "action": "BUY",
                "block_level": "HARD",
            },
        }, "side_a")

        assert event is not None
        summary = build_blocked_actions_summary()
        assert summary.event_count >= 1

    def test_floor_2_replay_ref_pipeline(self):
        _connect_pipeline()

        event = ingest_event({
            "event_type": "replay_created",
            "source": "floor_2",
            "emitter": "floor_2",
            "family": "REPLAY_REF",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "ref_key": "trade_id:T123",
                "replay_session_id": "RS_001",
            },
            "refs": {"ref_key": "trade_id:T123"},
        }, "floor_2")

        assert event is not None
        assert event.family == MemoryEventFamily.REPLAY_REF


class TestRejectionPaths:
    """Test that invalid events are properly rejected."""

    def test_unknown_emitter_rejected(self):
        with pytest.raises(ValueError, match="Unauthorised emitter"):
            ingest_event({
                "event_type": "test",
                "source": "unknown",
                "emitter": "unknown",
                "family": "HEALTH_EVENT",
                "timestamp": "2026-06-09T10:00:00Z",
                "severity": "INFO",
                "payload": {"state": "HEALTHY", "source_name": "test"},
            }, "unknown_emitter")

    def test_floor_1_cannot_write_trade_journal(self):
        with pytest.raises(ValueError, match="not allowed to write"):
            ingest_event({
                "event_type": "trade",
                "source": "floor_1",
                "emitter": "floor_1",
                "family": "TRADE_JOURNAL",
                "timestamp": "2026-06-09T10:00:00Z",
                "severity": "INFO",
                "payload": {
                    "trade_id": "T1", "entry": 100, "exit": 200,
                    "pnl": 100, "mode": "PAPER",
                },
            }, "floor_1")

    def test_malformed_event_rejected(self):
        with pytest.raises(ValueError, match="Unauthorised|missing|Unknown"):
            ingest_event({
                "source": "floor_1",
                "emitter": "floor_1",
            }, "floor_1")


class TestAppendOnly:
    """Verify append-first is enforced globally."""

    def test_append_only_events(self):
        _connect_pipeline()
        event = ingest_event({
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }, "floor_1")

        # Verify the event is unchanged when retrieved via query
        results = query_cross_store(
            MemoryQuery(families=[EventFamily.HEALTH_EVENT])
        )
        assert len(results) >= 1
        retrieved = results[0]
        assert retrieved.envelope_id == event.envelope_id
        assert retrieved.family == MemoryEventFamily.HEALTH_EVENT
        assert retrieved.source == "floor_1"
        assert retrieved.event_type == "test"

    def test_multiple_emitters_independent(self):
        """Multiple emitters can write to their respective families."""
        _connect_pipeline()

        # floor_1 writes health event
        ingest_event({
            "event_type": "health_check",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }, "floor_1")

        # side_a writes trade journal
        ingest_event({
            "event_type": "trade_completed",
            "source": "side_a",
            "emitter": "side_a",
            "family": "TRADE_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "trade_id": "T1", "entry": 100, "exit": 200,
                "pnl": 100, "mode": "PAPER",
            },
            "refs": {"trade_id": "T1"},
        }, "side_a")

        # floor_5 writes decision journal
        ingest_event({
            "event_type": "decision",
            "source": "floor_5",
            "emitter": "floor_5",
            "family": "DECISION_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "decision": "TRADE",
                "conviction_band": "MODERATE",
                "reason": "Test",
            },
            "refs": {"decision_id": "D1"},
        }, "floor_5")

        # All 3 should co-exist
        results = query_cross_store(MemoryQuery())
        assert len(results) == 3
