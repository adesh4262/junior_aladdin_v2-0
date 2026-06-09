"""Floor 4 — Head-specific types and helper utilities.

Defines enums and helper types used by all Department Heads.
Shared types (HeadReport, HeadState, BiasType, FreshnessTag, FloorSummary)
live in ``shared/types.py`` — this file extends them with Floor 4 specifics.

Architecture rules (LOCKED):
- CONFIDENCE = Floor 4 (NOT quality, NOT conviction)
- Every Head must define invalidation (mandatory)
- SMC/ICT Heads must provide context_quality_score (mandatory)
- Macro/Psychology Heads must NOT produce primary_setup or backup_setup
- Heads reduce complexity for Captain, never increase it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# =============================================================================
# ENUMS
# =============================================================================


class HeadDecision(Enum):
    """High-level decision a Head communicates to Captain.

    Each Head decides one of these after interpreting Floor 3 inputs.
    """
    SETUP_ACTIVE = "SETUP_ACTIVE"          # Strongest — a valid setup exists
    WATCHING = "WATCHING"                   # Watching for trigger
    NO_SETUP = "NO_SETUP"                   # No valid setup right now
    BLOCKING = "BLOCKING"                   # Actively blocking (Psychology/Macro)


class SetupGrade(Enum):
    """Quality grade for a Head's primary/backup setup candidates.

    This is NOT confidence and NOT conviction.
    It is a structured quality hint for Captain's weighted confluence.
    """
    A = "A"  # High quality — multiple confluences, clean structure
    B = "B"  # Medium quality — some confluence, acceptable structure
    C = "C"  # Low quality — weak confluence, noisy structure


class TriggerStatus(Enum):
    """Status of an armed trigger condition."""
    PENDING = "PENDING"           # Waiting for price to reach zone
    ACTIVE = "ACTIVE"             # Zone touched — watching confirmation
    TRIGGERED = "TRIGGERED"       # Full trigger condition met
    EXPIRED = "EXPIRED"           # Trigger window closed
    INVALIDATED = "INVALIDATED"   # Structure broke before trigger


class ZoneStatus(Enum):
    """Status of an active price zone tracked by a Head."""
    ACTIVE = "ACTIVE"             # Zone is valid and relevant
    APPROACHING = "APPROACHING"   # Price moving toward zone
    TOUCHED = "TOUCHED"          # Price entered zone
    MITIGATED = "MITIGATED"       # Zone purpose fulfilled
    BROKEN = "BROKEN"             # Zone structure broken
    INVALID = "INVALID"           # No longer relevant


# =============================================================================
# HELPER DATACLASSES
# =============================================================================


@dataclass
class ZoneInfo:
    """A price zone tracked by a Head.

    Fields:
        zone_type: Human-readable type (e.g., ``"FVG"``, ``"ORDER_BLOCK"``).
        price_level: The key price level of the zone.
        direction: ``"bullish"`` or ``"bearish"``.
        status: Current zone status.
        strength: Relative strength (0.0–1.0).
        signal_ref: Reference to the originating Floor 3 signal_id.
    """
    zone_type: str = ""
    price_level: float = 0.0
    direction: str = ""
    status: ZoneStatus = ZoneStatus.ACTIVE
    strength: float = 0.5
    signal_ref: str = ""


@dataclass
class TriggerInfo:
    """A trigger condition being watched by a Head.

    Fields:
        trigger_type: Type of trigger (e.g., ``"zone_touch"``, ``"reclaim"``).
        condition: Human-readable condition description.
        zone_ref: Reference to the zone this trigger belongs to.
        status: Current trigger status.
        price_level: Price level at which the trigger activates.
    """
    trigger_type: str = ""
    condition: str = ""
    zone_ref: str = ""
    status: TriggerStatus = TriggerStatus.PENDING
    price_level: float = 0.0


@dataclass
class InvalidationRule:
    """An invalidation rule for a Head's setup.

    Every Head MUST define at least one invalidation rule.
    Captain uses these for thesis integrity tracking.

    Fields:
        condition: Human-readable invalidation condition.
        price_level: Price level at which invalidation occurs.
        reason: Why this invalidation exists.
    """
    condition: str = ""
    price_level: float = 0.0
    reason: str = ""


# =============================================================================
# FRESHNESS HELPERS
# =============================================================================

_FRESH_MAX_SECONDS = 120        # < 2 min → FRESH
_WARM_MAX_SECONDS = 600         # < 10 min → WARM
_STALE_MAX_SECONDS = 1800       # < 30 min → STALE
_CRITICAL_STALE_SECONDS = 3600  # > 60 min → severely stale


def compute_freshness(
    last_update: datetime | None,
    current_time: datetime | None = None,
) -> tuple[float, Any, int]:
    """Compute freshness score and tag from last update time.

    Args:
        last_update: When the Head was last updated (UTC).
        current_time: Current time (UTC). Uses ``datetime.utcnow()`` if None.

    Returns:
        ``(freshness_score, freshness_tag, seconds_since_update)`` tuple.
        - freshness_score: 0.0 (stale) to 1.0 (fresh).
        - freshness_tag: FreshnessTag enum member.
        - seconds_since_update: Raw seconds since last update.
    """
    from junior_aladdin.shared.types import FreshnessTag

    if last_update is None:
        return 0.0, FreshnessTag.STALE, _CRITICAL_STALE_SECONDS

    now = current_time or datetime.utcnow()
    seconds = (now - last_update).total_seconds()

    if seconds < _FRESH_MAX_SECONDS:
        score = max(0.0, 1.0 - seconds / _FRESH_MAX_SECONDS)
        return score, FreshnessTag.FRESH, int(seconds)
    elif seconds < _WARM_MAX_SECONDS:
        score = max(0.0, 0.5 - (seconds - _FRESH_MAX_SECONDS) / (_WARM_MAX_SECONDS - _FRESH_MAX_SECONDS) * 0.3)
        return score, FreshnessTag.WARM, int(seconds)
    elif seconds < _STALE_MAX_SECONDS:
        score = max(0.0, 0.2 - (seconds - _WARM_MAX_SECONDS) / (_STALE_MAX_SECONDS - _WARM_MAX_SECONDS) * 0.15)
        return score, FreshnessTag.STALE, int(seconds)
    else:
        return 0.0, FreshnessTag.STALE, int(seconds)


# =============================================================================
# BIAS HELPERS
# =============================================================================


def compute_bias_from_signals(
    bullish_count: int,
    bearish_count: int,
    neutral_threshold: float = 0.3,
) -> Any:
    """Determine bias from counted signal directions.

    Args:
        bullish_count: Number of bullish signals.
        bearish_count: Number of bearish signals.
        neutral_threshold: If the minority/majority ratio is above this
            threshold, bias is NEUTRAL (default 0.3 = 30%).

    Returns:
        ``BiasType`` enum member (BULLISH / BEARISH / NEUTRAL).
    """
    from junior_aladdin.shared.types import BiasType

    total = bullish_count + bearish_count
    if total == 0:
        return BiasType.NEUTRAL

    majority = max(bullish_count, bearish_count)
    minority = min(bullish_count, bearish_count)

    ratio = minority / majority if majority > 0 else 1.0
    if ratio > neutral_threshold:
        return BiasType.NEUTRAL

    return BiasType.BULLISH if bullish_count > bearish_count else BiasType.BEARISH


def compute_confidence(
    base_score: float,
    freshness_score: float,
    context_quality: float = 0.5,
    signal_strength: float = 0.5,
) -> float:
    """Compute Head confidence from supporting factors.

    Confidence is a blend of:
    - base_score: The Head's internal assessment (0.0–1.0)
    - freshness_score: How recent the data is (0.0–1.0)
    - context_quality: Quality of the setup context (0.0–1.0)
    - signal_strength: Strength of supporting Floor 3 signals (0.0–1.0)

    Returns:
        Confidence value between 0.0 and 1.0.
    """
    score = (
        base_score * 0.4
        + freshness_score * 0.2
        + context_quality * 0.25
        + signal_strength * 0.15
    )
    return max(0.0, min(1.0, score))
