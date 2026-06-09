"""Side C Memory Layer — controlled ingress for all inbound events.

Every event entering Side C passes through this layer.  The ingest layer
validates emitter identity, family authorisation, and event schema before
normalising into a MemoryEnvelope and forwarding to the event router.

Architecture rules (LOCKED):
- Accept events ONLY from approved emitters (Floor 1, Floor 2, Floor 5, Side A).
- Validate emitter identity against emitter_registry.py.
- Validate event family is allowed for that emitter.
- Validate event schema against write_contracts.py.
- Apply MemoryEnvelope normalisation.
- Forward to event_router.
- Reject unauthorised emitters with logged error (no crash).
- Reject malformed events with logged error (Severity.CAUTION).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from junior_aladdin.shared.errors import MemoryError
from junior_aladdin.shared.logging import get_logger, severity_to_log_level
from junior_aladdin.shared.types import Severity
from junior_aladdin.side_c_memory.c_types import EventFamily, MemoryEnvelope
from junior_aladdin.side_c_memory.contracts.emitter_registry import (
    family_allowed_for_emitter,
    get_allowed_families,
    is_emitter_approved,
)
from junior_aladdin.side_c_memory.contracts.write_contracts import (
    validate_event_for_family,
)

logger = get_logger(__name__)


# =============================================================================
# Event router callback
# =============================================================================

#: Optional callback forwarded to after successful ingestion.
#: Set by :func:`set_event_router` once event_router.py is built (Step 3.4).
#: The callback may return a value (e.g. store name); ingest_layer ignores it.
_event_router_callback: Callable[[MemoryEnvelope], object] | None = None


def set_event_router(callback: Callable[[MemoryEnvelope], object] | None) -> None:
    """Connect the event router to the ingest layer.

    The router callback is invoked with the normalised ``MemoryEnvelope``
    after every successful ingestion.  Set to ``None`` to disconnect.

    Args:
        callback: A callable that accepts a ``MemoryEnvelope``, or
            ``None`` to clear the router.
    """
    global _event_router_callback
    _event_router_callback = callback
    if callback is not None:
        logger.info("Event router connected to ingest layer")
    else:
        logger.info("Event router disconnected from ingest layer")


# =============================================================================
# Public API
# =============================================================================


def ingest_event(
    event_data: dict[str, Any],
    emitter_id: str,
) -> MemoryEnvelope:
    """Ingest a raw event into Side C.

    Validates the emitter, event family, and event data against the
    registered contracts, normalises a ``MemoryEnvelope``, forwards
    to the event router, and returns the envelope.

    Args:
        event_data: Raw event data dict.  Must contain at minimum:
            ``event_type``, ``source``, ``emitter``, ``timestamp``,
            ``severity``, ``family``, and ``payload``.
        emitter_id: Approved emitter ID from the emitter registry
            (e.g. ``"floor_1"``, ``"side_a"``).

    Returns:
        Normalised ``MemoryEnvelope`` with a unique ``envelope_id``.

    Raises:
        ValueError: If the emitter is not approved, the family is not
            allowed, or the event data fails write-contract validation.
        MemoryError: If an unrecoverable system error occurs during
            processing.
    """
    # ── 1. Validate emitter identity ──────────────────────────────────
    if not is_emitter_approved(emitter_id):
        logger.warning(
            "Ingest rejected — unknown emitter",
            extra={"emitter_id": emitter_id},
        )
        raise ValueError(
            f"Unauthorised emitter: {emitter_id!r}. "
            f"Emitter is not registered in the approved emitter list."
        )

    # ── 2. Parse event family from raw data ───────────────────────────
    raw_family = event_data.get("family", "")
    try:
        family = EventFamily(raw_family)
    except (ValueError, TypeError):
        logger.warning(
            "Ingest rejected — unknown family",
            extra={"emitter_id": emitter_id, "family": raw_family},
        )
        raise ValueError(
            f"Unknown event family: {raw_family!r}. "
            f"Must be one of {[f.value for f in EventFamily]}"
        )

    # ── 3. Validate family is allowed for this emitter ─────────────────
    if not family_allowed_for_emitter(emitter_id, family):
        logger.warning(
            "Ingest rejected — family not allowed for emitter",
            extra={
                "emitter_id": emitter_id,
                "family": family.value,
                "allowed_families": [
                    f.value for f in get_allowed_families(emitter_id)
                ],
            },
        )
        raise ValueError(
            f"Emitter {emitter_id!r} is not allowed to write "
            f"family {family.value!r}."
        )

    # ── 4. Validate event against write contract ──────────────────────
    is_valid, errors = validate_event_for_family(event_data, family)
    if not is_valid:
        log_severity = Severity.CAUTION
        logger.log(
            severity_to_log_level(log_severity),
            "Ingest rejected — write contract validation failed",
            extra={
                "emitter_id": emitter_id,
                "family": family.value,
                "errors": errors,
            },
        )
        raise ValueError(
            f"Event validation failed for family {family.value!r}: "
            f"{'; '.join(errors)}"
        )

    # ── 5. Parse timestamp ────────────────────────────────────────────
    raw_timestamp = event_data.get("timestamp", "")
    parsed_timestamp = _parse_timestamp(raw_timestamp)

    # ── 6. Parse severity ─────────────────────────────────────────────
    raw_severity = event_data.get("severity", "INFO")
    try:
        parsed_severity = Severity(raw_severity)
    except (ValueError, TypeError):
        parsed_severity = Severity.INFO

    # ── 7. Build MemoryEnvelope ───────────────────────────────────────
    envelope = MemoryEnvelope(
        family=family,
        event_type=event_data.get("event_type", ""),
        source=event_data.get("source", ""),
        emitter=emitter_id,
        timestamp=parsed_timestamp,
        severity=parsed_severity,
        refs=event_data.get("refs", {}),
        payload_ref="",  # filled by store after persisting
    )
    # envelope_id is auto-generated by MemoryEnvelope.__post_init__

    # ── 8. Forward to event router ────────────────────────────────────
    _forward_to_router(envelope)

    logger.info(
        "Event ingested successfully",
        extra={
            "envelope_id": envelope.envelope_id,
            "family": family.value,
            "emitter": emitter_id,
            "event_type": envelope.event_type,
        },
    )

    return envelope


# =============================================================================
# Internal helpers
# =============================================================================


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp string into a datetime.

    Args:
        raw: The raw timestamp value from the event data (typically str).

    Returns:
        A timezone-aware ``datetime`` in UTC, or ``None`` if parsing fails.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        # Try full ISO-8601 first
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        try:
            # Fallback: parse as UTC epoch timestamp
            secs = float(raw)
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            logger.warning("Failed to parse timestamp", extra={"raw": raw})
            return None


def _forward_to_router(envelope: MemoryEnvelope) -> None:
    """Forward a normalised envelope to the event router.

    If the router callback is not set, the envelope is logged and
    buffered (no crash).  This allows the ingest layer to be built
    and tested before the event router exists (Step 3.4).

    Args:
        envelope: The normalised ``MemoryEnvelope`` to forward.
    """
    if _event_router_callback is not None:
        _event_router_callback(envelope)
    else:
        logger.info(
            "Envelope forwarded (no router connected)",
            extra={
                "envelope_id": envelope.envelope_id,
                "family": envelope.family.value,
                "routing_hint": _get_routing_store_hint(envelope.family),
            },
        )


def _get_routing_store_hint(family: EventFamily) -> str:
    """Return the target store name for a given family.

    This duplicates the routing table from Step 3.4 and serves as a
    forward-compatibility hint until the event router is connected.

    Args:
        family: The event family to route.

    Returns:
        The store name (``"event_store"``, ``"journal_store"``, or
        ``"reference_store"``).
    """
    if family in (EventFamily.TRADE_JOURNAL, EventFamily.DECISION_JOURNAL):
        return "journal_store"
    if family in (EventFamily.REPLAY_REF, EventFamily.REVIEW_REF):
        return "reference_store"
    # EXECUTION_EVENT, HEALTH_EVENT, OVERRIDE, BLOCKED_ACTION
    return "event_store"
