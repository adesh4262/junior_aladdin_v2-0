"""Floor 2 Cleaning — options cleaner.

Cleans options snapshot data by:
- Validating strike prices, OI, and premiums.
- Rejecting snapshots with invalid option types (not CE/PE).
- Normalising numerical fields.
- Flagging suspicious values (zero OI with high premium).

Architecture rules:
- Cleaning is FACTUAL — removes glitches, does NOT interpret market meaning.
- Suspicious snapshots are flagged for review, not removed automatically.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import CleaningResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("options_cleaner")

VALID_OPTION_TYPES = {"CE", "PE"}


def clean_options_snapshot(
    record: dict[str, Any],
) -> CleaningResult:
    """Clean a single options snapshot packet.

    Args:
        record: The packet record dict (from ``NormalizedRawStore.get()``).

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

    anomaly_flags: list[str] = []
    original_values: dict[str, Any] = {}
    repaired = False
    repair_actions: list[str] = []

    # ── Extract fields ────────────────────────────────────────────────
    option_type = raw_data.get("option_type", "")
    strike = raw_data.get("strike")
    oi = raw_data.get("oi", 0)
    premium = raw_data.get("premium", 0.0)
    expiry = raw_data.get("expiry", "")
    iv = raw_data.get("iv", 0.0)
    change_in_oi = raw_data.get("change_in_oi", 0)

    cleaned = {
        "option_type": option_type,
        "strike": strike if strike is not None else 0.0,
        "oi": oi,
        "premium": premium,
        "expiry": expiry,
        "iv": iv,
        "change_in_oi": change_in_oi,
        "feed_type": feed_type,
    }

    # ── Option type validation ────────────────────────────────────────
    if option_type not in VALID_OPTION_TYPES:
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason=f"Invalid option type: {option_type}",
            anomaly_flags=[f"invalid_option_type_{option_type}"],
        )

    # ── Strike validation ─────────────────────────────────────────────
    if strike is None:
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason="Strike price is missing",
            anomaly_flags=["strike_missing"],
        )

    if not isinstance(strike, (int, float)) or strike <= 0:
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason=f"Invalid strike price: {strike}",
            anomaly_flags=[f"invalid_strike_{strike}"],
        )

    # ── OI validation ─────────────────────────────────────────────────
    if not isinstance(oi, (int, float)):
        anomaly_flags.append("oi_not_numeric")
        cleaned["oi"] = 0
        original_values["oi"] = oi
        repaired = True
        repair_actions.append("oi set to 0 (was non-numeric)")

    if isinstance(oi, (int, float)) and oi < 0:
        anomaly_flags.append("oi_negative")
        cleaned["oi"] = 0
        original_values["original_oi"] = oi
        repaired = True
        repair_actions.append("oi set to 0 (was negative)")

    # ── Premium validation ────────────────────────────────────────────
    if not isinstance(premium, (int, float)):
        anomaly_flags.append("premium_not_numeric")
        cleaned["premium"] = 0.0
        original_values["premium"] = premium
        repaired = True
        repair_actions.append("premium set to 0 (was non-numeric)")

    if isinstance(premium, (int, float)) and premium < 0:
        anomaly_flags.append("premium_negative")
        cleaned["premium"] = 0.0
        original_values["premium"] = premium
        repaired = True
        repair_actions.append("premium set to 0 (was negative)")

    # ── Suspicious: zero OI but high premium ──────────────────────────
    if cleaned["oi"] == 0 and cleaned["premium"] > 0:
        anomaly_flags.append("zero_oi_with_premium")

    # ── Expiry validation ─────────────────────────────────────────────
    if not expiry:
        anomaly_flags.append("expiry_missing")

    # ── Assemble result ───────────────────────────────────────────────
    logger.debug(
        "Options snapshot cleaned",
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
