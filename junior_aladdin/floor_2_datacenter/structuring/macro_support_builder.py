"""Floor 2 Structuring — macro support stream builder.

Builds structured ``MacroSupportStream`` objects from cleaned macro data.

Supports 4 macro data types:
- ``VIX``: India VIX tick data from ``vix_tick`` feed
- ``FII_DII``: FII/DII net data from ``macro_data`` feed
- ``GLOBAL_CUE``: Global market cues from ``macro_data`` feed
- ``CALENDAR``: Calendar events (holidays, expiry) from ``calendar_event`` feed

Architecture rules:
- Macro packets are structured DATA, not intelligence or opinion.
- VIX values, FII/DII numbers, and calendar events are reported as-is,
  with NO trading interpretation.
- Freshness tags are computed from timestamp age, not from market opinion.
- Macro domain owns interpretation in Floor 3 — Floor 2 only structures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    MacroSupportPacket,
    MacroSupportStream,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType, StructureResult
from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("macro_support_builder")

# Freshness thresholds in seconds
_FRESH_MAX_AGE_S: float = 60.0       # < 1 minute = FRESH
_WARM_MAX_AGE_S: float = 300.0       # < 5 minutes = WARM
# Older than WARM_MAX_AGE_S = STALE

# Which fields in cleaned_data map to our structured fields per data_type
_DATA_TYPE_FIELD_MAP: dict[str, dict[str, str]] = {
    "VIX": {
        "value": "value",
        "source": "source",
    },
    "MACRO_DATA": {
        "value": "value",
        "sub_type": "data_type",       # e.g. "FII_DII", "GLOBAL_CUE"
        "source": "source",
    },
    "CALENDAR": {
        "value": "event_type",         # e.g. "expiry", "holiday"
        "event_date": "event_date",
        "description": "description",
        "source": "source",
    },
}


def build_macro_support_stream(
    cleaned_writer: CleanedLayerWriter,
    data_type: str = "VIX",
    source: str | None = None,
    max_packets: int = 100,
) -> StructureResult:
    """Build a ``MacroSupportStream`` from cleaned macro/support records.

    Queries the cleaned layer for records matching the given macro
    data type (VIX, MACRO_DATA, or CALENDAR) and structures them into
    a stream with freshness tagging.

    Args:
        cleaned_writer: The cleaned layer writer to read from.
        data_type: One of ``"VIX"``, ``"MACRO_DATA"``, or ``"CALENDAR"``.
        source: Optional source filter (e.g., ``"angel_one"``, ``"manual"``).
        max_packets: Maximum packets to include.

    Returns:
        A ``StructureResult`` with ``stream_type=MACRO_SUPPORT`` and
        ``stream_data`` containing a ``MacroSupportStream``.

    Raises:
        ValueError: If ``data_type`` is not recognised.
    """
    if data_type not in _DATA_TYPE_FIELD_MAP:
        raise ValueError(
            f"Unknown macro data_type: {data_type!r}. "
            f"Must be one of {list(_DATA_TYPE_FIELD_MAP)}",
        )

    # Determine which feed_type(s) to query based on data_type
    if data_type == "VIX":
        feed_types = ["vix_tick"]
    elif data_type == "CALENDAR":
        feed_types = ["calendar_event"]
    else:
        feed_types = ["macro_data"]

    # Gather records from all relevant feed types
    all_records: list[dict[str, Any]] = []
    for ft in feed_types:
        records = cleaned_writer.query(feed_type=ft, source=source)
        all_records.extend(records)

    if not all_records:
        logger.info(
            "No cleaned records found for macro support stream",
            extra={"data_type": data_type, "source": source},
        )
        stream_id = f"macro_{data_type.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        return StructureResult(
            stream_type=StreamType.MACRO_SUPPORT,
            stream_data=MacroSupportStream(
                stream_id=stream_id,
                data_type=data_type,
            ),
            metadata={
                "data_type": data_type,
                "source": source,
                "packet_count": 0,
                "stream_id": stream_id,
            },
        )

    # ── Build MacroSupportPacket list ──────────────────────────────────
    now = datetime.now(timezone.utc)
    packets: list[MacroSupportPacket] = []
    field_map = _DATA_TYPE_FIELD_MAP[data_type]

    # Sort by timestamp
    sorted_records = sorted(
        all_records,
        key=lambda r: _extract_timestamp(r) or datetime.min,
    )

    for entry in sorted_records:
        if len(packets) >= max_packets:
            break

        ts = _extract_timestamp(entry)
        cleaned = entry.get("cleaned_data", {}) or {}

        # ── Extract value ──────────────────────────────────────────────
        value: Any = None
        if data_type == "VIX":
            value = cleaned.get(field_map.get("value", "value"), 0.0)
        elif data_type == "MACRO_DATA":
            value = cleaned.get(field_map.get("value", "value"), {})
        elif data_type == "CALENDAR":
            value = cleaned.get(field_map.get("value", "value"), "")

        # ── Build metadata dict ────────────────────────────────────────
        meta: dict[str, Any] = {}

        if data_type == "VIX":
            meta["high"] = cleaned.get("high", value)
            meta["low"] = cleaned.get("low", value)
            meta["change"] = cleaned.get("change", 0.0)

        elif data_type == "MACRO_DATA":
            sub_type = cleaned.get(field_map.get("sub_type", "data_type"), "GENERIC")
            meta["sub_type"] = sub_type
            meta["unit"] = cleaned.get("unit", "")
            meta["direction"] = cleaned.get("direction", "")

        elif data_type == "CALENDAR":
            meta["event_date"] = cleaned.get(field_map.get("event_date", "event_date"), "")
            meta["description"] = cleaned.get(field_map.get("description", "description"), "")

        # ── Freshness tag ──────────────────────────────────────────────
        freshness = _compute_freshness(ts, now)

        # ── Source ─────────────────────────────────────────────────────
        src = source or cleaned.get(field_map.get("source", "source"), entry.get("source", "unknown"))

        packet = MacroSupportPacket(
            timestamp=ts,
            data_type=data_type if data_type != "MACRO_DATA" else meta.get("sub_type", "MACRO_DATA"),
            value=value,
            source=src,
            freshness=freshness,
            metadata=meta,
        )
        packets.append(packet)

    # ── Build MacroSupportStream ───────────────────────────────────────
    stream_id = f"macro_{data_type.lower()}_{now.strftime('%Y%m%d_%H%M%S')}"
    start_time = packets[0].timestamp if packets else None
    end_time = packets[-1].timestamp if packets else None

    macro_stream = MacroSupportStream(
        stream_id=stream_id,
        data_type=data_type,
        packets=packets,
    )

    logger.info(
        "Macro support stream built",
        extra={
            "stream_id": stream_id,
            "data_type": data_type,
            "packet_count": len(packets),
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
        },
    )

    return StructureResult(
        stream_type=StreamType.MACRO_SUPPORT,
        stream_data=macro_stream,
        metadata={
            "data_type": data_type,
            "source": source,
            "packet_count": len(packets),
            "stream_id": stream_id,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
        },
    )


def build_all_macro_support_streams(
    cleaned_writer: CleanedLayerWriter,
    source: str | None = None,
) -> list[StructureResult]:
    """Build macro support streams for all known data types.

    Convenience function that calls ``build_macro_support_stream`` for
    each supported data type (VIX, MACRO_DATA, CALENDAR).

    Args:
        cleaned_writer: The cleaned layer writer to read from.
        source: Optional source filter.

    Returns:
        A list of ``StructureResult`` objects, one per data type.
    """
    results: list[StructureResult] = []
    for dtype in ["VIX", "MACRO_DATA", "CALENDAR"]:
        result = build_macro_support_stream(
            cleaned_writer=cleaned_writer,
            data_type=dtype,
            source=source,
        )
        results.append(result)
    return results


# ── Helpers ─────────────────────────────────────────────────────────────────


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


def _compute_freshness(ts: datetime | None, now: datetime | None = None) -> str:
    """Compute a freshness tag (FRESH / WARM / STALE) from a timestamp.

    Args:
        ts: The timestamp to evaluate.
        now: Current time (defaults to ``datetime.now(timezone.utc)``).

    Returns:
        ``"FRESH"``, ``"WARM"``, or ``"STALE"``.
    """
    if ts is None:
        return "STALE"
    now = now or datetime.now(timezone.utc)
    age_s = (now - ts).total_seconds()
    if age_s < _FRESH_MAX_AGE_S:
        return "FRESH"
    if age_s < _WARM_MAX_AGE_S:
        return "WARM"
    return "STALE"
