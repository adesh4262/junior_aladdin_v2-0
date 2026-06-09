"""Tests for Floor 2 Cleaning sub-system (Step 2.5).

Tests cover:
- tick_cleaner: valid ticks, zero-price removal, volume repair, price jump flag
- options_cleaner: valid snapshots, invalid option type, strike/OI/premium validation
- packet_cleaner: VIX/macro/calendar/manual cleaning, missing required fields
- anomaly_repair: NaN/Inf/None repair, negative unsigned fields, previous values
- cleaned_layer_writer: store, get, query, delete, clear, repair tracking
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from junior_aladdin.floor_2_datacenter.cleaning.anomaly_repair import repair_anomalies
from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.floor_2_datacenter.cleaning.options_cleaner import (
    clean_options_snapshot,
)
from junior_aladdin.floor_2_datacenter.cleaning.packet_cleaner import clean_packet
from junior_aladdin.floor_2_datacenter.cleaning.tick_cleaner import clean_tick
from junior_aladdin.floor_2_datacenter.datacenter_types import CleaningResult


# =============================================================================
# Helpers
# =============================================================================


def _make_record(
    packet_id: str = "pkt_001",
    source: str = "angel_one",
    feed_type: str = "spot_tick",
    raw_data: dict | None = None,
) -> dict:
    return {
        "packet_id": packet_id,
        "source": source,
        "feed_type": feed_type,
        "original_raw_packet": raw_data or {},
        "minimal_source_envelope": {
            "source": source,
            "feed_type": feed_type,
            "connection_id": "c1",
            "packet_id": packet_id,
            "routing_id": "SPOT_FEED",
            "received_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# =============================================================================
# Tick Cleaner Tests
# =============================================================================


class TestTickCleaner:
    def test_clean_valid_tick(self) -> None:
        record = _make_record(raw_data={"ltp": 18500.0, "volume": 1500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-01T00:00:00"})
        result = clean_tick(record)
        assert result.removed is False
        assert result.cleaned_record is not None
        assert result.cleaned_record["ltp"] == 18500.0
        assert result.cleaned_record["volume"] == 1500

    def test_removes_zero_ltp(self) -> None:
        record = _make_record(raw_data={"ltp": 0, "volume": 1500})
        result = clean_tick(record)
        assert result.removed is True
        assert "ltp_zero_or_negative" in result.anomaly_flags

    def test_removes_negative_ltp(self) -> None:
        record = _make_record(raw_data={"ltp": -100, "volume": 1500})
        result = clean_tick(record)
        assert result.removed is True
        assert "ltp_zero_or_negative" in result.anomaly_flags

    def test_removes_none_ltp(self) -> None:
        record = _make_record(raw_data={"ltp": None, "volume": 1500})
        result = clean_tick(record)
        assert result.removed is True

    def test_removes_non_numeric_ltp(self) -> None:
        record = _make_record(raw_data={"ltp": "abc", "volume": 1500})
        result = clean_tick(record)
        assert result.removed is True
        assert "ltp_not_numeric" in result.anomaly_flags

    def test_repairs_negative_volume(self) -> None:
        record = _make_record(raw_data={"ltp": 18500.0, "volume": -100})
        result = clean_tick(record)
        assert result.removed is False
        assert result.repaired is True
        assert result.cleaned_record["volume"] == 0

    def test_repairs_non_numeric_volume(self) -> None:
        record = _make_record(raw_data={"ltp": 18500.0, "volume": "lots"})
        result = clean_tick(record)
        assert result.removed is False
        assert result.repaired is True
        assert result.cleaned_record["volume"] == 0

    def test_flags_price_jump(self) -> None:
        record = _make_record(raw_data={"ltp": 25000.0, "volume": 1500})
        result = clean_tick(record, previous_price=18500.0)
        assert result.removed is False
        jump_flags = [f for f in result.anomaly_flags if f.startswith("price_jump_")]
        assert len(jump_flags) >= 1

    def test_no_price_jump_flag_within_threshold(self) -> None:
        record = _make_record(raw_data={"ltp": 18600.0, "volume": 1500})
        result = clean_tick(record, previous_price=18500.0)
        jump_flags = [f for f in result.anomaly_flags if f.startswith("price_jump_")]
        assert len(jump_flags) == 0

    def test_removes_empty_raw_data(self) -> None:
        record = _make_record(raw_data={})
        result = clean_tick(record)
        assert result.removed is True
        assert "empty_raw_data" in result.anomaly_flags


# =============================================================================
# Options Cleaner Tests
# =============================================================================


class TestOptionsCleaner:
    def test_clean_valid_snapshot(self) -> None:
        raw_data = {"option_type": "CE", "strike": 18500.0, "oi": 50000, "premium": 150.0, "expiry": "2026-03-26", "iv": 15.5, "change_in_oi": 200}
        record = _make_record(feed_type="options_snapshot", raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is False
        assert result.cleaned_record is not None
        assert result.cleaned_record["option_type"] == "CE"
        assert result.cleaned_record["strike"] == 18500.0

    def test_removes_invalid_option_type(self) -> None:
        raw_data = {"option_type": "XX", "strike": 18500.0, "oi": 50000, "premium": 150.0}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is True
        assert any("invalid_option_type" in f for f in result.anomaly_flags)

    def test_removes_missing_strike(self) -> None:
        raw_data = {"option_type": "PE", "oi": 50000, "premium": 150.0}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is True

    def test_removes_zero_strike(self) -> None:
        raw_data = {"option_type": "CE", "strike": 0, "oi": 50000, "premium": 150.0}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is True

    def test_repairs_negative_oi(self) -> None:
        raw_data = {"option_type": "PE", "strike": 18000.0, "oi": -100, "premium": 200.0, "expiry": "2026-03-26"}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is False
        assert result.repaired is True
        assert result.cleaned_record["oi"] == 0

    def test_repairs_negative_premium(self) -> None:
        raw_data = {"option_type": "CE", "strike": 18000.0, "oi": 50000, "premium": -50.0, "expiry": "2026-03-26"}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is False
        assert result.repaired is True
        assert result.cleaned_record["premium"] == 0.0

    def test_flags_zero_oi_with_premium(self) -> None:
        raw_data = {"option_type": "CE", "strike": 18000.0, "oi": 0, "premium": 150.0, "expiry": "2026-03-26"}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert result.removed is False
        assert "zero_oi_with_premium" in result.anomaly_flags

    def test_flags_missing_expiry(self) -> None:
        raw_data = {"option_type": "PE", "strike": 18000.0, "oi": 50000, "premium": 200.0}
        record = _make_record(raw_data=raw_data)
        result = clean_options_snapshot(record)
        assert "expiry_missing" in result.anomaly_flags


# =============================================================================
# Packet Cleaner Tests
# =============================================================================


class TestPacketCleaner:
    def test_clean_vix_tick(self) -> None:
        raw_data = {"value": 14.5, "feed_type": "vix_tick", "timestamp": "2026-01-01T00:00:00"}
        record = _make_record(feed_type="vix_tick", raw_data=raw_data)
        result = clean_packet(record)
        assert result.removed is False
        assert result.cleaned_record["value"] == 14.5

    def test_removes_vix_missing_value(self) -> None:
        record = _make_record(feed_type="vix_tick", raw_data={"feed_type": "vix_tick"})
        result = clean_packet(record)
        assert result.removed is True

    def test_clean_macro_data(self) -> None:
        raw_data = {"feed_type": "macro_data", "stub": True}
        record = _make_record(feed_type="macro_data", raw_data=raw_data)
        result = clean_packet(record)
        assert result.removed is False

    def test_removes_macro_missing_stub(self) -> None:
        record = _make_record(feed_type="macro_data", raw_data={"feed_type": "macro_data"})
        result = clean_packet(record)
        assert result.removed is True

    def test_clean_calendar_event(self) -> None:
        raw_data = {"feed_type": "calendar_event", "stub": False}
        record = _make_record(feed_type="calendar_event", raw_data=raw_data)
        result = clean_packet(record)
        assert result.removed is False

    def test_clean_manual_packet(self) -> None:
        raw_data = {"payload": {"event": "expiry", "date": "2026-03-26"}, "source": "manual"}
        record = _make_record(feed_type="MANUAL_CALENDAR", raw_data=raw_data)
        result = clean_packet(record)
        assert result.removed is False

    def test_removes_manual_missing_payload(self) -> None:
        record = _make_record(feed_type="MANUAL_CALENDAR", raw_data={"source": "manual"})
        result = clean_packet(record)
        assert result.removed is True

    def test_repairs_non_numeric_vix_value(self) -> None:
        raw_data = {"value": "14.5", "feed_type": "vix_tick", "timestamp": "2026-01-01T00:00:00"}
        record = _make_record(feed_type="vix_tick", raw_data=raw_data)
        result = clean_packet(record)
        assert result.removed is False
        assert result.repaired is True
        assert result.cleaned_record["value"] == 14.5

    def test_removes_empty_raw_data(self) -> None:
        record = _make_record(feed_type="vix_tick", raw_data={})
        result = clean_packet(record)
        assert result.removed is True


# =============================================================================
# Anomaly Repair Tests
# =============================================================================


class TestAnomalyRepair:
    def test_clean_data_unchanged(self) -> None:
        raw_data = {"ltp": 18500.0, "volume": 1500, "symbol": "NIFTY"}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record)
        assert result.removed is False
        assert result.repaired is False
        assert result.cleaned_record["ltp"] == 18500.0

    def test_repairs_nan(self) -> None:
        raw_data = {"ltp": float("nan"), "volume": 1500}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record)
        assert result.removed is False
        assert result.repaired is True
        assert any("ltp_was_nan" in f for f in result.anomaly_flags)

    def test_repairs_nan_with_previous_value(self) -> None:
        raw_data = {"ltp": float("nan"), "volume": 1500}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record, previous_values={"ltp": 18400.0})
        assert result.repaired is True
        assert result.cleaned_record["ltp"] == 18400.0

    def test_repairs_inf(self) -> None:
        raw_data = {"ltp": float("inf"), "volume": 1500}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record)
        assert result.repaired is True
        assert any("ltp_was_inf" in f for f in result.anomaly_flags)

    def test_repairs_none_with_field_default(self) -> None:
        raw_data = {"ltp": 18500.0, "volume": None}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record)
        assert result.repaired is True
        assert result.cleaned_record["volume"] == 0

    def test_repairs_none_with_previous_value(self) -> None:
        raw_data = {"ltp": None, "volume": 1500}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record, previous_values={"ltp": 18400.0})
        assert result.repaired is True
        assert result.cleaned_record["ltp"] == 18400.0

    def test_clamps_negative_unsigned_field(self) -> None:
        raw_data = {"ltp": 18500.0, "volume": -100}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record)
        assert result.repaired is True
        assert result.cleaned_record["volume"] == 0

    def test_removes_empty_raw_data(self) -> None:
        record = _make_record(raw_data={})
        result = repair_anomalies(record)
        assert result.removed is True

    def test_preserves_original_values(self) -> None:
        raw_data = {"ltp": float("nan"), "volume": 1500}
        record = _make_record(raw_data=raw_data)
        result = repair_anomalies(record)
        assert result.original_values is not None
        assert "ltp" in result.original_values


# =============================================================================
# CleanedLayerWriter Tests
# =============================================================================


class TestCleanedLayerWriter:
    def test_write_and_get(self) -> None:
        writer = CleanedLayerWriter()
        record = _make_record()
        result = CleaningResult(cleaned_record={"ltp": 18500.0, "volume": 1500})
        pid = writer.write(record, result)
        assert pid == "pkt_001"
        assert writer.count == 1

        entry = writer.get("pkt_001")
        assert entry is not None
        assert entry["cleaned_data"]["ltp"] == 18500.0

    def test_get_cleaned_data(self) -> None:
        writer = CleanedLayerWriter()
        record = _make_record()
        result = CleaningResult(cleaned_record={"ltp": 18500.0})
        writer.write(record, result)

        data = writer.get_cleaned_data("pkt_001")
        assert data == {"ltp": 18500.0}

    def test_write_removed_returns_none(self) -> None:
        writer = CleanedLayerWriter()
        record = _make_record()
        result = CleaningResult(removed=True, removal_reason="test")
        pid = writer.write(record, result)
        assert pid is None
        assert writer.count == 0

    def test_write_no_packet_id(self) -> None:
        writer = CleanedLayerWriter()
        record = _make_record(packet_id="")
        result = CleaningResult(cleaned_record={"ltp": 18500.0})
        pid = writer.write(record, result)
        assert pid is None

    def test_tracks_repaired(self) -> None:
        writer = CleanedLayerWriter()
        record = _make_record(packet_id="p1")
        result = CleaningResult(
            cleaned_record={"ltp": 18500.0},
            repaired=True,
            repair_action="fixed NaN",
            anomaly_flags=["ltp_was_nan"],
        )
        writer.write(record, result)

        record2 = _make_record(packet_id="p2")
        result2 = CleaningResult(cleaned_record={"ltp": 18600.0})
        writer.write(record2, result2)

        assert writer.count_repaired() == 1

    def test_query_by_feed_type(self) -> None:
        writer = CleanedLayerWriter()
        writer.write(
            _make_record(packet_id="p1", feed_type="spot_tick"),
            CleaningResult(cleaned_record={"ltp": 18500.0}),
        )
        writer.write(
            _make_record(packet_id="p2", feed_type="vix_tick"),
            CleaningResult(cleaned_record={"value": 14.5}),
        )

        results = writer.query(feed_type="spot_tick")
        assert len(results) == 1

    def test_query_only_repaired(self) -> None:
        writer = CleanedLayerWriter()
        writer.write(
            _make_record(packet_id="p1"),
            CleaningResult(cleaned_record={"ltp": 18500.0}, repaired=True),
        )
        writer.write(
            _make_record(packet_id="p2"),
            CleaningResult(cleaned_record={"ltp": 18600.0}),
        )

        results = writer.query(only_repaired=True)
        assert len(results) == 1

    def test_delete(self) -> None:
        writer = CleanedLayerWriter()
        writer.write(
            _make_record(),
            CleaningResult(cleaned_record={"ltp": 18500.0}),
        )
        assert writer.count == 1
        assert writer.delete("pkt_001") is True
        assert writer.count == 0

    def test_clear(self) -> None:
        writer = CleanedLayerWriter()
        writer.write(
            _make_record(),
            CleaningResult(cleaned_record={"ltp": 18500.0}),
        )
        writer.clear()
        assert writer.count == 0

    def test_properties(self) -> None:
        writer = CleanedLayerWriter()
        assert writer.count == 0
        assert writer.packet_ids == []
        assert writer.feed_types == set()
