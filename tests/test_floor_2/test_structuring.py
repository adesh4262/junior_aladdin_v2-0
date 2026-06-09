"""Tests for Floor 2 Structuring sub-system (Step 2.6).

Tests cover:
- tick_stream_builder: builds TickStream from cleaned ticks, sequence IDs, gaps
- candle_stream_builder: builds 1m OHLCV CandleStream, bucket aggregation
- options_snapshot_builder: builds OptionsSnapshotStream, interval grouping
- session_packet_builder: builds SessionPacket from time context
- major_minor_classifier: feed/stream classification as MAJOR/MINOR
- structured_writer: store, get, get_by_type, get_latest, delete, clear
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    CleaningResult,
    DataClass,
    StreamType,
    StructureResult,
)
from junior_aladdin.floor_2_datacenter.structuring.candle_stream_builder import (
    build_candle_stream,
)
from junior_aladdin.floor_2_datacenter.structuring.major_minor_classifier import (
    classify_feed,
    classify_stream,
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


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cleaned_writer() -> CleanedLayerWriter:
    """A CleanedLayerWriter pre-loaded with test tick data."""
    writer = CleanedLayerWriter()
    base_ts = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Add 10 ticks at 1-second intervals
    for i in range(10):
        ts = base_ts.replace(second=i)
        record = {
            "packet_id": f"pkt_tick_{i:03d}",
            "source": "angel_one",
            "feed_type": "spot_tick",
            "original_raw_packet": {},
        }
        result = CleaningResult(
            cleaned_record={
                "ltp": 18500.0 + float(i),
                "volume": 1000 + i * 10,
                "symbol": "NIFTY",
                "feed_type": "spot_tick",
                "timestamp": ts.isoformat(),
            },
        )
        writer.write(record, result)

    return writer


@pytest.fixture
def cleaned_options_writer() -> CleanedLayerWriter:
    """A CleanedLayerWriter with options snapshot data."""
    writer = CleanedLayerWriter()
    base_ts = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    # 3 strikes, 2 option types
    for strike in [18000, 18500, 19000]:
        for opt_type in ["CE", "PE"]:
            record = {
                "packet_id": f"opt_{strike}_{opt_type}",
                "source": "angel_one",
                "feed_type": "options_snapshot",
            }
            result = CleaningResult(
                cleaned_record={
                    "option_type": opt_type,
                    "strike": float(strike),
                    "oi": 50000 + strike,
                    "premium": 150.0 if opt_type == "CE" else 200.0,
                    "expiry": "2026-03-26",
                    "iv": 15.5,
                    "change_in_oi": 100,
                    "timestamp": base_ts.isoformat(),
                },
            )
            writer.write(record, result)

    return writer


# =============================================================================
# Tick Stream Builder
# =============================================================================


class TestTickStreamBuilder:
    def test_builds_tick_stream(self, cleaned_writer: CleanedLayerWriter) -> None:
        result = build_tick_stream(cleaned_writer, feed_type="spot_tick")
        assert result.stream_type == StreamType.TICK_STREAM
        assert result.stream_data is not None
        assert result.stream_data.tick_count == 10

    def test_assigns_sequence_ids(self, cleaned_writer: CleanedLayerWriter) -> None:
        result = build_tick_stream(cleaned_writer, feed_type="spot_tick")
        ticks = result.stream_data.ticks
        for i, tick in enumerate(ticks):
            assert tick.sequence_id == i

    def test_detects_gaps(self) -> None:
        """Ticks with large time gaps should produce gap entries."""
        writer = CleanedLayerWriter()
        # Tick at T=0s, then gap of 70s, then gap of 10s
        timestamps = [
            datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),     # T=0
            datetime(2026, 1, 15, 10, 1, 10, tzinfo=timezone.utc),     # T=70s - MAJOR gap
            datetime(2026, 1, 15, 10, 1, 20, tzinfo=timezone.utc),     # T=80s - MINOR gap (10s)
        ]
        for i, ts in enumerate(timestamps):
            record = {"packet_id": f"pkt_gap_{i}", "source": "test", "feed_type": "spot_tick"}
            result = CleaningResult(
                cleaned_record={"ltp": 18500.0, "volume": 1000, "timestamp": ts.isoformat()},
            )
            writer.write(record, result)

        result = build_tick_stream(writer, feed_type="spot_tick")
        assert len(result.stream_data.gaps) >= 1

    def test_no_records(self) -> None:
        writer = CleanedLayerWriter()
        result = build_tick_stream(writer, feed_type="spot_tick")
        assert result.stream_data.tick_count == 0

    def test_sorts_by_timestamp(self) -> None:
        """Ticks should be sorted chronologically regardless of insertion order."""
        writer = CleanedLayerWriter()
        ts_later = datetime(2026, 1, 15, 10, 0, 10, tzinfo=timezone.utc)
        ts_earlier = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        # Insert out of order
        for rec in [
            ("pkt_late", ts_later, 18600.0),
            ("pkt_early", ts_earlier, 18500.0),
        ]:
            record = {"packet_id": rec[0], "source": "test", "feed_type": "spot_tick"}
            result = CleaningResult(cleaned_record={"ltp": rec[2], "volume": 1000, "timestamp": rec[1].isoformat()})
            writer.write(record, result)

        result = build_tick_stream(writer, feed_type="spot_tick")
        assert result.stream_data.tick_count == 2
        assert result.stream_data.ticks[0].price == 18500.0  # First by time

    def test_structure_result_shape(self, cleaned_writer: CleanedLayerWriter) -> None:
        result = build_tick_stream(cleaned_writer, feed_type="spot_tick")
        assert isinstance(result, StructureResult)
        assert isinstance(result.metadata, dict)
        assert result.metadata["tick_count"] == 10


# =============================================================================
# Candle Stream Builder
# =============================================================================


class TestCandleStreamBuilder:
    def test_builds_candle_stream(self, cleaned_writer: CleanedLayerWriter) -> None:
        result = build_candle_stream(cleaned_writer, feed_type="spot_tick")
        assert result.stream_type == StreamType.CANDLE_STREAM
        assert result.stream_data is not None

    def test_candles_have_ohlcv(self, cleaned_writer: CleanedLayerWriter) -> None:
        result = build_candle_stream(cleaned_writer, feed_type="spot_tick")
        candles = result.stream_data.candles
        if candles:
            candle = candles[0]
            assert candle.open > 0
            assert candle.high > 0
            assert candle.low > 0
            assert candle.close > 0

    def test_no_records(self) -> None:
        writer = CleanedLayerWriter()
        result = build_candle_stream(writer, feed_type="spot_tick")
        assert len(result.stream_data.candles) == 0

    def test_correct_resolution(self, cleaned_writer: CleanedLayerWriter) -> None:
        result = build_candle_stream(cleaned_writer, feed_type="spot_tick")
        assert result.metadata["resolution_min"] == 1


# =============================================================================
# Options Snapshot Builder
# =============================================================================


class TestOptionsSnapshotBuilder:
    def test_builds_snapshot_stream(
        self, cleaned_options_writer: CleanedLayerWriter,
    ) -> None:
        result = build_options_snapshot_stream(cleaned_options_writer)
        assert result.stream_type == StreamType.OPTIONS_SNAPSHOT
        assert result.stream_data is not None

    def test_has_snapshots(self, cleaned_options_writer: CleanedLayerWriter) -> None:
        result = build_options_snapshot_stream(cleaned_options_writer)
        assert len(result.stream_data.snapshots) > 0

    def test_default_interval(self, cleaned_options_writer: CleanedLayerWriter) -> None:
        result = build_options_snapshot_stream(cleaned_options_writer)
        assert result.stream_data.interval_minutes == 5

    def test_no_records(self) -> None:
        writer = CleanedLayerWriter()
        result = build_options_snapshot_stream(writer)
        assert len(result.stream_data.snapshots) == 0

    def test_snapshot_fields(self, cleaned_options_writer: CleanedLayerWriter) -> None:
        result = build_options_snapshot_stream(cleaned_options_writer)
        snap = result.stream_data.snapshots[0]
        assert snap.oi > 0
        assert snap.strike > 0
        assert snap.option_type in ("CE", "PE")


# =============================================================================
# Session Packet Builder
# =============================================================================


class TestSessionPacketBuilder:
    def test_builds_session_packet(self) -> None:
        result = build_session_packet()
        assert result.stream_type == StreamType.SESSION_PACKET
        assert result.stream_data is not None

    def test_session_packet_has_id(self) -> None:
        result = build_session_packet()
        assert len(result.stream_data.session_id) > 0
        assert "sess" in result.stream_data.session_id

    def test_session_packet_has_type(self) -> None:
        result = build_session_packet()
        assert result.stream_data.session_type in (
            "PRE_OPEN", "REGULAR", "CLOSING", "POST_CLOSE", "PRE_MARKET", "UNKNOWN",
        )

    def test_session_packet_custom_time(self) -> None:
        """Pre-open market: 03:30 UTC = 09:00 IST."""
        ts = datetime(2026, 1, 15, 3, 30, tzinfo=timezone.utc)
        result = build_session_packet(timestamp=ts)
        assert result.stream_data.session_type == "PRE_OPEN"

    def test_post_close(self) -> None:
        """Post-close: 10:00 UTC = 15:30 IST."""
        ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        result = build_session_packet(timestamp=ts)
        assert result.stream_data.session_type == "POST_CLOSE"

    def test_regular_session(self) -> None:
        """Regular: 04:00 UTC = 09:30 IST."""
        ts = datetime(2026, 1, 15, 4, 0, tzinfo=timezone.utc)
        result = build_session_packet(timestamp=ts)
        assert result.stream_data.session_type == "REGULAR"

    def test_references_present(self) -> None:
        result = build_session_packet()
        refs = result.stream_data.references
        assert "asia_active" in refs
        assert "london_active" in refs
        assert "ny_active" in refs


# =============================================================================
# Major/Minor Classifier
# =============================================================================


class TestMajorMinorClassifier:
    def test_spot_tick_is_major(self) -> None:
        assert classify_feed("spot_tick") == DataClass.MAJOR
        assert is_major("spot_tick") is True

    def test_options_snapshot_is_major(self) -> None:
        assert classify_feed("options_snapshot") == DataClass.MAJOR

    def test_macro_data_is_minor(self) -> None:
        assert classify_feed("macro_data") == DataClass.MINOR
        assert is_minor("macro_data") is True

    def test_tick_stream_is_major(self) -> None:
        assert classify_stream(StreamType.TICK_STREAM) == DataClass.MAJOR

    def test_candle_stream_is_major(self) -> None:
        assert classify_stream(StreamType.CANDLE_STREAM) == DataClass.MAJOR

    def test_session_packet_is_minor(self) -> None:
        assert classify_stream(StreamType.SESSION_PACKET) == DataClass.MINOR

    def test_macro_support_is_minor(self) -> None:
        assert classify_stream(StreamType.MACRO_SUPPORT) == DataClass.MINOR

    def test_unknown_feed_defaults_minor(self) -> None:
        assert classify_feed("unknown") == DataClass.MINOR
        assert is_minor("unknown") is True

    def test_classify_structure_result(self, cleaned_writer: CleanedLayerWriter) -> None:
        from junior_aladdin.floor_2_datacenter.structuring.major_minor_classifier import (
            classify_structure_result,
        )
        result = build_tick_stream(cleaned_writer, feed_type="spot_tick")
        assert classify_structure_result(result) == DataClass.MAJOR


# =============================================================================
# Structured Writer
# =============================================================================


class TestStructuredWriter:
    def test_write_and_get(self) -> None:
        writer = StructuredWriter()
        now = datetime.now(timezone.utc)
        result = StructureResult(
            stream_type=StreamType.TICK_STREAM,
            stream_data={"ticks": []},
            metadata={"stream_id": "test_stream_001", "tick_count": 0},
        )
        sid = writer.write(result)
        assert sid == "test_stream_001"

        entry = writer.get("test_stream_001")
        assert entry is not None
        assert entry["stream_type"] == "TICK_STREAM"

    def test_get_by_type(self) -> None:
        writer = StructuredWriter()
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "ts1"},
        ))
        writer.write(StructureResult(
            stream_type=StreamType.CANDLE_STREAM,
            metadata={"stream_id": "cs1"},
        ))
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "ts2"},
        ))

        ticks = writer.get_by_type(StreamType.TICK_STREAM)
        assert len(ticks) == 2

        candles = writer.get_by_type(StreamType.CANDLE_STREAM)
        assert len(candles) == 1

    def test_get_latest(self) -> None:
        writer = StructuredWriter()
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "first"},
        ))
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "second"},
        ))

        latest = writer.get_latest(StreamType.TICK_STREAM)
        assert latest is not None
        assert latest["metadata"]["stream_id"] == "second"

    def test_get_stream_data(self) -> None:
        writer = StructuredWriter()
        data = {"ticks": [1, 2, 3]}
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            stream_data=data,
            metadata={"stream_id": "ts1"},
        ))

        result = writer.get_stream_data(StreamType.TICK_STREAM)
        assert result == data

    def test_delete(self) -> None:
        writer = StructuredWriter()
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "ts1"},
        ))
        assert writer.count == 1
        assert writer.delete("ts1") is True
        assert writer.count == 0

    def test_delete_nonexistent(self) -> None:
        writer = StructuredWriter()
        assert writer.delete("nonexistent") is False

    def test_clear(self) -> None:
        writer = StructuredWriter()
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            metadata={"stream_id": "ts1"},
        ))
        writer.clear()
        assert writer.count == 0

    def test_properties(self) -> None:
        writer = StructuredWriter()
        assert writer.count == 0
        assert writer.stream_types == set()
        assert writer.count_by_type(StreamType.TICK_STREAM) == 0
