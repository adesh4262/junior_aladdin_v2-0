"""SMC — Market Structure Analysis.

Pure-function module for detecting swing highs/lows and classifying market
structure into BULLISH_HH_HL, BEARISH_LH_LL, CHOP, or BREAKOUT.

Architecture rules:
- Pure functions only — no state, no external calls, no side effects.
- Same input → same output (deterministic, seeded if randomness needed).
- Minimum data points enforced before returning meaningful results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    MarketStructureType,
    SwingPoint,
)

# ── Module-level constants ──────────────────────────────────────────────────
BREAKOUT_THRESHOLD: float = 0.005  # 0.5% — minimum move to qualify as breakout
STRUCTURE_BULLISH_THRESHOLD: float = 0.7  # 70%+ bullish pairs → uptrend
STRUCTURE_BEARISH_THRESHOLD: float = 0.7  # 70%+ bearish pairs → downtrend
MIN_SWING_POINTS_FOR_CLASSIFICATION: int = 4
STRENGTH_FLOOR: float = 0.1  # minimum strength for any valid swing


# =============================================================================
# PUBLIC API
# =============================================================================


def analyze_structure(
    candles: list[dict[str, Any]],
    lookback: int = 50,
    pivot_window: int = 2,
) -> dict[str, Any]:
    """Analyze market structure from OHLCV candle data.

    Detects swing highs/lows and classifies the overall market structure
    type based on the sequence of pivots.

    Args:
        candles: List of OHLCV candle dicts. Each dict must have
            ``"high"``, ``"low"``, and ``"timestamp"`` keys.
            Optional: ``"open"``, ``"close"``, ``"volume"``.
        lookback: Maximum number of candles to analyze.
            Must be >= ``pivot_window * 2 + 1``.
        pivot_window: Number of candles on each side to confirm a pivot.
            A swing high must be higher than ``pivot_window`` candles
            before and after it. Default 2.

    Returns:
        Dict with keys:
        - ``structure_type`` (MarketStructureType): Detected structure.
        - ``swing_points`` (list[SwingPoint]): Detected swing points,
          ordered by time.
        - ``segments`` (list[dict]): Structure segments with start/end
          indices and type.
        - ``candle_count`` (int): Number of candles analyzed.
        - ``swing_high_count`` (int): Number of swing highs detected.
        - ``swing_low_count`` (int): Number of swing lows detected.
        - ``valid`` (bool): Whether sufficient data was available.

    Raises:
        ValueError: If ``pivot_window < 1`` or ``lookback < 3``.
    """
    if pivot_window < 1:
        raise ValueError(f"pivot_window must be >= 1, got {pivot_window}")
    if lookback < 3:
        raise ValueError(f"lookback must be >= 3, got {lookback}")

    # Take only the last `lookback` candles
    if len(candles) > lookback:
        candles = candles[-lookback:]

    # Minimum data check
    min_required = pivot_window * 2 + 1
    if len(candles) < min_required:
        return {
            "structure_type": MarketStructureType.CHOP,
            "swing_points": [],
            "segments": [],
            "candle_count": len(candles),
            "swing_high_count": 0,
            "swing_low_count": 0,
            "valid": False,
        }

    # Detect swing points (unified pivot detection)
    swing_highs = _detect_pivots(candles, pivot_window, mode="HIGH")
    swing_lows = _detect_pivots(candles, pivot_window, mode="LOW")

    # Combine and sort by time (skip untimestamped candles)
    timestamped = [
        sp for sp in swing_highs + swing_lows
        if sp.timestamp is not None
    ]
    all_swings: list[SwingPoint] = sorted(
        timestamped,
        key=lambda sp: sp.timestamp if sp.timestamp else datetime.min,
    )

    # Classify structure from swing points
    structure_type, segments = _classify_structure(all_swings)

    return {
        "structure_type": structure_type,
        "swing_points": all_swings,
        "segments": segments,
        "candle_count": len(candles),
        "swing_high_count": len(swing_highs),
        "swing_low_count": len(swing_lows),
        "valid": True,
    }


def detect_hh_hl(
    candles: list[dict[str, Any]],
    pivot_window: int = 2,
) -> list[dict[str, Any]]:
    """Detect market structure segments (HH/HL/LH/LL sequences).

    Breaks the candle series into segments where the structure type
    is consistent (e.g., a bullish segment, then chop, then bearish).

    Args:
        candles: List of OHLCV candle dicts.
        pivot_window: Pivot detection window size.

    Returns:
        List of segment dicts, each with:
        - ``start_index`` (int): Start candle index.
        - ``end_index`` (int): End candle index (inclusive).
        - ``structure_type`` (MarketStructureType): Segment structure.
        - ``swing_points`` (list[SwingPoint]): Swings in this segment.
        - ``description`` (str): Human-readable segment description.
    """
    result = analyze_structure(candles, lookback=len(candles), pivot_window=pivot_window)
    return result["segments"]


# =============================================================================
# UNIFIED PIVOT DETECTION
# =============================================================================


def _detect_pivots(
    candles: list[dict[str, Any]],
    window: int,
    mode: str,
) -> list[SwingPoint]:
    """Detect swing pivot points (highs or lows) in candle data.

    In HIGH mode: a pivot is found when a candle's high is the highest
    among ``window`` candles before and after it.
    In LOW mode: a pivot is found when a candle's low is the lowest
    among ``window`` candles before and after it.

    Args:
        candles: List of OHLCV candle dicts.
        window: Number of candles on each side to confirm.
        mode: ``"HIGH"`` for swing highs, ``"LOW"`` for swing lows.

    Returns:
        List of detected ``SwingPoint`` objects.
    """
    is_high_mode = mode == "HIGH"
    field = "high" if is_high_mode else "low"
    swings: list[SwingPoint] = []
    n = len(candles)

    for i in range(window, n - window):
        current_val = candles[i].get(field, 0 if is_high_mode else float("inf"))
        ts = candles[i].get("timestamp")

        # Skip candles without timestamps
        if not isinstance(ts, datetime):
            continue

        if is_high_mode:
            # Check if current high is the highest in the window
            left_higher = any(
                candles[j].get(field, 0) >= current_val
                for j in range(i - window, i)
            )
            right_higher = any(
                candles[j].get(field, 0) > current_val
                for j in range(i + 1, i + window + 1)
            )
            if left_higher or right_higher:
                continue
            # Strength: how much higher than the nearest competitor
            left_extreme = max(candles[j].get(field, 0) for j in range(i - window, i))
            right_extreme = max(candles[j].get(field, 0) for j in range(i + 1, i + window + 1))
            nearest = max(left_extreme, right_extreme)
            diff = current_val - nearest
        else:
            # Check if current low is the lowest in the window
            left_lower = any(
                candles[j].get(field, float("inf")) <= current_val
                for j in range(i - window, i)
            )
            right_lower = any(
                candles[j].get(field, float("inf")) < current_val
                for j in range(i + 1, i + window + 1)
            )
            if left_lower or right_lower:
                continue
            # Strength: how much lower than the nearest competitor
            left_extreme = min(candles[j].get(field, float("inf")) for j in range(i - window, i))
            right_extreme = min(candles[j].get(field, float("inf")) for j in range(i + 1, i + window + 1))
            nearest = min(left_extreme, right_extreme)
            diff = nearest - current_val

        strength = _normalize_strength(diff, current_val)

        swings.append(SwingPoint(
            price=current_val,
            timestamp=ts,
            swing_type=mode,
            strength=strength,
        ))

    return swings


# =============================================================================
# STRUCTURE CLASSIFICATION
# =============================================================================


def _classify_structure(
    swing_points: list[SwingPoint],
) -> tuple[MarketStructureType, list[dict[str, Any]]]:
    """Classify market structure from a sorted list of swing points.

    Analyzes the sequence of alternating swing HIGHs and LOWs to determine
    whether the market is in an uptrend (HH/HL), downtrend (LH/LL), or
    range (CHOP).

    Args:
        swing_points: Sorted list of SwingPoint objects (timestamped only).

    Returns:
        Tuple of ``(MarketStructureType, list[segment_dicts])``.
    """
    if len(swing_points) < MIN_SWING_POINTS_FOR_CLASSIFICATION:
        return MarketStructureType.CHOP, _build_single_segment(
            MarketStructureType.CHOP, swing_points,
            "Insufficient swing points to classify structure",
        )

    # Separate alternating HIGH/LOW sequence
    highs = [sp for sp in swing_points if sp.swing_type == "HIGH"]
    lows = [sp for sp in swing_points if sp.swing_type == "LOW"]

    if len(highs) < 2 or len(lows) < 2:
        return MarketStructureType.CHOP, _build_single_segment(
            MarketStructureType.CHOP, swing_points,
            "Not enough alternating swings to classify",
        )

    # Detect HH/HL (uptrend) vs LH/LL (downtrend) vs CHOP (mixed)
    hh_count = sum(
        1 for i in range(1, len(highs)) if highs[i].price > highs[i - 1].price
    )
    hl_count = sum(
        1 for i in range(1, len(lows)) if lows[i].price > lows[i - 1].price
    )
    lh_count = len(highs) - 1 - hh_count
    ll_count = len(lows) - 1 - hl_count

    total_swing_pairs = len(highs) - 1 + len(lows) - 1
    if total_swing_pairs == 0:
        return MarketStructureType.CHOP, _build_single_segment(
            MarketStructureType.CHOP, swing_points, "No swing pairs available",
        )

    bullish_ratio = (hh_count + hl_count) / total_swing_pairs
    bearish_ratio = (lh_count + ll_count) / total_swing_pairs

    # Determine structure type
    if bullish_ratio >= STRUCTURE_BULLISH_THRESHOLD:
        structure = MarketStructureType.BULLISH_HH_HL
    elif bearish_ratio >= STRUCTURE_BEARISH_THRESHOLD:
        structure = MarketStructureType.BEARISH_LH_LL
    elif _is_recent_breakout(swing_points):
        structure = MarketStructureType.BREAKOUT
    else:
        structure = MarketStructureType.CHOP

    segments = _build_single_segment(
        structure, swing_points,
        _describe_structure(structure, bullish_ratio, bearish_ratio),
    )

    return structure, segments


def _is_recent_breakout(swing_points: list[SwingPoint]) -> bool:
    """Check if a recent breakout has occurred.

    A breakout is detected when the last 2 swings break the pattern
    of the preceding swings (e.g., a new HH after a series of LHs).

    Args:
        swing_points: Sorted list of SwingPoint objects.

    Returns:
        ``True`` if a recent breakout pattern is detected.
    """
    if len(swing_points) < 4:
        return False

    # Look at the last 3 swing points
    last_three = swing_points[-3:]

    highs = [sp for sp in last_three if sp.swing_type == "HIGH"]
    lows = [sp for sp in last_three if sp.swing_type == "LOW"]

    if len(highs) >= 2:
        if highs[-1].price > highs[-2].price * (1 + BREAKOUT_THRESHOLD):
            return True

    if len(lows) >= 2:
        if lows[-1].price < lows[-2].price * (1 - BREAKOUT_THRESHOLD):
            return True

    return False


# =============================================================================
# HELPERS
# =============================================================================


def _normalize_strength(diff: float, reference: float) -> float:
    """Normalize a price difference into a strength score (0.0–1.0).

    A valid swing always gets at least ``STRENGTH_FLOOR`` (0.1).
    A very dominant swing (2%+ away from nearest competitor) gets 1.0.

    Args:
        diff: The absolute price difference (always >= 0).
        reference: The reference price for percentage calculation.

    Returns:
        A strength score between 0.0 and 1.0, floored at STRENGTH_FLOOR.
    """
    if reference <= 0 or diff <= 0:
        return STRENGTH_FLOOR
    pct = diff / reference
    # Scale: 0% → 0.1, 0.5% → ~0.35, 2%+ → 1.0
    raw = pct * 50  # 0.5% → 0.25, 2% → 1.0
    return max(STRENGTH_FLOOR, min(1.0, raw))


def _build_single_segment(
    structure_type: MarketStructureType,
    swing_points: list[SwingPoint],
    description: str,
) -> list[dict[str, Any]]:
    """Build a single segment dict for the entire analyzed range.

    Args:
        structure_type: The market structure type.
        swing_points: List of swing points in this segment.
        description: Human-readable description.

    Returns:
        List containing one segment dict.
    """
    return [
        {
            "start_index": 0,
            "end_index": max(len(swing_points) - 1, 0),
            "structure_type": structure_type,
            "swing_points": swing_points,
            "description": description,
        },
    ]


def _describe_structure(
    structure_type: MarketStructureType,
    bullish_ratio: float,
    bearish_ratio: float,
) -> str:
    """Generate a human-readable description of the market structure.

    Args:
        structure_type: The classified market structure type.
        bullish_ratio: Ratio of bullish swing pairs (HH + HL).
        bearish_ratio: Ratio of bearish swing pairs (LH + LL).

    Returns:
        A description string.
    """
    descriptions = {
        MarketStructureType.BULLISH_HH_HL: (
            f"Bullish structure: {bullish_ratio:.0%} of swing pairs are "
            f"bullish (HH/HL)"
        ),
        MarketStructureType.BEARISH_LH_LL: (
            f"Bearish structure: {bearish_ratio:.0%} of swing pairs are "
            f"bearish (LH/LL)"
        ),
        MarketStructureType.CHOP: (
            f"Choppy/Range-bound: bullish {bullish_ratio:.0%}, "
            f"bearish {bearish_ratio:.0%}"
        ),
        MarketStructureType.BREAKOUT: (
            f"Breakout detected: recent swing breaks prior range"
        ),
    }
    return descriptions.get(
        structure_type,
        f"Structure type: {structure_type.value}",
    )
