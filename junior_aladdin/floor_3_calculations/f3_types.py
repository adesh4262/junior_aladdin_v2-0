"""Floor 3 — Calculation Engine shared types.

This file defines ALL enums and dataclasses used across Floor 3 calculation
domains (SMC, ICT, Technical). It is the SINGLE SOURCE OF TRUTH for Floor 3
type definitions.

Architecture rules:
- Imports ONLY from shared/types.py (Phase 0) and Python standard library.
- NO imports from other Floor 3 modules (smc/, ict/, technical/).
- NO imports from Floor 4, Floor 5, Side A, or Side B.
- Quality = Floor 3 (NOT confidence, NOT conviction).

Every domain engine (SMC, ICT, Technical) uses these types for input/output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from junior_aladdin.shared.types import DataHealth, MarketPhase


# =============================================================================
# ENUMS
# =============================================================================


class CalculationDomain(Enum):
    """Floor 3 calculation domain classification.

    Each value maps to a dedicated calculation engine.
    """
    SMC = "SMC"
    ICT = "ICT"
    TECHNICAL = "TECHNICAL"
    OPTIONS = "OPTIONS"
    MACRO = "MACRO"
    PSYCHOLOGY = "PSYCHOLOGY"


class EngineStatus(Enum):
    """Operational status of a calculation engine after a run cycle."""
    IDLE = "IDLE"
    CALCULATING = "CALCULATING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class CalculationQuality(Enum):
    """Quality classification for a calculation output.

    NOMINAL: full data, no warnings, clean calculation.
    DEGRADED: partial data, some warnings, calculation completed.
    INSUFFICIENT_DATA: below minimum data points required.
    """
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ── SMC Domain Enums ────────────────────────────────────────────────────────


class MarketStructureType(Enum):
    """Market structure classification based on swing point analysis."""
    BULLISH_HH_HL = "BULLISH_HH_HL"  # Higher Highs + Higher Lows (uptrend)
    BEARISH_LH_LL = "BEARISH_LH_LL"  # Lower Highs + Lower Lows (downtrend)
    CHOP = "CHOP"                     # No clear directional structure
    BREAKOUT = "BREAKOUT"             # Structure break with momentum


class FvgType(Enum):
    """Fair Value Gap directional classification."""
    BULLISH_FVG = "BULLISH_FVG"
    BEARISH_FVG = "BEARISH_FVG"


class ObType(Enum):
    """Order Block directional classification."""
    BULLISH_OB = "BULLISH_OB"
    BEARISH_OB = "BEARISH_OB"


class ChoChType(Enum):
    """Change of Character directional classification."""
    BULLISH_CHOCH = "BULLISH_CHOCH"  # Bearish → Bullish structure shift
    BEARISH_CHOCH = "BEARISH_CHOCH"  # Bullish → Bearish structure shift


# ── ICT Domain Enums ────────────────────────────────────────────────────────


class PdArrayType(Enum):
    """Premium/Discount Array zone classification."""
    PREMIUM = "PREMIUM"                          # Above equilibrium (expensive)
    DISCOUNT = "DISCOUNT"                         # Below equilibrium (cheap)
    OPTIMAL_TRADE_ENTRY = "OPTIMAL_TRADE_ENTRY"   # Optimal Trade Entry zone


class KillZoneType(Enum):
    """ICT Kill Zone time classifications (IST timezone)."""
    ASIAN = "ASIAN"                # 02:30 – 09:15 IST
    LONDON_OPEN = "LONDON_OPEN"    # 12:30 – 14:30 IST
    NY_AM_OPEN = "NY_AM_OPEN"      # 17:30 – 20:00 IST
    NY_PM_CLOSE = "NY_PM_CLOSE"    # 22:00 – 23:00 IST


class LiquidityType(Enum):
    """Liquidity level directional classification."""
    BUY_SIDE = "BUY_SIDE"                   # Liquidity above price (stop hunts)
    SELL_SIDE = "SELL_SIDE"                 # Liquidity below price (stop hunts)
    DOUBLE_DISTRIBUTION = "DOUBLE_DISTRIBUTION"  # Both sides present


# ── Technical Domain Enums ──────────────────────────────────────────────────


class TaIndicatorType(Enum):
    """Technical Analysis indicator type classification."""
    RSI = "RSI"
    MA_FAST = "MA_FAST"
    MA_SLOW = "MA_SLOW"
    ATR = "ATR"
    VOLUME_PROFILE = "VOLUME_PROFILE"


# =============================================================================
# DATACLASSES — SMC Sub-types
# =============================================================================


@dataclass
class SwingPoint:
    """A single swing high/low point detected in market structure analysis.

    Fields:
        price: Price level of the swing point.
        timestamp: When the swing point occurred.
        swing_type: ``"HIGH"`` or ``"LOW"``.
        strength: Normalised strength indicator (0.0–1.0).
    """
    price: float
    timestamp: datetime
    swing_type: str  # HIGH / LOW
    strength: float = 0.5


@dataclass
class FairValueGap:
    """A detected Fair Value Gap between three consecutive candles.

    Fields:
        fvg_type: BULLISH_FVG or BEARISH_FVG.
        top: Upper boundary of the gap.
        bottom: Lower boundary of the gap.
        formation_timestamp: When the gap was formed.
        mitigated: Whether the gap has been mitigated (filled).
        mitigated_at: When the gap was mitigated (None if not mitigated).
        gap_size_pips: Size of the gap in pips.
    """
    fvg_type: FvgType
    top: float
    bottom: float
    formation_timestamp: datetime
    mitigated: bool = False
    mitigated_at: datetime | None = None
    gap_size_pips: float = 0.0


@dataclass
class OrderBlock:
    """A detected Order Block at a swing point.

    Fields:
        ob_type: BULLISH_OB or BEARISH_OB.
        price: Price level of the order block.
        timestamp: When the order block was formed.
        strength: Normalised strength (0.0–1.0).
        swing_ref: Reference to the associated swing point.
    """
    ob_type: ObType
    price: float
    timestamp: datetime
    strength: float = 0.5
    swing_ref: SwingPoint | None = None


@dataclass
class ChoCh:
    """A detected Change of Character (structure shift).

    Fields:
        choch_type: BULLISH_CHOCH or BEARISH_CHOCH.
        break_price: The price level where the break occurred.
        timestamp: When the CHOCH was confirmed.
        prior_structure: The market structure type before the break.
        confirmed: Whether the CHOCH is fully confirmed.
    """
    choch_type: ChoChType
    break_price: float
    timestamp: datetime
    prior_structure: MarketStructureType
    confirmed: bool = False


# =============================================================================
# DATACLASSES — ICT Sub-types
# =============================================================================


@dataclass
class PdArrayLevel:
    """A single Premium/Discount Array level.

    Fields:
        pd_type: PREMIUM, DISCOUNT, or OPTIMAL_TRADE_ENTRY.
        level: Price level of the PD Array boundary.
        timestamp: When this level was calculated.
        strength: Normalised strength (0.0–1.0).
    """
    pd_type: PdArrayType
    level: float
    timestamp: datetime
    strength: float = 0.5


@dataclass
class KillZone:
    """An active or upcoming ICT Kill Zone window.

    Fields:
        kill_zone_type: The kill zone classification.
        start_time: When the kill zone starts (IST).
        end_time: When the kill zone ends (IST).
        active: Whether the kill zone is currently active.
        time_remaining_s: Seconds remaining if active (0 if not active).
    """
    kill_zone_type: KillZoneType
    start_time: datetime
    end_time: datetime
    active: bool = False
    time_remaining_s: float = 0.0


@dataclass
class LiquidityLevel:
    """A detected liquidity level (stop-hunt target).

    Fields:
        liquidity_type: BUY_SIDE or SELL_SIDE.
        price: The price level of the liquidity.
        timestamp: When the level was identified.
        swept: Whether this level has been swept (hit).
        swept_at: When the level was swept (None if not swept).
        size: Relative size of the liquidity pool (0.0–1.0).
    """
    liquidity_type: LiquidityType
    price: float
    timestamp: datetime
    swept: bool = False
    swept_at: datetime | None = None
    size: float = 0.5


# =============================================================================
# DATACLASSES — Technical Sub-types
# =============================================================================


@dataclass
class RsiValue:
    """A single RSI calculation output.

    Fields:
        timestamp: Candle timestamp.
        value: RSI value (0.0–100.0).
        oversold: Whether RSI is in oversold territory (< 30).
        overbought: Whether RSI is in overbought territory (> 70).
    """
    timestamp: datetime
    value: float
    oversold: bool = False
    overbought: bool = False


@dataclass
class MaValue:
    """A single Moving Average calculation output.

    Fields:
        timestamp: Candle timestamp.
        value: Moving average price.
        ma_type: ``"SMA"`` or ``"EMA"``.
        period: The period used for calculation.
    """
    timestamp: datetime
    value: float
    ma_type: str  # SMA / EMA
    period: int


@dataclass
class AtrValue:
    """A single ATR (Average True Range) calculation output.

    Fields:
        timestamp: Candle timestamp.
        value: ATR value.
    """
    timestamp: datetime
    value: float


@dataclass
class VolumeProfile:
    """Volume Profile calculation output (VPVR).

    Fields:
        timestamp: When this profile was calculated.
        poc: Point of Control — price level with highest volume.
        vah: Value Area High — upper boundary of value area.
        val: Value Area Low — lower boundary of value area.
        value_area_volume: Total volume within the value area.
        total_volume: Total volume across all price levels.
    """
    timestamp: datetime
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    value_area_volume: int = 0
    total_volume: int = 0


# =============================================================================
# DATACLASSES — Core Floor 3 Contracts
# =============================================================================


@dataclass
class CalculationParameters:
    """Parameters for a single calculation engine run.

    Fields:
        domain: The calculation domain this parameter set is for.
        timeframe: The candle timeframe (e.g., ``"1m"``, ``"5m"``, ``"15m"``).
        lookback_periods: Number of candles/bars to look back.
        thresholds: Domain-specific threshold values
            (e.g., ``{"rsi_oversold": 30, "fvg_min_gap_pips": 0.5}``).
    """
    domain: CalculationDomain
    timeframe: str
    lookback_periods: int = 50
    thresholds: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalculationInput:
    """Input data for a single calculation cycle.

    Fields:
        packet_envelope_id: Reference to the originating Floor 2 packet.
        market_phase: Current market session phase.
        symbol: Trading symbol (e.g., ``"NIFTY"``).
        timestamp: Data timestamp.
        data: Domain-specific input data
            (candles, ticks, options data, etc.).
    """
    packet_envelope_id: str
    market_phase: MarketPhase
    symbol: str
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalculationResult:
    """Raw output from a single calculation step within a domain engine.

    Fields:
        signal_id: Unique identifier (UUID v4), generated once and immutable.
        domain: The domain that produced this result.
        indicator_type: Specific indicator/pattern type within the domain.
        value: The calculated value (type varies by indicator).
        timestamp: When this result was calculated.
        metadata: Domain-specific additional data.
    """
    signal_id: str = ""
    domain: CalculationDomain = CalculationDomain.SMC
    indicator_type: str = ""
    value: Any = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalculationLog:
    """Audit log for a single calculated signal.

    Provides full provenance for replay verification and auditing.

    Fields:
        signal_id: Matches the CalculatedSignal this log belongs to.
        domain: The domain that produced this signal.
        engine_version: Version identifier of the engine that calculated it.
        input_hash: Hash of the input data (for replay determinism check).
        parameters_used: List of parameter sets used during calculation.
        calculation_steps: Ordered list of steps taken during calculation.
        warnings: Any warnings generated during calculation.
    """
    signal_id: str = ""
    domain: CalculationDomain = CalculationDomain.SMC
    engine_version: str = "1.0"
    input_hash: str = ""
    parameters_used: list[dict[str, Any]] = field(default_factory=list)
    calculation_steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CalculatedSignal:
    """Complete calculated signal output from a domain engine.

    This is the PRIMARY output unit from Floor 3 to Floor 4.
    EVERY signal MUST have a unique signal_id and a CalculationLog.

    Fields:
        signal_id: Unique identifier (UUID v4), immutable after creation.
        domain: Which domain produced this signal.
        indicator_type: Specific indicator/pattern type.
        value: The calculated value.
        timestamp: When this signal was calculated.
        quality: Quality classification (NOMINAL / DEGRADED / INSUFFICIENT_DATA).
        metadata: Domain-specific additional context.
        calculation_log: Full audit log for this signal.
    """
    signal_id: str = ""
    domain: CalculationDomain = CalculationDomain.SMC
    indicator_type: str = ""
    value: Any = None
    timestamp: datetime | None = None
    quality: CalculationQuality = CalculationQuality.NOMINAL
    metadata: dict[str, Any] = field(default_factory=dict)
    calculation_log: CalculationLog | None = None


@dataclass
class EngineRunReport:
    """Report from a single engine run cycle.

    Produced by every domain engine after each calculation cycle.
    Sent to the orchestrator for aggregation.

    Fields:
        engine_name: Human-readable engine name (e.g., ``"smc_engine"``).
        domain: The calculation domain.
        status: Engine status after the run.
        signals_generated: List of signal IDs generated in this run.
        signals: Full CalculatedSignal objects generated in this run.
        duration_ms: Wall-clock duration of the calculation in milliseconds.
        errors: Any errors encountered during the run.
    """
    engine_name: str = ""
    domain: CalculationDomain = CalculationDomain.SMC
    status: EngineStatus = EngineStatus.IDLE
    signals_generated: list[str] = field(default_factory=list)
    signals: list[CalculatedSignal] = field(default_factory=list)
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class Floor3Summary:
    """Aggregated summary of a complete Floor 3 calculation cycle.

    Produced by the orchestrator after ALL domain engines have run.
    Sent to Floor 4 as part of the output contract.

    Fields:
        domain_summaries: Per-domain summary data (domain → summary dict).
        signals_count: Total signals generated across all domains.
        engine_statuses: Per-engine status (engine_name → EngineStatus).
        data_health: Aggregate data health for this calculation cycle.
    """
    domain_summaries: dict[str, Any] = field(default_factory=dict)
    signals_count: int = 0
    engine_statuses: dict[str, str] = field(default_factory=dict)
    data_health: DataHealth = DataHealth.GOOD


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def generate_signal_id() -> str:
    """Generate a unique, immutable signal identifier.

    Returns:
        A UUID v4 hex string (e.g., ``"a1b2c3d4e5f6..."``).
    """
    return uuid.uuid4().hex


def compute_input_hash(data: dict[str, Any]) -> str:
    """Compute a deterministic hash of input data for replay verification.

    Uses a simple string-based hash (NOT cryptographic).
    Same input → same hash, always.

    Args:
        data: The input data dict to hash.

    Returns:
        A hex string hash of the input data.
    """
    import hashlib
    import json

    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
