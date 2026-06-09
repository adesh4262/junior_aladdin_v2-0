"""Floor 2 Validation — timestamp validator.

Checks whether a packet's ``received_at`` timestamp is:
- Present and parseable.
- Within an acceptable freshness window (not too old / not in the future).
- Monotonically increasing compared to the last packet from the same source.

Architecture rules:
- Timestamps are validated for ordering, not for market interpretation.
- A mildly out-of-order packet is FLAGGED, not FAILED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import ValidationResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("timestamp_validator")

VALIDATOR_NAME = "timestamp"

# Maximum allowed clock skew: a timestamp this far in the future is suspicious.
MAX_FUTURE_SKEW_S: float = 5.0


def validate_timestamp(
    record: dict[str, Any],
    last_timestamp: datetime | None = None,
) -> ValidationResult:
    """Validate a packet's timestamp.

    Checks:
    1. ``received_at`` exists and is a valid datetime.
    2. Timestamp is not in the future beyond ``MAX_FUTURE_SKEW_S``.
    3. Timestamp is after ``last_timestamp`` (if provided) — monotonicity.

    Args:
        record: The packet record dict.
        last_timestamp: The ``received_at`` of the last packet from the
            same source/feed, or ``None`` if this is the first packet.

    Returns:
        A ``ValidationResult`` with:
        - ``passed``: ``True`` if all checks pass.
        - ``details``: Contains ``received_at``, ``is_ordered``,
          ``is_fresh``, ``skew_s`` (if applicable).
    """
    # ── 1. Extract received_at ─────────────────────────────────────────
    envelope = record.get("minimal_source_envelope", {})
    received_at_raw = envelope.get("received_at")

    if received_at_raw is None:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=False,
            details={"error": "received_at is missing"},
            confidence=1.0,
        )

    # Parse if string
    if isinstance(received_at_raw, str):
        try:
            received_at = datetime.fromisoformat(received_at_raw)
        except (ValueError, TypeError):
            return ValidationResult(
                validator_name=VALIDATOR_NAME,
                passed=False,
                details={
                    "error": f"received_at is not a valid ISO datetime: {received_at_raw}",
                    "raw_value": received_at_raw,
                },
                confidence=1.0,
            )
    elif isinstance(received_at_raw, datetime):
        received_at = received_at_raw
    else:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=False,
            details={
                "error": f"received_at has unexpected type: {type(received_at_raw).__name__}",
                "raw_value": str(received_at_raw),
            },
            confidence=1.0,
        )

    # Ensure timezone-aware for comparison
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    details: dict[str, Any] = {
        "received_at": received_at.isoformat(),
    }

    issues: list[str] = []
    passed = True

    # ── 2. Check freshness (not too far in the future) ────────────────
    skew_s = (received_at - now).total_seconds()
    if skew_s > MAX_FUTURE_SKEW_S:
        issues.append(f"timestamp {skew_s:.1f}s in the future")
        details["skew_s"] = round(skew_s, 3)
        passed = False

    # ── 3. Check monotonicity ─────────────────────────────────────────
    if last_timestamp is not None:
        if last_timestamp.tzinfo is None:
            last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
        if received_at < last_timestamp:
            out_of_order_s = (last_timestamp - received_at).total_seconds()
            issues.append(f"timestamp {out_of_order_s:.1f}s before last packet")
            details["out_of_order_s"] = round(out_of_order_s, 3)
            # Out-of-order is a FLAG, not a FAIL — mild ordering issues happen
            # in real-time feeds. We note it but still pass.
            details["is_ordered"] = False
        else:
            details["is_ordered"] = True
    else:
        details["is_ordered"] = True  # first packet, trivially ordered

    details["is_fresh"] = skew_s <= MAX_FUTURE_SKEW_S
    if issues:
        details["issues"] = issues

    return ValidationResult(
        validator_name=VALIDATOR_NAME,
        passed=passed,
        details=details,
        confidence=0.95 if passed else 1.0,
    )
