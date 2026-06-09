"""Technical — Moving Average (MA) Calculator.

Calculates Simple Moving Average (SMA) and Exponential Moving Average (EMA)
from OHLCV candle data over a specified period.

SMA Formula:
    SMA(i) = (close[i-period] + close[i-period+1] + ... + close[i-1]) / period

EMA Formula (Wilder-style):
    multiplier = 2 / (period + 1)
    EMA(0) = SMA over first `period` candles (seed value)
    EMA(i) = (close[i] - EMA(i-1)) * multiplier + EMA(i-1)

Architecture rules:
- Pure function — no state, no external calls, no side effects.
- Deterministic — same candles + period + type → same MA values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import MaValue


_TYPES = frozenset(["SMA", "EMA"])


# =============================================================================
# PUBLIC API
# =============================================================================


def calculate_ma(
    candles: list[dict[str, Any]],
    period: int,
    ma_type: str = "SMA",
) -> list[MaValue]:
    """Calculate Moving Average values from OHLCV candle data.

    Supports both SMA and EMA. The first valid value appears at index
    ``period - 1`` (requires ``period`` candles).

    Args:
        candles: List of OHLCV candle dicts with ``\"close\"`` and
            ``\"timestamp\"`` keys. Must have at least ``period`` candles.
        period: Lookback period for the moving average.
            Must be >= 1 for SMA, >= 2 for EMA.
        ma_type: ``\"SMA\"`` or ``\"EMA\"``. Default ``\"SMA\"``.

    Returns:
        A list of ``MaValue`` objects, one per valid candle position
        (starting at index ``period - 1``). Empty list if insufficient data.

    Raises:
        ValueError: If ``period < 1``, or if ``ma_type`` is not supported.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if ma_type not in _TYPES:
        raise ValueError(f"unsupported ma_type {ma_type!r}, expected one of {sorted(_TYPES)}")

    if ma_type == "EMA" and period < 2:
        raise ValueError(f"EMA period must be >= 2, got {period}")

    # Filter valid candles (must have close + timestamp)
    closes: list[float] = []
    timestamps: list[datetime] = []
    for c in candles:
        ts = c.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        close = c.get("close")
        if close is None or not isinstance(close, (int, float)):
            continue
        closes.append(float(close))
        timestamps.append(ts)

    n = len(closes)
    if n < period:
        return []

    if ma_type == "SMA":
        return _compute_sma(closes, timestamps, period)
    else:  # EMA
        return _compute_ema(closes, timestamps, period)


def classify_ma_cross(
    fast_values: list[MaValue],
    slow_values: list[MaValue],
) -> str:
    """Classify the relationship between two MAs (fast vs slow).

    Compares the most recent values. Both lists must be non-empty and
    aligned (same timestamp positions).

    Args:
        fast_values: Faster MA values (e.g., 9-period).
        slow_values: Slower MA values (e.g., 21-period).

    Returns:
        One of ``\"BULLISH_CROSS\"`` (fast > slow),
        ``\"BEARISH_CROSS\"`` (fast < slow), or ``\"EQUAL\"``.
    """
    if not fast_values or not slow_values:
        return "EQUAL"

    fast_latest = fast_values[-1].value
    slow_latest = slow_values[-1].value

    if fast_latest > slow_latest:
        return "BULLISH_CROSS"
    elif fast_latest < slow_latest:
        return "BEARISH_CROSS"
    return "EQUAL"


# =============================================================================
# INTERNAL
# =============================================================================


def _compute_sma(
    closes: list[float],
    timestamps: list[datetime],
    period: int,
) -> list[MaValue]:
    """Compute SMA values from pre-filtered close prices.

    Args:
        closes: Valid close prices.
        timestamps: Valid timestamps (same length as ``closes``).
        period: SMA period.

    Returns:
        List of ``MaValue`` objects.
    """
    results: list[MaValue] = []
    running_sum = sum(closes[:period])
    results.append(MaValue(
        timestamp=timestamps[period - 1],
        value=round(running_sum / period, 2),
        ma_type="SMA",
        period=period,
    ))

    for i in range(period, len(closes)):
        running_sum += closes[i] - closes[i - period]
        results.append(MaValue(
            timestamp=timestamps[i],
            value=round(running_sum / period, 2),
            ma_type="SMA",
            period=period,
        ))

    return results


def _compute_ema(
    closes: list[float],
    timestamps: list[datetime],
    period: int,
) -> list[MaValue]:
    """Compute EMA values from pre-filtered close prices.

    Uses the SMA of the first ``period`` candles as the seed EMA value,
    then applies Wilder-style exponential smoothing.

    Args:
        closes: Valid close prices.
        timestamps: Valid timestamps (same length as ``closes``).
        period: EMA period (must be >= 2).

    Returns:
        List of ``MaValue`` objects.
    """
    multiplier = 2.0 / (period + 1)
    results: list[MaValue] = []

    # Seed: SMA of first `period` candles
    ema = sum(closes[:period]) / period
    results.append(MaValue(
        timestamp=timestamps[period - 1],
        value=round(ema, 2),
        ma_type="EMA",
        period=period,
    ))

    # Subsequent values use exponential smoothing
    for i in range(period, len(closes)):
        ema = (closes[i] - ema) * multiplier + ema
        results.append(MaValue(
            timestamp=timestamps[i],
            value=round(ema, 2),
            ma_type="EMA",
            period=period,
        ))

    return results
