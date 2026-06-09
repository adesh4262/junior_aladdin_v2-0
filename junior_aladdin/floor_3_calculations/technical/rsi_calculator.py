"""Technical — RSI (Relative Strength Index) Calculator.

Calculates the Relative Strength Index using Wilder's smoothing method
over a specified lookback period. Outputs RSI values with oversold/overbought
classification based on configurable thresholds.

RSI Formula (Wilder's smoothing):
1. Price changes: close[i] - close[i-1]
2. First average gain/loss = mean of gains/losses over initial `period` periods
3. Subsequent smoothing:
   Avg Gain = (Prev Avg Gain × (period - 1) + Current Gain) / period
   Avg Loss = (Prev Avg Loss × (period - 1) + Current Loss) / period
4. RS = Avg Gain / Avg Loss
5. RSI = 100 - (100 / (1 + RS))

Architecture rules:
- Pure function — no state, no external calls, no side effects.
- Deterministic — same prices + period → same RSI values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_config import TechnicalParameters
from junior_aladdin.floor_3_calculations.f3_types import RsiValue


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PERIOD: int = 14
_DEFAULT_OVERSOLD: float = 30.0
_DEFAULT_OVERBOUGHT: float = 70.0


# =============================================================================
# PUBLIC API
# =============================================================================


def calculate_rsi(
    candles: list[dict[str, Any]],
    period: int = _DEFAULT_PERIOD,
    params: TechnicalParameters | None = None,
) -> list[RsiValue]:
    """Calculate RSI values from OHLCV candle data.

    Uses Wilder's smoothing method. The first valid RSI value appears at
    index ``period`` (requires ``period + 1`` candles).

    Args:
        candles: List of OHLCV candle dicts with ``\"close\"`` and
            ``\"timestamp\"`` keys. Must have at least ``period + 1``
            candles.
        period: RSI lookback period. Default 14.
        params: Technical parameters with oversold/overbought thresholds.
            If ``None``, uses defaults (oversold=30, overbought=70).

    Returns:
        A list of ``RsiValue`` objects, one per valid candle position
        (starting at index ``period``). Empty list if insufficient data.

    Raises:
        ValueError: If ``period < 2``.
    """
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}")

    n = len(candles)
    if n < period + 1:
        return []

    oversold = _DEFAULT_OVERSOLD
    overbought = _DEFAULT_OVERBOUGHT
    if params is not None:
        oversold = params.rsi_oversold
        overbought = params.rsi_overbought

    # Extract close prices and timestamps
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

    if len(closes) < period + 1:
        return []

    # Calculate price changes
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Separate gains and losses
    gains = [max(ch, 0.0) for ch in changes]
    losses = [max(-ch, 0.0) for ch in changes]

    # Initial average gain/loss (simple mean over first `period` periods)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    results: list[RsiValue] = []

    # First valid RSI at index `period` (uses changes[0:period])
    rsi = _compute_rsi(avg_gain, avg_loss)
    results.append(RsiValue(
        timestamp=timestamps[period],
        value=round(rsi, 2),
        oversold=rsi <= oversold,
        overbought=rsi >= overbought,
    ))

    # Subsequent values use Wilder's smoothing
    for i in range(period + 1, len(closes)):
        idx = i - 1  # index in gains/losses
        avg_gain = (avg_gain * (period - 1) + gains[idx]) / period
        avg_loss = (avg_loss * (period - 1) + losses[idx]) / period
        rsi = _compute_rsi(avg_gain, avg_loss)
        results.append(RsiValue(
            timestamp=timestamps[i],
            value=round(rsi, 2),
            oversold=rsi <= oversold,
            overbought=rsi >= overbought,
        ))

    return results


def classify_rsi(value: float, oversold: float = _DEFAULT_OVERSOLD, overbought: float = _DEFAULT_OVERBOUGHT) -> str:
    """Classify an RSI value into a human-readable label.

    Args:
        value: The RSI value (0.0–100.0).
        oversold: Oversold threshold. Default 30.
        overbought: Overbought threshold. Default 70.

    Returns:
        One of ``\"OVERSOLD\"``, ``\"OVERBOUGHT\"``, or ``\"NEUTRAL\"``.
    """
    if value <= oversold:
        return "OVERSOLD"
    elif value >= overbought:
        return "OVERBOUGHT"
    return "NEUTRAL"


# =============================================================================
# INTERNAL
# =============================================================================


def _compute_rsi(avg_gain: float, avg_loss: float) -> float:
    """Compute RSI from average gain and average loss.

    Args:
        avg_gain: The smoothed average gain.
        avg_loss: The smoothed average loss.

    Returns:
        The RSI value (0.0–100.0). Returns 100.0 if avg_loss is 0,
        and 0.0 if avg_gain is 0.
    """
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
