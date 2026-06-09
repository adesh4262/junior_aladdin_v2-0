"""Floor 2 Data Center — feed schemas and contract definitions.

All feed schemas are defined here as Python dataclasses/templates.
Three contract categories:
  - Incoming contracts (Floor 1 → Floor 2)
  - Internal contracts (between Floor 2 sub-systems)
  - Outgoing contracts (Floor 2 → Floor 3)

Architecture rules:
- All mandatory fields are documented per contract.
- Floor 2 contracts are FACTUAL — no intelligence, no opinion.
- Outgoing contracts match Floor 3's expected input exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import DataClass, FeedContract


# =============================================================================
# INCOMING CONTRACTS — Floor 1 → Floor 2
# =============================================================================

FLOOR1_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "original_raw_packet",
    "minimal_source_envelope",
    "feed_routing_identity",
    "source_health_facts",
    "manual_source_tags",
})

SOURCE_ENVELOPE_KEYS: frozenset[str] = frozenset({
    "source",
    "feed_type",
    "connection_id",
    "packet_id",
    "routing_id",
    "received_at",
})

FEED_TYPE_TO_VALIDATION_TIER: dict[str, str] = {
    # Tier A — very strong (all 5 validators)
    "spot_tick": "A",
    "options_snapshot": "A",
    # Tier B — strong (4 validators, skip corruption)
    "vix_tick": "B",
    # Tier C — medium/basic (2 validators: schema + timestamp)
    "macro_data": "C",
    "calendar_event": "C",
}

FEED_TYPE_TO_DATA_CLASS: dict[str, str] = {
    "spot_tick": "MAJOR",
    "options_snapshot": "MAJOR",
    "vix_tick": "MAJOR",
    "calendar_event": "MINOR",
    "macro_data": "MINOR",
}

FEED_TYPE_TO_ROUTING_IDENTITY: dict[str, str] = {
    "spot_tick": "SPOT_FEED",
    "options_snapshot": "OPTIONS_FEED",
    "vix_tick": "VIX_FEED",
    "macro_data": "MACRO_FEED",
    "calendar_event": "CALENDAR_FEED",
}


# =============================================================================
# INTERNAL CONTRACTS — Between Floor 2 sub-systems
# =============================================================================


# --- Floor 2 Ingest Payload (ingress/ → raw/) ---


@dataclass
class Floor2IngestPayload:
    """Normalised ingest payload passed from the ingress sub-system to raw storage.

    Preserves ALL Floor 1 fields (additive, never subtractive) and adds
    Floor 2 ingest metadata.

    Mandatory fields:
        original_raw_packet: Exact copy of Floor 1 raw data.
        minimal_source_envelope: Dict with source, feed_type, connection_id,
            packet_id, routing_id, received_at.
        feed_routing_identity: FeedType value string (e.g. ``"SPOT_FEED"``).
        source_health_facts: Dict with lifecycle_state, latency_ms,
            heartbeat_age_s, reconnect_count.
        manual_source_tags: Dict or None.
        ingested_at: When Floor 2 ingested this packet (UTC).
        ingest_batch_id: Batch identifier for this ingest run.
    """
    original_raw_packet: dict[str, Any] = field(default_factory=dict)
    minimal_source_envelope: dict[str, Any] = field(default_factory=dict)
    feed_routing_identity: str = ""
    source_health_facts: dict[str, Any] = field(default_factory=dict)
    manual_source_tags: dict[str, Any] | None = None
    ingested_at: datetime | None = None
    ingest_batch_id: str = ""


# =============================================================================
# OUTGOING CONTRACTS — Floor 2 → Floor 3 (7 mandatory categories)
# =============================================================================


@dataclass
class ValidatedTick:
    """A single validated tick in a tick stream.

    Fields:
        timestamp: Tick timestamp.
        price: Last traded price.
        volume: Tick volume.
        source: Source name (e.g., ``"angel_one"``).
        feed_type: Feed type (e.g., ``"spot_tick"``).
        sequence_id: Monotonically increasing position in the stream.
    """
    timestamp: datetime | None = None
    price: float = 0.0
    volume: int = 0
    source: str = ""
    feed_type: str = ""
    sequence_id: int = 0


@dataclass
class TickStream:
    """Category 1: Structured tick stream with sequential ordering.

    Fields:
        stream_id: Unique stream identifier.
        ticks: Ordered list of validated ticks.
        start_time: Timestamp of the first tick.
        end_time: Timestamp of the last tick.
        tick_count: Total number of ticks.
        gaps: List of detected gaps (if any).
    """
    stream_id: str = ""
    ticks: list[ValidatedTick] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    tick_count: int = 0
    gaps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Candle:
    """A single OHLCV candle.

    Fields:
        timestamp: Candle open time.
        open: Opening price.
        high: Highest price.
        low: Lowest price.
        close: Closing price.
        volume: Total volume.
        is_complete: Whether this candle represents a complete time window.
    """
    timestamp: datetime | None = None
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    is_complete: bool = False


@dataclass
class CandleStream:
    """Category 2: 1m OHLCV candle stream (minimum resolution).

    Higher timeframes are built in Floor 3 from this foundation.

    Fields:
        stream_id: Unique stream identifier.
        candles: Ordered list of 1m candles.
        source: Source name.
        feed_type: Feed type (e.g., ``"spot_tick"``).
    """
    stream_id: str = ""
    candles: list[Candle] = field(default_factory=list)
    source: str = ""
    feed_type: str = ""


@dataclass
class OptionsSnapshot:
    """Category 3: OI snapshot at a configured interval.

    Fields:
        timestamp: Snapshot timestamp.
        expiry: Option expiry date.
        strike: Strike price.
        option_type: ``"CE"`` or ``"PE"``.
        oi: Open interest.
        premium: Last traded premium.
        iv: Implied volatility (percentage, e.g., 15.5 for 15.5%).
        change_in_oi: Change in OI since last snapshot.
    """
    timestamp: datetime | None = None
    expiry: str = ""
    strike: float = 0.0
    option_type: str = ""  # CE / PE
    oi: int = 0
    premium: float = 0.0
    iv: float = 0.0
    change_in_oi: int = 0


@dataclass
class OptionsSnapshotStream:
    """Collection of options snapshots for a configured interval.

    Fields:
        stream_id: Unique stream identifier.
        interval_minutes: Snapshot interval in minutes.
        snapshots: Ordered list of option snapshots.
    """
    stream_id: str = ""
    interval_minutes: int = 5
    snapshots: list[OptionsSnapshot] = field(default_factory=list)


@dataclass
class SessionPacket:
    """Category 4: Explicit session context packet.

    Fields:
        session_id: Unique session identifier.
        session_type: Market session type (e.g., ``"REGULAR"``, ``"PRE_OPEN"``).
        session_phase: Current phase (e.g., ``"OPENING"``, ``"MID"``, ``"CLOSING"``).
        session_status: ``"ACTIVE"`` or ``"CLOSED"``.
        timestamp: When this session packet was created.
        references: Dict of broader session references (Asia, London, NY).
    """
    session_id: str = ""
    session_type: str = ""
    session_phase: str = ""
    session_status: str = ""
    timestamp: datetime | None = None
    references: dict[str, Any] = field(default_factory=dict)


@dataclass
class MacroSupportPacket:
    """Category 5: Structured macro/support/context feed packet.

    Fields:
        timestamp: Data timestamp.
        data_type: Type of data (e.g., ``"VIX"``, ``"FII_DII"``, ``"GLOBAL_CUE"``).
        value: The primary value of this data point.
        source: Source of the data.
        freshness: ``"FRESH"``, ``"WARM"``, or ``"STALE"``.
        metadata: Dict with additional context-specific fields.
    """
    timestamp: datetime | None = None
    data_type: str = ""
    value: Any = None
    source: str = ""
    freshness: str = "FRESH"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MacroSupportStream:
    """Collection of macro/support packets.

    Fields:
        stream_id: Unique stream identifier.
        data_type: Type of data this stream carries.
        packets: Ordered list of macro support packets.
    """
    stream_id: str = ""
    data_type: str = ""
    packets: list[MacroSupportPacket] = field(default_factory=list)


# =============================================================================
# COMPUTED-READY HOOKS (Category 7)
# =============================================================================


@dataclass
class ComputedReadyHook:
    """Category 7: Stable interface definition for Floor 3 computation staging.

    NOT computation, NOT intelligence — just the interface contract.

    Fields:
        hook_name: Name of the computed-ready hook.
        version: Hook version for compatibility tracking.
        input_schema: Dict describing expected input fields and types.
        output_format: Description of the output format.
        description: Human-readable description of what this hook enables.
    """
    hook_name: str = ""
    version: str = "1.0"
    input_schema: dict[str, str] = field(default_factory=dict)
    output_format: str = ""
    description: str = ""


# =============================================================================
# FLOOR 3 HANDOFF — ALL 7 CATEGORIES
# =============================================================================


@dataclass
class Floor3Handoff:
    """Complete Floor 2 → Floor 3 handoff payload.

    All 7 output categories must be present.

    Fields:
        validated_tick_stream: Category 1 — structured tick stream.
        validated_candle_streams: Category 2 — 1m OHLCV candles.
        options_snapshots: Category 3 — OI snapshots at configured intervals.
        session_packets: Category 4 — explicit session context.
        macro_support_packets: Category 5 — structured macro/support feeds.
        metadata_side_channel: Category 6 — quality facts, traceability, review state.
        computed_ready_hooks: Category 7 — stable computation staging interfaces.
    """
    validated_tick_stream: TickStream = field(default_factory=TickStream)
    validated_candle_streams: CandleStream = field(default_factory=CandleStream)
    options_snapshots: OptionsSnapshotStream = field(default_factory=OptionsSnapshotStream)
    session_packets: list[SessionPacket] = field(default_factory=list)
    macro_support_packets: list[MacroSupportStream] = field(default_factory=list)
    metadata_side_channel: dict[str, Any] = field(default_factory=dict)
    computed_ready_hooks: list[ComputedReadyHook] = field(default_factory=list)


# =============================================================================
# DEFAULT CONTRACT REGISTRY
# =============================================================================


def default_feed_contracts() -> list[FeedContract]:
    """Return the default set of feed contracts for the Data Contract Registry.

    These define the expected schema, quality, and governance rules for
    each known feed type.
    """
    return [
        FeedContract(
            name="spot_tick",
            ownership="Floor 2 / Raw Storage",
            schema_fields={
                "ltp": "float",
                "volume": "int",
                "symbol": "str",
                "feed_type": "str",
                "timestamp": "str",
            },
            freshness_expectation_s=1.0,
            source_expectations=["angel_one"],
            data_class=DataClass.MAJOR,
            consumers=["Floor 3 — All Domains"],
            description="NIFTY 50 spot market tick data (LTP, volume, bid/ask).",
        ),
        FeedContract(
            name="options_snapshot",
            ownership="Floor 2 / Raw Storage",
            schema_fields={
                "oi": "int",
                "premium": "float",
                "strike": "float",
                "expiry": "str",
                "option_type": "str",
                "feed_type": "str",
            },
            freshness_expectation_s=5.0,
            source_expectations=["angel_one"],
            data_class=DataClass.MAJOR,
            consumers=["Floor 3 — Options Domain"],
            description="Options chain snapshot with OI, premium, and strike data.",
        ),
        FeedContract(
            name="vix_tick",
            ownership="Floor 2 / Raw Storage",
            schema_fields={
                "value": "float",
                "feed_type": "str",
                "timestamp": "str",
            },
            freshness_expectation_s=5.0,
            source_expectations=["angel_one"],
            data_class=DataClass.MAJOR,
            consumers=["Floor 3 — Macro Domain"],
            description="India VIX tick data.",
        ),
        FeedContract(
            name="macro_data",
            ownership="Floor 2 / Raw Storage",
            schema_fields={
                "feed_type": "str",
                "stub": "bool",
            },
            freshness_expectation_s=300.0,
            source_expectations=["angel_one", "manual"],
            data_class=DataClass.MINOR,
            consumers=["Floor 3 — Macro Domain"],
            description="Macro data (FII/DII, global cues) — currently stub.",
        ),
        FeedContract(
            name="calendar_event",
            ownership="Floor 2 / Raw Storage",
            schema_fields={
                "feed_type": "str",
                "stub": "bool",
            },
            freshness_expectation_s=3600.0,
            source_expectations=["manual"],
            data_class=DataClass.MINOR,
            consumers=["Floor 3 — Macro Domain", "Floor 4 — Psychology Head"],
            description="Calendar events (holidays, expiry) — currently stub.",
        ),
        FeedContract(
            name="MANUAL_CALENDAR",
            ownership="Floor 1 / Manual Ingress",
            schema_fields={
                "source": "str",
                "feed_type": "str",
                "manual_source_tag": "str",
                "payload": "dict",
            },
            freshness_expectation_s=86400.0,
            source_expectations=["manual"],
            data_class=DataClass.MINOR,
            consumers=["Floor 3 — Macro Domain"],
            description="Manual calendar event (e.g., NIFTY expiry).",
        ),
        FeedContract(
            name="MANUAL_OVERRIDE",
            ownership="Floor 1 / Manual Ingress",
            schema_fields={
                "source": "str",
                "feed_type": "str",
                "manual_source_tag": "str",
                "payload": "dict",
            },
            freshness_expectation_s=86400.0,
            source_expectations=["manual"],
            data_class=DataClass.MINOR,
            consumers=["Floor 4 — All Heads", "Floor 5 — Captain"],
            description="Manual override (e.g., position size, blocking rule).",
        ),
    ]


def validate_floor1_payload(payload: dict[str, Any]) -> list[str]:
    """Validate that a Floor 1 5-family payload has all mandatory keys.

    Args:
        payload: The incoming Floor 1 handoff payload.

    Returns:
        A list of missing key names. Empty list if all keys are present.
    """
    missing = []
    for key in FLOOR1_PAYLOAD_KEYS:
        if key not in payload:
            missing.append(key)
    return missing


def validate_source_envelope(envelope: dict[str, Any]) -> list[str]:
    """Validate that a source envelope has all mandatory fields.

    Args:
        envelope: The ``minimal_source_envelope`` dict from Floor 1.

    Returns:
        A list of missing field names. Empty list if all fields are present.
    """
    missing = []
    for key in SOURCE_ENVELOPE_KEYS:
        if key not in envelope:
            missing.append(key)
    return missing


def get_validation_tier_for_feed(feed_type: str) -> str:
    """Return the validation tier for a given feed type.

    Defaults to ``"C"`` for unknown feed types.
    """
    return FEED_TYPE_TO_VALIDATION_TIER.get(feed_type, "C")


def get_data_class_for_feed(feed_type: str) -> str:
    """Return the data class (MAJOR/MINOR) for a given feed type.

    Defaults to ``"MINOR"`` for unknown feed types.
    """
    return FEED_TYPE_TO_DATA_CLASS.get(feed_type, "MINOR")
