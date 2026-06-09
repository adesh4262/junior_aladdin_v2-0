"""Tests for Floor 2 Metadata sub-system (Step 2.7).

Tests cover:
- packet_metadata_builder: builds PacketMetadata from records
- source_trace_builder: builds SourceTrace with pipeline stage tracking
- transform_stage_tracker: tracks TransformStage progression with NormalizedRawStore
- quality_fact_builder: builds QualityFacts from validation + cleaning results
- retention_metadata_builder: builds retention summary + per-feed report
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AggregateValidation,
    CleaningResult,
    ContinuityStatus,
    DataClass,
    PacketMetadata,
    QualityFacts,
    SourceTrace,
    StageHistory,
    TransformStage,
    ValidationDecision,
    ValidationResult,
    ValidationTier,
)
from junior_aladdin.floor_2_datacenter.metadata.packet_metadata_builder import (
    build_packet_metadata,
    build_packet_metadata_batch,
)
from junior_aladdin.floor_2_datacenter.metadata.quality_fact_builder import (
    build_quality_facts,
)
from junior_aladdin.floor_2_datacenter.metadata.retention_metadata_builder import (
    build_feed_storage_report,
    build_retention_summary,
)
from junior_aladdin.floor_2_datacenter.metadata.source_trace_builder import (
    build_source_trace,
    build_source_trace_batch,
)
from junior_aladdin.floor_2_datacenter.metadata.transform_stage_tracker import (
    TransformStageTracker,
)
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.raw.original_raw_store import OriginalRawStore
from junior_aladdin.floor_2_datacenter.raw.raw_retention_manager import (
    RawRetentionManager,
)
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_envelope(
    packet_id: str,
    source: str = "angel_one",
    feed_type: str = "spot_tick",
) -> dict:
    """Create a minimal source envelope dict."""
    return {
        "packet_id": packet_id,
        "source": source,
        "feed_type": feed_type,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_record(
    packet_id: str,
    source: str = "angel_one",
    feed_type: str = "spot_tick",
) -> dict:
    """Create a record dict matching NormalizedRawStore output."""
    now = datetime.now(timezone.utc)
    return {
        "packet_id": packet_id,
        "source": source,
        "feed_type": feed_type,
        "original_raw_packet": {"ltp": 18500.0, "volume": 1000},
        "minimal_source_envelope": _make_envelope(packet_id, source, feed_type),
        "ingested_at": now,
        "stored_at": now,
        "transform_stage": "RAW",
        "review_status": "PENDING",
    }


def _store_payload(
    store: NormalizedRawStore,
    packet_id: str,
    source: str = "angel_one",
    feed_type: str = "spot_tick",
) -> str | None:
    """Helper to create and store a Floor2IngestPayload."""
    now = datetime.now(timezone.utc)
    payload = Floor2IngestPayload(
        original_raw_packet={"ltp": 18500.0},
        minimal_source_envelope={
            "packet_id": packet_id,
            "source": source,
            "feed_type": feed_type,
            "received_at": now.isoformat(),
        },
        feed_routing_identity="spot_tick_v1",
        source_health_facts={},
        manual_source_tags=None,
        ingested_at=now,
        ingest_batch_id="batch_001",
    )
    return store.store(payload)


# =============================================================================
# Packet Metadata Builder
# =============================================================================


class TestPacketMetadataBuilder:
    def test_builds_packet_metadata(self) -> None:
        record = _make_record("pkt_001")
        meta = build_packet_metadata(record)

        assert isinstance(meta, PacketMetadata)
        assert meta.packet_id == "pkt_001"
        assert meta.source == "angel_one"
        assert meta.feed_type == "spot_tick"
        assert meta.received_at is not None
        assert meta.packet_size_bytes > 0

    def test_builds_metadata_no_raw_data(self) -> None:
        record = _make_record("pkt_002")
        record["original_raw_packet"] = {}
        meta = build_packet_metadata(record, estimate_size=True)
        assert meta.packet_size_bytes == 0

    def test_builds_metadata_from_cleaned_record(self) -> None:
        record = _make_record("pkt_003")
        record["original_raw_packet"] = {}
        record["cleaned_data"] = {"ltp": 18600.0, "volume": 500}
        meta = build_packet_metadata(record)
        assert meta.packet_size_bytes > 0

    def test_skips_size_estimation(self) -> None:
        record = _make_record("pkt_004")
        meta = build_packet_metadata(record, estimate_size=False)
        assert meta.packet_size_bytes == 0

    def test_handles_missing_fields(self) -> None:
        meta = build_packet_metadata({})
        assert isinstance(meta, PacketMetadata)
        assert meta.packet_id == "unknown"
        assert meta.source == "unknown"

    def test_builds_batch(self) -> None:
        records = [_make_record(f"pkt_{i:03d}") for i in range(5)]
        batch = build_packet_metadata_batch(records)
        assert len(batch) == 5
        assert all(isinstance(m, PacketMetadata) for m in batch)

    def test_packet_size_is_reasonable(self) -> None:
        record = _make_record("pkt_large")
        meta = build_packet_metadata(record)
        # The raw data string length should be > 20 chars
        assert meta.packet_size_bytes > 20


# =============================================================================
# Source Trace Builder
# =============================================================================


class TestSourceTraceBuilder:
    def test_builds_source_trace(self) -> None:
        record = _make_record("pkt_001")
        trace = build_source_trace(record)

        assert isinstance(trace, SourceTrace)
        assert trace.source == "angel_one"
        assert trace.transform_stage == TransformStage.RAW
        assert trace.review_status == "PENDING"

    def test_builds_trace_from_transform_stage(self) -> None:
        record = _make_record("pkt_002")
        record["transform_stage"] = "VALIDATED"
        trace = build_source_trace(record)
        assert trace.transform_stage == TransformStage.VALIDATED

    def test_builds_trace_with_review_status(self) -> None:
        record = _make_record("pkt_003")
        record["review_status"] = "REVIEWED"
        trace = build_source_trace(record)
        assert trace.review_status == "REVIEWED"

    def test_source_override(self) -> None:
        record = _make_record("pkt_004", source="original")
        trace = build_source_trace(record, source="override")
        assert trace.source == "override"

    def test_validated_at(self) -> None:
        record = _make_record("pkt_005")
        now = datetime.now(timezone.utc)
        trace = build_source_trace(record, validated_at=now)
        assert trace.validated_at == now

    def test_invalid_transform_stage_defaults_raw(self) -> None:
        record = _make_record("pkt_006")
        record["transform_stage"] = "INVALID"
        trace = build_source_trace(record)
        assert trace.transform_stage == TransformStage.RAW

    def test_builds_batch(self) -> None:
        records = [_make_record(f"pkt_{i:03d}") for i in range(3)]
        batch = build_source_trace_batch(records)
        assert len(batch) == 3
        assert all(isinstance(t, SourceTrace) for t in batch)

    def test_batch_default_stage(self) -> None:
        """When records have no transform_stage field, default_stage applies."""
        records = [
            {"packet_id": "pkt_100", "source": "test", "feed_type": "test"},
            {"packet_id": "pkt_101", "source": "test", "feed_type": "test"},
        ]
        batch = build_source_trace_batch(records, default_stage=TransformStage.CLEANED)
        assert all(t.transform_stage == TransformStage.CLEANED for t in batch)

    def test_handles_missing_record(self) -> None:
        """Empty dict should not crash, uses defaults."""
        trace = build_source_trace({})
        assert trace.source == "unknown"
        assert trace.transform_stage == TransformStage.RAW


# =============================================================================
# Transform Stage Tracker
# =============================================================================


class TestTransformStageTracker:
    @pytest.fixture
    def store(self) -> NormalizedRawStore:
        store = NormalizedRawStore()
        _store_payload(store, "pkt_001")
        _store_payload(store, "pkt_002")
        _store_payload(store, "pkt_003")
        return store

    @pytest.fixture
    def tracker(self, store: NormalizedRawStore) -> TransformStageTracker:
        return TransformStageTracker(store)

    def test_advance_to_validated(self, tracker: TransformStageTracker) -> None:
        assert tracker.advance("pkt_001", TransformStage.VALIDATED) is True

    def test_advance_to_cleaned(self, tracker: TransformStageTracker) -> None:
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        assert tracker.advance("pkt_001", TransformStage.CLEANED) is True

    def test_advance_to_structured(self, tracker: TransformStageTracker) -> None:
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        tracker.advance("pkt_001", TransformStage.CLEANED)
        assert tracker.advance("pkt_001", TransformStage.STRUCTURED) is True

    def test_cannot_skip_stage(self, tracker: TransformStageTracker) -> None:
        """Stages must be advanced sequentially — cannot skip directly to STRUCTURED."""
        assert tracker.advance("pkt_001", TransformStage.STRUCTURED) is False

    def test_cannot_regress_stage(self, tracker: TransformStageTracker) -> None:
        """Cannot go from VALIDATED back to RAW."""
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        assert tracker.advance("pkt_001", TransformStage.RAW) is False

    def test_advance_nonexistent_packet(self, tracker: TransformStageTracker) -> None:
        assert tracker.advance("nonexistent", TransformStage.VALIDATED) is False

    def test_get_history(self, tracker: TransformStageTracker) -> None:
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        history = tracker.get_history("pkt_001")
        assert isinstance(history, StageHistory)
        assert history.packet_id == "pkt_001"
        assert history.raw_at is not None
        assert history.validated_at is not None

    def test_get_history_nonexistent(self, tracker: TransformStageTracker) -> None:
        assert tracker.get_history("nonexistent") is None

    def test_get_current_stage(self, tracker: TransformStageTracker) -> None:
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        assert tracker.get_current_stage("pkt_001") == TransformStage.VALIDATED

    def test_get_current_stage_nonexistent(
        self, tracker: TransformStageTracker,
    ) -> None:
        assert tracker.get_current_stage("nonexistent") is None

    def test_find_stuck_packets(self, tracker: TransformStageTracker) -> None:
        """A packet stuck at VALIDATED for > 5 minutes should be flagged."""
        tracker.advance("pkt_002", TransformStage.VALIDATED)

        # Manipulate the history to look like it's been 10 minutes
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        history = tracker.get_history("pkt_002")
        assert history is not None
        # Both raw_at and validated_at were set during advance() — set both to old
        history.raw_at = old  # type: ignore[assignment]
        history.validated_at = old  # type: ignore[assignment]

        stuck = tracker.find_stuck_packets()
        stuck_ids = [s["packet_id"] for s in stuck]
        assert "pkt_002" in stuck_ids

    def test_find_stuck_packets_no_stuck(
        self, tracker: TransformStageTracker,
    ) -> None:
        """Packets that advanced recently should not be stuck."""
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        stuck = tracker.find_stuck_packets()
        stuck_ids = [s["packet_id"] for s in stuck]
        assert "pkt_001" not in stuck_ids

    def test_reset_packet(self, tracker: TransformStageTracker) -> None:
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        assert tracker.reset("pkt_001") is True
        assert tracker.get_current_stage("pkt_001") == TransformStage.RAW

    def test_reset_nonexistent(self, tracker: TransformStageTracker) -> None:
        assert tracker.reset("nonexistent") is False


# =============================================================================
# Quality Fact Builder
# =============================================================================


class TestQualityFactBuilder:
    def test_builds_quality_facts_default(self) -> None:
        qf = build_quality_facts()
        assert isinstance(qf, QualityFacts)
        assert qf.raw_trust_level == 1.0
        assert qf.validation_confidence == 0.5
        assert qf.packet_completeness == 0.8
        assert qf.continuity_status == ContinuityStatus.GOOD
        assert qf.source_health_state == "HEALTHY"

    def test_validation_passed(self) -> None:
        agg = AggregateValidation(
            tier=ValidationTier.A,
            decision=ValidationDecision.PASS,
            results=[],
            validation_confidence=1.0,
        )
        qf = build_quality_facts(aggregate_validation=agg)
        assert qf.validation_confidence == 1.0
        assert qf.raw_trust_level == 1.0

    def test_validation_failed(self) -> None:
        agg = AggregateValidation(
            tier=ValidationTier.A,
            decision=ValidationDecision.FAIL,
            results=[],
            validation_confidence=0.0,
        )
        qf = build_quality_facts(aggregate_validation=agg)
        assert qf.raw_trust_level == 0.7  # 1.0 - 0.3

    def test_validation_flagged(self) -> None:
        agg = AggregateValidation(
            tier=ValidationTier.A,
            decision=ValidationDecision.FLAG,
            results=[],
            validation_confidence=0.8,
        )
        qf = build_quality_facts(aggregate_validation=agg)
        assert qf.raw_trust_level == 0.9  # 1.0 - 0.1

    def test_cleaning_repaired(self) -> None:
        cleaning = CleaningResult(
            cleaned_record={"ltp": 18500.0},
            repaired=True,
            repair_action="fixed NaN",
            anomaly_flags=["nan_value"],
        )
        qf = build_quality_facts(cleaning_result=cleaning)
        assert qf.raw_trust_level == 0.95  # 1.0 - 0.05
        assert qf.packet_completeness < 1.0  # anomaly detected

    def test_cleaning_removed(self) -> None:
        cleaning = CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason="bad data",
            anomaly_flags=["corrupt"],
        )
        qf = build_quality_facts(cleaning_result=cleaning)
        assert qf.raw_trust_level == 0.9  # 1.0 - 0.1
        assert qf.packet_completeness == 0.0  # removed

    def test_continuity_status_from_validation(self) -> None:
        agg = AggregateValidation(
            tier=ValidationTier.A,
            decision=ValidationDecision.PASS,
            results=[
                ValidationResult(
                    validator_name="continuity",
                    passed=True,
                    details={"continuity_status": "MINOR_GAP"},
                ),
            ],
            validation_confidence=1.0,
        )
        qf = build_quality_facts(aggregate_validation=agg)
        assert qf.continuity_status == ContinuityStatus.MINOR_GAP

    def test_custom_source_health(self) -> None:
        qf = build_quality_facts(source_health_state="DEGRADED")
        assert qf.source_health_state == "DEGRADED"

    def test_combined_fail_and_repair(self) -> None:
        agg = AggregateValidation(
            tier=ValidationTier.A,
            decision=ValidationDecision.FAIL,
            results=[],
            validation_confidence=0.2,
        )
        cleaning = CleaningResult(
            cleaned_record={"ltp": 18500.0},
            repaired=True,
            repair_action="fixed NaN",
            anomaly_flags=["nan_value"],
        )
        qf = build_quality_facts(
            aggregate_validation=agg, cleaning_result=cleaning,
        )
        assert qf.raw_trust_level == 0.65  # 1.0 - 0.3 - 0.05
        assert qf.validation_confidence == 0.2


# =============================================================================
# Retention Metadata Builder
# =============================================================================


class TestRetentionMetadataBuilder:
    @pytest.fixture
    def original_store(self) -> OriginalRawStore:
        store = OriginalRawStore()
        now = datetime.now(timezone.utc)
        for pid in ["pkt_001", "pkt_002"]:
            payload = Floor2IngestPayload(
                original_raw_packet={"ltp": 18500.0, "volume": 1000},
                minimal_source_envelope={
                    "packet_id": pid,
                    "source": "angel_one",
                    "feed_type": "spot_tick",
                    "received_at": now.isoformat(),
                },
                feed_routing_identity="spot_tick_v1",
                source_health_facts={},
                manual_source_tags=None,
                ingested_at=now,
                ingest_batch_id="batch_001",
            )
            store.store(payload)
        return store

    @pytest.fixture
    def normalized_store(self) -> NormalizedRawStore:
        store = NormalizedRawStore()
        _store_payload(store, "pkt_001")
        _store_payload(store, "pkt_002", feed_type="macro_data")
        _store_payload(store, "pkt_003", feed_type="vix_tick")
        return store

    @pytest.fixture
    def cleaned_writer(self) -> CleanedLayerWriter:
        writer = CleanedLayerWriter()
        writer.write(
            {"packet_id": "pkt_001", "source": "angel_one", "feed_type": "spot_tick"},
            CleaningResult(cleaned_record={"ltp": 18500.0}),
        )
        return writer

    @pytest.fixture
    def structured_writer(self) -> StructuredWriter:
        from junior_aladdin.floor_2_datacenter.datacenter_types import (
            StreamType,
            StructureResult,
        )
        writer = StructuredWriter()
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "ts_001"},
        ))
        return writer

    @pytest.fixture
    def retention_manager(self) -> RawRetentionManager:
        return RawRetentionManager()

    def test_builds_retention_summary(
        self,
        original_store: OriginalRawStore,
        normalized_store: NormalizedRawStore,
        cleaned_writer: CleanedLayerWriter,
        structured_writer: StructuredWriter,
        retention_manager: RawRetentionManager,
    ) -> None:
        summary = build_retention_summary(
            original_store, normalized_store, cleaned_writer,
            structured_writer, retention_manager,
        )
        assert "timestamp" in summary
        assert "storage" in summary
        assert "retention_policies" in summary
        assert "total_packets" in summary

    def test_summary_counts(
        self,
        original_store: OriginalRawStore,
        normalized_store: NormalizedRawStore,
        cleaned_writer: CleanedLayerWriter,
        structured_writer: StructuredWriter,
        retention_manager: RawRetentionManager,
    ) -> None:
        summary = build_retention_summary(
            original_store, normalized_store, cleaned_writer,
            structured_writer, retention_manager,
        )
        storage = summary["storage"]
        assert storage["original_raw"]["count"] == 2
        assert storage["normalized_raw"]["count"] == 3
        assert storage["cleaned"]["count"] == 1
        assert storage["structured"]["count"] == 1

    def test_summary_feed_types(
        self,
        original_store: OriginalRawStore,
        normalized_store: NormalizedRawStore,
        cleaned_writer: CleanedLayerWriter,
        structured_writer: StructuredWriter,
        retention_manager: RawRetentionManager,
    ) -> None:
        summary = build_retention_summary(
            original_store, normalized_store, cleaned_writer,
            structured_writer, retention_manager,
        )
        storage = summary["storage"]
        assert "spot_tick" in storage["original_raw"]["feed_types"]
        assert "feed_types" in storage["normalized_raw"]
        assert "feed_types" in storage["cleaned"]

    def test_summary_stage_distribution(
        self,
        normalized_store: NormalizedRawStore,
        original_store: OriginalRawStore,
        cleaned_writer: CleanedLayerWriter,
        structured_writer: StructuredWriter,
        retention_manager: RawRetentionManager,
    ) -> None:
        summary = build_retention_summary(
            original_store, normalized_store, cleaned_writer,
            structured_writer, retention_manager,
        )
        stages = summary["storage"]["normalized_raw"]["stage_distribution"]
        assert isinstance(stages, dict)
        assert "RAW" in stages
        assert stages["RAW"] == 3  # All 3 packets are at RAW stage

    def test_summary_retention_policies(
        self,
        original_store: OriginalRawStore,
        normalized_store: NormalizedRawStore,
        cleaned_writer: CleanedLayerWriter,
        structured_writer: StructuredWriter,
        retention_manager: RawRetentionManager,
    ) -> None:
        summary = build_retention_summary(
            original_store, normalized_store, cleaned_writer,
            structured_writer, retention_manager,
        )
        assert "retention_policies" in summary

    def test_build_feed_storage_report(
        self,
        normalized_store: NormalizedRawStore,
    ) -> None:
        report = build_feed_storage_report(normalized_store, "spot_tick")
        assert report["feed_type"] == "spot_tick"
        assert report["packet_count"] == 1

    def test_feed_storage_report_stage_breakdown(
        self,
        normalized_store: NormalizedRawStore,
    ) -> None:
        report = build_feed_storage_report(normalized_store, "macro_data")
        assert "stage_breakdown" in report
        assert report["stage_breakdown"].get("RAW", 0) == 1

    def test_feed_storage_report_time_range(
        self,
        normalized_store: NormalizedRawStore,
    ) -> None:
        report = build_feed_storage_report(normalized_store, "vix_tick")
        assert report["oldest_packet"] is not None
        assert report["newest_packet"] is not None

    def test_feed_storage_report_nonexistent(
        self,
        normalized_store: NormalizedRawStore,
    ) -> None:
        report = build_feed_storage_report(normalized_store, "nonexistent")
        assert report["packet_count"] == 0
        assert report["oldest_packet"] is None
