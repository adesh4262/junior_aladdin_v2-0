"""Floor 2 Structuring — options snapshot builder.

Builds ``OptionsSnapshotStream`` objects from cleaned options snapshot data.

Groups cleaned options_snapshot records by interval, producing structured
option snapshots with OI, premium, IV, and change-in-OI.

Architecture rules:
- Configurable snapshot interval (default 5 minutes).
- Each snapshot captures the state at the end of its interval.
- No trading interpretation of OI changes or IV levels.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    OptionsSnapshot,
    OptionsSnapshotStream,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType, StructureResult
from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("options_snapshot_builder")

DEFAULT_INTERVAL_MIN: int = 5


def build_options_snapshot_stream(
    cleaned_writer: CleanedLayerWriter,
    source: str | None = None,
    feed_type: str = "options_snapshot",
    interval_minutes: int = DEFAULT_INTERVAL_MIN,
    max_snapshots: int = 500,
) -> StructureResult:
    """Build an ``OptionsSnapshotStream`` from cleaned options records.

    Args:
        cleaned_writer: The cleaned layer writer to read from.
        source: Optional source filter.
        feed_type: Feed type (default ``\"options_snapshot\"``).
        interval_minutes: Snapshot interval in minutes (default 5).
        max_snapshots: Maximum snapshots to include.

    Returns:
        A ``StructureResult`` with ``stream_type=OPTIONS_SNAPSHOT``.
    """
    records = cleaned_writer.query(feed_type=feed_type, source=source)

    if not records:
        logger.info(
            "No cleaned options records found",
            extra={"feed_type": feed_type},
        )
        return StructureResult(
            stream_type=StreamType.OPTIONS_SNAPSHOT,
            stream_data=OptionsSnapshotStream(
                interval_minutes=interval_minutes,
            ),
            metadata={"feed_type": feed_type, "snapshot_count": 0},
        )

    # ── Group options data by interval bucket ─────────────────────────
    snapshots: list[OptionsSnapshot] = []
    # Track the latest snapshot per strike+option_type within each interval
    # bucket_key -> { (strike, option_type) -> latest_record }
    interval_data: dict[
        tuple[int, int, int, int, int],
        dict[tuple[float, str], dict[str, Any]],
    ] = defaultdict(dict)

    for entry in records:
        ts = _extract_timestamp(entry)
        if ts is None:
            continue

        cleaned = entry.get("cleaned_data", {})
        option_type = cleaned.get("option_type", "")
        strike = cleaned.get("strike", 0.0)

        # Round timestamp to nearest interval
        interval_min = (ts.minute // interval_minutes) * interval_minutes
        bucket_key = (ts.year, ts.month, ts.day, ts.hour, interval_min)
        strike_key = (float(strike), str(option_type))

        # Keep the most recent record for this strike+type in this interval
        current = interval_data[bucket_key].get(strike_key)
        if current is None:
            interval_data[bucket_key][strike_key] = cleaned
        else:
            # Replace with newer data (same bucket)
            current_ts = _extract_timestamp_value(current)
            new_ts = _extract_timestamp_value(cleaned)
            if new_ts and current_ts and new_ts > current_ts:
                interval_data[bucket_key][strike_key] = cleaned

    # ── Build snapshots ───────────────────────────────────────────────
    now = datetime.now(timezone.utc)

    for key in sorted(interval_data.keys()):
        if len(snapshots) >= max_snapshots:
            break

        year, month, day, hour, interval_min = key
        snapshot_time = datetime(year, month, day, hour, interval_min, tzinfo=timezone.utc)

        for strike_key, cleaned in interval_data[key].items():
            strike, option_type = strike_key

            snapshot = OptionsSnapshot(
                timestamp=snapshot_time,
                expiry=str(cleaned.get("expiry", "")),
                strike=strike,
                option_type=option_type,
                oi=int(cleaned.get("oi", 0)),
                premium=float(cleaned.get("premium", 0.0)),
                iv=float(cleaned.get("iv", 0.0)),
                change_in_oi=int(cleaned.get("change_in_oi", 0)),
            )
            snapshots.append(snapshot)

    # ── Build stream ──────────────────────────────────────────────────
    stream_id = (
        f"options_{interval_minutes}m_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )

    snapshot_stream = OptionsSnapshotStream(
        stream_id=stream_id,
        interval_minutes=interval_minutes,
        snapshots=snapshots,
    )

    logger.info(
        "Options snapshot stream built",
        extra={
            "stream_id": stream_id,
            "snapshot_count": len(snapshots),
            "interval_minutes": interval_minutes,
        },
    )

    return StructureResult(
        stream_type=StreamType.OPTIONS_SNAPSHOT,
        stream_data=snapshot_stream,
        metadata={
            "feed_type": feed_type,
            "source": source,
            "snapshot_count": len(snapshots),
            "interval_minutes": interval_minutes,
            "stream_id": stream_id,
        },
    )


def _extract_timestamp(entry: dict[str, Any]) -> datetime | None:
    """Extract a datetime from a cleaned writer entry."""
    cleaned = entry.get("cleaned_data", {})
    ts_raw = cleaned.get("timestamp")
    if not ts_raw:
        return None
    if isinstance(ts_raw, datetime):
        if ts_raw.tzinfo is None:
            return ts_raw.replace(tzinfo=timezone.utc)
        return ts_raw
    if isinstance(ts_raw, str):
        try:
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts
        except (ValueError, TypeError):
            return None
    return None


def _extract_timestamp_value(cleaned: dict[str, Any]) -> datetime | None:
    """Extract timestamp value from cleaned data for comparison."""
    ts_raw = cleaned.get("timestamp")
    if not ts_raw:
        return None
    if isinstance(ts_raw, datetime):
        return ts_raw
    if isinstance(ts_raw, str):
        try:
            return datetime.fromisoformat(ts_raw)
        except (ValueError, TypeError):
            return None
    return None
