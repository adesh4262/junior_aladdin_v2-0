"""Floor 2 Cleaning — tick cleaner.

Cleans spot tick data by:
- Rejecting zero-price ticks (data glitches).
- Rejecting negative prices or volumes.
- Normalising float/int field types.
- Flagging suspicious ticks (unrealistic price jumps, stale ticks).

Architecture rules:
- Cleaning is FACTUAL — removes glitches, does NOT interpret market meaning.
- Suspicious ticks are flagged for review, not removed automatically.
- Original values are preserved in ``CleaningResult.original_values``.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import CleaningResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("tick_cleaner")

MAX_PRICE_CHANGE_PCT: float = 15.0  # Max % change from previous tick to flag


def clean_tick(
    record: dict[str, Any],
    previous_price: float | None = None,
) -> CleaningResult:
    """Clean a single spot tick packet.

    Args:
        record: The packet record dict (from ``NormalizedRawStore.get()``).
        previous_price: The LTP of the previous tick from the same source+feed,
            for price-jump detection. ``None`` if this is the first tick.

    Returns:
        A ``CleaningResult`` with the cleaned data or removal reason.
    """
    raw_data = record.get("original_raw_packet", {})
    if not raw_data:
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason="Empty raw data — nothing to clean",
            anomaly_flags=["empty_raw_data"],
        )

    packet_id = record.get("packet_id", "unknown")
    feed_type = record.get("feed_type", "unknown")

    # ── Extract & validate tick fields ────────────────────────────────
    ltp = raw_data.get("ltp")
    volume = raw_data.get("volume", 0)
    symbol = raw_data.get("symbol", "")
    timestamp = raw_data.get("timestamp", "")

    cleaned = {
        "ltp": ltp,
        "volume": volume,
        "symbol": symbol,
        "feed_type": feed_type,
        "timestamp": timestamp,
    }

    anomaly_flags: list[str] = []
    original_values: dict[str, Any] = {}
    repaired = False
    repair_actions: list[str] = []

    # ── LTP validation ────────────────────────────────────────────────
    if ltp is None:
        anomaly_flags.append("ltp_is_none")
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason="Tick has no LTP value — removing",
            anomaly_flags=anomaly_flags,
        )

    if not isinstance(ltp, (int, float)):
        anomaly_flags.append("ltp_not_numeric")
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason=f"Tick LTP is not numeric: {type(ltp).__name__}",
            anomaly_flags=anomaly_flags,
        )

    if ltp <= 0:
        anomaly_flags.append("ltp_zero_or_negative")
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason=f"Tick has non-positive LTP: {ltp}",
            anomaly_flags=anomaly_flags,
        )

    # ── Volume validation ─────────────────────────────────────────────
    if not isinstance(volume, (int, float)):
        anomaly_flags.append("volume_not_numeric")
        cleaned["volume"] = 0
        original_values["volume"] = volume
        repaired = True
        repair_actions.append("volume set to 0 (was non-numeric)")

    if isinstance(volume, (int, float)) and volume < 0:
        anomaly_flags.append("volume_negative")
        cleaned["volume"] = 0
        original_values["volume"] = volume
        repaired = True
        repair_actions.append("volume set to 0 (was negative)")

    # ── Price jump detection (not a removal, just a flag) ────────────
    if previous_price is not None and previous_price > 0:
        change_pct = abs(ltp - previous_price) / previous_price * 100
        if change_pct > MAX_PRICE_CHANGE_PCT:
            anomaly_flags.append(
                f"price_jump_{change_pct:.1f}pct"
            )

    # ── Assemble result ───────────────────────────────────────────────
    logger.debug(
        "Tick cleaned",
        extra={
            "packet_id": packet_id,
            "anomalies": len(anomaly_flags),
            "repaired": repaired,
        },
    )

    return CleaningResult(
        cleaned_record=cleaned,
        removed=False,
        repaired=repaired,
        repair_action="; ".join(repair_actions) if repair_actions else None,
        original_values=original_values if original_values else None,
        anomaly_flags=anomaly_flags,
    )
