"""SMC — Order Block (OB) Calculator.

Detects Order Blocks at swing high/low pivot points and classifies them
as Bullish OB (support) or Bearish OB (resistance).

An Order Block is the candle at a swing extreme where institutional orders
were placed, creating a price pivot. OBs serve as potential support/
resistance zones that price may revisit.

Architecture rules:
- Pure functions — no state, no external calls, no side effects.
- Same input → same output (deterministic).
- OB must be at a swing point and align with the given trend direction.
- OB zone = the full range (high to low) of the order-block candle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    MarketStructureType,
    ObType,
    OrderBlock,
    SwingPoint,
)
from junior_aladdin.floor_3_calculations.smc._shared import find_swing_candle_index
from junior_aladdin.floor_3_calculations.smc.market_structure import (
    analyze_structure,
)


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PIVOT_WINDOW: int = 2
_DEFAULT_LOOKBACK: int = 50
_MIN_OB_STRENGTH: float = 0.1


# =============================================================================
# PUBLIC API
# =============================================================================


def detect_order_blocks(
    candles: list[dict[str, Any]],
    trend: MarketStructureType | str | None = None,
    pivot_window: int = _DEFAULT_PIVOT_WINDOW,
    lookback: int = _DEFAULT_LOOKBACK,
) -> list[OrderBlock]:
    """Detect Order Blocks from swing pivot points in candle data.

    Identifies the candle at each swing high (Bearish OB) and swing low
    (Bullish OB). The OB zone spans the full candle range (high to low).

    When a trend is specified, OBs that align with the trend are preferred:
    - BULLISH_HH_HL: primarily Bullish OBs (support levels in uptrend).
    - BEARISH_LH_LL: primarily Bearish OBs (resistance in downtrend).
    - CHOP / None: both types are detected.

    Args:
        candles: List of OHLCV candle dicts with ``\"high\"``, ``\"low\"``,
            ``\"close\"``, and ``\"timestamp\"`` keys.
        trend: Optional market structure type to filter OBs by trend.
            If a string, it is converted to ``MarketStructureType``.
        pivot_window: Pivot detection window (passed to market_structure).
        lookback: Maximum candles to analyze.

    Returns:
        List of detected ``OrderBlock`` objects, sorted by time.
        Empty list if no OBs found.

    Raises:
        ValueError: If ``pivot_window < 1``.
    """
    if pivot_window < 1:
        raise ValueError(f"pivot_window must be >= 1, got {pivot_window}")

    # Resolve trend string to enum if needed
    trend_enum: MarketStructureType | None = None
    if isinstance(trend, str):
        try:
            trend_enum = MarketStructureType(trend)
        except ValueError:
            trend_enum = None
    elif isinstance(trend, MarketStructureType):
        trend_enum = trend

    # Run market structure analysis to find swing points
    struct_result = analyze_structure(
        candles,
        lookback=lookback,
        pivot_window=pivot_window,
    )

    if not struct_result["valid"]:
        return []

    swing_points: list[SwingPoint] = struct_result["swing_points"]
    if not swing_points:
        return []

    order_blocks: list[OrderBlock] = []

    for sp in swing_points:
        # Find the candle index for this swing point by matching
        candle_idx = find_swing_candle_index(sp, candles, pivot_window)
        if candle_idx is None:
            continue

        ob_candle = candles[candle_idx]
        ts = ob_candle.get("timestamp")
        if not isinstance(ts, datetime):
            continue

        ob_close = ob_candle.get("close", 0)
        ob_high = ob_candle.get("high", 0)
        ob_low = ob_candle.get("low", float("inf"))
        ob_range = ob_high - ob_low if ob_high > ob_low else 0

        if sp.swing_type == "LOW":
            # Bullish OB at swing low
            if trend_enum == MarketStructureType.BEARISH_LH_LL:
                continue  # Skip bullish OBs in bearish trend

            strength = _calculate_ob_strength(
                swing_price=sp.price,
                candle_range=ob_range,
                near_candle=candle_idx,
                candles=candles,
                direction="bullish",
                pivot_window=pivot_window,
            )

            if strength < _MIN_OB_STRENGTH:
                continue

            order_blocks.append(OrderBlock(
                ob_type=ObType.BULLISH_OB,
                price=sp.price,
                timestamp=ts,
                strength=round(strength, 2),
                swing_ref=sp,
            ))

        elif sp.swing_type == "HIGH":
            # Bearish OB at swing high
            if trend_enum == MarketStructureType.BULLISH_HH_HL:
                continue  # Skip bearish OBs in bullish trend

            strength = _calculate_ob_strength(
                swing_price=sp.price,
                candle_range=ob_range,
                near_candle=candle_idx,
                candles=candles,
                direction="bearish",
                pivot_window=pivot_window,
            )

            if strength < _MIN_OB_STRENGTH:
                continue

            order_blocks.append(OrderBlock(
                ob_type=ObType.BEARISH_OB,
                price=sp.price,
                timestamp=ts,
                strength=round(strength, 2),
                swing_ref=sp,
            ))

    return order_blocks


def detect_bullish_obs(
    candles: list[dict[str, Any]],
    pivot_window: int = _DEFAULT_PIVOT_WINDOW,
    lookback: int = _DEFAULT_LOOKBACK,
) -> list[OrderBlock]:
    """Detect only Bullish Order Blocks (swing low support levels).

    Convenience wrapper around :func:`detect_order_blocks` that filters
    to bullish OBs only. Passes ``BULLISH_HH_HL`` as the trend, which
    skips Bearish OBs (swing highs) since they conflict with uptrend.

    Args:
        candles: List of OHLCV candle dicts.
        pivot_window: Pivot detection window.
        lookback: Maximum candles to analyze.

    Returns:
        List of Bullish ``OrderBlock`` objects.
    """
    return detect_order_blocks(
        candles,
        trend=MarketStructureType.BULLISH_HH_HL,
        pivot_window=pivot_window,
        lookback=lookback,
    )


def detect_bearish_obs(
    candles: list[dict[str, Any]],
    pivot_window: int = _DEFAULT_PIVOT_WINDOW,
    lookback: int = _DEFAULT_LOOKBACK,
) -> list[OrderBlock]:
    """Detect only Bearish Order Blocks (swing high resistance levels).

    Convenience wrapper around :func:`detect_order_blocks` that filters
    to bearish OBs only. Passes ``BEARISH_LH_LL`` as the trend, which
    skips Bullish OBs (swing lows) since they conflict with downtrend.

    Args:
        candles: List of OHLCV candle dicts.
        pivot_window: Pivot detection window.
        lookback: Maximum candles to analyze.

    Returns:
        List of Bearish ``OrderBlock`` objects.
    """
    return detect_order_blocks(
        candles,
        trend=MarketStructureType.BEARISH_LH_LL,
        pivot_window=pivot_window,
        lookback=lookback,
    )


def classify_ob(strength: float) -> ObType:
    """Classify an Order Block by its strength score.

    This is a convenience function — the actual OB type is determined
    by the swing direction (HIGH → BEARISH_OB, LOW → BULLISH_OB).
    This function exists for use cases where strength determines type.

    Args:
        strength: Normalised OB strength (0.0–1.0).

    Returns:
        ``ObType.BULLISH_OB`` if strength >= 0.5, ``ObType.BEARISH_OB``
        otherwise.
    """
    return ObType.BULLISH_OB if strength >= 0.5 else ObType.BEARISH_OB


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _calculate_ob_strength(
    swing_price: float,
    candle_range: float,
    near_candle: int,
    candles: list[dict[str, Any]],
    direction: str,
    pivot_window: int,
) -> float:
    """Calculate the strength of an Order Block.

    Strength is based on:
    1. How far price moved away from the OB (the impulse move size).
    2. The range of the OB candle itself (wider range = stronger).

    Args:
        swing_price: The price level of the swing point.
        candle_range: The range (high - low) of the OB candle.
        near_candle: Index of the OB candle in the candle list.
        candles: Full candle list for calculating the impulse move.
        direction: ``\"bullish\"`` or ``\"bearish\"``.
        pivot_window: Pivot window for impulse lookahead.

    Returns:
        A strength score (0.0–1.0).
    """
    # Calculate impulse move: how far price moved in the next N candles
    end = min(near_candle + pivot_window * 4, len(candles))
    if end <= near_candle + 1:
        return _MIN_OB_STRENGTH

    if direction == "bullish":
        max_price = max(
            candles[j].get("high", 0) for j in range(near_candle + 1, end)
        )
        impulse = max_price - swing_price
        # Look at the OB's own candle too for range contribution
        range_factor = min(1.0, candle_range / max(swing_price * 0.02, 0.01))
    else:
        min_price = min(
            candles[j].get("low", float("inf")) for j in range(near_candle + 1, end)
        )
        impulse = swing_price - min_price
        range_factor = min(1.0, candle_range / max(swing_price * 0.02, 0.01))

    if impulse <= 0:
        return _MIN_OB_STRENGTH

    # Normalise impulse: 0% → 0.0, 1% → 0.5, 3%+ → 1.0
    impulse_pct = impulse / max(swing_price, 0.01)
    impulse_factor = min(1.0, impulse_pct * 50)

    # Combine: 70% impulse, 30% candle range
    strength = impulse_factor * 0.7 + range_factor * 0.3
    return max(_MIN_OB_STRENGTH, strength)
