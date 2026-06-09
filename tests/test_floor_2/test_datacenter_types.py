"""Tests for Step 2.1 — Floor 2 types and contracts.

Covers:
  - datacenter_types.py: all enums, dataclasses, type aliases
  - datacenter_contracts.py: incoming contracts, feed schemas, contract helpers
"""

from __future__ import annotations

from datetime import datetime

import pytest

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    FEED_TYPE_TO_DATA_CLASS,
    FEED_TYPE_TO_ROUTING_IDENTITY,
    FEED_TYPE_TO_VALIDATION_TIER,
    FLOOR1_PAYLOAD_KEYS,
    SOURCE_ENVELOPE_KEYS,
    Candle,
    CandleStream,
    ComputedReadyHook,
    Floor2IngestPayload,
    Floor3Handoff,
    MacroSupportPacket,
    MacroSupportStream,
    OptionsSnapshot,
    OptionsSnapshotStream,
    SessionPacket,
    TickStream,
    ValidatedTick,
    default_feed_contracts,
    get_data_class_for_feed,
    get_validation_tier_for_feed,
    validate_floor1_payload,
    validate_source_envelope,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AggregateValidation,
    AuditReport,
    CleaningResult,
    ContinuityStatus,
    DataClass,
    FeedContract,
    HealthEvent,
    PacketMetadata,
    QualityFacts,
    ReplayQuery,
    ReplaySession,
    ReviewSignal,
    SourceTrace,
    StageHistory,
    StreamType,
    StructureResult,
    TransformStage,
    ValidationDecision,
    ValidationResult,
    ValidationTier,
)


# =============================================================================
# Test: ENUMS — importable and correct values
# =============================================================================


class TestEnums:
    """All enums importable and have correct values."""

    def test_validation_tier_values(self):
        assert ValidationTier.A.value == "A"
        assert ValidationTier.B.value == "B"
        assert ValidationTier.C.value == "C"

    def test_data_class_values(self):
        assert DataClass.MAJOR.value == "MAJOR"
        assert DataClass.MINOR.value == "MINOR"

    def test_transform_stage_values(self):
        assert TransformStage.RAW.value == "RAW"
        assert TransformStage.VALIDATED.value == "VALIDATED"
        assert TransformStage.CLEANED.value == "CLEANED"
        assert TransformStage.STRUCTURED.value == "STRUCTURED"

    def test_review_signal_values(self):
        assert ReviewSignal.GOOD.value == "GOOD"
        assert ReviewSignal.CAUTION.value == "CAUTION"
        assert ReviewSignal.DEGRADED.value == "DEGRADED"
        assert ReviewSignal.CRITICAL.value == "CRITICAL"

    def test_continuity_status_values(self):
        assert ContinuityStatus.GOOD.value == "GOOD"
        assert ContinuityStatus.MINOR_GAP.value == "MINOR_GAP"
        assert ContinuityStatus.MAJOR_GAP.value == "MAJOR_GAP"
        assert ContinuityStatus.GAP_RECOVERED.value == "GAP_RECOVERED"

    def test_stream_type_values(self):
        assert StreamType.TICK_STREAM.value == "TICK_STREAM"
        assert StreamType.CANDLE_STREAM.value == "CANDLE_STREAM"
        assert StreamType.OPTIONS_SNAPSHOT.value == "OPTIONS_SNAPSHOT"
        assert StreamType.SESSION_PACKET.value == "SESSION_PACKET"
        assert StreamType.MACRO_SUPPORT.value == "MACRO_SUPPORT"

    def test_validation_decision_values(self):
        assert ValidationDecision.PASS.value == "PASS"
        assert ValidationDecision.FAIL.value == "FAIL"
        assert ValidationDecision.FLAG.value == "FLAG"


# =============================================================================
# Test: DATACLASSES — instantiation and field population
# =============================================================================


class TestValidationDataclasses:
    """ValidationResult and AggregateValidation."""

    def test_validation_result_defaults(self):
        vr = ValidationResult(validator_name="duplicate_validator", passed=True)
        assert vr.validator_name == "duplicate_validator"
        assert vr.passed is True
        assert vr.details == {}
        assert vr.confidence == 1.0

    def test_validation_result_custom(self):
        vr = ValidationResult(
            validator_name="schema_validator",
            passed=False,
            details={"missing_fields": ["ltp"]},
            confidence=0.95,
        )
        assert vr.passed is False
        assert vr.details["missing_fields"] == ["ltp"]

    def test_aggregate_validation_defaults(self):
        av = AggregateValidation(tier=ValidationTier.A, decision=ValidationDecision.PASS)
        assert av.tier == ValidationTier.A
        assert av.decision == ValidationDecision.PASS
        assert av.results == []
        assert av.validation_confidence == 0.0

    def test_aggregate_validation_with_results(self):
        r1 = ValidationResult("dup", True)
        r2 = ValidationResult("ts", True)
        av = AggregateValidation(
            tier=ValidationTier.A,
            decision=ValidationDecision.PASS,
            results=[r1, r2],
            validation_confidence=1.0,
        )
        assert len(av.results) == 2
        assert av.validation_confidence == 1.0


class TestCleaningDataclasses:
    """CleaningResult."""

    def test_cleaning_result_kept(self):
        cr = CleaningResult(cleaned_record={"ltp": 19500.0})
        assert cr.cleaned_record == {"ltp": 19500.0}
        assert cr.removed is False
        assert cr.repaired is False
        assert cr.anomaly_flags == []

    def test_cleaning_result_removed(self):
        cr = CleaningResult(
            removed=True,
            removal_reason="zero_volume",
            anomaly_flags=["zero_volume"],
        )
        assert cr.cleaned_record is None
        assert cr.removed is True
        assert cr.removal_reason == "zero_volume"

    def test_cleaning_result_repaired(self):
        cr = CleaningResult(
            cleaned_record={"ltp": 19500.5},
            repaired=True,
            repair_action="interpolated_missing_tick",
            original_values={"ltp": 0.0},
        )
        assert cr.repaired is True
        assert cr.repair_action == "interpolated_missing_tick"


class TestStructuringDataclasses:
    """StructureResult."""

    def test_structure_result_defaults(self):
        sr = StructureResult(stream_type=StreamType.TICK_STREAM)
        assert sr.stream_type == StreamType.TICK_STREAM
        assert sr.stream_data is None
        assert sr.metadata == {}

    def test_structure_result_with_data(self):
        sr = StructureResult(
            stream_type=StreamType.CANDLE_STREAM,
            stream_data=[{"timestamp": "10:00", "open": 19500}],
            metadata={"tick_count": 60},
        )
        assert sr.stream_type == StreamType.CANDLE_STREAM
        assert len(sr.stream_data) == 1


# =============================================================================
# Test: METADATA DATACLASSES
# =============================================================================


class TestMetadataDataclasses:
    """QualityFacts, PacketMetadata, SourceTrace, StageHistory."""

    def test_quality_facts_defaults(self):
        qf = QualityFacts()
        assert qf.raw_trust_level == 1.0
        assert qf.validation_confidence == 1.0
        assert qf.packet_completeness == 1.0
        assert qf.continuity_status == ContinuityStatus.GOOD
        assert qf.source_health_state == "HEALTHY"

    def test_quality_facts_custom(self):
        qf = QualityFacts(
            raw_trust_level=0.85,
            validation_confidence=0.75,
            packet_completeness=0.9,
            continuity_status=ContinuityStatus.MINOR_GAP,
            source_health_state="DEGRADED",
        )
        assert qf.raw_trust_level == 0.85
        assert qf.continuity_status == ContinuityStatus.MINOR_GAP

    def test_quality_facts_no_trade_judgment(self):
        """Verify no intelligence/trade-related fields exist."""
        qf = QualityFacts()
        fields = set(qf.__dataclass_fields__.keys())
        forbidden = {"bias", "signal", "setup", "confidence", "conviction", "trade"}
        assert fields.isdisjoint(forbidden)

    def test_quality_facts_fields_are_descriptive(self):
        """Field names should be factual, not interpretive."""
        qf = QualityFacts()
        field_names = list(qf.__dataclass_fields__.keys())
        # All fields should sound factual
        assert "raw_trust_level" in field_names
        assert "validation_confidence" in field_names
        assert "packet_completeness" in field_names

    def test_packet_metadata(self):
        pm = PacketMetadata(
            packet_id="pkt_001",
            source="angel_one",
            feed_type="spot_tick",
        )
        assert pm.packet_id == "pkt_001"
        assert pm.packet_size_bytes == 0

    def test_source_trace_defaults(self):
        st = SourceTrace(source="angel_one")
        assert st.source == "angel_one"
        assert st.transform_stage == TransformStage.RAW
        assert st.review_status == "PENDING"

    def test_source_trace_after_validation(self):
        st = SourceTrace(
            source="angel_one",
            validated_at=datetime(2026, 6, 10, 9, 15, 0),
            transform_stage=TransformStage.VALIDATED,
        )
        assert st.transform_stage == TransformStage.VALIDATED

    def test_stage_history(self):
        sh = StageHistory(packet_id="pkt_001")
        assert sh.packet_id == "pkt_001"
        assert sh.stuck is False

    def test_stage_history_tracks_progression(self):
        now = datetime(2026, 6, 10, 9, 15, 0)
        sh = StageHistory(
            packet_id="pkt_001",
            raw_at=now,
            validated_at=now,
            cleaned_at=now,
            structured_at=now,
        )
        assert sh.raw_at is not None
        assert sh.structured_at is not None
        assert sh.stuck is False


# =============================================================================
# Test: REVIEW + REPLAY DATACLASSES
# =============================================================================


class TestReviewDataclasses:
    """HealthEvent and AuditReport."""

    def test_health_event(self):
        he = HealthEvent(
            event_type="packet_corruption_spike",
            severity="SEVERE",
            source="validation_router",
            message="10 consecutive corruption failures",
        )
        assert he.event_type == "packet_corruption_spike"
        assert he.severity == "SEVERE"
        assert he.details == {}

    def test_audit_report(self):
        ar = AuditReport(report_id="audit_001", report_type="SCHEDULED")
        assert ar.report_id == "audit_001"
        assert ar.score == 1.0
        assert ar.findings == []

    def test_audit_report_with_findings(self):
        ar = AuditReport(
            report_id="audit_002",
            report_type="INVESTIGATION",
            summary="Found 3 validation anomalies",
            findings=[{"type": "duplicate", "count": 5}],
            score=0.85,
        )
        assert len(ar.findings) == 1
        assert ar.score == 0.85


class TestReplayDataclasses:
    """ReplayQuery and ReplaySession."""

    def test_replay_query(self):
        rq = ReplayQuery(
            start_time=datetime(2026, 6, 10, 9, 15, 0),
            end_time=datetime(2026, 6, 10, 15, 30, 0),
        )
        assert rq.sources is None
        assert rq.feed_types is None
        assert rq.transform_stage == TransformStage.RAW

    def test_replay_query_with_filters(self):
        rq = ReplayQuery(
            start_time=datetime(2026, 6, 10, 9, 15, 0),
            end_time=datetime(2026, 6, 10, 15, 30, 0),
            sources=["angel_one"],
            feed_types=["spot_tick"],
            transform_stage=TransformStage.STRUCTURED,
        )
        assert rq.sources == ["angel_one"]
        assert rq.transform_stage == TransformStage.STRUCTURED

    def test_replay_session_defaults(self):
        rq = ReplayQuery(
            start_time=datetime(2026, 6, 10, 9, 15, 0),
            end_time=datetime(2026, 6, 10, 15, 30, 0),
        )
        rs = ReplaySession(session_id="replay_001", query=rq)
        assert rs.session_id == "replay_001"
        assert rs.status == "ACTIVE"
        assert rs.packets_replayed == 0


# =============================================================================
# Test: GOVERNANCE DATACLASSES
# =============================================================================


class TestGovernanceDataclasses:
    """FeedContract."""

    def test_feed_contract_defaults(self):
        fc = FeedContract(name="spot_tick", ownership="Floor 2")
        assert fc.freshness_expectation_s == 300.0
        assert fc.data_class == DataClass.MINOR
        assert fc.consumers == []

    def test_feed_contract_custom(self):
        fc = FeedContract(
            name="spot_tick",
            ownership="Floor 2",
            schema_fields={"ltp": "float", "volume": "int"},
            freshness_expectation_s=1.0,
            source_expectations=["angel_one"],
            data_class=DataClass.MAJOR,
            consumers=["Floor 3"],
        )
        assert fc.data_class == DataClass.MAJOR
        assert len(fc.schema_fields) == 2


# =============================================================================
# Test: CONTRACTS — incoming, outgoing, helpers
# =============================================================================


class TestIncomingContracts:
    """Floor 1 → Floor 2 contract validation."""

    def test_floor1_payload_keys_defined(self):
        """All 5 mandatory keys are defined."""
        expected = {
            "original_raw_packet",
            "minimal_source_envelope",
            "feed_routing_identity",
            "source_health_facts",
            "manual_source_tags",
        }
        assert FLOOR1_PAYLOAD_KEYS == expected

    def test_validate_floor1_payload_all_present(self):
        """Valid payload with all 5 keys → empty missing list."""
        payload = {
            "original_raw_packet": {},
            "minimal_source_envelope": {},
            "feed_routing_identity": "SPOT_FEED",
            "source_health_facts": {},
            "manual_source_tags": None,
        }
        missing = validate_floor1_payload(payload)
        assert missing == []

    def test_validate_floor1_payload_missing_keys(self):
        """Payload missing keys → returns list of missing key names."""
        payload = {"original_raw_packet": {}}
        missing = validate_floor1_payload(payload)
        assert "minimal_source_envelope" in missing
        assert "feed_routing_identity" in missing
        assert "source_health_facts" in missing
        assert "manual_source_tags" in missing
        assert len(missing) == 4

    def test_source_envelope_keys_defined(self):
        """All 6 mandatory envelope keys are defined."""
        expected = {
            "source",
            "feed_type",
            "connection_id",
            "packet_id",
            "routing_id",
            "received_at",
        }
        assert SOURCE_ENVELOPE_KEYS == expected

    def test_validate_source_envelope_all_present(self):
        envelope = {
            "source": "angel_one",
            "feed_type": "spot_tick",
            "connection_id": "conn_001",
            "packet_id": "pkt_001",
            "routing_id": "angel_one::spot_tick",
            "received_at": "2026-06-10T09:15:00+00:00",
        }
        missing = validate_source_envelope(envelope)
        assert missing == []

    def test_validate_source_envelope_missing(self):
        envelope = {"source": "angel_one"}
        missing = validate_source_envelope(envelope)
        assert "feed_type" in missing
        assert len(missing) == 5


class TestFeedTypeMappings:
    """FEED_TYPE_TO_* mappings for validation tier, data class, routing."""

    def test_tier_a_feeds(self):
        assert FEED_TYPE_TO_VALIDATION_TIER["spot_tick"] == "A"
        assert FEED_TYPE_TO_VALIDATION_TIER["options_snapshot"] == "A"

    def test_tier_b_feeds(self):
        assert FEED_TYPE_TO_VALIDATION_TIER["vix_tick"] == "B"

    def test_tier_c_feeds(self):
        assert FEED_TYPE_TO_VALIDATION_TIER["macro_data"] == "C"
        assert FEED_TYPE_TO_VALIDATION_TIER["calendar_event"] == "C"

    def test_unknown_feed_defaults_to_c(self):
        assert get_validation_tier_for_feed("unknown_feed") == "C"

    def test_major_feeds(self):
        assert FEED_TYPE_TO_DATA_CLASS["spot_tick"] == "MAJOR"
        assert FEED_TYPE_TO_DATA_CLASS["options_snapshot"] == "MAJOR"
        assert FEED_TYPE_TO_DATA_CLASS["vix_tick"] == "MAJOR"

    def test_minor_feeds(self):
        assert FEED_TYPE_TO_DATA_CLASS["macro_data"] == "MINOR"
        assert FEED_TYPE_TO_DATA_CLASS["calendar_event"] == "MINOR"

    def test_unknown_feed_defaults_to_minor(self):
        assert get_data_class_for_feed("unknown_feed") == "MINOR"

    def test_routing_identities(self):
        assert FEED_TYPE_TO_ROUTING_IDENTITY["spot_tick"] == "SPOT_FEED"
        assert FEED_TYPE_TO_ROUTING_IDENTITY["options_snapshot"] == "OPTIONS_FEED"
        assert FEED_TYPE_TO_ROUTING_IDENTITY["vix_tick"] == "VIX_FEED"
        assert FEED_TYPE_TO_ROUTING_IDENTITY["macro_data"] == "MACRO_FEED"
        assert FEED_TYPE_TO_ROUTING_IDENTITY["calendar_event"] == "CALENDAR_FEED"


class TestInternalContracts:
    """Floor 2 ingest payload (ingress/ → raw/)."""

    def test_floor2_ingest_payload_defaults(self):
        fip = Floor2IngestPayload()
        assert fip.original_raw_packet == {}
        assert fip.minimal_source_envelope == {}
        assert fip.manual_source_tags is None
        assert fip.ingest_batch_id == ""

    def test_floor2_ingest_payload_all_fields(self):
        fip = Floor2IngestPayload(
            original_raw_packet={"ltp": 19500.0},
            minimal_source_envelope={"source": "angel_one"},
            feed_routing_identity="SPOT_FEED",
            source_health_facts={"lifecycle_state": "HEALTHY"},
            manual_source_tags=None,
            ingested_at=datetime(2026, 6, 10, 9, 15, 0),
            ingest_batch_id="batch_001",
        )
        assert fip.original_raw_packet == {"ltp": 19500.0}
        assert fip.ingest_batch_id == "batch_001"


class TestOutgoingContracts:
    """Floor 2 → Floor 3 (7 mandatory categories)."""

    def test_validated_tick_defaults(self):
        vt = ValidatedTick()
        assert vt.price == 0.0
        assert vt.volume == 0
        assert vt.sequence_id == 0

    def test_validated_tick_custom(self):
        vt = ValidatedTick(
            timestamp=datetime(2026, 6, 10, 9, 15, 0, 500000),
            price=19500.5,
            volume=25000,
            source="angel_one",
            feed_type="spot_tick",
            sequence_id=1,
        )
        assert vt.price == 19500.5
        assert vt.sequence_id == 1

    def test_tick_stream(self):
        ts = TickStream(stream_id="stream_001")
        assert ts.tick_count == 0
        assert ts.ticks == []

    def test_candle_defaults(self):
        c = Candle()
        assert c.open == 0.0
        assert c.is_complete is False

    def test_candle_stream(self):
        cs = CandleStream(stream_id="candle_001", source="angel_one", feed_type="spot_tick")
        assert cs.candles == []

    def test_options_snapshot(self):
        os = OptionsSnapshot(
            timestamp=datetime(2026, 6, 10, 9, 15, 0),
            expiry="2026-06-25",
            strike=19500.0,
            option_type="CE",
            oi=100000,
            premium=150.0,
            iv=15.5,
            change_in_oi=5000,
        )
        assert os.option_type == "CE"
        assert os.oi == 100000

    def test_options_snapshot_stream(self):
        oss = OptionsSnapshotStream(stream_id="opt_001")
        assert oss.interval_minutes == 5
        assert oss.snapshots == []

    def test_session_packet(self):
        sp = SessionPacket(
            session_id="session_001",
            session_type="REGULAR",
            session_phase="OPENING",
            session_status="ACTIVE",
        )
        assert sp.references == {}

    def test_macro_support_packet(self):
        msp = MacroSupportPacket(
            data_type="VIX",
            value=14.5,
            source="angel_one",
        )
        assert msp.freshness == "FRESH"

    def test_macro_support_stream(self):
        mss = MacroSupportStream(stream_id="macro_001", data_type="VIX")
        assert mss.packets == []

    def test_computed_ready_hook(self):
        crh = ComputedReadyHook(
            hook_name="candle_aggregator",
            input_schema={"candles": "list[Candle]"},
            output_format="list[HigherTFCandle]",
        )
        assert crh.version == "1.0"

    def test_floor3_handoff_all_7_categories(self):
        handoff = Floor3Handoff()
        assert isinstance(handoff.validated_tick_stream, TickStream)
        assert isinstance(handoff.validated_candle_streams, CandleStream)
        assert isinstance(handoff.options_snapshots, OptionsSnapshotStream)
        assert isinstance(handoff.session_packets, list)
        assert isinstance(handoff.macro_support_packets, list)
        assert isinstance(handoff.metadata_side_channel, dict)
        assert isinstance(handoff.computed_ready_hooks, list)

    def test_floor3_handoff_mandatory_categories_count(self):
        """Floor3Handoff has exactly 7 mandatory categories."""
        handoff = Floor3Handoff()
        # Count non-default fields that represent categories
        categories = [
            "validated_tick_stream",
            "validated_candle_streams",
            "options_snapshots",
            "session_packets",
            "macro_support_packets",
            "metadata_side_channel",
            "computed_ready_hooks",
        ]
        for cat in categories:
            assert hasattr(handoff, cat), f"Missing category: {cat}"
        assert len(categories) == 7


class TestDefaultContracts:
    """Default feed contract registry."""

    def test_default_contracts_count(self):
        contracts = default_feed_contracts()
        assert len(contracts) >= 5  # spot, options, vix, macro, calendar

    def test_spot_tick_is_major(self):
        contracts = default_feed_contracts()
        spot = [c for c in contracts if c.name == "spot_tick"][0]
        assert spot.data_class == DataClass.MAJOR
        assert spot.freshness_expectation_s == 1.0

    def test_macro_data_is_minor(self):
        contracts = default_feed_contracts()
        macro = [c for c in contracts if c.name == "macro_data"][0]
        assert macro.data_class == DataClass.MINOR
        assert macro.freshness_expectation_s == 300.0

    def test_all_contracts_have_ownership(self):
        contracts = default_feed_contracts()
        for c in contracts:
            assert c.ownership, f"Contract {c.name} missing ownership"


# =============================================================================
# Test: ARCHITECTURE RULES — No intelligence fields
# =============================================================================


class TestArchitectureRules:
    """Floor 2 types must NOT contain intelligence/opinion fields."""

    @pytest.mark.parametrize(
        "dataclass_type",
        [
            ValidationResult,
            QualityFacts,
            CleaningResult,
            StructureResult,
            TickStream,
            Candle,
            OptionsSnapshot,
            SessionPacket,
            MacroSupportPacket,
        ],
    )
    def test_no_market_interpretation_fields(self, dataclass_type):
        """None of these dataclasses should have bias/signal/setup fields."""
        fields = set(dataclass_type.__dataclass_fields__.keys())
        forbidden = {"bias", "signal", "setup", "conviction", "trade"}
        assert fields.isdisjoint(forbidden), (
            f"{dataclass_type.__name__} contains forbidden fields: "
            f"{fields & forbidden}"
        )

    def test_no_opinion_in_quality_facts(self):
        """QualityFacts must be descriptive not prescriptive."""
        qf = QualityFacts()
        field_names = list(qf.__dataclass_fields__.keys())
        opinion_words = {"recommend", "suggest", "favorable", "worthy", "good_for"}
        field_words = set(" ".join(field_names).split("_"))
        assert field_words.isdisjoint(opinion_words), (
            f"QualityFacts contains opinion-like fields"
        )
