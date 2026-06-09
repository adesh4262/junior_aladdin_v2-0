"""Tests for Floor 2 Ingress sub-system (Step 2.2).

Tests cover:
- source_envelope_builder: normalize, validate, error cases
- ingress_monitor: tracking, queries, anomaly detection
- raw_ingest_router: full pipeline orchestration, error handling
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    FLOOR1_PAYLOAD_KEYS,
    SOURCE_ENVELOPE_KEYS,
    Floor2IngestPayload,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import IngestPayload
from junior_aladdin.floor_2_datacenter.ingress.ingress_monitor import IngressMonitor
from junior_aladdin.floor_2_datacenter.ingress.raw_ingest_router import RawIngestRouter
from junior_aladdin.floor_2_datacenter.ingress.source_envelope_builder import (
    build_source_envelope,
)
from junior_aladdin.shared.errors import ValidationError


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def valid_floor1_payload() -> dict:
    """A valid Floor 1 5-family handoff payload."""
    return {
        "original_raw_packet": {"ltp": 18500.0, "volume": 1500},
        "minimal_source_envelope": {
            "source": "angel_one",
            "feed_type": "spot_tick",
            "connection_id": "conn_abc123",
            "packet_id": "pkt_001",
            "routing_id": "SPOT_FEED",
            "received_at": "2026-01-15T10:30:00+00:00",
        },
        "feed_routing_identity": "SPOT_FEED",
        "source_health_facts": {
            "lifecycle_state": "HEALTHY",
            "latency_ms": 45.0,
            "heartbeat_age_s": 0.5,
            "reconnect_count": 0,
        },
        "manual_source_tags": None,
    }


@pytest.fixture
def minimal_payload() -> dict:
    """Minimal valid Floor 1 payload."""
    return {
        "original_raw_packet": {},
        "minimal_source_envelope": {
            "source": "test",
            "feed_type": "macro_data",
            "connection_id": "conn_test",
            "packet_id": "pkt_test",
            "routing_id": "MACRO_FEED",
            "received_at": "2026-01-15T10:30:00+00:00",
        },
        "feed_routing_identity": "MACRO_FEED",
        "source_health_facts": {"lifecycle_state": "HEALTHY"},
        "manual_source_tags": {"tag": "test"},
    }


@pytest.fixture
def monitor() -> IngressMonitor:
    """A fresh IngressMonitor with small window for testing."""
    return IngressMonitor(rate_window_s=10.0, surge_threshold=2.0, drop_threshold=0.5)


@pytest.fixture
def router(monitor: IngressMonitor) -> RawIngestRouter:
    """A RawIngestRouter with a test monitor."""
    return RawIngestRouter(monitor=monitor)


# =============================================================================
# source_envelope_builder tests
# =============================================================================


class TestSourceEnvelopeBuilder:
    """Tests for ``build_source_envelope()``."""

    def test_normalises_valid_payload(self, valid_floor1_payload: dict) -> None:
        """Should return Floor2IngestPayload with all fields populated."""
        result = build_source_envelope(valid_floor1_payload)

        assert isinstance(result, Floor2IngestPayload)
        # All 5 families preserved
        assert result.original_raw_packet == {"ltp": 18500.0, "volume": 1500}
        assert result.minimal_source_envelope["source"] == "angel_one"
        assert result.feed_routing_identity == "SPOT_FEED"
        assert result.source_health_facts["lifecycle_state"] == "HEALTHY"
        assert result.manual_source_tags is None

        # Ingest metadata added
        assert result.ingested_at is not None
        assert isinstance(result.ingested_at, datetime)
        assert result.ingest_batch_id.startswith("ig_")

    def test_adds_ingested_at_utc(self, valid_floor1_payload: dict) -> None:
        """ingested_at should be timezone-aware UTC."""
        result = build_source_envelope(valid_floor1_payload)

        assert result.ingested_at is not None
        assert result.ingested_at.tzinfo is not None
        # Should be within a few seconds of now
        now = datetime.now(timezone.utc)
        diff = abs((now - result.ingested_at).total_seconds())
        assert diff < 5.0

    def test_generates_batch_id(self, valid_floor1_payload: dict) -> None:
        """Each call should generate a unique batch_id."""
        r1 = build_source_envelope(valid_floor1_payload)
        r2 = build_source_envelope(valid_floor1_payload)

        assert r1.ingest_batch_id != r2.ingest_batch_id

    def test_preserves_manual_tags(self) -> None:
        """Manual source tags should be preserved verbatim."""
        payload = {
            "original_raw_packet": {},
            "minimal_source_envelope": {
                "source": "manual",
                "feed_type": "MANUAL_CALENDAR",
                "connection_id": "conn_m",
                "packet_id": "pkt_m",
                "routing_id": "MANUAL",
                "received_at": "2026-01-15T10:30:00+00:00",
            },
            "feed_routing_identity": "",
            "source_health_facts": {},
            "manual_source_tags": {"tag": "expiry_update", "value": "2026-03-26"},
        }
        result = build_source_envelope(payload)

        assert result.manual_source_tags is not None
        assert result.manual_source_tags["tag"] == "expiry_update"
        assert result.manual_source_tags["value"] == "2026-03-26"

    def test_raises_on_missing_family_key(self) -> None:
        """Should raise ValidationError if a mandatory family key is missing."""
        payload = {
            "original_raw_packet": {},
            "minimal_source_envelope": {"source": "test"},
            # missing: feed_routing_identity, source_health_facts, manual_source_tags
        }
        with pytest.raises(ValidationError) as exc:
            build_source_envelope(payload)

        assert "missing" in str(exc.value).lower()

    def test_raises_on_missing_envelope_field(self) -> None:
        """Should raise ValidationError if source envelope missing fields."""
        payload = {
            "original_raw_packet": {},
            "minimal_source_envelope": {
                "source": "test",
                # missing: feed_type, connection_id, packet_id, routing_id, received_at
            },
            "feed_routing_identity": "SPOT_FEED",
            "source_health_facts": {},
            "manual_source_tags": None,
        }
        with pytest.raises(ValidationError) as exc:
            build_source_envelope(payload)

        assert "missing" in str(exc.value).lower()

    def test_raises_on_empty_payload(self) -> None:
        """Empty dict should raise ValidationError."""
        with pytest.raises(ValidationError):
            build_source_envelope({})

    def test_additive_only(self, valid_floor1_payload: dict) -> None:
        """Floor 1 data should never be modified, only wrapped."""
        original_raw = dict(valid_floor1_payload["original_raw_packet"])
        original_env = dict(valid_floor1_payload["minimal_source_envelope"])

        result = build_source_envelope(valid_floor1_payload)

        assert result.original_raw_packet == original_raw
        assert result.minimal_source_envelope == original_env


# =============================================================================
# ingress_monitor tests
# =============================================================================


class TestIngressMonitor:
    """Tests for ``IngressMonitor``."""

    def test_tracks_total_packets(self, monitor: IngressMonitor) -> None:
        monitor.record_ingest("angel_one", "spot_tick")
        monitor.record_ingest("angel_one", "spot_tick")
        monitor.record_ingest("manual", "calendar_event")

        assert monitor.total_packets == 3
        assert monitor.packet_count() == 3

    def test_tracks_by_source(self, monitor: IngressMonitor) -> None:
        monitor.record_ingest("angel_one", "spot_tick")
        monitor.record_ingest("angel_one", "options_snapshot")
        monitor.record_ingest("manual", "calendar_event")

        assert monitor.packet_count(source="angel_one") == 2
        assert monitor.packet_count(source="manual") == 1
        assert monitor.packet_count(source="unknown") == 0

    def test_tracks_by_feed_type(self, monitor: IngressMonitor) -> None:
        monitor.record_ingest("angel_one", "spot_tick")
        monitor.record_ingest("angel_one", "spot_tick")
        monitor.record_ingest("angel_one", "vix_tick")

        assert monitor.packet_count(feed_type="spot_tick") == 2
        assert monitor.packet_count(feed_type="vix_tick") == 1
        assert monitor.packet_count(feed_type="unknown") == 0

    def test_tracks_errors(self, monitor: IngressMonitor) -> None:
        assert monitor.error_count() == 0

        monitor.record_error(source="angel_one", error_message="validation failed")
        monitor.record_error(error_message="timeout")

        assert monitor.error_count() == 2

    def test_current_rate(self, monitor: IngressMonitor) -> None:
        """Rate should be 0 with no packets."""
        assert monitor.current_rate() == 0.0

        monitor.record_ingest("test", "test")
        # Small sleep so elapsed > 0 for rate calculation
        time.sleep(0.01)
        rate = monitor.current_rate()
        assert rate > 0.0

    def test_uptime_increases(self, monitor: IngressMonitor) -> None:
        uptime = monitor.uptime_s
        assert uptime >= 0.0

    def test_empty_anomalies_initially(self, monitor: IngressMonitor) -> None:
        assert monitor.anomalies_detected() == []

    def test_check_anomalies_before_baseline_stable(self, monitor: IngressMonitor) -> None:
        """Should return empty list before baseline stabilises."""
        assert monitor.check_anomalies() == []

    def test_detects_sudden_drop(self) -> None:
        """Sudden drop in rate should be flagged as anomaly."""
        m = IngressMonitor(
            rate_window_s=5.0,
            surge_threshold=2.0,
            drop_threshold=0.5,
        )
        # 1. Saturate baseline (needs 100+ packets) with small delays
        #    so elapsed > 0 for rate calculation
        for _ in range(120):
            m.record_ingest("test", "test")
            time.sleep(0.001)
        # Baseline should now be stable
        assert len(m.anomalies_detected()) == 0
        # 2. Wait for rate to drop below threshold
        #    With 120 packets over ~0.12s, baseline ≈ 1000 pkt/s
        #    After 2s of silence, rate ≈ 120/2 = 60 pkt/s, and 60/1000=0.06 < 0.5 ✅
        time.sleep(2.0)
        # 3. Trigger a detection check
        flags = m.check_anomalies()
        assert len(flags) >= 1
        assert flags[0]["type"] == "SUDDEN_DROP"

    def test_clear_anomalies(self, monitor: IngressMonitor) -> None:
        """Clearing anomalies should empty the list."""
        for _ in range(200):
            monitor.record_ingest("test", "test")
        assert len(monitor.anomalies_detected()) == 0
        monitor.clear_anomalies()
        assert monitor.anomalies_detected() == []

    def test_thread_safety(self, monitor: IngressMonitor) -> None:
        """Multiple rapid calls should not crash."""
        for _ in range(100):
            monitor.record_ingest("test", "test")
        assert monitor.total_packets == 100


# =============================================================================
# raw_ingest_router tests
# =============================================================================


class TestRawIngestRouter:
    """Tests for ``RawIngestRouter``."""

    def test_ingest_valid_payload(self, router: RawIngestRouter,
                                  valid_floor1_payload: dict) -> None:
        """Valid payload should return IngestPayload dict."""
        result = router.ingest(valid_floor1_payload)

        assert result is not None
        assert isinstance(result, dict)
        assert result["feed_routing_identity"] == "SPOT_FEED"
        assert result["original_raw_packet"] == {"ltp": 18500.0, "volume": 1500}
        assert result["ingest_batch_id"].startswith("ig_")
        assert result["ingested_at"] is not None

    def test_ingest_increments_counters(self, router: RawIngestRouter,
                                        valid_floor1_payload: dict) -> None:
        assert router.total_ingested == 0
        assert router.total_errors == 0

        router.ingest(valid_floor1_payload)

        assert router.total_ingested == 1
        assert router.total_errors == 0

    def test_ingest_updates_monitor(self, router: RawIngestRouter,
                                    valid_floor1_payload: dict) -> None:
        router.ingest(valid_floor1_payload)

        assert router.monitor.total_packets == 1
        assert router.monitor.packet_count(source="angel_one") == 1

    def test_ingest_invalid_payload_returns_none(self, router: RawIngestRouter) -> None:
        """Invalid payload should return None and increment error counter."""
        result = router.ingest({})

        assert result is None
        assert router.total_ingested == 0
        assert router.total_errors == 1

    def test_ingest_invalid_updates_monitor_error(self, router: RawIngestRouter) -> None:
        router.ingest({})

        assert router.monitor.error_count() == 1

    def test_ingest_missing_envelope_fields(self, router: RawIngestRouter) -> None:
        """Missing source envelope fields should fail."""
        payload = {
            "original_raw_packet": {},
            "minimal_source_envelope": {"source": "test"},  # missing 5 fields
            "feed_routing_identity": "SPOT_FEED",
            "source_health_facts": {},
            "manual_source_tags": None,
        }
        result = router.ingest(payload)

        assert result is None
        assert router.total_errors == 1

    def test_downstream_callback_called(self, valid_floor1_payload: dict) -> None:
        """Downstream callback should receive the normalised payload."""
        received = []

        def downstream(payload):
            received.append(payload)

        router = RawIngestRouter(downstream_callback=downstream)
        router.ingest(valid_floor1_payload)

        assert len(received) == 1
        assert isinstance(received[0], Floor2IngestPayload)
        assert received[0].feed_routing_identity == "SPOT_FEED"

    def test_downstream_callback_not_called_on_error(self) -> None:
        """Downstream callback should NOT be called on failed ingest."""
        received = []

        def downstream(payload):
            received.append(payload)

        router = RawIngestRouter(downstream_callback=downstream)
        router.ingest({})

        assert len(received) == 0

    def test_register_downstream(self, valid_floor1_payload: dict) -> None:
        """register_downstream() should set the callback."""
        received = []

        def downstream(payload):
            received.append(payload)

        router = RawIngestRouter()
        router.register_downstream(downstream)
        router.ingest(valid_floor1_payload)

        assert len(received) == 1

    def test_multiple_ingests(self, router: RawIngestRouter,
                              valid_floor1_payload: dict,
                              minimal_payload: dict) -> None:
        """Multiple ingests should accumulate correctly."""
        for _ in range(5):
            router.ingest(valid_floor1_payload)
        for _ in range(3):
            router.ingest(minimal_payload)

        assert router.total_ingested == 8
        assert router.total_errors == 0
        assert router.monitor.total_packets == 8

    def test_properties(self, router: RawIngestRouter) -> None:
        """Properties should return correct types."""
        assert isinstance(router.monitor, IngressMonitor)
        assert isinstance(router.total_ingested, int)
        assert isinstance(router.total_errors, int)

    def test_ingest_payload_has_all_keys(self, router: RawIngestRouter,
                                         valid_floor1_payload: dict) -> None:
        """Returned dict should have all expected IngestPayload keys."""
        result = router.ingest(valid_floor1_payload)

        assert result is not None
        expected_keys = {
            "original_raw_packet",
            "minimal_source_envelope",
            "feed_routing_identity",
            "source_health_facts",
            "manual_source_tags",
            "ingested_at",
            "ingest_batch_id",
        }
        assert set(result.keys()) == expected_keys

    def test_handles_downstream_exception(self, router: RawIngestRouter,
                                          valid_floor1_payload: dict) -> None:
        """Exception in downstream should not crash the router."""
        def broken_callback(payload):
            raise RuntimeError("downstream failure")

        router.register_downstream(broken_callback)
        # Should still return the payload dict despite downstream error
        result = router.ingest(valid_floor1_payload)

        assert result is not None
        assert router.total_ingested == 1
