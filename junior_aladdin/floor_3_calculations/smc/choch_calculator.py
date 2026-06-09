"""SMC — Change of Character (CHOCH) Calculator.

Detects shifts in market structure where price breaks the prior trend
pattern and signals a potential trend reversal.

Bullish CHOCH: Market shifts from bearish (LH/LL) → bullish (HH/HL).
    Price breaks above the most recent swing high after a series of
    lower highs / lower lows.

Bearish CHOCH: Market shifts from bullish (HH/HL) → bearish (LH/LL).
    Price breaks below the most recent swing low after a series of
    higher highs / higher lows.

Architecture rules:
- Pure functions — no state, no external calls, no side effects.
- Same input → same output (deterministic).
- CHOCH confirmed only after ``consecutive_required`` candles post-break.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    ChoCh,
    ChoChType,
    MarketStructureType,
    SwingPoint,
)
from junior_aladdin.floor_3_calculations.smc._shared import find_swing_candle_index
from junior_aladdin.floor_3_calculations.smc.market_structure import (
    analyze_structure,
)


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PIVOT_WINDOW: int = 2
_DEFAULT_LOOKBACK: int = 50
_DEFAULT_CONFIRMATION_CANDLES: int = 2  # choch_required_consecutive from config


# =============================================================================
# PUBLIC API
# =============================================================================


def detect_choch(
    candles: list[dict[str, Any]],
    pivot_window: int = _DEFAULT_PIVOT_WINDOW,
    lookback: int = _DEFAULT_LOOKBACK,
    consecutive_required: int = _DEFAULT_CONFIRMATION_CANDLES,
) -> list[ChoCh]:
    """Detect Changes of Character (structure shifts) in candle data.

    Scans the candle series for pattern where price breaks a prior
    swing extreme, potentially signalling a trend reversal.

    The detection works in two passes:
    1. Analyze market structure to find swing points and current structure.
    2. For each swing point, check if price subsequently breaks it
       in the opposite direction with confirmation.

    Args:
        candles: List of OHLCV candle dicts with ``\"high\"``, ``\"low\"``,
            ``\"close\"``, and ``\"timestamp\"`` keys.
        pivot_window: Pivot detection window.
        lookback: Maximum candles to analyze.
        consecutive_required: Number of candles post-break needed to
            confirm the CHOCH (default 2).

    Returns:
        List of detected ``ChoCh`` objects, ordered by formation time.
        Empty list if no CHOCH found.

    Raises:
        ValueError: If ``consecutive_required < 1``.
    """
    if consecutive_required < 1:
        raise ValueError(
            f"consecutive_required must be >= 1, got {consecutive_required}"
        )
    if len(candles) < 10:
        return []

    # Analyze market structure
    struct_result = analyze_structure(
        candles,
        lookback=lookback,
        pivot_window=pivot_window,
    )
    if not struct_result["valid"]:
        return []

    swing_points: list[SwingPoint] = struct_result["swing_points"]
    if len(swing_points) < 4:
        return []

    current_structure = struct_result["structure_type"]
    chochs: list[ChoCh] = []

    # For each swing point, check if it was broken by subsequent price action
    for idx, swing in enumerate(swing_points):
        choch = _check_swing_for_choch(
            swing=swing,
            swing_index=idx,
            swing_points=swing_points,
            candles=candles,
            current_structure=current_structure,
            pivot_window=pivot_window,
            consecutive_required=consecutive_required,
        )
        if choch is not None:
            chochs.append(choch)

    return chochs


def classify_choch(direction: str) -> ChoChType:
    """Classify a CHOCH by its direction string.

    Args:
        direction: ``\"bullish\"`` or ``\"bearish\"`` (case-insensitive).

    Returns:
        ``ChoChType.BULLISH_CHOCH`` or ``ChoChType.BEARISH_CHOCH``.

    Raises:
        ValueError: If direction is not recognised.
    """
    lower = direction.strip().lower()
    if lower in ("bullish", "buy", "up"):
        return ChoChType.BULLISH_CHOCH
    elif lower in ("bearish", "sell", "down"):
        return ChoChType.BEARISH_CHOCH
    else:
        raise ValueError(
            f"Unrecognised direction: {direction!r}. "
            f"Expected 'bullish' or 'bearish'."
        )


# =============================================================================
# INTERNAL DETECTION
# =============================================================================


def _check_swing_for_choch(
    swing: SwingPoint,
    swing_index: int,
    swing_points: list[SwingPoint],
    candles: list[dict[str, Any]],
    current_structure: MarketStructureType,
    pivot_window: int,
    consecutive_required: int,
) -> ChoCh | None:
    """Check if a swing point was broken by subsequent price action.

    A swing high being broken upward = potential Bullish CHOCH.
    A swing low being broken downward = potential Bearish CHOCH.

    The check requires the break to be confirmed by
    ``consecutive_required`` candles closing beyond the swing level.

    Args:
        swing: The swing point to check.
        swing_index: Index of this swing in the swing_points list.
        swing_points: All detected swing points.
        candles: Full candle list.
        current_structure: Current market structure type.
        pivot_window: Pivot window for finding the candle index.
        consecutive_required: Candles needed post-break to confirm.

    Returns:
        A ``ChoCh`` if detected, ``None`` otherwise.
    """
    # Find the candle index for this swing point
    candle_idx = find_swing_candle_index(swing, candles, pivot_window)
    if candle_idx is None or candle_idx >= len(candles) - consecutive_required:
        return None

    ts = candles[candle_idx].get("timestamp")
    if not isinstance(ts, datetime):
        return None

    if swing.swing_type == "HIGH":
        # A swing HIGH being broken ABOVE = Bullish CHOCH
        return _check_bullish_break(
            swing=swing,
            swing_index=swing_index,
            swing_points=swing_points,
            candles=candles,
            candle_idx=candle_idx,
            current_structure=current_structure,
            consecutive_required=consecutive_required,
            formation_ts=ts,
        )
    else:
        # A swing LOW being broken BELOW = Bearish CHOCH
        return _check_bearish_break(
            swing=swing,
            swing_index=swing_index,
            swing_points=swing_points,
            candles=candles,
            candle_idx=candle_idx,
            current_structure=current_structure,
            consecutive_required=consecutive_required,
            formation_ts=ts,
        )


def _check_bullish_break(
    swing: SwingPoint,
    swing_index: int,
    swing_points: list[SwingPoint],
    candles: list[dict[str, Any]],
    candle_idx: int,
    current_structure: MarketStructureType,
    consecutive_required: int,
    formation_ts: datetime,
) -> ChoCh | None:
    """Check if price broke above a swing high = Bullish CHOCH.

    A bullish CHOCH occurs when:
    1. Price is in or was recently in bearish structure (LH/LL or CHOP).
    2. Price breaks above a prior swing high.
    3. The break is confirmed by ``consecutive_required`` candles
       closing above the swing level.

    Args:
        swing: The swing HIGH being broken.
        swing_index: Index in swing_points.
        swing_points: All swing points.
        candles: Full candle list.
        candle_idx: Candle index of this swing.
        current_structure: Current market structure.
        consecutive_required: Confirmation candle count.
        formation_ts: Timestamp of the swing candle.

    Returns:
        A Bullish ``ChoCh`` if detected, ``None`` otherwise.
    """
    # Don't detect bullish breaks in an already-strong bullish structure
    if current_structure == MarketStructureType.BULLISH_HH_HL:
        return None

    break_level = swing.price

    # Limit: only check the 3 most recent swing highs for CHOCH
    recent_highs = [sp for sp in swing_points if sp.swing_type == "HIGH"][-3:]
    if swing not in recent_highs:
        return None

    # Check if subsequent candles break above this swing high
    break_candle_idx = _find_first_close_above(
        candles, candle_idx + 1, break_level
    )
    if break_candle_idx is None:
        return None

    # Confirm: check that `consecutive_required` candles close above
    if not _confirm_break(
        candles, break_candle_idx, break_level, "above", consecutive_required
    ):
        return None

    break_ts = candles[break_candle_idx].get("timestamp")

    return ChoCh(
        choch_type=ChoChType.BULLISH_CHOCH,
        break_price=break_level,
        timestamp=break_ts if isinstance(break_ts, datetime) else formation_ts,
        prior_structure=_infer_prior_structure(swing_points, swing_index),
        confirmed=True,
    )


def _check_bearish_break(
    swing: SwingPoint,
    swing_index: int,
    swing_points: list[SwingPoint],
    candles: list[dict[str, Any]],
    candle_idx: int,
    current_structure: MarketStructureType,
    consecutive_required: int,
    formation_ts: datetime,
) -> ChoCh | None:
    """Check if price broke below a swing low = Bearish CHOCH.

    A bearish CHOCH occurs when:
    1. Price is in or was recently in bullish structure (HH/HL or CHOP).
    2. Price breaks below a prior swing low.
    3. The break is confirmed by ``consecutive_required`` candles
       closing below the swing level.

    Args:
        swing: The swing LOW being broken.
        swing_index: Index in swing_points.
        swing_points: All swing points.
        candles: Full candle list.
        candle_idx: Candle index of this swing.
        current_structure: Current market structure.
        consecutive_required: Confirmation candle count.
        formation_ts: Timestamp of the swing candle.

    Returns:
        A Bearish ``ChoCh`` if detected, ``None`` otherwise.
    """
    # Don't detect bearish breaks in an already-strong bearish structure
    if current_structure == MarketStructureType.BEARISH_LH_LL:
        return None

    break_level = swing.price

    # Limit: only check the 3 most recent swing lows for CHOCH
    recent_lows = [sp for sp in swing_points if sp.swing_type == "LOW"][-3:]
    if swing not in recent_lows:
        return None

    # Check if subsequent candles break below this swing low
    break_candle_idx = _find_first_close_below(
        candles, candle_idx + 1, break_level
    )
    if break_candle_idx is None:
        return None

    # Confirm: check that `consecutive_required` candles close below
    if not _confirm_break(
        candles, break_candle_idx, break_level, "below", consecutive_required
    ):
        return None

    break_ts = candles[break_candle_idx].get("timestamp")

    return ChoCh(
        choch_type=ChoChType.BEARISH_CHOCH,
        break_price=break_level,
        timestamp=break_ts if isinstance(break_ts, datetime) else formation_ts,
        prior_structure=_infer_prior_structure(swing_points, swing_index),
        confirmed=True,
    )


# =============================================================================
# BREAK DETECTION HELPERS
# =============================================================================


def _find_first_close_above(
    candles: list[dict[str, Any]],
    start_idx: int,
    level: float,
) -> int | None:
    """Find the first candle whose close is above a price level.

    Args:
        candles: Full candle list.
        start_idx: Index to start searching from.
        level: Price level to check against.

    Returns:
        Candle index if found, ``None`` otherwise.
    """
    for i in range(start_idx, len(candles)):
        close = candles[i].get("close")
        if close is not None and close > level:
            return i
    return None


def _find_first_close_below(
    candles: list[dict[str, Any]],
    start_idx: int,
    level: float,
) -> int | None:
    """Find the first candle whose close is below a price level.

    Args:
        candles: Full candle list.
        start_idx: Index to start searching from.
        level: Price level to check against.

    Returns:
        Candle index if found, ``None`` otherwise.
    """
    for i in range(start_idx, len(candles)):
        close = candles[i].get("close")
        if close is not None and close < level:
            return i
    return None


def _confirm_break(
    candles: list[dict[str, Any]],
    break_idx: int,
    level: float,
    direction: str,
    required: int,
) -> bool:
    """Confirm a break by checking consecutive closes beyond the level.

    Args:
        candles: Full candle list.
        break_idx: Index of the first break candle.
        level: Price level to check against.
        direction: ``\"above\"`` or ``\"below\"``.
        required: Number of consecutive candles needed.

    Returns:
        ``True`` if the break is confirmed.
    """
    count = 0
    for i in range(break_idx, min(break_idx + required * 3, len(candles))):
        close = candles[i].get("close")
        if close is None:
            continue  # Skip malformed candles
        if direction == "above":
            if close > level:
                count += 1
                if count >= required:
                    return True
            else:
                count = 0  # Reset on non-confirming candle
        else:
            if close < level:
                count += 1
                if count >= required:
                    return True
            else:
                count = 0
    return count >= required


# =============================================================================
# STRUCTURE INFERENCE
# =============================================================================


def _infer_prior_structure(
    swing_points: list[SwingPoint],
    swing_index: int,
) -> MarketStructureType:
    """Infer the market structure PRIOR to a given swing point.

    Analyzes the swings leading up to the given index to determine
    whether the market was in an uptrend, downtrend, or range before
    the potential CHOCH.

    Args:
        swing_points: All detected swing points.
        swing_index: Index of the swing being examined.

    Returns:
        The inferred ``MarketStructureType`` prior to this swing.
    """
    if swing_index < 4:
        return MarketStructureType.CHOP

    preceding = swing_points[max(0, swing_index - 4):swing_index]
    highs = [sp for sp in preceding if sp.swing_type == "HIGH"]
    lows = [sp for sp in preceding if sp.swing_type == "LOW"]

    if len(highs) < 2 or len(lows) < 2:
        return MarketStructureType.CHOP

    hh_count = sum(
        1 for i in range(1, len(highs)) if highs[i].price > highs[i - 1].price
    )
    hl_count = sum(
        1 for i in range(1, len(lows)) if lows[i].price > lows[i - 1].price
    )
    lh_count = len(highs) - 1 - hh_count
    ll_count = len(lows) - 1 - hl_count

    total = len(highs) - 1 + len(lows) - 1
    if total == 0:
        return MarketStructureType.CHOP

    bullish_ratio = (hh_count + hl_count) / total
    bearish_ratio = (lh_count + ll_count) / total

    if bullish_ratio >= 0.7:
        return MarketStructureType.BULLISH_HH_HL
    elif bearish_ratio >= 0.7:
        return MarketStructureType.BEARISH_LH_LL
    return MarketStructureType.CHOP



