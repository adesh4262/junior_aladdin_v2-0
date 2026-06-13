"""Tests for Side C ingest layer (ingest_layer.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope
from junior_aladdin.side_c_memory.ingest_layer import (
    ingest_event,
    set_event_router,
)


def valid_health_event():
    return {
        "event_type": "connection_degraded",
        "source": "floor_1",
        "emitter": "floor_1",
        "family": "HEALTH_EVENT",
        "timestamp": "2026-06-09T10:00:00Z",
        "severity": "CAUTION",
        "payload": {
            "state": "DEGRADED",
            "source_name": "angel_one_ws",
            "latency_ms": 2500,
        },
        "refs": {"connection_id": "conn_123"},
    }


@pytest.fixture(autouse=True)
def reset_router():
    """Clear the router callback before and after each test."""
    set_event_router(None)
    yield
    set_event_router(None)


class TestIngestValid:
    def test_ingest_health_event_from_floor_1(self):
        envelope = ingest_event(valid_health_event(), "floor_1")
        assert isinstance(envelope, MemoryEnvelope)
        assert envelope.envelope_id.startswith("env_")
        assert envelope.family.value == "HEALTH_EVENT"
        assert envelope.source == "floor_1"
        assert envelope.emitter == "floor_1"

    def test_ingest_trade_journal_from_side_a(self):
        event = {
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
            "refs": {"decision_id": "D456"},
        }
        envelope = ingest_event(event, "side_a")
        assert envelope.family.value == "TRADE_JOURNAL"

    def test_ingest_decision_journal_from_floor_5(self):
        event = {
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
        }
        envelope = ingest_event(event, "floor_5")
        assert envelope.family.value == "DECISION_JOURNAL"

    def test_envelope_has_auto_generated_id(self):
        envelope = ingest_event(valid_health_event(), "floor_1")
        assert envelope.envelope_id != ""

    def test_ingest_with_timestamp_parsing(self):
        event = valid_health_event()
        envelope = ingest_event(event, "floor_1")
        assert envelope.timestamp is not None
        assert envelope.timestamp.tzinfo is not None


class TestIngestRejection:
    def test_unknown_emitter_rejected(self):
        with pytest.raises(ValueError, match="Unauthorised emitter"):
            ingest_event(valid_health_event(), "unknown_emitter")

    def test_wrong_family_for_emitter_rejected(self):
        # floor_1 cannot write TRADE_JOURNAL
        event = {
            "event_type": "trade_completed",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "TRADE_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"trade_id": "T123", "entry": 18500, "exit": 18650, "pnl": 1500, "mode": "PAPER"},
        }
        with pytest.raises(ValueError, match="not allowed to write"):
            ingest_event(event, "floor_1")

    def test_floor_5_cannot_write_health(self):
        event = {
            "event_type": "test",
            "source": "floor_5",
            "emitter": "floor_5",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }
        with pytest.raises(ValueError, match="not allowed to write"):
            ingest_event(event, "floor_5")

    def test_malformed_event_missing_fields_rejected(self):
        # Has correct family but missing mandatory payload fields
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            # Missing 'payload' field (mandatory)
        }
        with pytest.raises(ValueError, match="validation failed|missing"):
            ingest_event(event, "floor_1")

    def test_unknown_family_rejected(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "UNKNOWN_FAMILY",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }
        with pytest.raises(ValueError, match="Unknown event family"):
            ingest_event(event, "floor_1")


class TestIngestRouterForwarding:
    def test_forwards_to_router(self):
        """Verify ingest forwards envelope to router when connected."""
        router_results = []

        def mock_router(env):
            router_results.append(env)

        set_event_router(mock_router)
        envelope = ingest_event(valid_health_event(), "floor_1")
        assert len(router_results) == 1
        assert router_results[0].envelope_id == envelope.envelope_id

    def test_works_without_router(self):
        """Verify ingest works even without a router connected."""
        envelope = ingest_event(valid_health_event(), "floor_1")
        assert envelope is not None
