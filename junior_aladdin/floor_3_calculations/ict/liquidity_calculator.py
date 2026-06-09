"""ICT — Liquidity Level Calculator.

Detects liquidity levels (swing points where stop hunts occur) and checks
whether those levels have been swept by price action.

Liquidity concepts (ICT):
- BUY_SIDE liquidity: stops of short sellers sitting above swing highs.
  Price hunts these to the upside. Level = swing high price.
- SELL_SIDE liquidity: stops of long buyers sitting below swing lows.
  Price hunts these to the downside. Level = swing low price.
- DOUBLE_DISTRIBUTION: when both buy-side and sell-side liquidity are
  present in a consolidation area (range extremes).

A level is considered "swept" when price closes beyond the level by at
least `liquidity_sweep_threshold_pips` (configurable, default 0.3 pips).

Architecture rules:
- Pure functions — no state, no external calls, no side effects.
- Same input + config → same output (deterministic).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_config import IctParameters
from junior_aladdin.floor_3_calculations.f3_types import LiquidityLevel, LiquidityType


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PIVOT_WINDOW: int = 5
"""Number of candles each side to confirm a swing high/low."""


# =============================================================================
# PUBLIC API
# =============================================================================


def detect_liquidity_levels(
    candles: list[dict[str, Any]],
    params: IctParameters | None = None,
    pivot_window: int = _DEFAULT_PIVOT_WINDOW,
) -> list[LiquidityLevel]:
    """Detect liquidity levels from OHLCV candle data.

    Identifies swing highs (BUY_SIDE liquidity above market) and swing lows
    (SELL_SIDE liquidity below market) using a simple pivot window approach.
    Each detected level is checked against subsequent candles to see if it
    has already been swept.

    Args:
        candles: List of OHLCV candle dicts with ``\"high\"``, ``\"low\"``,
            ``\"close\"``, and ``\"timestamp\"`` keys.
        params: ICT parameters with sweep threshold.
            If ``None``, uses default ``IctParameters()``.
        pivot_window: Number of candles on each side to confirm a swing
            point. Default 5.

    Returns:
        A list of ``LiquidityLevel`` objects, sorted by timestamp ascending.
        Empty list if insufficient data.
    """
    if params is None:
        params = IctParameters()

    threshold = float(params.liquidity_sweep_threshold_pips)
    n = len(candles)

    if n < pivot_window * 2 + 1:
        return []

    levels: list[LiquidityLevel] = []

    for i in range(pivot_window, n - pivot_window):
        candle = candles[i]
        ts = candle.get("timestamp")
        if not isinstance(ts, datetime):
            continue

        high = candle.get("high", 0)
        low = candle.get("low", 0)

        # Check for swing HIGH (higher than both sides)
        is_swing_high = all(
            high > candles[j].get("high", 0)
            for j in range(i - pivot_window, i + pivot_window + 1)
            if j != i
        )

        # Check for swing LOW (lower than both sides)
        is_swing_low = all(
            low < candles[j].get("low", float("inf"))
            for j in range(i - pivot_window, i + pivot_window + 1)
            if j != i
        )

        if is_swing_high:
            # BUY_SIDE liquidity = stops above price at swing high
            swept, swept_at = _check_level_swept(
                level=high,
                is_buy_side=True,
                candles=candles,
                start_idx=i + 1,
                threshold=threshold,
            )
            levels.append(LiquidityLevel(
                liquidity_type=LiquidityType.BUY_SIDE,
                price=high,
                timestamp=ts,
                swept=swept,
                swept_at=swept_at,
                size=_calculate_liquidity_size(candles, i, pivot_window, is_high=True),
            ))

        if is_swing_low:
            # SELL_SIDE liquidity = stops below price at swing low
            swept, swept_at = _check_level_swept(
                level=low,
                is_buy_side=False,
                candles=candles,
                start_idx=i + 1,
                threshold=threshold,
            )
            levels.append(LiquidityLevel(
                liquidity_type=LiquidityType.SELL_SIDE,
                price=low,
                timestamp=ts,
                swept=swept,
                swept_at=swept_at,
                size=_calculate_liquidity_size(candles, i, pivot_window, is_high=False),
            ))

    return levels


def check_sweep(
    level: float,
    candles: list[dict[str, Any]],
    is_buy_side: bool = True,
    params: IctParameters | None = None,
) -> tuple[bool, datetime | None]:
    """Check whether a specific price level has been swept by price action.

    A BUY_SIDE level (swing high above market) is swept when a candle's
    close exceeds the level by at least ``liquidity_sweep_threshold_pips``.

    A SELL_SIDE level (swing low below market) is swept when a candle's
    close goes below the level by at least ``liquidity_sweep_threshold_pips``.

    Args:
        level: The price level to check.
        candles: All available candles. The function searches all candles
            to find the first sweep event.
        is_buy_side: ``True`` for BUY_SIDE liquidity (above market),
            ``False`` for SELL_SIDE liquidity (below market).
        params: ICT parameters with sweep threshold.
            If ``None``, uses default ``IctParameters()``.

    Returns:
        A tuple of ``(swept, swept_at)``:
        - ``swept``: ``True`` if the level was swept.
        - ``swept_at``: Timestamp of the first sweep, or ``None``.
    """
    if params is None:
        params = IctParameters()

    threshold = float(params.liquidity_sweep_threshold_pips)
    return _check_level_swept(level, is_buy_side, candles, 0, threshold)


def classify_liquidity(
    buy_side_levels: list[LiquidityLevel],
    sell_side_levels: list[LiquidityLevel],
) -> LiquidityType:
    """Classify overall liquidity context from lists of detected levels.

    - If both sides have active (non-swept) levels → DOUBLE_DISTRIBUTION
    - If only buy-side has active levels → BUY_SIDE
    - If only sell-side has active levels → SELL_SIDE
    - If neither has active levels → BUY_SIDE (default, price is in no-man's-land)

    Args:
        buy_side_levels: Detected BUY_SIDE liquidity levels.
        sell_side_levels: Detected SELL_SIDE liquidity levels.

    Returns:
        The dominant ``LiquidityType`` classification.
    """
    has_active_buy = any(not l.swept for l in buy_side_levels)
    has_active_sell = any(not l.swept for l in sell_side_levels)

    if has_active_buy and has_active_sell:
        return LiquidityType.DOUBLE_DISTRIBUTION
    elif has_active_buy:
        return LiquidityType.BUY_SIDE
    elif has_active_sell:
        return LiquidityType.SELL_SIDE
    # No active levels on either side — all detected swing points have been swept.
    # Price is in a "no-man's-land" between active liquidity pools.
    # BUY_SIDE is returned as a safe default (no "NEUTRAL" option exists in LiquidityType).
    return LiquidityType.BUY_SIDE


# =============================================================================
# INTERNAL
# =============================================================================


def _check_level_swept(
    level: float,
    is_buy_side: bool,
    candles: list[dict[str, Any]],
    start_idx: int,
    threshold: float,
) -> tuple[bool, datetime | None]:
    """Check if a price level has been swept by subsequent candles.

    Iterates candles from ``start_idx`` onward to find the first sweep.

    Args:
        level: The price level to check.
        is_buy_side: ``True`` for BUY_SIDE (price must close above level),
            ``False`` for SELL_SIDE (price must close below level).
        candles: Full list of candles (sweep is checked from ``start_idx``).
        start_idx: Index to start searching for sweep.
        threshold: Minimum price overshoot to confirm sweep (pips).

    Returns:
        ``(swept, swept_at)`` tuple.
    """
    for i in range(start_idx, len(candles)):
        candle = candles[i]
        close = candle.get("close")

        if close is None:
            continue

        if not isinstance(close, (int, float)):
            continue

        if _is_swept(close, level, is_buy_side, threshold):
            swept_at = candle.get("timestamp")
            if isinstance(swept_at, datetime):
                return True, swept_at
            return True, None

    return False, None


def _is_swept(
    close: float,
    level: float,
    is_buy_side: bool,
    threshold: float,
) -> bool:
    """Determine if a single candle's close sweeps a level.

    Args:
        close: Candle close price.
        level: The liquidity level price.
        is_buy_side: ``True`` for BUY_SIDE (close > level + threshold),
            ``False`` for SELL_SIDE (close < level - threshold).
        threshold: Minimum overshoot pips.

    Returns:
        ``True`` if the level is swept by this close.
    """
    if is_buy_side:
        return close > level + threshold
    else:
        return close < level - threshold


def _calculate_liquidity_size(
    candles: list[dict[str, Any]],
    idx: int,
    pivot_window: int,
    is_high: bool,
) -> float:
    """Estimate the relative size/importance of a liquidity level (0.0–1.0).

    Uses a combination of:
    - Number of candles the swing spans (wider = larger pool)
    - Volume at the swing point (higher volume = more participants)
    - Proximity to nearby swings (isolated = more significant)

    Args:
        candles: Full candle list.
        idx: Index of the swing candle.
        pivot_window: Pivot window used for detection.
        is_high: ``True`` for swing high, ``False`` for swing low.

    Returns:
        A relative size score (0.0–1.0).
    """
    if len(candles) < pivot_window * 2 + 1:
        return 0.5

    # Factor 1: Swing distance score (bigger swing = larger pool)
    if is_high:
        nearby_lows = [
            candles[j].get("low", float("inf"))
            for j in range(max(0, idx - pivot_window), min(len(candles), idx + pivot_window + 1))
            if j != idx
        ]
        peak = candles[idx].get("high", 0)
        avg_low = sum(nearby_lows) / len(nearby_lows) if nearby_lows else 0
        swing_distance = abs(peak - avg_low) / max(peak, 0.01)
        distance_score = min(1.0, swing_distance / 10.0)  # Normalise
    else:
        nearby_highs = [
            candles[j].get("high", 0)
            for j in range(max(0, idx - pivot_window), min(len(candles), idx + pivot_window + 1))
            if j != idx
        ]
        trough = candles[idx].get("low", 0)
        avg_high = sum(nearby_highs) / len(nearby_highs) if nearby_highs else 0
        swing_distance = abs(avg_high - trough) / max(trough, 0.01)
        distance_score = min(1.0, swing_distance / 10.0)

    # Factor 2: Volume score (if volume data available)
    volume = candles[idx].get("volume", 0)
    if volume and isinstance(volume, (int, float)):
        # Compare to average volume in window
        volumes = [
            candles[j].get("volume", 0) or 0
            for j in range(max(0, idx - pivot_window), min(len(candles), idx + pivot_window + 1))
        ]
        avg_vol = sum(volumes) / len(volumes) if volumes else 1
        vol_ratio = float(volume) / max(float(avg_vol), 0.01)
        volume_score = min(1.0, vol_ratio / 2.0)
    else:
        volume_score = 0.3  # Neutral if no volume data

    # Combine: 60% distance, 40% volume
    return round(0.6 * distance_score + 0.4 * volume_score, 2)
