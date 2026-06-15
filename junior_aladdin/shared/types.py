"""Shared enums, dataclasses, and base contracts for Junior Aladdin.

This file is the SINGLE SOURCE OF TRUTH for type definitions used across
all 5 floors and 3 sides. Every module imports from here.

Architecture rules:
- QUALITY = Floor 3
- CONFIDENCE = Floor 4
- CONVICTION = Floor 5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# =============================================================================
# ENUMS
# =============================================================================


class MarketPhase(Enum):
    """NIFTY 50 market session phases."""
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    LUNCH = "LUNCH"
    CLOSING = "CLOSING"
    POST_CLOSE = "POST_CLOSE"


class SessionType(Enum):
    """Global trading session classification."""
    ASIA = "ASIA"
    LONDON = "LONDON"
    NY = "NY"
    ALL = "ALL"


class BiasType(Enum):
    """Directional bias."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TrendState(Enum):
    """Market trend classification."""
    STRONG_UP = "STRONG_UP"
    WEAK_UP = "WEAK_UP"
    RANGE = "RANGE"
    WEAK_DOWN = "WEAK_DOWN"
    STRONG_DOWN = "STRONG_DOWN"


class HeadState(Enum):
    """Department Head operational state."""
    READY = "READY"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"


class CaptainMood(Enum):
    """Captain's current decision-making temperament."""
    OBSERVER = "OBSERVER"
    PATIENT = "PATIENT"
    AGGRESSIVE = "AGGRESSIVE"
    DEFENSIVE = "DEFENSIVE"
    SILENT = "SILENT"


class DecisionType(Enum):
    """Final Captain decision."""
    TRADE = "TRADE"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"


class TradeClass(Enum):
    """Classification of trade type."""
    SCALP = "SCALP"
    CONTINUATION = "CONTINUATION"
    REVERSAL = "REVERSAL"
    LIQUIDITY_RECLAIM = "LIQUIDITY_RECLAIM"
    OPTIONS_PRESSURE = "OPTIONS_PRESSURE"


class ExecutionMode(Enum):
    """Side A execution mode."""
    ALERT = "ALERT"
    PAPER = "PAPER"
    REAL = "REAL"


class DataHealth(Enum):
    """Data quality / system health level.

    Used by Floor 2 review signals and consumed by Floor 5 (Captain)
    and Side A (Risk Gate / Data Health Policy).

    Values:
        GOOD: All data sources healthy.
        CAUTION: Minor degradation detected.
        DEGRADED: Significant degradation — stricter checks.
        STALE: Data not updating — block new entries.
        CRITICAL: Critical failure — escalation required.
    """
    GOOD = "GOOD"
    CAUTION = "CAUTION"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    CRITICAL = "CRITICAL"


class FreshnessTag(Enum):
    """Freshness classification for heads and data."""
    FRESH = "FRESH"
    WARM = "WARM"
    STALE = "STALE"


class Severity(Enum):
    """Event severity classification."""
    INFO = "INFO"
    CAUTION = "CAUTION"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


class LifecycleState(Enum):
    """Source connection lifecycle state (Floor 1)."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    AUTH_FAILED = "AUTH_FAILED"
    DISCONNECTED = "DISCONNECTED"


class MemoryEventFamily(Enum):
    """Side C event family classification."""
    TRADE_JOURNAL = "TRADE_JOURNAL"
    DECISION_JOURNAL = "DECISION_JOURNAL"
    EXECUTION_EVENT = "EXECUTION_EVENT"
    HEALTH_EVENT = "HEALTH_EVENT"
    OVERRIDE = "OVERRIDE"
    REPLAY_REF = "REPLAY_REF"
    REVIEW_REF = "REVIEW_REF"
    BLOCKED_ACTION = "BLOCKED_ACTION"


class FeedType(Enum):
    """Floor 1 feed routing identities."""
    SPOT_FEED = "SPOT_FEED"
    OPTIONS_FEED = "OPTIONS_FEED"
    VIX_FEED = "VIX_FEED"
    CALENDAR_FEED = "CALENDAR_FEED"
    MACRO_FEED = "MACRO_FEED"


# =============================================================================
# DATACLASSES — FLOOR 1
# =============================================================================


@dataclass
class PacketEnvelope:
    """Standardized operational envelope for all incoming data.

    Floor 1 wraps every raw packet in this envelope before forwarding to Floor 2.
    """
    source: str
    feed_type: str
    connection_id: str
    packet_id: str
    routing_id: str
    received_at: datetime
    source_timestamp: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceHealth:
    """Floor 1 source connection health metrics."""
    lifecycle_state: LifecycleState = LifecycleState.HEALTHY
    latency_ms: float = 0.0
    heartbeat_age_s: float = 0.0
    reconnect_count: int = 0
    ltp: float = 0.0  # Latest price from WebSocket tick


# =============================================================================
# DATACLASSES — FLOOR 4
# =============================================================================


@dataclass
class HeadReport:
    """Individual Department Head report sent to Captain.

    Every head produces this exact structure.
    Macro and Psychology heads must NOT produce primary_setup or backup_setup.
    """
    head_name: str
    state: HeadState
    freshness_score: float  # 0.0–1.0
    freshness_tag: FreshnessTag
    last_deep_update: datetime
    bias: BiasType
    confidence: float  # 0.0–1.0
    dominant_tf: str
    timeframe_view: str
    primary_setup: str | None = None
    backup_setup: str | None = None
    active_zones: list[dict[str, Any]] = field(default_factory=list)
    armed_triggers: list[dict[str, Any]] = field(default_factory=list)
    invalidation: dict[str, Any] = field(default_factory=dict)
    bull_case: str = ""
    bear_case: str = ""
    confluence_note: str = ""
    witness_summary: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # SMC / ICT mandatory fields
    context_quality_score: float | None = None  # MANDATORY for SMC/ICT heads

    # Macro head specific
    event_risk_flag: bool = False

    # Psychology head specific
    trade_allowed: bool = True
    caution_level: float = 0.0
    cooldown_active: bool = False
    repeated_mistake_flag: bool = False
    trap_pressure: bool = False
    block_reason: str = ""


@dataclass
class FloorSummary:
    """Aggregated summary of all 6 head reports for Captain.

    Captain reads this FIRST (summary-first workflow),
    then drills down into individual reports if needed.
    """
    summary_timestamp: datetime
    floor_bias_snapshot: dict[str, Any] = field(default_factory=dict)
    floor_confidence_snapshot: dict[str, Any] = field(default_factory=dict)
    active_setup_count: int = 0
    primary_setups_by_head: dict[str, Any] = field(default_factory=dict)
    backup_setups_by_head: dict[str, Any] = field(default_factory=dict)
    ready_heads_count: int = 0
    uncertain_heads_count: int = 0
    stale_heads_count: int = 0
    conflict_present: bool = False
    stale_warning_present: bool = False
    strongest_domain_signal: str = ""
    strongest_context_signal: str = ""
    strongest_risk_warning: str = ""
    data_health_signal: DataHealth = DataHealth.GOOD
    summary_witness_lines: list[str] = field(default_factory=list)
    core_head_health_snapshot: dict[str, Any] = field(default_factory=dict)
    head_health_snapshot: dict[str, Any] = field(default_factory=dict)
    setup_presence: str | None = None  # HAS_SETUP / NO_SETUP / None
    setup_absence_context: str | None = None  # READY_NO_SETUP / UNCERTAIN_NO_SETUP / STALE_NO_SETUP


# =============================================================================
# DATACLASSES — FLOOR 5 (CAPTAIN)
# =============================================================================


@dataclass
class ArmedPlan:
    """Conditional trade plan created by Captain after heavy cycle.

    Light cycle watches these plans for trigger conditions only.
    """
    plan_id: str
    direction: str  # BUY / SELL
    setup_class: str
    trigger_condition: dict[str, Any] = field(default_factory=dict)
    expiry_condition: dict[str, Any] = field(default_factory=dict)
    invalidation_level: float = 0.0
    originating_heads: list[str] = field(default_factory=list)
    readiness: str = "WATCHING"  # WATCHING / TRIGGERED / EXPIRED / INVALIDATED
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DecisionSnapshot:
    """Frozen snapshot of every major Captain decision.

    Used for audit, review, shadow logging, confidence calibration.
    """
    snapshot_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    market_story_summary: str = ""
    narrative_timeline_excerpt: list[str] = field(default_factory=list)
    heads_summary: dict[str, Any] = field(default_factory=dict)
    armed_plan_reference: str | None = None
    conviction_score: float = 0.0
    invalidation: dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""
    session_context: dict[str, Any] = field(default_factory=dict)
    capital_context: dict[str, Any] = field(default_factory=dict)
    mood: CaptainMood = CaptainMood.OBSERVER


@dataclass
class CaptainDecision:
    """Final Captain output sent to Side A for execution."""
    decision: DecisionType
    action: str  # BUY / SELL
    option_side: str  # CE / PE
    selected_strike: str
    trade_class: TradeClass
    permission_score: float = 0.0
    conviction_score: float = 0.0
    no_trade_score: float = 0.0
    entry_plan: dict[str, Any] = field(default_factory=dict)
    invalidation_level: float = 0.0
    stop_loss_plan: dict[str, Any] = field(default_factory=dict)
    target_plan: dict[str, Any] = field(default_factory=dict)
    reason_summary: str = ""
    silence_reason: str | None = None
    snapshot_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DATACLASSES — SIDE A (EXECUTION)
# =============================================================================


@dataclass
class ExecutionIntent:
    """Captain's trade intent sent to Side A for execution.

    This is the primary contract between Floor 5 (Captain) and Side A (Execution).
    All mandatory fields must be populated before forwarding to the execution path.

    Fields:
        trade_id: Unique trade identifier.
        action: BUY or SELL.
        option_side: CE or PE.
        selected_strike: The chosen strike price as string.
        trade_class: Classification of the trade (SCALP, CONTINUATION, etc.).
        entry_plan: Dict with trigger, zone, and confirmation details.
        invalidation_level: Price level at which the trade thesis is invalid.
        stop_loss_plan: Dict with price and type for stop loss.
        target_plan: Dict with targets list and trailing config.
        capital_context: Dict with available_capital, max_risk_per_trade.
        mode: Execution mode (ALERT / PAPER / REAL).
        intervention_allowed: Whether Captain allows override during execution.
        intent_fingerprint: Unique execution identity for duplicate detection.
        timestamp: When this intent was created.
    """
    trade_id: str
    action: str  # BUY / SELL
    option_side: str  # CE / PE
    selected_strike: str
    trade_class: TradeClass
    entry_plan: dict[str, Any] = field(default_factory=dict)
    invalidation_level: float = 0.0
    stop_loss_plan: dict[str, Any] = field(default_factory=dict)
    target_plan: dict[str, Any] = field(default_factory=dict)
    capital_context: dict[str, Any] = field(default_factory=dict)
    mode: ExecutionMode = ExecutionMode.ALERT
    intervention_allowed: bool = False
    intent_fingerprint: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DATACLASSES — SIDE C (MEMORY)
# =============================================================================


@dataclass
class MemoryEvent:
    """Standard event record for Side C storage."""
    event_type: str
    source: str  # emitting floor/side name
    family: str  # must be one of MemoryEventFamily values
    emitter: str = ""  # specific emitter id (e.g., "floor_1", "side_a")
    timestamp: datetime = field(default_factory=datetime.utcnow)
    severity: Severity = Severity.INFO
    payload: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# DATACLASSES — FLOOR 2 (DATA CENTER)
# =============================================================================


@dataclass
class Floor2Handoff:
    """Complete Floor 1 → Floor 2 handoff payload.

    All 5 payload families must be present.
    """
    original_raw_packet: dict[str, Any] = field(default_factory=dict)
    minimal_source_envelope: dict[str, Any] = field(default_factory=dict)
    feed_routing_identity: str = ""
    source_health_facts: dict[str, Any] = field(default_factory=dict)
    manual_source_tags: dict[str, Any] | None = None


# =============================================================================
# DATACLASSES — FLOOR 3 (CALCULATIONS)
# =============================================================================


@dataclass
class CMSP:
    """Common Market State Projection — shared state across all domains.

    Owner: Floor 3
    Consumers: Floor 4 heads, Floor 5 Captain (via Floor Summary)
    """
    price_state: dict[str, Any] = field(default_factory=dict)
    volatility_state: dict[str, Any] = field(default_factory=dict)
    session_state: dict[str, Any] = field(default_factory=dict)
    regime_state: dict[str, Any] = field(default_factory=dict)
    key_levels: list[float] = field(default_factory=list)
