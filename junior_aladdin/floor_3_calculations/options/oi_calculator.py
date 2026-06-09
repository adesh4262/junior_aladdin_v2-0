"""Options — OI Change Calculator.

Detects open interest changes across CE and PE options and classifies
them as BUYING (OI increasing) or UNWINDING (OI decreasing).

Pure function — no state, no external calls.

Input: list of dict with keys:
    strike, option_type, oi, change_in_oi, premium, timestamp

Output: list of OI_CHANGE signal dicts with:
    oi_direction (BUYING/UNWINDING), change_pct, strike,
    option_type (CE/PE), change_in_oi, premium
"""

from __future__ import annotations

from typing import Any


def calculate_oi_changes(
    snapshots: list[dict[str, Any]],
    min_oi_change_pct: float = 5.0,
) -> list[dict[str, Any]]:
    """Calculate OI changes across all snapshots and classify direction.

    Args:
        snapshots: List of OptionsSnapshot-like dicts, each with:
            strike, option_type, oi, change_in_oi, premium, timestamp.
        min_oi_change_pct: Minimum percentage change to classify as
            meaningful (default 5%%). Smaller changes are ignored.

    Returns:
        List of OI_CHANGE signal dicts, sorted by |change_pct|
        descending (most significant first).
    """
    results: list[dict[str, Any]] = []

    for snap in snapshots:
        strike = snap.get("strike", 0.0)
        option_type = snap.get("option_type", "")
        oi = snap.get("oi", 0)
        change_in_oi = snap.get("change_in_oi", 0)
        premium = snap.get("premium", 0.0)

        # Skip entries with no OI or no change
        if oi <= 0:
            continue

        # Calculate percentage change relative to previous OI
        prev_oi = oi - change_in_oi
        if prev_oi <= 0:
            # First snapshot or reset — skip direction classification
            continue

        change_pct = abs(change_in_oi / prev_oi) * 100.0

        # Skip insignificant changes
        if change_pct < min_oi_change_pct:
            continue

        # Classify direction
        if change_in_oi > 0:
            direction = "BUYING"
        else:
            direction = "UNWINDING"

        results.append({
            "oi_direction": direction,
            "change_pct": round(change_pct, 2),
            "strike": strike,
            "option_type": option_type,
            "change_in_oi": change_in_oi,
            "premium": premium,
        })

    # Sort by |change_pct| descending (most significant first)
    results.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return results


def calculate_oi_summary(
    oi_changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a summary of OI activity across all strikes.

    Args:
        oi_changes: Output from ``calculate_oi_changes``.

    Returns:
        Dict with aggregate counts:
            ce_buying, ce_unwinding, pe_buying, pe_unwinding,
            total_significant_changes.
    """
    ce_buying = sum(1 for c in oi_changes if c["option_type"] == "CE" and c["oi_direction"] == "BUYING")
    ce_unwinding = sum(1 for c in oi_changes if c["option_type"] == "CE" and c["oi_direction"] == "UNWINDING")
    pe_buying = sum(1 for c in oi_changes if c["option_type"] == "PE" and c["oi_direction"] == "BUYING")
    pe_unwinding = sum(1 for c in oi_changes if c["option_type"] == "PE" and c["oi_direction"] == "UNWINDING")

    return {
        "ce_buying": ce_buying,
        "ce_unwinding": ce_unwinding,
        "pe_buying": pe_buying,
        "pe_unwinding": pe_unwinding,
        "total_significant_changes": len(oi_changes),
    }
