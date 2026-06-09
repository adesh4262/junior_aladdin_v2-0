"""Floor 2 Structuring — candle stream builder.

Builds 1-minute OHLCV ``CandleStream`` objects from cleaned tick data.

Aggregates ticks into 1-minute candles using open-high-low-close-volume.
Higher timeframes are built in Floor 3 from this 1m foundation.

Architecture rules:
- 1m candles are the minimum resolution — higher timeframes belong to Floor 3.
- Candles only include complete minute windows (``is_complete=True``).
- No intelligence or market interpretation of candle patterns.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import Candle, CandleStream
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType, StructureResult
from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("candle_stream_builder")

# Candle resolution in minutes
CANDLE_RESOLUTION_MIN: int = 1


def build_candle_stream(
    cleaned_writer: CleanedLayerWriter,
    source: str | None = None,
    feed_type: str = "spot_tick",
    max_candles: int = 390,  # ~1 trading day at 1m
) -> StructureResult:
    """Build a 1m OHLCV ``CandleStream`` from cleaned tick records.

    Args:
        cleaned_writer: The cleaned layer writer to read from.
        source: Optional source filter.
        feed_type: Feed type for tick data (default ``\"spot_tick\"``).
        max_candles: Maximum candles to produce (default 390 = 1 trading day).

    Returns:
        A ``StructureResult`` with ``stream_type=CANDLE_STREAM``.
    """
    records = cleaned_writer.query(feed_type=feed_type, source=source)

    if not records:
        logger.info(
            "No cleaned records found for candle stream",
            extra={"feed_type": feed_type},
        )
        return StructureResult(
            stream_type=StreamType.CANDLE_STREAM,
            stream_data=CandleStream(),
            metadata={"feed_type": feed_type, "candle_count": 0},
        )

    # ── Group ticks into 1-minute buckets ─────────────────────────────
    # bucket_key = (year, month, day, hour, minute)
    buckets: dict[tuple[int, int, int, int, int], list[dict[str, Any]]] = defaultdict(list)

    for entry in records:
        ts = _extract_timestamp(entry)
        if ts is None:
            continue
        cleaned = entry.get("cleaned_data", {})
        bucket_key = (ts.year, ts.month, ts.day, ts.hour, ts.minute)
        buckets[bucket_key].append(cleaned)

    # ── Build candles from buckets ────────────────────────────────────
    candles: list[Candle] = []
    now = datetime.now(timezone.utc)

    for key in sorted(buckets.keys()):
        if len(candles) >= max_candles:
            break

        year, month, day, hour, minute = key
        ts = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        ticks = buckets[key]

        if not ticks:
            continue

        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        total_volume = 0

        for tick in ticks:
            ltp = tick.get("ltp")
            if ltp is None or not isinstance(ltp, (int, float)):
                continue
            price = float(ltp)
            opens.append(price)
            highs.append(price)
            lows.append(price)
            closes.append(price)
            vol = tick.get("volume", 0)
            if isinstance(vol, (int, float)):
                total_volume += int(vol)

        if not opens:
            continue

        candle = Candle(
            timestamp=ts,
            open=opens[0],
            high=max(highs),
            low=min(lows),
            close=closes[-1],
            volume=total_volume,
            # Mark incomplete if this candle's window hasn't closed yet
            is_complete=(ts + timedelta(minutes=CANDLE_RESOLUTION_MIN) <= now),
        )
        candles.append(candle)

    # ── Build CandleStream ────────────────────────────────────────────
    stream_id = (
        f"candle_{CANDLE_RESOLUTION_MIN}m_{feed_type}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )
    candle_source = source or "unknown"

    candle_stream = CandleStream(
        stream_id=stream_id,
        candles=candles,
        source=candle_source,
        feed_type=feed_type,
    )

    logger.info(
        "Candle stream built",
        extra={
            "stream_id": stream_id,
            "candle_count": len(candles),
            "resolution_min": CANDLE_RESOLUTION_MIN,
        },
    )

    return StructureResult(
        stream_type=StreamType.CANDLE_STREAM,
        stream_data=candle_stream,
        metadata={
            "feed_type": feed_type,
            "source": candle_source,
            "candle_count": len(candles),
            "resolution_min": CANDLE_RESOLUTION_MIN,
            "stream_id": stream_id,
            "start_time": candles[0].timestamp.isoformat() if candles else None,
            "end_time": candles[-1].timestamp.isoformat() if candles else None,
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
