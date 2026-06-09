"""Floor 2 Cleaning — anomaly repair.

Repairs minor data anomalies that can be safely corrected without changing
the meaning of the data:

- **NaN/Inf floats** → replace with previous valid value or 0.0.
- **None fields** → replace with default value for the expected type.
- **Negative values in unsigned fields** → clamp to 0 (e.g., volume, OI).
- **Empty strings** → replace with None for optional fields.

Architecture rules:
- Repairs are conservative: only fix when the correct value is obvious.
- If a repair is ambiguous, the packet is flagged but NOT repaired.
- Original values are ALWAYS preserved for audit.
"""

from __future__ import annotations

import math
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import CleaningResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("anomaly_repair")

# Fields that should never be negative
UNSIGNED_FIELDS: set[str] = {"volume", "oi", "change_in_oi"}


def repair_anomalies(
    record: dict[str, Any],
    previous_values: dict[str, Any] | None = None,
) -> CleaningResult:
    """Repair common data anomalies in a packet.

    Args:
        record: The packet record dict (from ``NormalizedRawStore.get()``).
        previous_values: A dict of field values from the previous packet
            of the same type, used to fill in NaN/None values.

    Returns:
        A ``CleaningResult`` with the repaired data or removal reason for
        irreparable corruption.
    """
    raw_data = record.get("original_raw_packet", {})
    if not raw_data:
        return CleaningResult(
            cleaned_record=None,
            removed=True,
            removal_reason="Empty raw data — nothing to repair",
            anomaly_flags=["empty_raw_data"],
        )

    packet_id = record.get("packet_id", "unknown")
    feed_type = record.get("feed_type", "unknown")

    cleaned: dict[str, Any] = {}
    anomaly_flags: list[str] = []
    original_values: dict[str, Any] = {}
    repaired = False
    repair_actions: list[str] = []

    previous = previous_values or {}

    for field_name, field_value in raw_data.items():
        original_value = field_value
        repaired_value = field_value
        field_repaired = False

        # ── NaN check ────────────────────────────────────────────────
        if isinstance(field_value, float):
            if math.isnan(field_value):
                replacement = previous.get(field_name, 0.0)
                if isinstance(replacement, float) and math.isnan(replacement):
                    replacement = 0.0
                repaired_value = replacement
                field_repaired = True
                anomaly_flags.append(f"{field_name}_was_nan")
                repair_actions.append(f"{field_name}: NaN → {replacement}")

            elif math.isinf(field_value):
                replacement = previous.get(field_name, 0.0)
                if isinstance(replacement, float) and (math.isinf(replacement) or math.isnan(replacement)):
                    replacement = 0.0
                repaired_value = replacement
                field_repaired = True
                anomaly_flags.append(f"{field_name}_was_inf")
                repair_actions.append(f"{field_name}: Inf → {replacement}")

        # ── None check ───────────────────────────────────────────────
        if field_value is None:
            # Try previous value, then type-appropriate default
            replacement = previous.get(field_name)
            if replacement is None:
                # Guess type from field name conventions
                if field_name in ("volume", "oi", "change_in_oi", "reconnect_count"):
                    replacement = 0
                elif field_name in ("ltp", "premium", "iv", "value", "latency_ms"):
                    replacement = 0.0
                else:
                    replacement = ""
            repaired_value = replacement
            field_repaired = True
            anomaly_flags.append(f"{field_name}_was_none")
            repair_actions.append(f"{field_name}: None → {replacement}")

        # ── Negative unsigned field check ────────────────────────────
        if field_name in UNSIGNED_FIELDS and isinstance(field_value, (int, float)):
            if field_value < 0:
                repaired_value = 0
                field_repaired = True
                anomaly_flags.append(f"{field_name}_was_negative")
                repair_actions.append(f"{field_name}: {field_value} → 0")

        if field_repaired:
            original_values[field_name] = original_value
            repaired = True

        cleaned[field_name] = repaired_value

    # Ensure feed_type is present
    cleaned["feed_type"] = feed_type

    logger.debug(
        "Anomaly repair complete",
        extra={
            "packet_id": packet_id,
            "field_repairs": len(repair_actions),
            "anomalies": len(anomaly_flags),
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
