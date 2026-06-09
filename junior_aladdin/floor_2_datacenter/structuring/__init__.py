"""Structuring layer — tick streams, candle streams, options snapshots, session packets.

Exports:
- :func:`build_tick_stream` — Build ``TickStream`` from cleaned ticks.
- :func:`build_candle_stream` — Build 1m OHLCV ``CandleStream``.
- :func:`build_options_snapshot_stream` — Build ``OptionsSnapshotStream``.
- :func:`build_session_packet` — Build ``SessionPacket`` from time context.
- :func:`classify_feed` / :func:`classify_stream` — MAJOR/MINOR classification.
- :class:`StructuredWriter` — In-memory store for structured products.
"""

from junior_aladdin.floor_2_datacenter.structuring.candle_stream_builder import (
    build_candle_stream,
)
from junior_aladdin.floor_2_datacenter.structuring.major_minor_classifier import (
    classify_feed,
    classify_stream,
    classify_structure_result,
    is_major,
    is_minor,
)
from junior_aladdin.floor_2_datacenter.structuring.options_snapshot_builder import (
    build_options_snapshot_stream,
)
from junior_aladdin.floor_2_datacenter.structuring.session_packet_builder import (
    build_session_packet,
)
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)
from junior_aladdin.floor_2_datacenter.structuring.tick_stream_builder import (
    build_tick_stream,
)

__all__ = [
    "build_candle_stream",
    "build_options_snapshot_stream",
    "build_session_packet",
    "build_tick_stream",
    "classify_feed",
    "classify_stream",
    "classify_structure_result",
    "is_major",
    "is_minor",
    "StructuredWriter",
]
