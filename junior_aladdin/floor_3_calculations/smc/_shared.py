"""SMC — Shared utilities for sub-modules.

Common helper functions used by multiple SMC sub-calculators
(market_structure, fvg_calculator, ob_calculator, choch_calculator).

All functions are pure — no state, no side effects.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import SwingPoint


def find_swing_candle_index(
    swing: SwingPoint,
    candles: list[dict[str, Any]],
    pivot_window: int,
) -> int | None:
    """Find the candle index for a given swing point by price matching.

    Matches the swing point's price to the closest candle's high (for
    swing HIGH) or low (for swing LOW) within a tight tolerance.

    Args:
        swing: The SwingPoint to locate.
        candles: The candle list to search.
        pivot_window: Pivot window to narrow the search range.

    Returns:
        Candle index, or ``None`` if not found.
    """
    field = "high" if swing.swing_type == "HIGH" else "low"
    start = pivot_window
    end = len(candles) - pivot_window

    best_idx: int | None = None
    best_diff: float = float("inf")

    for i in range(start, end):
        price = candles[i].get(field, 0 if field == "high" else float("inf"))
        diff = abs(price - swing.price)
        if diff < best_diff and diff <= 0.05:
            best_diff = diff
            best_idx = i

    return best_idx
