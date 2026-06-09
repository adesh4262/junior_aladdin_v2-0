"""Floor 2 Data Center — custom types and dataclasses.

This file defines Floor 2's own enums and dataclasses for the validation
pipeline, cleaning layer, structuring layer, metadata side-channel, review
engine, and replay engine.

Architecture rules:
- Floor 2 types are FACTUAL — no intelligence, no confidence, no opinion.
- Quality scores describe process confidence (did validation pass?),
  NOT market confidence (is this tradeable?).
- Every dataclass documents mandatory vs optional fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# =============================================================================
# ENUMS
# =============================================================================


class ValidationTier(Enum):
    """Validation strength tier for dynamic per-feed validation.

    Tier A (very strong): tick data, options chain, OI snapshots
        → ALL 5 validators run
    Tier B (strong): candle data, session packets, major structured streams
        → 4 validators (skip corruption)
    Tier C (medium/basic): macro support, secondary references, auxiliary
        → 2 validators (schema + timestamp)
    """
    A = "A"
    B = "B"
    C = "C"


class DataClass(Enum):
    """Data importance classification for storage and processing priority.

    MAJOR: tick data, candle streams, options chain, OI snapshots, core market feeds
    MINOR: support feeds, auxiliary feeds, secondary references, slower contextual
    """
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class TransformStage(Enum):
    """Pipeline transform stage tracking for each packet.

    Tracks the progress of a packet through the Floor 2 pipeline.
    """
    RAW = "RAW"
    VALIDATED = "VALIDATED"
    CLEANED = "CLEANED"
    STRUCTURED = "STRUCTURED"


class ReviewSignal(Enum):
    """4-level data health signal for transport to upper floors.

    Lightweight signal that reflects the overall health of the data pipeline.
    Travels through the metadata side-channel — NOT a direct Captain feed.
    """
    GOOD = "GOOD"
    CAUTION = "CAUTION"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class ContinuityStatus(Enum):
    """Continuity state of a tick/candle stream.

    Tracks whether the expected data sequence is contiguous or has gaps.
    """
    GOOD = "GOOD"
    MINOR_GAP = "MINOR_GAP"
    MAJOR_GAP = "MAJOR_GAP"
    GAP_RECOVERED = "GAP_RECOVERED"


class StreamType(Enum):
    """Types of structured streams produced by the structuring layer."""
    TICK_STREAM = "TICK_STREAM"
    CANDLE_STREAM = "CANDLE_STREAM"
    OPTIONS_SNAPSHOT = "OPTIONS_SNAPSHOT"
    SESSION_PACKET = "SESSION_PACKET"
    MACRO_SUPPORT = "MACRO_SUPPORT"


class ValidationDecision(Enum):
    """Aggregate validation outcome after all applicable validators run."""
    PASS = "PASS"
    FAIL = "FAIL"
    FLAG = "FLAG"  # passed but flagged for review


# =============================================================================
# DATACLASSES — VALIDATION PIPELINE
# =============================================================================


@dataclass
class ValidationResult:
    """Output from a single validator run.

    Fields:
        validator_name: Name of the validator that produced this result.
        passed: Whether the validation check passed.
        details: Dict with validator-specific output fields
            (e.g., is_duplicate, is_ordered, is_corrupt, missing_fields).
        confidence: Process confidence score (0.0–1.0).
            Describes how certain the validator is about its result,
            NOT market confidence.
    """
    validator_name: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class AggregateValidation:
    """Aggregated validation result after routing through all applicable validators.

    Fields:
        tier: The ValidationTier used for this packet.
        decision: PASS / FAIL / FLAG.
        results: List of individual ValidationResult from each validator.
        validation_confidence: Proportion of validators that passed (0.0–1.0).
    """
    tier: ValidationTier
    decision: ValidationDecision
    results: list[ValidationResult] = field(default_factory=list)
    validation_confidence: float = 0.0


# =============================================================================
# DATACLASSES — CLEANING LAYER
# =============================================================================


@dataclass
class CleaningResult:
    """Output from a single cleaning operation on a packet.

    Fields:
        cleaned_record: The cleaned version of the packet.
            None if the packet was removed/quarantined.
        removed: Whether the packet was removed (quarantined) instead of cleaned.
        removal_reason: Explanation for removal (None if kept).
        repaired: Whether any anomaly repair was applied.
        repair_action: Description of the repair action taken (None if no repair).
        anomaly_flags: List of anomalies detected during cleaning.
    """
    cleaned_record: dict[str, Any] | None = None
    removed: bool = False
    removal_reason: str | None = None
    repaired: bool = False
    repair_action: str | None = None
    original_values: dict[str, Any] | None = None
    anomaly_flags: list[str] = field(default_factory=list)


# =============================================================================
# DATACLASSES — STRUCTURING LAYER
# =============================================================================


@dataclass
class StructureResult:
    """Output from the structuring layer for a single structured product.

    Fields:
        stream_type: One of StreamType values.
        stream_data: The structured data (tick stream, candle, snapshot, etc.).
        metadata: Dict with stream metadata (start_time, end_time, count, gaps, etc.).
    """
    stream_type: StreamType
    stream_data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# DATACLASSES — METADATA SIDE-CHANNEL
# =============================================================================


@dataclass
class QualityFacts:
    """Factual quality metrics for a packet or stream.

    These are DESCRIPTIVE quality facts, NOT prescriptive trading judgments.
    - Allowed: ``packet_completeness=96%``
    - Forbidden: ``this feed is good for trading``

    Fields:
        raw_trust_level: How much raw data was available vs expected (0.0–1.0).
        validation_confidence: Proportion of validators that passed (0.0–1.0).
        packet_completeness: How complete the packet data is (0.0–1.0).
        continuity_status: Current continuity state of the stream.
        source_health_state: Current health state of the source.
    """
    raw_trust_level: float = 1.0
    validation_confidence: float = 1.0
    packet_completeness: float = 1.0
    continuity_status: ContinuityStatus = ContinuityStatus.GOOD
    source_health_state: str = "HEALTHY"


@dataclass
class PacketMetadata:
    """Packet-level metadata for dashboard debugging and traceability.

    Fields:
        packet_id: Unique packet identifier.
        source: Source name (e.g., ``"angel_one"``, ``"manual"``).
        feed_type: Feed type string (e.g., ``"spot_tick"``).
        received_at: When Floor 1 received this packet.
        packet_size_bytes: Approximate size of the raw packet.
    """
    packet_id: str
    source: str
    feed_type: str
    received_at: datetime | None = None
    packet_size_bytes: int = 0


@dataclass
class SourceTrace:
    """Source lineage through pipeline stages for a single packet.

    Enables answering: "Where did this packet come from?
    What stage did it pass through?"

    Fields:
        source: Source name.
        fetched_at: When the source data was fetched.
        validated_at: When validation completed (None if not validated).
        review_status: Current review status.
        transform_stage: Current pipeline stage.
    """
    source: str
    fetched_at: datetime | None = None
    validated_at: datetime | None = None
    review_status: str = "PENDING"
    transform_stage: TransformStage = TransformStage.RAW


@dataclass
class StageHistory:
    """Timestamp record for each pipeline stage a packet passes through.

    Fields:
        packet_id: Unique packet identifier.
        raw_at: When the packet entered the raw store.
        validated_at: When validation completed (None if not validated).
        cleaned_at: When cleaning completed (None if not cleaned).
        structured_at: When structuring completed (None if not structured).
        stuck: Whether the packet is stuck at a stage (not progressing).
    """
    packet_id: str
    raw_at: datetime | None = None
    validated_at: datetime | None = None
    cleaned_at: datetime | None = None
    structured_at: datetime | None = None
    stuck: bool = False


# =============================================================================
# DATACLASSES — REVIEW ENGINE
# =============================================================================


@dataclass
class HealthEvent:
    """A single health event emitted by the review engine.

    Fields:
        event_type: Type/category of the health event.
        severity: CAUTION / SEVERE / CRITICAL.
        source: The source or component that triggered the event.
        message: Human-readable description.
        timestamp: When the event occurred.
        details: Dict with additional event-specific data.
    """
    event_type: str
    severity: str
    source: str
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    """An audit report produced by a scheduled or event-triggered review.

    Fields:
        report_id: Unique report identifier.
        report_type: Type of audit (e.g., ``"SCHEDULED"``, ``"INVESTIGATION"``).
        summary: Human-readable summary of findings.
        findings: List of specific findings or observations.
        score: Overall health score (0.0–1.0) for the audited scope.
        timestamp: When the report was generated.
    """
    report_id: str
    report_type: str
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    score: float = 1.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DATACLASSES — REPLAY ENGINE
# =============================================================================


@dataclass
class ReplayQuery:
    """Query parameters for a replay session.

    Fields:
        start_time: Inclusive start of the replay time range.
        end_time: Inclusive end of the replay time range.
        sources: Optional list of source names to filter by.
        feed_types: Optional list of feed types to filter by.
        transform_stage: Which stage to replay from (RAW, CLEANED, STRUCTURED).
    """
    start_time: datetime
    end_time: datetime
    sources: list[str] | None = None
    feed_types: list[str] | None = None
    transform_stage: TransformStage = TransformStage.RAW


@dataclass
class ReplaySession:
    """Metadata for an active or completed replay session.

    Fields:
        session_id: Unique session identifier.
        query: The replay query that started this session.
        status: Current session status (ACTIVE, COMPLETED, FAILED).
        packets_replayed: Number of packets replayed so far.
        started_at: When the session started.
    """
    session_id: str
    query: ReplayQuery
    status: str = "ACTIVE"
    packets_replayed: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DATACLASSES — GOVERNANCE
# =============================================================================


@dataclass
class FeedContract:
    """A single feed contract registered in the Data Contract Registry.

    Defines the expected schema, quality, and governance rules for a feed.

    Fields:
        name: Stream/packet name (e.g., ``"spot_tick"``).
        ownership: Team or floor that owns this feed (e.g., ``"Floor 2"``).
        schema_fields: Dict of field_name → expected_type.
        freshness_expectation_s: Maximum acceptable age in seconds.
        source_expectations: Expected source(s) for this feed.
        data_class: MAJOR or MINOR classification.
        consumers: List of downstream consumers (e.g., ``["Floor 3"]``).
    """
    name: str
    ownership: str
    schema_fields: dict[str, str] = field(default_factory=dict)
    freshness_expectation_s: float = 300.0
    source_expectations: list[str] = field(default_factory=list)
    data_class: DataClass = DataClass.MINOR
    consumers: list[str] = field(default_factory=list)
    description: str = ""


# =============================================================================
# TYPE ALIASES
# =============================================================================

# Incoming Floor 1 5-family payload
Floor1Payload = dict[str, Any]
# {
#     "original_raw_packet": dict,
#     "minimal_source_envelope": dict,
#     "feed_routing_identity": str,
#     "source_health_facts": dict,
#     "manual_source_tags": dict | None,
# }

# Raw ingest payload (Floor 1 data + Floor 2 ingest metadata)
IngestPayload = dict[str, Any]
# Floor1Payload + {
#     "ingested_at": datetime,
#     "ingest_batch_id": str,
# }
