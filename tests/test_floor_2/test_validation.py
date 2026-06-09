"""Tests for Floor 2 Validation sub-system (Step 2.4).

Tests cover:
- duplicate_validator: detects duplicates, passes fresh packets
- timestamp_validator: ordering, freshness, missing timestamps
- continuity_validator: gap detection (minor, major), first packet
- schema_validator: missing fields, unknown feed types
- corruption_validator: NaN, Inf, None, empty strings, type mismatches
- validation_router: tier routing (A=5, B=4, C=2), aggregation, state
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AggregateValidation,
    ContinuityStatus,
    ValidationDecision,
    ValidationResult,
    ValidationTier,
)
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.validation.continuity_validator import (
    validate_continuity,
)
from junior_aladdin.floor_2_datacenter.validation.corruption_validator import (
    validate_corruption,
)
from junior_aladdin.floor_2_datacenter.validation.duplicate_validator import (
    validate_duplicate,
)
from junior_aladdin.floor_2_datacenter.validation.schema_validator import (
    validate_schema,
)
from junior_aladdin.floor_2_datacenter.validation.timestamp_validator import (
    validate_timestamp,
)
from junior_aladdin.floor_2_datacenter.validation.validation_router import (
    ValidationRouter,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def store() -> NormalizedRawStore:
    return NormalizedRawStore()


@pytest.fixture
def router(store: NormalizedRawStore) -> ValidationRouter:
    return ValidationRouter(store)


def _make_record(
    packet_id: str = "pkt_001",
    source: str = "angel_one",
    feed_type: str = "spot_tick",
    received_at: str | None = None,
    raw_data: dict | None = None,
    skip_timestamp: bool = False,
) -> dict:
    """Helper to create a test record dict matching NormalizedRawStore shape."""
    if skip_timestamp:
        ts: str | None = None
    elif received_at is not None:
        ts = received_at
    else:
        ts = datetime.now(timezone.utc).isoformat()

    default_raw = {"ltp": 18500.0, "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": ts or ""}
    return {
        "packet_id": packet_id,
        "source": source,
        "feed_type": feed_type,
        "original_raw_packet": raw_data or default_raw,
        "minimal_source_envelope": {
            "source": source,
            "feed_type": feed_type,
            "connection_id": "conn_001",
            "packet_id": packet_id,
            "routing_id": "SPOT_FEED",
            "received_at": ts,
        },
        "feed_routing_identity": "SPOT_FEED",
        "source_health_facts": {"lifecycle_state": "HEALTHY"},
    }


# =============================================================================
# Duplicate Validator
# =============================================================================


class TestDuplicateValidator:
    def test_passes_fresh_packet(self, store: NormalizedRawStore) -> None:
        record = _make_record("pkt_new")
        result = validate_duplicate(record, store)
        assert result.passed is True
        assert result.validator_name == "duplicate"
        assert result.details["is_duplicate"] is False

    def test_detects_duplicate(self, store: NormalizedRawStore) -> None:
        # Pre-store a packet
        payload = Floor2IngestPayload(
            minimal_source_envelope={
                "source": "test", "feed_type": "spot_tick",
                "connection_id": "c1", "packet_id": "pkt_dub",
                "routing_id": "SPOT_FEED", "received_at": "2026-01-01T00:00:00+00:00",
            },
        )
        store.store(payload)

        record = _make_record("pkt_dub")
        result = validate_duplicate(record, store)
        assert result.passed is False
        assert result.details["is_duplicate"] is True

    def test_no_packet_id(self, store: NormalizedRawStore) -> None:
        record = _make_record("")
        result = validate_duplicate(record, store)
        assert result.passed is False


# =============================================================================
# Timestamp Validator
# =============================================================================


class TestTimestampValidator:
    def test_valid_timestamp(self, now_ts: str) -> None:
        record = _make_record(received_at=now_ts)
        result = validate_timestamp(record)
        assert result.passed is True

    def test_missing_timestamp(self) -> None:
        record = _make_record(skip_timestamp=True)
        result = validate_timestamp(record)
        assert result.passed is False

    def test_invalid_format(self) -> None:
        record = _make_record(received_at="not-a-date")
        result = validate_timestamp(record)
        assert result.passed is False

    def test_future_timestamp(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        record = _make_record(received_at=future)
        result = validate_timestamp(record)
        assert result.passed is False

    def test_out_of_order(self) -> None:
        now = datetime.now(timezone.utc)
        later = (now + timedelta(seconds=2)).isoformat()
        earlier = (now - timedelta(seconds=2)).isoformat()

        record_later = _make_record(received_at=later)
        result1 = validate_timestamp(record_later)
        assert result1.passed is True

        # Second packet is earlier — out of order
        record_earlier = _make_record(packet_id="pkt_002", received_at=earlier)
        result2 = validate_timestamp(record_earlier, last_timestamp=now + timedelta(seconds=2))
        # Out-of-order passes but notes it
        assert result2.passed is True
        assert result2.details.get("is_ordered") is False


# =============================================================================
# Continuity Validator
# =============================================================================


class TestContinuityValidator:
    def test_first_packet_no_gap(self) -> None:
        record = _make_record()
        result = validate_continuity(record)
        assert result.passed is True
        assert result.details["continuity_status"] == "GOOD"

    def test_no_gap(self) -> None:
        now = datetime.now(timezone.utc)
        recent = now - timedelta(seconds=1)
        record = _make_record(received_at=now.isoformat())
        result = validate_continuity(record, last_timestamp=recent)
        assert result.passed is True
        assert result.details["continuity_status"] == "GOOD"

    def test_minor_gap(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(seconds=10)
        record = _make_record(received_at=now.isoformat())
        result = validate_continuity(record, last_timestamp=old)
        assert result.passed is True  # minor gaps pass but are noted
        assert result.details["continuity_status"] == "MINOR_GAP"

    def test_major_gap(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(seconds=120)
        record = _make_record(received_at=now.isoformat())
        result = validate_continuity(record, last_timestamp=old)
        assert result.passed is False
        assert result.details["continuity_status"] == "MAJOR_GAP"

    def test_out_of_order_not_a_gap(self) -> None:
        now = datetime.now(timezone.utc)
        later = now + timedelta(seconds=10)
        record = _make_record(received_at=now.isoformat())
        result = validate_continuity(record, last_timestamp=later)
        assert result.passed is True  # out-of-order is not a gap
        assert result.details.get("reversed") is True


# =============================================================================
# Schema Validator
# =============================================================================


class TestSchemaValidator:
    def test_valid_schema(self) -> None:
        record = _make_record(feed_type="spot_tick")
        result = validate_schema(record)
        assert result.passed is True

    def test_missing_expected_field(self) -> None:
        record = _make_record(feed_type="vix_tick", raw_data={"value": 14.5})
        result = validate_schema(record)
        # vix_tick expects: value, feed_type, timestamp
        # Our data has value but not feed_type or timestamp
        assert result.passed is False
        assert "feed_type" in result.details.get("missing_fields", [])

    def test_unknown_feed_type(self) -> None:
        record = _make_record(feed_type="unknown_feed")
        result = validate_schema(record)
        assert result.passed is True  # unknown feed passes with reduced confidence
        assert result.confidence == 0.5

    def test_extra_fields_not_failing(self) -> None:
        raw_data = {"ltp": 18500.0, "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00", "extra_field": "unexpected"}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = validate_schema(record)
        # Extra fields don't cause failure — only missing fields do
        assert result.passed is True


# =============================================================================
# Corruption Validator
# =============================================================================


class TestCorruptionValidator:
    def test_clean_data(self) -> None:
        record = _make_record(feed_type="spot_tick", raw_data={"ltp": 18500.0, "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00"})
        result = validate_corruption(record)
        assert result.passed is True

    def test_nan_value(self) -> None:
        raw_data = {"ltp": float("nan"), "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00"}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = validate_corruption(record)
        assert result.passed is False
        assert any("NaN" in a for a in result.details.get("anomalies", []))

    def test_inf_value(self) -> None:
        raw_data = {"ltp": float("inf"), "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00"}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = validate_corruption(record)
        assert result.passed is False
        assert any("Inf" in a for a in result.details.get("anomalies", []))

    def test_none_value(self) -> None:
        raw_data = {"ltp": None, "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00"}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = validate_corruption(record)
        assert result.passed is False
        assert any("None" in a for a in result.details.get("anomalies", []))

    def test_empty_string(self) -> None:
        raw_data = {"ltp": 18500.0, "volume": 1500, "symbol": "", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00"}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = validate_corruption(record)
        assert result.passed is False

    def test_empty_raw_data(self) -> None:
        record = _make_record(feed_type="spot_tick", raw_data={})
        result = validate_corruption(record)
        assert result.passed is True  # Empty data is not corrupt — just noting

    def test_type_mismatch(self) -> None:
        """volume should be int but got str."""
        raw_data = {"ltp": 18500.0, "volume": "1500", "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00+00:00"}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = validate_corruption(record)
        assert result.passed is False
        assert any("volume" in a and "str" in a for a in result.details.get("anomalies", []))


# =============================================================================
# Validation Router
# =============================================================================


class TestValidationRouter:
    def test_tier_a_all_5_validators(self, router: ValidationRouter) -> None:
        """Tier A (spot_tick) should run all 5 validators."""
        record = _make_record(feed_type="spot_tick")
        result = router.validate(record)
        assert len(result.results) == 5
        assert result.tier == ValidationTier.A

    def test_tier_b_4_validators(self, router: ValidationRouter) -> None:
        """Tier B (vix_tick) should run 4 validators (no corruption)."""
        raw_data = {"value": 14.5, "feed_type": "vix_tick", "timestamp": datetime.now(timezone.utc).isoformat()}
        record = _make_record(feed_type="vix_tick", raw_data=raw_data)
        result = router.validate(record)
        assert len(result.results) == 4
        assert result.tier == ValidationTier.B

    def test_tier_c_2_validators(self, router: ValidationRouter) -> None:
        """Tier C (macro_data) should run 2 validators (schema + timestamp)."""
        raw_data = {"feed_type": "macro_data", "stub": True}
        record = _make_record(
            feed_type="macro_data",
            raw_data=raw_data,
        )
        result = router.validate(record)
        assert len(result.results) == 2
        assert result.tier == ValidationTier.C

    def test_unknown_feed_defaults_to_tier_c(self, router: ValidationRouter) -> None:
        """Unknown feed type should default to Tier C."""
        record = _make_record(feed_type="unknown_feed")
        result = router.validate(record)
        assert len(result.results) == 2
        assert result.tier == ValidationTier.C

    def test_passes_clean_packet(self, router: ValidationRouter) -> None:
        """A clean spot_tick packet should PASS."""
        record = _make_record(feed_type="spot_tick")
        result = router.validate(record)
        assert result.decision == ValidationDecision.PASS
        assert result.validation_confidence == 1.0

    def test_fails_duplicate(self, router: ValidationRouter, store: NormalizedRawStore) -> None:
        """Duplicate packet should FAIL."""
        # Pre-store the packet
        payload = Floor2IngestPayload(
            minimal_source_envelope={
                "source": "angel_one", "feed_type": "spot_tick",
                "connection_id": "c1", "packet_id": "pkt_001",
                "routing_id": "SPOT_FEED", "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        store.store(payload)

        record = _make_record("pkt_001")
        result = router.validate(record)
        assert result.decision == ValidationDecision.FAIL

    def test_fails_schema_mismatch(self, router: ValidationRouter) -> None:
        """Missing expected fields should FAIL."""
        raw_data = {"ltp": 18500.0}  # missing volume, symbol, feed_type, timestamp
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = router.validate(record)
        assert result.decision == ValidationDecision.FAIL

    def test_tracks_last_timestamp(self, router: ValidationRouter) -> None:
        """Router should track last timestamp per source+feed_type."""
        now = datetime.now(timezone.utc)
        ts = now.isoformat()

        record1 = _make_record("pkt_a", received_at=ts)
        router.validate(record1)

        last = router.get_last_timestamp("angel_one", "spot_tick")
        assert last is not None
        # Should be within 1 second of now
        assert abs((last - now).total_seconds()) < 2.0

    def test_reset_state(self, router: ValidationRouter) -> None:
        """Reset should clear tracked timestamps."""
        record = _make_record()
        router.validate(record)
        assert router.get_last_timestamp("angel_one", "spot_tick") is not None

        router.reset_state()
        assert router.get_last_timestamp("angel_one", "spot_tick") is None

    def test_validation_confidence_partial_fail(self, router: ValidationRouter) -> None:
        """Partial failures should reduce confidence below 1.0."""
        # Create a record that will fail schema (missing fields) but pass others
        raw_data = {"ltp": 18500.0}  # missing many fields for spot_tick
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = router.validate(record)
        assert result.decision == ValidationDecision.FAIL
        # At least one validator should fail (schema), so confidence < 1.0
        assert result.validation_confidence < 1.0

    def test_tier_a_corruption_included(self, router: ValidationRouter) -> None:
        """Tier A should include corruption validator."""
        raw_data = {"ltp": float("nan"), "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": datetime.now(timezone.utc).isoformat()}
        record = _make_record(feed_type="spot_tick", raw_data=raw_data)
        result = router.validate(record)

        # Should have corruption in results
        corruption_results = [r for r in result.results if r.validator_name == "corruption"]
        assert len(corruption_results) == 1
        assert corruption_results[0].passed is False

    def test_tier_b_skips_corruption(self, router: ValidationRouter) -> None:
        """Tier B should skip corruption validator."""
        raw_data = {"value": 14.5, "feed_type": "vix_tick", "timestamp": datetime.now(timezone.utc).isoformat()}
        record = _make_record(feed_type="vix_tick", raw_data=raw_data)
        result = router.validate(record)

        corruption_results = [r for r in result.results if r.validator_name == "corruption"]
        assert len(corruption_results) == 0

    def test_aggregate_returns_results_in_order(self, router: ValidationRouter) -> None:
        """Results should be in the order: duplicate, timestamp, continuity, schema, corruption."""
        record = _make_record()
        result = router.validate(record)

        expected_order = ["duplicate", "timestamp", "continuity", "schema", "corruption"]
        actual_order = [r.validator_name for r in result.results]
        assert actual_order == expected_order

    def test_aggregate_validation_dataclass_shape(self, router: ValidationRouter) -> None:
        """AggregateValidation should have all expected fields populated."""
        record = _make_record()
        result = router.validate(record)

        assert isinstance(result, AggregateValidation)
        assert isinstance(result.tier, ValidationTier)
        assert isinstance(result.decision, ValidationDecision)
        assert isinstance(result.results, list)
        assert all(isinstance(r, ValidationResult) for r in result.results)
        assert isinstance(result.validation_confidence, float)
        assert 0.0 <= result.validation_confidence <= 1.0
