"""Support Metrics — Cooldown Metrics Calculator.

Tracks cooldown state after losses, errors, or consecutive trades.
Cooldown is time-based — it decays over seconds.

Pure function — no state, no external calls.

Input: remaining_seconds (float), last_loss_time (optional datetime)
Output: cooldown_active (bool), cooldown_remaining_s (float)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_COOLDOWN_SECONDS: float = 300.0  # 5 minutes default cooldown


def compute_cooldown_status(
    remaining_seconds: float = 0.0,
    sequence_length: int = 0,
    last_loss_time: datetime | None = None,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    """Compute cooldown status from recent loss information.

    Cooldown is triggered by consecutive losses:
    - 1 loss → 120s cooldown
    - 2 losses → 300s cooldown
    - 3+ losses → 600s (10 min) cooldown

    Args:
        remaining_seconds: Already remaining cooldown time.
        sequence_length: Current consecutive loss streak.
        last_loss_time: When the last loss occurred (for time-based decay).
        current_time: Current timestamp. Uses UTC now if None.

    Returns:
        Dict with:
        - ``cooldown_active`` (bool): Whether cooldown is active.
        - ``cooldown_remaining_s`` (float): Seconds remaining.
        - ``cooldown_total_s`` (float): Total cooldown duration.
    """
    now = current_time or datetime.now(timezone.utc)

    # Determine cooldown duration based on loss sequence
    if sequence_length >= 3:
        cooldown_total_s = 600.0
    elif sequence_length == 2:
        cooldown_total_s = 300.0
    elif sequence_length == 1:
        cooldown_total_s = 120.0
    else:
        cooldown_total_s = 0.0

    # Compute remaining cooldown
    if last_loss_time is not None and cooldown_total_s > 0:
        # Time-based decay from last loss
        elapsed = (now - last_loss_time).total_seconds()
        decayed = max(0.0, cooldown_total_s - elapsed)
    elif remaining_seconds > 0:
        # Use remaining from previous state
        decayed = remaining_seconds
    elif cooldown_total_s > 0:
        # New cooldown from loss sequence (no time info yet)
        decayed = cooldown_total_s
    else:
        decayed = 0.0

    # If no losses and no remaining cooldown, no cooldown
    if sequence_length == 0 and decayed <= 0:
        cooldown_active = False
        cooldown_remaining_s = 0.0
    else:
        cooldown_active = decayed > 0
        cooldown_remaining_s = round(decayed, 1)

    return {
        "cooldown_active": cooldown_active,
        "cooldown_remaining_s": cooldown_remaining_s,
        "cooldown_total_s": cooldown_total_s,
    }
