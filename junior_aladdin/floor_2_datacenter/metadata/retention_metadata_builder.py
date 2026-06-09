"""Floor 2 Metadata — retention metadata builder.

Builds retention metadata summaries from storage statistics and retention
policies. Provides a factual overview of the raw data store health and
retention state.

Architecture rules:
- Retention metadata is FACTUAL — counts, sizes, and policy summaries only.
- No decision-making about what to retain — that belongs to the retention
  manager's ``purge_expired()`` method.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import TransformStage
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.raw.original_raw_store import OriginalRawStore
from junior_aladdin.floor_2_datacenter.raw.raw_retention_manager import (
    RawRetentionManager,
)
from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("retention_metadata_builder")


def build_retention_summary(
    original_store: OriginalRawStore,
    normalized_store: NormalizedRawStore,
    cleaned_writer: CleanedLayerWriter,
    structured_writer: StructuredWriter,
    retention_manager: RawRetentionManager,
) -> dict[str, Any]:
    """Build a comprehensive retention metadata summary.

    Args:
        original_store: The original raw store instance.
        normalized_store: The normalised raw store instance.
        cleaned_writer: The cleaned layer writer instance.
        structured_writer: The structured writer instance.
        retention_manager: The raw retention manager instance.

    Returns:
        A dict with storage counts, policy summaries, and expiry info.
    """
    now = datetime.now(timezone.utc)

    # ── Storage counts per layer ──────────────────────────────────────
    original_count = original_store.count
    normalized_count = normalized_store.count
    cleaned_count = cleaned_writer.count
    structured_count = structured_writer.count

    # ── Expiry counts ─────────────────────────────────────────────────
    original_expired = len(retention_manager.get_expired_ids(original_store))
    normalized_expired = len(retention_manager.get_expired_ids(normalized_store))

    # ── Feed type distribution ────────────────────────────────────────
    original_feed_types = sorted(original_store.feed_types)
    normalized_feed_types = sorted(normalized_store.feed_types)
    cleaned_feed_types = sorted(cleaned_writer.feed_types)

    # ── Transform stage distribution (from normalized store) ──────────
    stage_counts: dict[str, int] = {}
    for stage in TransformStage:
        stage_counts[stage.value] = 0
    for pid in normalized_store.packet_ids:
        record = normalized_store.get(pid)
        if record:
            stage_str = record.get("transform_stage", "RAW")
            if stage_str in stage_counts:
                stage_counts[stage_str] += 1

    # ── Retention policies ────────────────────────────────────────────
    policy_report = retention_manager.report_policies()

    summary = {
        "timestamp": now.isoformat(),
        "storage": {
            "original_raw": {
                "count": original_count,
                "expired_count": original_expired,
                "feed_types": original_feed_types,
            },
            "normalized_raw": {
                "count": normalized_count,
                "expired_count": normalized_expired,
                "feed_types": normalized_feed_types,
                "stage_distribution": stage_counts,
            },
            "cleaned": {
                "count": cleaned_count,
                "feed_types": cleaned_feed_types,
            },
            "structured": {
                "count": structured_count,
                "stream_types": sorted(structured_writer.stream_types),
            },
        },
        "retention_policies": policy_report,
        "total_packets": original_count + normalized_count + cleaned_count,
    }

    logger.info(
        "Retention summary built",
        extra={
            "total_packets": summary["total_packets"],
            "expired_original": original_expired,
            "expired_normalized": normalized_expired,
        },
    )

    return summary


def build_feed_storage_report(
    normalized_store: NormalizedRawStore,
    feed_type: str,
) -> dict[str, Any]:
    """Build a per-feed-type storage report.

    Args:
        normalized_store: The normalised raw store instance.
        feed_type: The feed type to report on.

    Returns:
        A dict with packet count, stage breakdown, and storage time range.
    """
    records = normalized_store.query(feed_type=feed_type)
    count = len(records)

    # Stage breakdown
    stage_breakdown: dict[str, int] = {}
    timestamps: list[datetime] = []

    for r in records:
        stage_str = r.get("transform_stage", "RAW")
        stage_breakdown[stage_str] = stage_breakdown.get(stage_str, 0) + 1
        ts = r.get("stored_at") or r.get("ingested_at")
        if ts:
            timestamps.append(ts)

    return {
        "feed_type": feed_type,
        "packet_count": count,
        "stage_breakdown": stage_breakdown,
        "oldest_packet": min(timestamps).isoformat() if timestamps else None,
        "newest_packet": max(timestamps).isoformat() if timestamps else None,
    }
