"""Technical — ATR (Average True Range) Calculator.

Calculates the Average True Range using Wilder's smoothing method.
ATR measures market volatility by decomposing the entire range of a
candle.

True Range (TR) Formula:
    TR = max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close)
    )

ATR Formula (Wilder's smoothing):
    First ATR = mean of TR over initial `period` periods
    Subsequent ATR(i) = (Prev ATR × (period - 1) + Current TR) / period

Architecture rules:
- Pure function — no state, no external calls, no side effects.
- Deterministic — same candles + period → same ATR values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import AtrValue


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PERIOD: int = 14


# =============================================================================
# PUBLIC API
# =============================================================================


def calculate_atr(
    candles: list[dict[str, Any]],
    period: int = _DEFAULT_PERIOD,
) -> list[AtrValue]:
    """Calculate ATR values from OHLCV candle data.

    Uses Wilder's smoothing method. The first valid ATR value appears at
    index ``period`` (requires ``period + 1`` candles — the first candle
    has no previous close to compute TR).

    Args:
        candles: List of OHLCV candle dicts with ``\"high\"``, ``\"low\"``,
            ``\"close\"``, and ``\"timestamp\"`` keys. Must have at least
            ``period + 1`` candles.
        period: ATR lookback period. Default 14.

    Returns:
        A list of ``AtrValue`` objects, one per valid candle position
        (starting at index ``period``). Empty list if insufficient data.

    Raises:
        ValueError: If ``period < 2``.
    """
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}")

    n = len(candles)
    if n < period + 1:
        return []

    # Extract OHLC values with validation
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    timestamps: list[datetime] = []
    for c in candles:
        ts = c.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        high = c.get("high")
        low = c.get("low")
        close = c.get("close")
        if any(v is None or not isinstance(v, (int, float)) for v in (high, low, close)):
            continue
        highs.append(float(high))
        lows.append(float(low))
        closes.append(float(close))
        timestamps.append(ts)

    if len(closes) < period + 1:
        return []

    # Compute True Range for each candle (starting at index 1)
    tr_values: list[float] = []
    tr_timestamps: list[datetime] = []
    for i in range(1, len(closes)):
        tr = _compute_true_range(highs[i], lows[i], closes[i], closes[i - 1])
        tr_values.append(tr)
        tr_timestamps.append(timestamps[i])

    # First ATR = mean of TR over first `period` periods
    results: list[AtrValue] = []
    atr = sum(tr_values[:period]) / period
    results.append(AtrValue(
        timestamp=tr_timestamps[period - 1],
        value=round(atr, 2),
    ))

    # Subsequent values use Wilder's smoothing
    for i in range(period, len(tr_values)):
        atr = (atr * (period - 1) + tr_values[i]) / period
        results.append(AtrValue(
            timestamp=tr_timestamps[i],
            value=round(atr, 2),
        ))

    return results


def classify_volatility(
    atr_value: float,
    reference_atr: float,
) -> str:
    """Classify current volatility relative to a reference ATR.

    Useful for comparing current ATR to a longer-term average to
    determine if volatility is expanding or contracting.

    Args:
        atr_value: Current ATR value.
        reference_atr: Reference ATR (e.g., 20-period average).

    Returns:
        One of ``\"HIGH\"``, ``\"LOW\"``, or ``\"NORMAL\"``.
    """
    if reference_atr <= 0:
        return "NORMAL"
    ratio = atr_value / reference_atr
    if ratio >= 1.5:
        return "HIGH"
    elif ratio <= 0.5:
        return "LOW"
    return "NORMAL"


# =============================================================================
# INTERNAL
# =============================================================================


def _compute_true_range(
    high: float,
    low: float,
    close: float,
    prev_close: float,
) -> float:
    """Compute the True Range for a single candle.

    TR = max(high - low, abs(high - prev_close), abs(low - prev_close))

    Args:
        high: Current candle high.
        low: Current candle low.
        close: Current candle close (used as fallback).
        prev_close: Previous candle close.

    Returns:
        The True Range value (always non-negative).
    """
    hl = high - low
    hc = abs(high - prev_close)
    lc = abs(low - prev_close)
    return max(hl, hc, lc)
