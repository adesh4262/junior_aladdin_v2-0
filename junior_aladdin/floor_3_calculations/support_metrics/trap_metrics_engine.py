"""Support Metrics — Trap Metrics Calculator.

Detects trap pressure by analyzing recent trade mistakes.
A "trap" occurs when the market repeatedly triggers false breakouts
or fake move patterns that catch the system on the wrong side.

Pure function — no state, no external calls.

Input: mistake_history (list of dicts with zone_id, is_same_zone, timestamp)
Output: trap_pressure (bool), trap_density (0.0–1.0), trap_count (int)
"""

from __future__ import annotations

from typing import Any

TRAP_DENSITY_THRESHOLD: float = 0.5  # Above this = trap_pressure=True
TRAP_WINDOW_SIZE: int = 10  # Last N mistakes to analyze
TRAP_SAME_ZONE_RATIO: float = 0.4  # Ratio threshold for "dense" traps


def detect_trap_pressure(
    mistake_history: list[dict[str, Any]] | None = None,
    same_zone_failures: int = 0,
    total_mistakes: int = 0,
) -> dict[str, Any]:
    """Analyze mistake history to detect trap pressure.

    Args:
        mistake_history: Optional list of mistake dicts, each with:
            - ``zone_id`` (str): Which zone/pattern the mistake was in.
            - ``is_same_zone`` (bool): Whether it's the same zone as previous.
            - ``timestamp`` (str/optional): When it happened.
        same_zone_failures: Count of same-zone failures (if history not available).
        total_mistakes: Total mistake count.

    Returns:
        Dict with:
        - ``trap_pressure`` (bool): Whether trap pressure is elevated.
        - ``trap_density`` (float): Normalised density score (0.0–1.0).
        - ``trap_count`` (int): Number of traps detected.
        - ``same_zone_failures`` (int): Same-zone failure count.
    """
    trap_count = 0
    same_zone = same_zone_failures
    recent_traps = 0

    if mistake_history:
        # Analyze from history
        recent = mistake_history[-TRAP_WINDOW_SIZE:]
        same_zone = sum(1 for m in recent if m.get("is_same_zone", False))
        trap_count = same_zone
        recent_traps = len(recent)
    else:
        # Estimate from counts
        trap_count = same_zone
        recent_traps = max(total_mistakes, 1)

    # Compute density
    if recent_traps > 0:
        trap_density = min(1.0, same_zone / (recent_traps * TRAP_SAME_ZONE_RATIO))
    else:
        trap_density = 0.0

    trap_pressure = trap_density > TRAP_DENSITY_THRESHOLD

    return {
        "trap_pressure": trap_pressure,
        "trap_density": round(trap_density, 4),
        "trap_count": trap_count,
        "same_zone_failures": same_zone,
    }
