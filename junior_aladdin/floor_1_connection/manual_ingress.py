"""Manual ingress lane for Floor 1.

Handles manually entered calendar events, overrides, and special inputs.
Every manual packet receives the same PacketEnvelope treatment as live data.

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import PacketEnvelope

from junior_aladdin.floor_1_connection.packet_envelope import build_envelope

logger = get_logger("manual_ingress")

# Allowed manual event types
MANUAL_CALENDAR = "MANUAL_CALENDAR"
MANUAL_EVENT = "MANUAL_EVENT"
MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {MANUAL_CALENDAR, MANUAL_EVENT, MANUAL_OVERRIDE}
)


def create_manual_packet(
    event_type: str,
    data: dict[str, Any],
    source_tag: str,
    connection_id: str,
    source_timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Create an envelope-ready manual ingress packet.

    Validates the event type, wraps the data with manual metadata, and
    returns a dict ready for :func:`build_envelope` wrapping.

    Args:
        event_type: One of ``MANUAL_CALENDAR``, ``MANUAL_EVENT``,
            or ``MANUAL_OVERRIDE``.
        data: Event details payload.
        source_tag: Manual source identifier (e.g., ``"operator"``,
            ``"admin"``, ``"system"``).
        connection_id: Active connection identifier to associate with
            this manual packet.
        source_timestamp: Optional timestamp from the source/provider.

    Returns:
        An envelope-ready dict with:
        - ``source`` = ``"manual"``
        - ``feed_type`` = ``event_type`` (e.g. ``"MANUAL_CALENDAR"``)
        - ``manual_source_tag`` = ``source_tag``
        - ``payload`` = ``data``

    Raises:
        ValidationError: If ``event_type`` is not one of the 3 valid types.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValidationError(
            f"Invalid manual event_type '{event_type}'. "
            f"Must be one of {', '.join(sorted(VALID_EVENT_TYPES))}."
        )

    envelope_ready = {
        "source": "manual",
        "feed_type": event_type,
        "manual_source_tag": source_tag,
        "payload": data.copy() if data else {},
    }

    logger.info(
        "Manual packet created",
        extra={
            "event_type": event_type,
            "source_tag": source_tag,
            "connection_id": connection_id,
        },
    )

    return envelope_ready


def build_manual_envelope(
    event_type: str,
    data: dict[str, Any],
    source_tag: str,
    connection_id: str,
    source_timestamp: datetime | None = None,
) -> PacketEnvelope:
    """Convenience: create a manual packet AND wrap it in a PacketEnvelope.

    Equivalent to::

        packet = create_manual_packet(...)
        return build_envelope(
            raw_payload=packet["payload"],
            source=packet["source"],
            feed_type=packet["feed_type"],
            connection_id=connection_id,
            source_timestamp=source_timestamp,
        )

    Validation, logging, and governance are identical to
    :func:`create_manual_packet`.
    """
    packet = create_manual_packet(
        event_type=event_type,
        data=data,
        source_tag=source_tag,
        connection_id=connection_id,
        source_timestamp=source_timestamp,
    )

    envelope = build_envelope(
        raw_payload=packet["payload"],
        source=packet["source"],
        feed_type=packet["feed_type"],
        connection_id=connection_id,
        source_timestamp=source_timestamp,
    )

    # Attach manual source tag metadata to the envelope payload
    # so downstream consumers (Floor 2 handoff) can distinguish manual packets.
    envelope.payload["manual_source_tag"] = source_tag

    return envelope
