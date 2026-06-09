"""SMC — Fair Value Gap (FVG) Calculator.

Detects Fair Value Gaps from 3-candle sequences and checks mitigation
(price filling the gap). Pure functions only.

Architecture rules:
- Pure functions — no state, no external calls, no side effects.
- Same input → same output (deterministic).
- FVG must span exactly 3 consecutive candles.
- Gap size must be >= fvg_min_gap_pips to qualify.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import FairValueGap, FvgType


# ── Module-level constants ──────────────────────────────────────────────────
# These serve as defaults; the SMC engine overrides from f3_config.
_DEFAULT_MIN_GAP_PIPS: float = 0.5


# =============================================================================
# PUBLIC API
# =============================================================================


def detect_fvg(
    candles: list[dict[str, Any]],
    min_gap_pips: float = _DEFAULT_MIN_GAP_PIPS,
) -> list[FairValueGap]:
    """Detect Fair Value Gaps in a list of OHLCV candles.

    A FVG is identified from 3 consecutive candles where the third candle's
    price leaves a gap relative to the first candle, indicating a rapid price
    move with unfilled space.

    Bullish FVG: candle[i].high < candle[i+2].low
        → Gap between candle[i].high and candle[i+2].low (price jumped up).
    Bearish FVG: candle[i].low > candle[i+2].high
        → Gap between candle[i+2].high and candle[i].low (price jumped down).

    Args:
        candles: List of OHLCV candle dicts. Each must have ``"high"``,
            ``"low"``, and ``"timestamp"`` keys.
        min_gap_pips: Minimum gap size to qualify as a FVG.
            Candles without timestamps are skipped.

    Returns:
        List of detected ``FairValueGap`` objects, ordered by formation time.
        Empty list if no FVGs found.

    Raises:
        ValueError: If ``min_gap_pips <= 0``.
    """
    if min_gap_pips <= 0:
        raise ValueError(f"min_gap_pips must be > 0, got {min_gap_pips}")

    if len(candles) < 3:
        return []

    fvgs: list[FairValueGap] = []

    for i in range(len(candles) - 2):
        c0 = candles[i]
        c2 = candles[i + 2]

        # Check for Bullish FVG (only needs c0 and c2)
        fvg = _check_bullish_fvg(c0, c2, min_gap_pips)
        if fvg is not None:
            fvgs.append(fvg)

        # Check for Bearish FVG (only needs c0 and c2)
        fvg = _check_bearish_fvg(c0, c2, min_gap_pips)
        if fvg is not None:
            fvgs.append(fvg)

    # Sort by formation timestamp (or index order)
    return fvgs


def check_mitigation(
    fvg: FairValueGap,
    candles: list[dict[str, Any]],
    start_index: int | None = None,
) -> tuple[bool, datetime | None]:
    """Check whether a Fair Value Gap has been mitigated (filled).

    A FVG is mitigated when price subsequently enters the gap zone:
    - Bullish FVG: any later candle's high >= gap bottom AND low <= gap top.
    - Bearish FVG: any later candle's low <= gap bottom AND high >= gap top.

    Simpler check: price touches or crosses the gap region.

    Args:
        fvg: The ``FairValueGap`` to check.
        candles: Full list of OHLCV candle dicts (must include post-FVG candles).
        start_index: Index to start searching from.
            Defaults to the index of the third candle of the FVG + 1.

    Returns:
        Tuple of ``(mitigated, mitigated_at)``.
        ``mitigated`` is ``True`` if the gap has been filled.
        ``mitigated_at`` is the timestamp of the first candle that fills it,
        or ``None`` if not mitigated.
    """
    if start_index is None:
        # Start searching from candle after the 3rd one (index 2 of the pattern)
        # We need to find which 3-candle sequence produced this FVG
        start_index = _find_fvg_index(fvg, candles)
        if start_index is None:
            return False, None
        start_index += 3  # Start after the 3-candle pattern

    if start_index >= len(candles):
        return fvg.mitigated, fvg.mitigated_at

    if fvg.fvg_type == FvgType.BULLISH_FVG:
        # Bullish FVG gap: bottom = fvg.bottom (candle0.high), top = fvg.top (candle2.low)
        # Mitigated when any candle's low <= fvg.top (price enters gap from above)
        # Or high >= fvg.bottom (price enters gap from below)
        for i in range(start_index, len(candles)):
            c = candles[i]
            c_high = c.get("high", 0)
            c_low = c.get("low", float("inf"))
            ts = c.get("timestamp")

            # Price has entered the gap zone
            if c_low <= fvg.top:
                return True, ts if isinstance(ts, datetime) else None
            if c_high >= fvg.bottom:
                return True, ts if isinstance(ts, datetime) else None
    else:
        # Bearish FVG gap: top = fvg.top (candle0.low), bottom = fvg.bottom (candle2.high)
        # Mitigated when any candle's high >= fvg.bottom (price enters gap from below)
        # Or low <= fvg.top (price enters gap from above)
        for i in range(start_index, len(candles)):
            c = candles[i]
            c_high = c.get("high", 0)
            c_low = c.get("low", float("inf"))
            ts = c.get("timestamp")

            if c_high >= fvg.bottom:
                return True, ts if isinstance(ts, datetime) else None
            if c_low <= fvg.top:
                return True, ts if isinstance(ts, datetime) else None

    return False, None


# =============================================================================
# INTERNAL DETECTION
# =============================================================================


def _check_bullish_fvg(
    c0: dict[str, Any],
    c2: dict[str, Any],
    min_gap_pips: float,
) -> FairValueGap | None:
    """Check for a Bullish FVG from the first and third candle.

    Bullish FVG condition: c0.high < c2.low (price jumped up, leaving gap).
    Gap region: top = c2.low, bottom = c0.high.
    The middle candle (c1) is not needed for the gap condition — only c0
    and c2 define the gap boundaries.

    Args:
        c0: First candle of the 3-candle sequence.
        c2: Third candle of the 3-candle sequence.
        min_gap_pips: Minimum gap size to qualify.

    Returns:
        A ``FairValueGap`` if detected, ``None`` otherwise.
    """
    c0_high = c0.get("high", 0)
    c2_low = c2.get("low", float("inf"))
    ts = c0.get("timestamp")

    # Skip untimestamped candles
    if not isinstance(ts, datetime):
        return None

    # Condition: c0.high < c2.low → gap exists
    if c0_high >= c2_low:
        return None

    gap_top = c2_low        # Upper boundary of the gap
    gap_bottom = c0_high    # Lower boundary of the gap
    gap_size = gap_top - gap_bottom

    if gap_size < min_gap_pips:
        return None

    return FairValueGap(
        fvg_type=FvgType.BULLISH_FVG,
        top=gap_top,
        bottom=gap_bottom,
        formation_timestamp=ts,
        mitigated=False,
        mitigated_at=None,
        gap_size_pips=round(gap_size, 2),
    )


def _check_bearish_fvg(
    c0: dict[str, Any],
    c2: dict[str, Any],
    min_gap_pips: float,
) -> FairValueGap | None:
    """Check for a Bearish FVG from the first and third candle.

    Bearish FVG condition: c0.low > c2.high (price jumped down, leaving gap).
    Gap region: top = c0.low, bottom = c2.high.
    The middle candle (c1) is not needed for the gap condition — only c0
    and c2 define the gap boundaries.

    Args:
        c0: First candle of the 3-candle sequence.
        c2: Third candle of the 3-candle sequence.
        min_gap_pips: Minimum gap size to qualify.

    Returns:
        A ``FairValueGap`` if detected, ``None`` otherwise.
    """
    c0_low = c0.get("low", float("inf"))
    c2_high = c2.get("high", 0)
    ts = c0.get("timestamp")

    # Skip untimestamped candles
    if not isinstance(ts, datetime):
        return None

    # Condition: c0.low > c2.high → gap exists
    if c0_low <= c2_high:
        return None

    gap_top = c0_low          # Upper boundary of the gap
    gap_bottom = c2_high      # Lower boundary of the gap
    gap_size = gap_top - gap_bottom

    if gap_size < min_gap_pips:
        return None

    return FairValueGap(
        fvg_type=FvgType.BEARISH_FVG,
        top=gap_top,
        bottom=gap_bottom,
        formation_timestamp=ts,
        mitigated=False,
        mitigated_at=None,
        gap_size_pips=round(gap_size, 2),
    )


def _find_fvg_index(
    fvg: FairValueGap,
    candles: list[dict[str, Any]],
) -> int | None:
    """Find the starting candle index for a given FVG.

    Matches by formation_timestamp and gap characteristics.

    Args:
        fvg: The FairValueGap to find.
        candles: The candle list to search.

    Returns:
        Index of the first candle of the FVG's 3-candle sequence,
        or ``None`` if not found.
    """
    if len(candles) < 3:
        return None

    for i in range(len(candles) - 2):
        c0 = candles[i]
        c2 = candles[i + 2]

        c0_ts = c0.get("timestamp")
        if isinstance(c0_ts, datetime) and fvg.formation_timestamp == c0_ts:
            return i

        # Fallback: match by gap boundaries
        c0_high = c0.get("high", 0)
        c2_low = c2.get("low", float("inf"))
        c0_low = c0.get("low", float("inf"))
        c2_high = c2.get("high", 0)

        if fvg.fvg_type == FvgType.BULLISH_FVG:
            if abs(c0_high - fvg.bottom) < 0.01 and abs(c2_low - fvg.top) < 0.01:
                return i
        else:
            if abs(c0_low - fvg.top) < 0.01 and abs(c2_high - fvg.bottom) < 0.01:
                return i

    return None
