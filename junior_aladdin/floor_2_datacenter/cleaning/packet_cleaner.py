"""Floor 2 Cleaning — general packet cleaner.

Cleans non-tick, non-options packets (macro, calendar, VIX, manual):
- Validates required field presence based on feed type.
- Normalises string/numerical field types.
- Removes packets with no usable data.
- Flags packets with incomplete but salvageable data.

Architecture rules:
- Cleaning is FACTUAL — removes glitches, does NOT interpret market meaning.
- Feed-type-agnostic: handles any packet by checking what fields exist.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import CleaningResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("packet_cleaner")

# Minimum required keys per feed type for a packet to be usable.
MINIMUM_REQUIRED_FIELDS: dict[str, list[str]] = {
    "vix_tick": ["value"],
    "macro_data": ["feed_type", "stub"],
    "calendar_event": ["feed_type", "stub"],
    "MANUAL_CALENDAR": ["payload"],
    "MANUAL_OVERRIDE": ["payload"],
    # Manual events from the manual ingress lane
    "MANUAL_EVENT": ["payload"],
}


def clean_packet(
    record: dict[str, Any],
) -> CleaningResult:
    """Clean a general (non-tick, non-options) packet.

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

    feed_type = record.get("feed_type", "unknown")
    packet_id = record.get("packet_id", "unknown")

    anomaly_flags: list[str] = []
    original_values: dict[str, Any] = {}
    repaired = False
    repair_actions: list[str] = []

    # ── Check minimum required fields ─────────────────────────────────
    required = MINIMUM_REQUIRED_FIELDS.get(feed_type, [])
    missing = [f for f in required if f not in raw_data]

    if missing:
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason=(
                f"Packet missing required fields for {feed_type}: {missing}"
            ),
            anomaly_flags=[f"missing_required_{'_'.join(missing)}"],
        )

    # ── Build cleaned record (preserve all original fields) ───────────
    cleaned = dict(raw_data)

    # Ensure feed_type is present in the cleaned record
    cleaned["feed_type"] = feed_type

    # ── VIX specific: ensure value is numeric ─────────────────────────
    if feed_type == "vix_tick" and "value" in cleaned:
        value = cleaned["value"]
        if not isinstance(value, (int, float)):
            anomaly_flags.append("value_not_numeric")
            original_values["value"] = value
            try:
                cleaned["value"] = float(value)
                repaired = True
                repair_actions.append("value coerced to float")
            except (ValueError, TypeError):
                cleaned["value"] = 0.0
                repaired = True
                repair_actions.append("value set to 0 (unparseable)")

    # ── Macro/Calendar: ensure stub is boolean ────────────────────────
    if feed_type in ("macro_data", "calendar_event") and "stub" in cleaned:
        stub = cleaned["stub"]
        if not isinstance(stub, bool):
            original_values["stub"] = stub
            cleaned["stub"] = bool(stub)
            repaired = True
            repair_actions.append("stub coerced to bool")

    # ── Manual: ensure payload is a dict ──────────────────────────────
    if feed_type.startswith("MANUAL_") and "payload" in cleaned:
        payload = cleaned["payload"]
        if not isinstance(payload, dict):
            anomaly_flags.append("payload_not_dict")
            original_values["payload"] = payload
            cleaned["payload"] = {}
            repaired = True
            repair_actions.append("payload set to {} (was not dict)")

    logger.debug(
        "Packet cleaned",
        extra={
            "packet_id": packet_id,
            "feed_type": feed_type,
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
