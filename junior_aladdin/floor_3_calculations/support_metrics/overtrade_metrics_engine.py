"""Support Metrics — Overtrade Metrics Calculator.

Detects overtrading patterns — when the system takes too many trades
in a short period, especially after consecutive losses.

Pure function — no state, no external calls.

Input: recent_trades, time_window_minutes
Output: overtrade_flag, trade_frequency, trades_in_window
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_TRADES_PER_WINDOW: int = 3  # Max trades in the time window
DEFAULT_WINDOW_MINUTES: int = 30  # Time window to check


def detect_overtrade(
    recent_trades: list[dict[str, Any]] | None = None,
    trade_count_today: int = 0,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    """Detect whether the system is overtrading.

    Args:
        recent_trades: Optional list of trade dicts, each with ``timestamp``.
        trade_count_today: Direct trade count (used if recent_trades not
            available).
        window_minutes: Time window in minutes to check.
        current_time: Current timestamp. Uses UTC now if None.

    Returns:
        Dict with:
        - ``overtrade_flag`` (bool): Whether overtrading detected.
        - ``trade_frequency`` (float): Trades per minute.
        - ``trades_in_window`` (int): Number of trades in the window.
    """
    now = current_time or datetime.now(timezone.utc)

    if recent_trades:
        # Count trades in the time window
        cutoff = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        from datetime import timedelta
        window_start = cutoff - timedelta(minutes=window_minutes)

        trades_in_window = 0
        for t in recent_trades:
            ts = t.get("timestamp")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= window_start:
                    trades_in_window += 1
    else:
        trades_in_window = trade_count_today

    # Compute frequency
    if window_minutes > 0:
        trade_frequency = round(trades_in_window / window_minutes, 4)
    else:
        trade_frequency = 0.0

    overtrade_flag = trades_in_window > MAX_TRADES_PER_WINDOW

    return {
        "overtrade_flag": overtrade_flag,
        "trade_frequency": trade_frequency,
        "trades_in_window": trades_in_window,
        "max_trades_allowed": MAX_TRADES_PER_WINDOW,
    }
