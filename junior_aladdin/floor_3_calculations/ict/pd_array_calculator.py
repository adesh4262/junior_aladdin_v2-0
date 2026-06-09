"""ICT — Premium/Discount Array (PD Array) Calculator.

Calculates the PD Array over a specified lookback period to determine
whether price is trading in Premium (expensive) or Discount (cheap)
territory, and identifies the Optimal Trade Entry (OTE) zone.

The PD Array divides the price range into:
- PREMIUM: Top 50% (above equilibrium) — price is expensive, look for sells.
- DISCOUNT: Bottom 50% (below equilibrium) — price is cheap, look for buys.
- OPTIMAL_TRADE_ENTRY: The 62.5% Fibonacci retracement zone — ideal entry area.

Architecture rules:
- Pure functions — no state, no external calls, no side effects.
- Same input → same output (deterministic).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import PdArrayLevel, PdArrayType


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PERIOD: int = 20
_OTE_FIB_LEVEL: float = 0.625  # 62.5% Fibonacci retracement
_EQUILIBRIUM_FIB: float = 0.5  # 50% marker
_OTE_TOLERANCE: float = 0.05   # 5% tolerance for OTE zone detection (2.5% each side)


# =============================================================================
# PUBLIC API
# =============================================================================


def calculate_pd_array(
    candles: list[dict[str, Any]],
    period: int = _DEFAULT_PERIOD,
) -> list[PdArrayLevel]:
    """Calculate Premium/Discount Array levels from OHLCV data.

    For each candle (starting after ``period`` candles), computes the
    PD Array based on the highest high and lowest low of the preceding
    ``period`` candles.

    Returns levels for:
    - PREMIUM zone boundary (top 50%)
    - DISCOUNT zone boundary (bottom 50%)
    - OPTIMAL_TRADE_ENTRY level (62.5% Fibonacci retracement)

    Args:
        candles: List of OHLCV candle dicts with ``\"high\"``, ``\"low\"``,
            and ``\"timestamp\"`` keys.
        period: Lookback period for range calculation. Default 20.

    Returns:
        List of ``PdArrayLevel`` objects, one per valid candle position.
        Empty list if insufficient data.

    Raises:
        ValueError: If ``period < 2``.
    """
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}")

    n = len(candles)
    if n < period + 1:
        return []

    levels: list[PdArrayLevel] = []

    for i in range(period, n):
        # Get the range of the last `period` candles
        window = candles[i - period:i]
        ts = candles[i].get("timestamp")

        high = max(c.get("high", 0) for c in window)
        low = min(c.get("low", float("inf")) for c in window)
        price = candles[i].get("close", candles[i].get("high", 0))

        if not isinstance(ts, datetime):
            continue

        level = _classify_single(price, high, low, ts)
        if level is not None:
            levels.append(level)

    return levels


def classify_pd(
    price: float,
    high: float,
    low: float,
    period: int = _DEFAULT_PERIOD,
) -> PdArrayType:
    """Classify a price level within a given high-low range.

    Determines whether the price is in Premium, Discount, or OTE territory
    relative to the specified high and low.

    Args:
        price: Current price to classify.
        high: Highest price in the lookback window.
        low: Lowest price in the lookback window.
        period: Lookback period (for context, not used in calculation).

    Returns:
        ``PdArrayType`` classification.

    Raises:
        ValueError: If ``high <= low``.
    """
    if high <= low:
        raise ValueError(f"high ({high}) must be > low ({low})")

    raw_range = high - low
    equilibrium = low + raw_range * _EQUILIBRIUM_FIB
    ote_entry = low + raw_range * _OTE_FIB_LEVEL
    ote_zone_half = raw_range * _OTE_TOLERANCE / 2

    # Check OTE zone first (most specific)
    if abs(price - ote_entry) <= ote_zone_half:
        return PdArrayType.OPTIMAL_TRADE_ENTRY

    # Then check Premium/Discount
    if price >= equilibrium:
        return PdArrayType.PREMIUM
    return PdArrayType.DISCOUNT


# =============================================================================
# INTERNAL
# =============================================================================


def _classify_single(
    price: float,
    high: float,
    low: float,
    timestamp: datetime,
) -> PdArrayLevel | None:
    """Build a single PdArrayLevel for a price within a high-low range.

    Args:
        price: Price to classify.
        high: Range high.
        low: Range low.
        timestamp: Current candle timestamp.

    Returns:
        A ``PdArrayLevel``, or ``None`` if the range is degenerate.
    """
    if high <= low or not price:
        return None

    raw_range = high - low
    equilibrium = low + raw_range * _EQUILIBRIUM_FIB
    ote_entry = low + raw_range * _OTE_FIB_LEVEL

    # Classify the price
    pd_type = _classify_price(price, equilibrium, ote_entry, raw_range)
    return PdArrayLevel(
        pd_type=pd_type,
        level=ote_entry if pd_type == PdArrayType.OPTIMAL_TRADE_ENTRY else (
            low if pd_type == PdArrayType.DISCOUNT else high
        ),
        timestamp=timestamp,
        strength=_calculate_strength(price, high, low, equilibrium, pd_type),
    )


def _classify_price(
    price: float,
    equilibrium: float,
    ote_entry: float,
    raw_range: float,
) -> PdArrayType:
    """Classify a price within Premium/Discount/OTE.

    Args:
        price: Price to classify.
        equilibrium: 50% level of the range.
        ote_entry: 62.5% level of the range.
        raw_range: Total range (high - low).

    Returns:
        The classified ``PdArrayType``.
    """
    ote_zone_half = raw_range * _OTE_TOLERANCE / 2

    if abs(price - ote_entry) <= ote_zone_half:
        return PdArrayType.OPTIMAL_TRADE_ENTRY
    elif price >= equilibrium:
        return PdArrayType.PREMIUM
    else:
        return PdArrayType.DISCOUNT


def _calculate_strength(
    price: float,
    high: float,
    low: float,
    equilibrium: float,
    pd_type: PdArrayType,
) -> float:
    """Calculate the strength of a PD Array classification.

    The strength reflects how deep into the zone the price is:
    - DISCOUNT: 0.0 at equilibrium, 1.0 at the low.
    - PREMIUM: 0.0 at equilibrium, 1.0 at the high.
    - OTE: 1.0 (full strength when at the ideal entry level).

    Args:
        price: Current price.
        high: Range high.
        low: Range low.
        equilibrium: 50% level.
        pd_type: The PD Array classification.

    Returns:
        A strength score (0.0–1.0).
    """
    if pd_type == PdArrayType.OPTIMAL_TRADE_ENTRY:
        return 1.0
    elif pd_type == PdArrayType.DISCOUNT:
        if price >= equilibrium:
            return 0.0
        return max(0.0, min(1.0, (equilibrium - price) / (equilibrium - low + 0.01)))
    else:  # PREMIUM
        if price <= equilibrium:
            return 0.0
        return max(0.0, min(1.0, (price - equilibrium) / (high - equilibrium + 0.01)))
