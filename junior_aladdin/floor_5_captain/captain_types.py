"""Floor 5 — Captain-specific types and helper definitions.

Defines enums and dataclasses used exclusively by the Captain floor.
Shared types (CaptainMood, DecisionType, TradeClass, ArmedPlan,
DecisionSnapshot, CaptainDecision, HeadReport, FloorSummary) live in
``shared/types.py`` — this file extends them with Floor 5 specifics.

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 1):
- QUALITY = Floor 3 (NOT Captain)
- CONFIDENCE = Floor 4 (NOT Captain)
- CONVICTION = Floor 5 (Captain owns this)
- Captain owns CONVICTION, decision approval, no-trade reasoning
- Captain does NOT recalculate quality or confidence — it judges them
- Captain does NOT consume Floor 3 packets as routine input
- Silence (WAIT/BLOCKED) is a valid, actively reasoned output
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from junior_aladdin.shared.types import (
    CaptainMood,
    DecisionType,
    FloorSummary,
    HeadReport,
    TradeClass,
)


# =============================================================================
# ENUMS
# =============================================================================


class DecisionState(Enum):
    """Captain's high-level operational decision state.

    Distinct from DecisionType (final output) — DecisionState includes
    intermediate states like PREPARED (armed plan created, watching).
    """
    TRADE = "TRADE"              # Final decision to trade
    WAIT = "WAIT"                # Waiting, no trade yet
    BLOCKED = "BLOCKED"          # Permission denied
    PREPARED = "PREPARED"        # Armed plan created, watching triggers


class ConvictionBand(Enum):
    """Conviction quality band for Captain's internal scoring.

    Mapped from conviction_score (0-100):
    - REJECT: 0-39   — no trade
    - WEAK: 40-59    — watch, no action
    - TRADABLE: 60-74 — trade possible, wait for confirmation
    - STRONG: 75-89  — high confidence, good to proceed
    - ELITE: 90+     — exceptional confluence, rare
    """
    REJECT = "REJECT"               # 0-39
    WEAK = "WEAK"                   # 40-59
    TRADABLE = "TRADABLE"           # 60-74
    STRONG = "STRONG"               # 75-89
    ELITE = "ELITE"                 # 90+


class ArmedPlanState(Enum):
    """Lifecycle state of an armed conditional plan.

    Plans start WATCHING after creation, then transition to one of
    TRIGGERED / EXPIRED / INVALIDATED / CANCELLED.
    """
    WATCHING = "WATCHING"           # Waiting for trigger condition
    TRIGGERED = "TRIGGERED"         # Trigger condition met — forward to execution
    EXPIRED = "EXPIRED"             # Plan timed out
    INVALIDATED = "INVALIDATED"     # Structure broke before trigger
    CANCELLED = "CANCELLED"         # Explicitly cancelled by Captain


class SilenceReason(Enum):
    """Structured reason for WAIT / BLOCKED / REJECT decisions.

    Every no-trade decision MUST carry at least one SilenceReason.
    """
    INSUFFICIENT_CONFLUENCE = "INSUFFICIENT_CONFLUENCE"
    PSYCHOLOGY_BLOCK = "PSYCHOLOGY_BLOCK"
    ACTIVE_TRADE_EXISTS = "ACTIVE_TRADE_EXISTS"
    DEAD_MARKET = "DEAD_MARKET"
    TRAP_RISK_HIGH = "TRAP_RISK_HIGH"
    STALE_SETUP = "STALE_SETUP"
    PLAN_EXPIRED = "PLAN_EXPIRED"
    NARRATIVE_SHIFT = "NARRATIVE_SHIFT"
    CAPITAL_MISMATCH = "CAPITAL_MISMATCH"
    REAL_MODE_LOCK = "REAL_MODE_LOCK"
    WEAK_CONVICTION = "WEAK_CONVICTION"


class InterventionSeverity(Enum):
    """Severity of a Captain intervention during an active trade.

    Intervention is RARE — NOT for routine management.
    """
    NORMAL = "NORMAL"                       # Standard intervention
    CAUTION = "CAUTION"                     # Significant concern
    EMERGENCY_OVERRIDE = "EMERGENCY_OVERRIDE"  # Critical risk event


class SessionPhase(Enum):
    """NIFTY 50 intraday session phases for Captain's aggression policy.

    Timings (IST):
    - OPENING: 9:15-9:45 — observe/cautious, context building
    - GOLDEN_MORNING: 9:45-11:00 — strongest permission window
    - LUNCH: 11:00-13:00 — defensive/selective, lower volume
    - CLOSING: 13:00-15:30 — cautious/risk-aware
    """
    OPENING = "OPENING"
    GOLDEN_MORNING = "GOLDEN_MORNING"
    LUNCH = "LUNCH"
    CLOSING = "CLOSING"


class ReportTrustTier(Enum):
    """Captain's trust tier for a head report after weighting.

    Computed from: head type priority × head state × freshness × context quality.
    """
    FULL = "FULL"           # Head is READY, fresh, high priority
    REDUCED = "REDUCED"     # Some concern (UNCERTAIN / warm / low context quality)
    MINIMAL = "MINIMAL"     # Major concern (STALE / very low freshness / core head STALE)


# =============================================================================
# DATACLASSES — Captain Input & State
# =============================================================================


@dataclass
class CaptainInput:
    """Full input payload received by Captain from Floor 4 and system context.

    Fields:
        floor_summary: The aggregated FloorSummary from Floor 4.
        head_reports: Dict mapping head_name → HeadReport. All 6 heads.
        system_context: Additional system-level context (mode, capital, session).
    """
    floor_summary: FloorSummary = field(default_factory=lambda: FloorSummary(
        summary_timestamp=datetime.utcnow(),
    ))
    head_reports: dict[str, HeadReport] = field(default_factory=dict)
    system_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaptainState:
    """Captain's current operational state for dashboard (Side B).

    Fields:
        mood: Current Captain mood.
        active_trade: Whether a trade is currently active.
        decision_state: Current decision state (TRADE/WAIT/BLOCKED/PREPARED).
        conviction_band: Current conviction quality band.
        market_story_summary: Short summary of today's market story.
        silence_reason: If no-trade, the primary silence reason.
        session_phase: Current session phase.
        real_mode_locked: Whether REAL mode is locked by loss_lock_manager.
    """
    mood: CaptainMood = CaptainMood.OBSERVER
    active_trade: bool = False
    decision_state: DecisionState = DecisionState.WAIT
    conviction_band: ConvictionBand = ConvictionBand.REJECT
    market_story_summary: str = ""
    silence_reason: str = ""
    session_phase: SessionPhase = SessionPhase.OPENING
    real_mode_locked: bool = False


# =============================================================================
# DATACLASSES — Permission Gate
# =============================================================================


@dataclass
class PermissionResult:
    """Result of Captain's permission gate check.

    If allowed is False, Captain must NOT proceed to trade construction.
    Psychology block is NON-OVERRIDABLE (locked architecture rule).

    Fields:
        allowed: Whether trading is permitted.
        block_reason: Human-readable reason if blocked.
        blocked_by: List of check names that caused the block.
        timestamp: When the permission check was performed.
    """
    allowed: bool = True
    block_reason: str = ""
    blocked_by: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DATACLASSES — Market Story & Narrative Timeline
# =============================================================================


@dataclass
class MarketStory:
    """Captain's understanding of today's market context.

    Built by market_story_engine from Floor Summary + head reports.

    Fields:
        regime: Market regime description (e.g., "TREND_UP", "RANGE", "CHOP").
        session_phase: Current session phase.
        premium_discount_location: Price location relative to PD array.
        key_levels_interaction: Description of how price is interacting with key levels.
        bias: Directional bias derived from market structure.
        summary: Human-readable market story summary.
        timestamp: When this story was built.
    """
    regime: str = ""
    session_phase: SessionPhase = SessionPhase.OPENING
    premium_discount_location: str = ""
    key_levels_interaction: str = ""
    bias: str = "NEUTRAL"
    summary: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NarrativeTimelineEvent:
    """A single event in Captain's narrative timeline.

    Fields:
        event_type: Type of event (e.g., "gap_up", "liquidity_sweep", "fvg_creation").
        details: Human-readable description.
        timestamp: When the event occurred.
        price_level: Price level at which the event occurred (if relevant).
    """
    event_type: str = ""
    details: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    price_level: float = 0.0


@dataclass
class NarrativeTimeline:
    """Captain's timestamped intraday event-chain memory.

    Tracks how the market arrived at its current state — not just
    what the market is doing now.

    Fields:
        events: Chronological list of significant market events.
        last_update: When the timeline was last updated.
        event_count: Total number of events tracked.
    """
    events: list[NarrativeTimelineEvent] = field(default_factory=list)
    last_update: datetime = field(default_factory=datetime.utcnow)
    event_count: int = 0


# =============================================================================
# DATACLASSES — Confluence & Opposite Case
# =============================================================================


@dataclass
class ConfluenceResult:
    """Result of Captain's weighted confluence analysis.

    Combines directional head reports with trust weighting.
    NOT simple democracy — SMC + ICT opposing = stronger veto.

    Fields:
        confluence_quality: Quality of alignment (0.0–1.0).
        conflict_present: Whether directional heads disagree.
        aligned_heads: List of heads aligned with dominant direction.
        opposing_heads: List of heads opposing dominant direction.
        dominant_direction: The dominant directional bias (BULLISH/BEARISH/NEUTRAL).
        weighting_summary: Dict mapping head_name → trust weight used.
        timestamp: When confluence was computed.
    """
    confluence_quality: float = 0.0
    conflict_present: bool = False
    aligned_heads: list[str] = field(default_factory=list)
    opposing_heads: list[str] = field(default_factory=list)
    dominant_direction: str = "NEUTRAL"
    weighting_summary: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OppositeCase:
    """Captain's pre-mortem opposite case analysis.

    Checks the strongest argument AGAINST the proposed trade direction
    before committing. Reduces one-sided overconfidence.

    Fields:
        exists: Whether a meaningful opposite case exists.
        strength: Strength of the opposite case (0.0–1.0).
        reasons: List of reasons why opposite case matters.
        mitigating_factors: List of factors that reduce opposite case risk.
    """
    exists: bool = False
    strength: float = 0.0
    reasons: list[str] = field(default_factory=list)
    mitigating_factors: list[str] = field(default_factory=list)


# =============================================================================
# DATACLASSES — Conviction Scores
# =============================================================================


@dataclass
class ConvictionScore:
    """Captain's three internal scores and conviction band.

    Locked architecture:
    - permission_score: How permissive is the environment (0-100).
    - conviction_score: How confident is Captain in this trade (0-100).
    - no_trade_score: How strong is the case for NOT trading (0-100).

    Conviction bands mapped from conviction_score:
    - 0-39  → REJECT
    - 40-59 → WEAK
    - 60-74 → TRADABLE
    - 75-89 → STRONG
    - 90+   → ELITE

    Fields:
        permission_score: Permission level (0-100).
        conviction_score: Conviction level (0-100).
        no_trade_score: No-trade justification level (0-100).
        conviction_band: Computed ConvictionBand from conviction_score.
        timestamp: When scores were computed.
    """
    permission_score: float = 0.0
    conviction_score: float = 0.0
    no_trade_score: float = 0.0
    conviction_band: ConvictionBand = ConvictionBand.REJECT
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def conviction_score_to_band(score: float) -> ConvictionBand:
    """Map a conviction score (0-100) to a ConvictionBand.

    Args:
        score: Conviction score between 0 and 100.

    Returns:
        The corresponding ConvictionBand enum member.
    """
    if score >= 90:
        return ConvictionBand.ELITE
    elif score >= 75:
        return ConvictionBand.STRONG
    elif score >= 60:
        return ConvictionBand.TRADABLE
    elif score >= 40:
        return ConvictionBand.WEAK
    return ConvictionBand.REJECT


def get_session_phase_from_time(hour: int, minute: int) -> SessionPhase:
    """Determine session phase from IST hour and minute.

    Args:
        hour: Hour in IST (24-hour format).
        minute: Minute in IST.

    Returns:
        The corresponding SessionPhase.
    """
    total_minutes = hour * 60 + minute
    opening_start = 9 * 60 + 15      # 9:15 IST
    golden_start = 9 * 60 + 45       # 9:45 IST
    lunch_start = 11 * 60 + 0        # 11:00 IST
    closing_start = 13 * 60 + 0      # 13:00 IST
    market_close = 15 * 60 + 30      # 15:30 IST

    if total_minutes < opening_start or total_minutes > market_close:
        return SessionPhase.OPENING  # Default to opening for pre/post market
    elif total_minutes < golden_start:
        return SessionPhase.OPENING
    elif total_minutes < lunch_start:
        return SessionPhase.GOLDEN_MORNING
    elif total_minutes < closing_start:
        return SessionPhase.LUNCH
    return SessionPhase.CLOSING


def get_aggression_modifier(phase: SessionPhase) -> float:
    """Get aggression modifier for a session phase.

    Modifier is applied to conviction threshold:
    - Positive = more aggressive (lower threshold)
    - Negative = less aggressive (higher threshold)

    Args:
        phase: The session phase.

    Returns:
        Float modifier (e.g., -0.2, +0.1).
    """
    modifiers = {
        SessionPhase.OPENING: -0.2,           # Cautious
        SessionPhase.GOLDEN_MORNING: 0.1,     # Slightly aggressive
        SessionPhase.LUNCH: -0.1,             # Defensive
        SessionPhase.CLOSING: -0.2,           # Cautious
    }
    return modifiers.get(phase, 0.0)


def get_permission_strictness(phase: SessionPhase) -> str:
    """Get permission strictness level for a session phase.

    Args:
        phase: The session phase.

    Returns:
        Strictness level string: "NORMAL", "HIGH", "VERY_HIGH".
    """
    strictness = {
        SessionPhase.OPENING: "HIGH",
        SessionPhase.GOLDEN_MORNING: "NORMAL",
        SessionPhase.LUNCH: "NORMAL",
        SessionPhase.CLOSING: "VERY_HIGH",
    }
    return strictness.get(phase, "HIGH")
