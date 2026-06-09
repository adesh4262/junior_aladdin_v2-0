"""Options — Wall Calculator.

Detects CALL_WALL (strike with highest CE OI) and PUT_WALL (strike
with highest PE OI) from OptionsSnapshot data.

A "wall" represents a strike where a large concentration of open
interest exists, potentially acting as support (put wall) or
resistance (call wall).

Pure function — no state, no external calls.

Input: list of dict with keys:
    strike, option_type, oi, premium, iv, timestamp

Output: list of wall signal dicts with:
    wall_type (CALL_WALL / PUT_WALL),
    wall_strike, wall_strength (OI at that strike),
    distance_pct (percentage from a reference price)
"""

from __future__ import annotations

from typing import Any


def detect_walls(
    snapshots: list[dict[str, Any]],
    reference_price: float = 0.0,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Detect CALL_WALL and PUT_WALL strikes from options snapshots.

    Groups snapshots by strike and option_type, sums OI, then identifies
    the strikes with the highest OI concentration for each side.

    Args:
        snapshots: List of OptionsSnapshot-like dicts.
        reference_price: Current market price for distance calculation.
            If 0, distance_pct is set to 0.
        top_n: Number of top walls to return per side (default 3).

    Returns:
        List of wall signal dicts, sorted by wall_strength descending.
        Each dict has:
            wall_type (str): "CALL_WALL" or "PUT_WALL".
            wall_strike (float): Strike price.
            wall_strength (float): Total OI at this strike.
            distance_pct (float): %% away from reference_price.
    """
    # Aggregate OI by strike + option_type
    ce_oi_by_strike: dict[float, int] = {}
    pe_oi_by_strike: dict[float, int] = {}

    for snap in snapshots:
        strike = snap.get("strike", 0.0)
        option_type = snap.get("option_type", "")
        oi = snap.get("oi", 0)

        if option_type == "CE":
            ce_oi_by_strike[strike] = ce_oi_by_strike.get(strike, 0) + oi
        elif option_type == "PE":
            pe_oi_by_strike[strike] = pe_oi_by_strike.get(strike, 0) + oi

    # Sort by OI descending and take top_n
    top_ce = sorted(ce_oi_by_strike.items(), key=lambda x: x[1], reverse=True)[:top_n]
    top_pe = sorted(pe_oi_by_strike.items(), key=lambda x: x[1], reverse=True)[:top_n]

    results: list[dict[str, Any]] = []

    for strike, oi in top_ce:
        distance_pct = _calc_distance_pct(strike, reference_price) if reference_price else 0.0
        results.append({
            "wall_type": "CALL_WALL",
            "wall_strike": strike,
            "wall_strength": oi,
            "distance_pct": round(distance_pct, 2),
        })

    for strike, oi in top_pe:
        distance_pct = _calc_distance_pct(strike, reference_price) if reference_price else 0.0
        results.append({
            "wall_type": "PUT_WALL",
            "wall_strike": strike,
            "wall_strength": oi,
            "distance_pct": round(distance_pct, 2),
        })

    # Sort by wall_strength descending
    results.sort(key=lambda w: w["wall_strength"], reverse=True)
    return results


def _calc_distance_pct(strike: float, reference_price: float) -> float:
    """Calculate the percentage distance from reference price to strike.

    Args:
        strike: The option strike price.
        reference_price: Current market price.

    Returns:
        Positive percentage if strike is above reference, negative if below.
    """
    if reference_price <= 0:
        return 0.0
    return ((strike - reference_price) / reference_price) * 100.0
