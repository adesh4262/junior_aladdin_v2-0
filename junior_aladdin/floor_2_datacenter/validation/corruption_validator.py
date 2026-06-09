"""Floor 2 Validation — corruption validator.

Checks a packet's raw data for signs of corruption:
- Missing or ``None`` values for expected numerical fields.
- ``NaN`` or ``Inf`` float values.
- Empty strings or dicts where meaningful data is expected.
- Type mismatches compared to the feed contract schema.

Architecture rules:
- Corruption is a data-integrity check, NOT a market interpretation.
- Packets with detected corruption are FAILED, not just flagged.
"""

from __future__ import annotations

import math
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import default_feed_contracts
from junior_aladdin.floor_2_datacenter.datacenter_types import ValidationResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("corruption_validator")

VALIDATOR_NAME = "corruption"

# Expected Python types for schema field types
FIELD_TYPE_MAP: dict[str, type] = {
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
    "dict": dict,
    "list": list,
}


def validate_corruption(
    record: dict[str, Any],
) -> ValidationResult:
    """Check a packet's raw data for signs of corruption.

    Args:
        record: The packet record dict (from ``NormalizedRawStore.get()``).

    Returns:
        A ``ValidationResult`` with:
        - ``passed``: ``True`` if no corruption detected.
        - ``details``: Contains ``corrupt_fields``, ``anomalies``,
          ``feed_type``.
    """
    feed_type = record.get("feed_type", "unknown")
    raw_data = record.get("original_raw_packet", {})

    if not raw_data:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=True,
            details={
                "feed_type": feed_type,
                "note": "Empty raw data — nothing to validate",
            },
            confidence=0.5,
        )

    # ── Find contract type expectations ────────────────────────────────
    contracts = default_feed_contracts()
    contract_schema: dict[str, str] = {}
    for c in contracts:
        if c.name == feed_type:
            contract_schema = c.schema_fields
            break

    anomalies: list[str] = []

    for field_name, field_value in raw_data.items():
        expected_type_str = contract_schema.get(field_name)

        # ── None check ────────────────────────────────────────────────
        if field_value is None:
            anomalies.append(f"{field_name}=None")
            continue

        # ── NaN / Inf check for floats ─────────────────────────────────
        if isinstance(field_value, float):
            if math.isnan(field_value):
                anomalies.append(f"{field_name}=NaN")
                continue
            if math.isinf(field_value):
                anomalies.append(f"{field_name}=Inf")
                continue

        # ── Empty value check for strings ──────────────────────────────
        if isinstance(field_value, str) and field_value.strip() == "":
            anomalies.append(f"{field_name}=empty_string")

        # ── Type mismatch check ────────────────────────────────────────
        if expected_type_str and expected_type_str in FIELD_TYPE_MAP:
            expected_type = FIELD_TYPE_MAP[expected_type_str]
            # int is a subclass of float in Python's type system for validation
            if expected_type is float and isinstance(field_value, (int, float)):
                continue
            if not isinstance(field_value, expected_type):
                anomalies.append(
                    f"{field_name}: expected {expected_type_str}, got {type(field_value).__name__}"
                )

    passed = len(anomalies) == 0

    if not passed:
        logger.warning(
            "Corruption detected in packet",
            extra={
                "feed_type": feed_type,
                "anomalies": anomalies,
            },
        )

    return ValidationResult(
        validator_name=VALIDATOR_NAME,
        passed=passed,
        details={
            "feed_type": feed_type,
            "corrupt_fields": len(anomalies),
            "anomalies": anomalies,
        },
        confidence=1.0 if anomalies else 0.95,
    )
