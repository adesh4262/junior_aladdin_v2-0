"""Floor 2 Metadata — packet metadata builder.

Builds ``PacketMetadata`` dataclasses from raw store records or cleaned
entries. Provides packet-level metadata for dashboard debugging,
traceability, and replay.

Architecture rules:
- Packet metadata is FACTUAL — size, source, type, and timing only.
- No interpretation, no quality judgment at this level.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import PacketMetadata


def build_packet_metadata(
    record: dict[str, Any],
    estimate_size: bool = True,
) -> PacketMetadata:
    """Build a ``PacketMetadata`` from a raw store or cleaned writer record.

    Args:
        record: A dict from ``NormalizedRawStore.get()``,
            ``OriginalRawStore.get()``, or ``CleanedLayerWriter.get()``.
            Must contain at least ``packet_id``, ``source``, and
            ``feed_type``.
        estimate_size: Whether to estimate ``packet_size_bytes`` from the
            raw data. Default ``True``.

    Returns:
        A fully populated ``PacketMetadata`` instance.
    """
    packet_id = str(record.get("packet_id", "unknown"))
    source = str(record.get("source", "unknown"))
    feed_type = str(record.get("feed_type", "unknown"))

    # Extract received_at from envelope (for raw records) or from stored data
    envelope = record.get("minimal_source_envelope", {})
    received_at = envelope.get("received_at") if envelope else None
    if received_at is None:
        received_at = record.get("ingested_at")

    # Estimate packet size from the raw data
    packet_size_bytes = 0
    if estimate_size:
        raw_data = record.get("original_raw_packet", {})
        if raw_data:
            packet_size_bytes = _estimate_size(raw_data)
        else:
            # Try cleaned data
            cleaned = record.get("cleaned_data", {})
            if cleaned:
                packet_size_bytes = _estimate_size(cleaned)

    return PacketMetadata(
        packet_id=packet_id,
        source=source,
        feed_type=feed_type,
        received_at=received_at,
        packet_size_bytes=packet_size_bytes,
    )


def build_packet_metadata_batch(
    records: list[dict[str, Any]],
) -> list[PacketMetadata]:
    """Build ``PacketMetadata`` for a batch of records.

    Args:
        records: List of record dicts.

    Returns:
        List of ``PacketMetadata`` instances.
    """
    return [build_packet_metadata(r) for r in records]


def _estimate_size(data: dict[str, Any]) -> int:
    """Estimate the byte size of a dict by serialising to string length.

    This is a fast approximation, not an exact byte count.
    """
    try:
        return len(str(data))
    except Exception:
        return 0
