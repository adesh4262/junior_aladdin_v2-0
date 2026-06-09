"""Options — IV (Implied Volatility) Calculator.

Aggregates implied volatility values across CE and PE options and
determines the overall IV context (HIGH / LOW / NORMAL).

Pure function — no state, no external calls.

Input: list of dict with keys:
    strike, option_type, oi, premium, iv, timestamp

Output: IV signal dict with:
    iv_value (average IV across all strikes),
    iv_percentile (optional positioning within a configurable range),
    iv_context (HIGH / LOW / NORMAL)
"""

from __future__ import annotations

from typing import Any

# Default thresholds for IV context classification
_DEFAULT_IV_HIGH_THRESHOLD: float = 30.0   # IV above this = HIGH
_DEFAULT_IV_LOW_THRESHOLD: float = 15.0    # IV below this = LOW
_DEFAULT_IV_HISTORICAL_P50: float = 20.0   # Approximate median IV for NIFTY options


def calculate_iv(
    snapshots: list[dict[str, Any]],
    iv_high_threshold: float = _DEFAULT_IV_HIGH_THRESHOLD,
    iv_low_threshold: float = _DEFAULT_IV_LOW_THRESHOLD,
    iv_historical_p50: float = _DEFAULT_IV_HISTORICAL_P50,
) -> dict[str, Any]:
    """Calculate aggregate IV state from options snapshots.

    Computes the average IV across all ATM/OTM strikes and classifies
    the overall IV context.

    Args:
        snapshots: List of OptionsSnapshot-like dicts.
        iv_high_threshold: IV above this % is considered HIGH.
        iv_low_threshold: IV below this % is considered LOW.
        iv_historical_p50: Approximate historical median IV for
            percentile estimation.

    Returns:
        Dict with:
            iv_value (float): Average IV (%%).
            iv_percentile (float): Estimated percentile (0-100).
            iv_context (str): "HIGH", "LOW", or "NORMAL".
            sample_count (int): Number of snapshots used.
    """
    iv_values: list[float] = []

    for snap in snapshots:
        iv = snap.get("iv")
        if iv is not None and isinstance(iv, (int, float)) and iv > 0:
            iv_values.append(float(iv))

    if not iv_values:
        return {
            "iv_value": 0.0,
            "iv_percentile": 50.0,
            "iv_context": "NORMAL",
            "sample_count": 0,
        }

    # Use median for robustness against outliers
    sorted_iv = sorted(iv_values)
    n = len(sorted_iv)
    if n % 2 == 0:
        median_iv = (sorted_iv[n // 2 - 1] + sorted_iv[n // 2]) / 2.0
    else:
        median_iv = sorted_iv[n // 2]

    iv_value = round(median_iv, 2)

    # Estimate percentile based on historical median
    if iv_historical_p50 > 0:
        # Simple estimation: ratio to historical median
        percentile = min(99.0, max(1.0, (iv_value / iv_historical_p50) * 50.0))
    else:
        percentile = 50.0

    # Classify context
    if iv_value >= iv_high_threshold:
        iv_context = "HIGH"
    elif iv_value <= iv_low_threshold:
        iv_context = "LOW"
    else:
        iv_context = "NORMAL"

    return {
        "iv_value": iv_value,
        "iv_percentile": round(percentile, 1),
        "iv_context": iv_context,
        "sample_count": len(iv_values),
    }
