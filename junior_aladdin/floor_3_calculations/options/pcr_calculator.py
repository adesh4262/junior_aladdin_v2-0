"""Options — PCR (Put-Call Ratio) Calculator.

Computes the Put-Call Ratio from OptionsSnapshot data and determines
whether the ratio is rising or falling compared to the previous value.

Pure function — no state, no external calls.

Input: list of dict with keys:
    strike, option_type, oi, change_in_oi, premium, iv, timestamp

Output: PCR signal dict with:
    pcr_value, pcr_trend (RISING/FALLING/STABLE), prev_pcr_value
"""

from __future__ import annotations

from typing import Any

_PCR_TREND_THRESHOLD: float = 0.02  # Minimum change to classify as RISING/FALLING


def calculate_pcr(
    snapshots: list[dict[str, Any]],
    prev_pcr_value: float | None = None,
) -> dict[str, Any]:
    """Calculate the Put-Call Ratio from a list of options snapshots.

    PCR = Total PE OI / Total CE OI

    Args:
        snapshots: List of OptionsSnapshot-like dicts.
        prev_pcr_value: Previous PCR value for trend calculation.
            If None, trend is "STABLE".

    Returns:
        Dict with:
            pcr_value (float): Computed PCR value.
            pcr_trend (str): "RISING", "FALLING", or "STABLE".
            prev_pcr_value (float or None): Previous value for reference.
            total_ce_oi (int): Total CE open interest.
            total_pe_oi (int): Total PE open interest.
    """
    total_ce_oi = 0
    total_pe_oi = 0

    for snap in snapshots:
        option_type = snap.get("option_type", "")
        oi = snap.get("oi", 0)

        if option_type == "CE":
            total_ce_oi += oi
        elif option_type == "PE":
            total_pe_oi += oi

    # PCR = PE OI / CE OI (standard formula)
    if total_ce_oi > 0:
        pcr_value = round(total_pe_oi / total_ce_oi, 4)
    else:
        pcr_value = 0.0

    # Determine trend
    pcr_trend = "STABLE"
    if prev_pcr_value is not None and prev_pcr_value > 0:
        change = pcr_value - prev_pcr_value
        if change > _PCR_TREND_THRESHOLD:
            pcr_trend = "RISING"
        elif change < -_PCR_TREND_THRESHOLD:
            pcr_trend = "FALLING"

    return {
        "pcr_value": pcr_value,
        "pcr_trend": pcr_trend,
        "prev_pcr_value": prev_pcr_value,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
    }
