"""Floor 2 Metadata — source trace builder.

Builds ``SourceTrace`` dataclasses that capture source lineage through
pipeline stages for a single packet.

Enables answering:
- ``Where did this packet come from?``
- ``What stage did it pass through?``
- ``What is its current transform stage?``

Architecture rules:
- Lineage is FACTUAL — timestamps, source names, and stage labels only.
- ``transform_stage`` is pulled from the record's stored value
  (``NormalizedRawStore`` tracks this per packet).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import SourceTrace, TransformStage


def build_source_trace(
    record: dict[str, Any],
    source: str | None = None,
    fetched_at: datetime | None = None,
    validated_at: datetime | None = None,
    review_status: str = "PENDING",
    transform_stage: TransformStage = TransformStage.RAW,
) -> SourceTrace:
    """Build a ``SourceTrace`` from a raw store record.

    Args:
        record: A record dict from ``NormalizedRawStore.get()`` or similar.
        source: Override source name. If ``None``, read from record.
        fetched_at: When the source data was fetched. If ``None``, read
            from record's ``ingested_at`` or ``stored_at``.
        validated_at: When validation completed. ``None`` if not yet validated.
        review_status: Current review status (default ``\"PENDING\"``).
        transform_stage: Current pipeline stage (default ``RAW``).

    Returns:
        A ``SourceTrace`` instance.
    """
    actual_source = source or str(record.get("source", "unknown"))

    # Determine fetched_at from available timestamps
    if fetched_at is None:
        fetched_at = record.get("ingested_at") or record.get("stored_at")

    # Read transform_stage from record if available
    stage_str = record.get("transform_stage")
    if stage_str is not None:
        try:
            transform_stage = TransformStage(stage_str)
        except (ValueError, TypeError):
            transform_stage = TransformStage.RAW

    # Read review_status from record if available
    actual_review_status = record.get("review_status", review_status)

    return SourceTrace(
        source=actual_source,
        fetched_at=fetched_at,
        validated_at=validated_at,
        review_status=actual_review_status,
        transform_stage=transform_stage,
    )


def build_source_trace_batch(
    records: list[dict[str, Any]],
    default_stage: TransformStage = TransformStage.RAW,
) -> list[SourceTrace]:
    """Build ``SourceTrace`` for a batch of records.

    Args:
        records: List of record dicts.
        default_stage: Default transform stage if not recorded.

    Returns:
        List of ``SourceTrace`` instances.
    """
    return [
        build_source_trace(r, transform_stage=default_stage)
        for r in records
    ]
