"""Floor 2 Ingress — source envelope builder.

Normalises a Floor 1 5-family handoff payload into a :class:`Floor2IngestPayload`
with ingest metadata (ingested_at, ingest_batch_id).

Architecture rules:
- ADDITIVE only: no Floor 1 fields are ever removed or modified.
- Validation is performed at the envelope level (mandatory key presence).
- Raw contents of each family are preserved verbatim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    Floor2IngestPayload,
    validate_floor1_payload,
    validate_source_envelope,
)
from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.floor_1_connection.shared_utils import generate_connection_id

logger = get_logger("source_envelope_builder")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_source_envelope(floor1_payload: dict[str, Any]) -> Floor2IngestPayload:
    """Normalise a Floor 1 5-family payload into a ``Floor2IngestPayload``.

    Args:
        floor1_payload: The incoming 5-family dict from Floor 1.

    Returns:
        A fully populated ``Floor2IngestPayload`` with ingest metadata.

    Raises:
        ValidationError: If mandatory Floor 1 keys or source-envelope keys
            are missing.
    """
    # ── 1. Validate top-level 5-family keys ──────────────────────────────
    missing = validate_floor1_payload(floor1_payload)
    if missing:
        msg = f"Floor 1 payload missing mandatory keys: {missing}"
        logger.error(msg, extra={"missing_keys": missing})
        raise ValidationError(msg, details={"missing_keys": missing})

    # ── 2. Validate source envelope sub-keys ─────────────────────────────
    source_envelope: dict[str, Any] = floor1_payload.get("minimal_source_envelope", {})
    missing_env = validate_source_envelope(source_envelope)
    if missing_env:
        msg = f"Source envelope missing mandatory fields: {missing_env}"
        logger.error(msg, extra={"missing_fields": missing_env})
        raise ValidationError(msg, details={"missing_fields": missing_env})

    # ── 3. Add ingest metadata ──────────────────────────────────────────
    ingested_at = datetime.now(timezone.utc)
    ingest_batch_id = _generate_batch_id()

    payload = Floor2IngestPayload(
        original_raw_packet=floor1_payload.get("original_raw_packet", {}),
        minimal_source_envelope=source_envelope,
        feed_routing_identity=floor1_payload.get("feed_routing_identity", ""),
        source_health_facts=floor1_payload.get("source_health_facts", {}),
        manual_source_tags=floor1_payload.get("manual_source_tags"),
        ingested_at=ingested_at,
        ingest_batch_id=ingest_batch_id,
    )

    logger.info(
        "Source envelope built",
        extra={
            "feed_routing_identity": payload.feed_routing_identity,
            "ingest_batch_id": ingest_batch_id,
            "source": source_envelope.get("source"),
        },
    )

    return payload


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_batch_id() -> str:
    """Generate a unique ingest batch identifier."""
    return f"ig_{generate_connection_id()}"
