"""Floor 2 Structuring — tick stream builder.

Builds structured ``TickStream`` objects from cleaned tick data.

Takes cleaned spot_tick records from ``CleanedLayerWriter`` and produces
a ``TickStream`` with sequential ordering, gap tracking, and per-tick
sequence IDs.

Architecture rules:
- Tick streams are ordered by timestamp, not by arrival order.
- Gaps are quantified (minor/major) but never interpreted as trade signals.
- Each tick gets a monotonically increasing ``sequence_id``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import TickStream, ValidatedTick
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType, StructureResult
from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("tick_stream_builder")

# Gap thresholds (seconds) for the tick stream
MINOR_GAP_S: float = 5.0
MAJOR_GAP_S: float = 60.0


def build_tick_stream(
    cleaned_writer: CleanedLayerWriter,
    source: str | None = None,
    feed_type: str = "spot_tick",
    max_ticks: int = 1000,
) -> StructureResult:
    """Build a ``TickStream`` from cleaned tick records.

    Reads all cleaned records of the specified ``feed_type`` from the
    cleaned layer, orders them by timestamp, assigns sequence IDs, and
    detects gaps.

    Args:
        cleaned_writer: The cleaned layer writer to read from.
        source: Optional source filter.
        feed_type: Feed type to build stream for (default ``\"spot_tick\"``).
        max_ticks: Maximum ticks to include (prevents unbounded memory use).

    Returns:
        A ``StructureResult`` with ``stream_type=TICK_STREAM`` and
        ``stream_data`` containing the ``TickStream``.
    """
    records = cleaned_writer.query(feed_type=feed_type, source=source)

    if not records:
        logger.info(
            "No cleaned records found for tick stream",
            extra={"feed_type": feed_type, "source": source},
        )
        return StructureResult(
            stream_type=StreamType.TICK_STREAM,
            stream_data=TickStream(),
            metadata={"feed_type": feed_type, "source": source, "tick_count": 0},
        )

    # ── Build ValidatedTick list ──────────────────────────────────────
    ticks: list[ValidatedTick] = []
    gaps: list[dict[str, Any]] = []
    previous_ts: datetime | None = None
    sequence_id = 0

    # Sort by timestamp (parse from chronological order)
    sorted_entries = sorted(
        records,
        key=lambda r: _extract_timestamp(r) or datetime.min,
    )

    for entry in sorted_entries:
        ts = _extract_timestamp(entry)
        if ts is None:
            continue

        cleaned_data = entry.get("cleaned_data", {})
        ltp = cleaned_data.get("ltp", 0.0)
        volume = cleaned_data.get("volume", 0)

        # Gap detection
        if previous_ts is not None:
            gap_s = (ts - previous_ts).total_seconds()
            if gap_s >= MINOR_GAP_S:
                gap_type = "MAJOR_GAP" if gap_s >= MAJOR_GAP_S else "MINOR_GAP"
                gaps.append({
                    "type": gap_type,
                    "from": previous_ts.isoformat(),
                    "to": ts.isoformat(),
                    "gap_s": round(gap_s, 3),
                })

        tick = ValidatedTick(
            timestamp=ts,
            price=float(ltp),
            volume=int(volume) if isinstance(volume, (int, float)) else 0,
            source=entry.get("source", "unknown"),
            feed_type=feed_type,
            sequence_id=sequence_id,
        )
        ticks.append(tick)
        previous_ts = ts
        sequence_id += 1

        if len(ticks) >= max_ticks:
            logger.warning(
                "Tick stream truncated at max_ticks",
                extra={"max_ticks": max_ticks},
            )
            break

    # ── Build TickStream ──────────────────────────────────────────────
    stream_id = f"tick_{feed_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    start_time = ticks[0].timestamp if ticks else None
    end_time = ticks[-1].timestamp if ticks else None

    tick_stream = TickStream(
        stream_id=stream_id,
        ticks=ticks,
        start_time=start_time,
        end_time=end_time,
        tick_count=len(ticks),
        gaps=gaps,
    )

    logger.info(
        "Tick stream built",
        extra={
            "stream_id": stream_id,
            "tick_count": len(ticks),
            "gap_count": len(gaps),
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
        },
    )

    return StructureResult(
        stream_type=StreamType.TICK_STREAM,
        stream_data=tick_stream,
        metadata={
            "feed_type": feed_type,
            "source": source,
            "tick_count": len(ticks),
            "gap_count": len(gaps),
            "stream_id": stream_id,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
        },
    )


def _extract_timestamp(entry: dict[str, Any]) -> datetime | None:
    """Extract a datetime from a cleaned writer entry."""
    cleaned = entry.get("cleaned_data", {})
    ts_raw = cleaned.get("timestamp")
    if not ts_raw:
        # Fall back to the envelope's received_at
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
