"""Floor 2 Validation — schema validator.

Checks a packet's raw data fields against the expected schema defined
in the Data Contract Registry (``FeedContract.schema_fields``).

Architecture rules:
- Schemas are defined in contracts, not hardcoded here.
- Unknown feed types pass with reduced confidence (no schema to validate).
- Missing fields are flagged, not necessarily failed — the caller decides.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import default_feed_contracts
from junior_aladdin.floor_2_datacenter.datacenter_types import ValidationResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("schema_validator")

VALIDATOR_NAME = "schema"


def validate_schema(
    record: dict[str, Any],
) -> ValidationResult:
    """Validate a packet's raw data against its expected feed schema.

    Looks up the ``FeedContract`` for the packet's feed type, then checks
    that all expected fields exist in the ``original_raw_packet``.

    Args:
        record: The packet record dict (from ``NormalizedRawStore.get()``).

    Returns:
        A ``ValidationResult`` with:
        - ``passed``: ``True`` if all expected fields are present.
        - ``details``: Contains ``missing_fields``, ``extra_fields``,
          ``expected_fields``, ``feed_type``.
    """
    feed_type = record.get("feed_type", "unknown")
    raw_data = record.get("original_raw_packet", {})

    # ── Find the contract for this feed type ───────────────────────────
    contracts = default_feed_contracts()
    contract = None
    for c in contracts:
        if c.name == feed_type:
            contract = c
            break

    if contract is None:
        # No schema on record — pass with reduced confidence
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=True,
            details={
                "feed_type": feed_type,
                "note": "No contract found for this feed type — schema not validated",
            },
            confidence=0.5,
        )

    expected_fields = set(contract.schema_fields.keys())
    actual_fields = set(raw_data.keys())

    missing = expected_fields - actual_fields
    extra = actual_fields - expected_fields

    details: dict[str, Any] = {
        "feed_type": feed_type,
        "expected_fields": sorted(expected_fields),
        "actual_fields": sorted(actual_fields),
        "missing_fields": sorted(missing),
        "extra_fields": sorted(extra),
    }

    if missing:
        logger.warning(
            "Schema validation failed — missing fields",
            extra={
                "feed_type": feed_type,
                "missing_fields": sorted(missing),
            },
        )
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=False,
            details=details,
            confidence=1.0,
        )

    return ValidationResult(
        validator_name=VALIDATOR_NAME,
        passed=True,
        details=details,
        confidence=1.0,
    )
