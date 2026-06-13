"""Support Metrics — Loss Metrics Calculator.

Tracks consecutive losses and total loss count from trade history.

Pure function — no state, no external calls.

Input: recent_trades (list of dicts with outcome: WIN/LOSS), or direct counts
Output: loss_count, sequence_length, has_loss_streak
"""

from __future__ import annotations

from typing import Any

LOSS_STREAK_THRESHOLD: int = 3  # 3 consecutive losses = dangerous streak


def compute_loss_report(
    recent_trades: list[dict[str, Any]] | None = None,
    loss_count: int = 0,
    sequence_length: int = 0,
) -> dict[str, Any]:
    """Compute loss report from recent trade history.

    Args:
        recent_trades: Optional list of trade dicts, each with ``outcome``
            (``\"WIN\"`` or ``\"LOSS\"``) and optionally ``timestamp``.
        loss_count: Direct loss count (used if recent_trades not available).
        sequence_length: Direct sequence length (used if recent_trades not
            available).

    Returns:
        Dict with:
        - ``loss_count`` (int): Total losses in the window.
        - ``sequence_length`` (int): Current consecutive loss streak.
        - ``has_loss_streak`` (bool): Whether streak exceeds threshold.
        - ``max_sequence_length`` (int): Longest sequence in the window.
    """
    if recent_trades:
        # Analyze from trade history
        actual_trades = [t for t in recent_trades if isinstance(t.get("outcome"), str)]
        losses = [t for t in actual_trades if t["outcome"].upper() == "LOSS"]
        loss_count = len(losses)
        wins = [t for t in actual_trades if t["outcome"].upper() == "WIN"]

        # Find current consecutive loss streak (from most recent)
        sequence_length = 0
        for t in reversed(actual_trades):
            if t["outcome"].upper() == "LOSS":
                sequence_length += 1
            else:
                break

        # Find max consecutive loss streak
        max_seq = 0
        current_seq = 0
        for t in actual_trades:
            if t["outcome"].upper() == "LOSS":
                current_seq += 1
                max_seq = max(max_seq, current_seq)
            else:
                current_seq = 0
    else:
        max_seq = sequence_length

    has_loss_streak = sequence_length >= LOSS_STREAK_THRESHOLD

    return {
        "loss_count": loss_count,
        "sequence_length": sequence_length,
        "has_loss_streak": has_loss_streak,
        "max_sequence_length": max(max_seq, sequence_length),
    }
