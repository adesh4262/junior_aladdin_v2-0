"""Options — Max Pain Calculator.

Finds the Max Pain strike — the strike price where the total OI
(CE + PE) is highest, representing the level where option buyers
experience maximum financial pain at expiry.

Pure function — no state, no external calls.

Input: list of dict with keys:
    strike, option_type, oi, premium, iv, timestamp

Output: Max Pain signal dict with:
    max_pain_strike, max_pain_oi (total OI at that strike),
    distance_pct (percentage from a reference price)
"""

from __future__ import annotations

from typing import Any


def calculate_max_pain(
    snapshots: list[dict[str, Any]],
    reference_price: float = 0.0,
) -> dict[str, Any]:
    """Calculate the Max Pain strike from options snapshots.

    Groups snapshots by strike, sums total OI (CE + PE), and finds
    the strike with the highest total OI.

    Args:
        snapshots: List of OptionsSnapshot-like dicts.
        reference_price: Current market price for distance calculation.
            If 0, distance_pct is set to 0.

    Returns:
        Dict with:
            max_pain_strike (float): Strike with highest total OI.
            max_pain_oi (int): Total OI at that strike.
            distance_pct (float): %% away from reference_price.
            total_oi_by_strike (dict): All strikes with their total OI
                (for debugging/transparency).
    """
    # Aggregate total OI by strike (CE + PE combined)
    oi_by_strike: dict[float, int] = {}

    for snap in snapshots:
        strike = snap.get("strike", 0.0)
        oi = snap.get("oi", 0)

        if strike > 0:
            oi_by_strike[strike] = oi_by_strike.get(strike, 0) + oi

    if not oi_by_strike:
        return {
            "max_pain_strike": 0.0,
            "max_pain_oi": 0,
            "distance_pct": 0.0,
            "total_oi_by_strike": {},
        }

    # Find strike with highest total OI
    max_pain_strike = max(oi_by_strike, key=oi_by_strike.get)
    max_pain_oi = oi_by_strike[max_pain_strike]

    # Calculate distance from reference price
    distance_pct = 0.0
    if reference_price > 0:
        distance_pct = ((max_pain_strike - reference_price) / reference_price) * 100.0

    return {
        "max_pain_strike": max_pain_strike,
        "max_pain_oi": max_pain_oi,
        "distance_pct": round(distance_pct, 2),
        "total_oi_by_strike": dict(
            sorted(oi_by_strike.items(), key=lambda x: x[1], reverse=True)
        ),
    }
