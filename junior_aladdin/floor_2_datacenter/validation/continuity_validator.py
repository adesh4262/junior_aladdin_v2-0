"""Floor 2 Validation — continuity validator.

Checks for gaps in a packet stream by comparing timestamps against the
last packet from the same source+feed_type.

Architecture rules:
- Continuity is about data completeness, NOT trading conditions.
- Gaps are quantified (minor vs major) but never interpreted as trade signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    ContinuityStatus,
    ValidationResult,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("continuity_validator")

VALIDATOR_NAME = "continuity"

# Default gap thresholds
MAJOR_GAP_S: float = 60.0   # gaps >= 60s are MAJOR
MINOR_GAP_S: float = 5.0    # gaps >= 5s are MINOR


def validate_continuity(
    record: dict[str, Any],
    last_timestamp: datetime | None = None,
    feed_type: str | None = None,
) -> ValidationResult:
    """Check for gaps in packet continuity.

    Compares the current packet's ``received_at`` against the last packet's
    timestamp (from the same source+feed_type). If the gap exceeds configured
    thresholds, it is flagged.

    Args:
        record: The packet record dict.
        last_timestamp: The ``received_at`` of the last packet from the
            same source+feed_type, or ``None`` if this is the first packet.
        feed_type: The feed type of the packet (for tier-appropriate
            threshold configuration).

    Returns:
        A ``ValidationResult`` with:
        - ``passed``: ``True`` if no major gap detected.
        - ``details``: Contains ``gap_s``, ``continuity_status``,
          ``last_timestamp``, ``current_timestamp``.
    """
    envelope = record.get("minimal_source_envelope", {})
    received_at_raw = envelope.get("received_at")

    if received_at_raw is None:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=True,  # Can't check continuity without a timestamp — not a failure
            details={"error": "received_at missing — cannot check continuity"},
            confidence=0.5,
        )

    # Parse the current timestamp
    if isinstance(received_at_raw, str):
        try:
            current_ts = datetime.fromisoformat(received_at_raw)
        except (ValueError, TypeError):
            return ValidationResult(
                validator_name=VALIDATOR_NAME,
                passed=True,
                details={"error": f"Cannot parse received_at: {received_at_raw}"},
                confidence=0.5,
            )
    elif isinstance(received_at_raw, datetime):
        current_ts = received_at_raw
    else:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=True,
            details={"error": f"Unexpected received_at type: {type(received_at_raw).__name__}"},
            confidence=0.5,
        )

    if current_ts.tzinfo is None:
        current_ts = current_ts.replace(tzinfo=timezone.utc)

    # ── First packet — trivially no gap ────────────────────────────────
    if last_timestamp is None:
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=True,
            details={
                "first_packet": True,
                "continuity_status": ContinuityStatus.GOOD.value,
                "current_timestamp": current_ts.isoformat(),
            },
            confidence=1.0,
        )

    if last_timestamp.tzinfo is None:
        last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)

    # ── Compute gap ────────────────────────────────────────────────────
    gap_s = (current_ts - last_timestamp).total_seconds()

    if gap_s < 0:
        # Out-of-order — handled by timestamp_validator, not here
        return ValidationResult(
            validator_name=VALIDATOR_NAME,
            passed=True,
            details={
                "gap_s": round(gap_s, 3),
                "continuity_status": ContinuityStatus.GOOD.value,
                "reversed": True,
                "note": "Packet is older than the last — out of order, not a gap",
                "last_timestamp": last_timestamp.isoformat(),
                "current_timestamp": current_ts.isoformat(),
            },
            confidence=0.9,
        )

    # Classify the gap
    if gap_s >= MAJOR_GAP_S:
        status = ContinuityStatus.MAJOR_GAP
        passed = False
    elif gap_s >= MINOR_GAP_S:
        status = ContinuityStatus.MINOR_GAP
        passed = True  # Minor gaps are acceptable but noted
    else:
        status = ContinuityStatus.GOOD
        passed = True

    if not passed:
        logger.warning(
            "Major continuity gap detected",
            extra={
                "gap_s": round(gap_s, 1),
                "feed_type": feed_type,
                "continuity_status": status.value,
            },
        )

    return ValidationResult(
        validator_name=VALIDATOR_NAME,
        passed=passed,
        details={
            "gap_s": round(gap_s, 3),
            "continuity_status": status.value,
            "last_timestamp": last_timestamp.isoformat(),
            "current_timestamp": current_ts.isoformat(),
        },
        confidence=0.95 if passed else 1.0,
    )
