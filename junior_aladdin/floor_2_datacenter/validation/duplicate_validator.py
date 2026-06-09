"""Floor 2 Validation — duplicate validator.

Checks whether a packet's ``packet_id`` already exists in the normalised
raw store, indicating a duplicate ingress.

Architecture rules:
- Duplicate governance belongs to Floor 2 (truth layer), not Floor 1.
- Duplicates are flagged — the caller decides whether to reject, isolate,
  or route according to validation contracts.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import ValidationResult
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("duplicate_validator")

VALIDATOR_NAME = "duplicate"


def validate_duplicate(
    record: dict[str, Any],
    normalized_store: NormalizedRawStore,
) -> ValidationResult:
    """Check whether a packet is a duplicate of one already stored.

    Looks up the packet's ``packet_id`` in the normalised raw store.
    If a record with that ID already exists, the packet is flagged as a
    duplicate.

    Args:
        record: The packet record dict (from ``NormalizedRawStore.get()``).
        normalized_store: The normalised raw store to check against.

    Returns:
        A ``ValidationResult`` with:
        - ``passed``: ``True`` if no duplicate found, ``False`` if duplicate.
        - ``details``: ``{\"is_duplicate\": bool, \"existing_record\": ...}``.
    """
    packet_id = record.get("packet_id", "")
    if not packet_id:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=False,
            details={"is_duplicate": False, "reason": "No packet_id in record"},
            confidence=1.0,
        )

    existing = normalized_store.get(packet_id)

    if existing is not None:
        logger.warning(
            "Duplicate packet detected",
            extra={"packet_id": packet_id},
        )
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=False,
            details={
                "is_duplicate": True,
                "packet_id": packet_id,
            },
            confidence=1.0,
        )

    return ValidationResult(
        validator_name=VALIDATOR_NAME,
        passed=True,
        details={"is_duplicate": False, "packet_id": packet_id},
        confidence=1.0,
    )
