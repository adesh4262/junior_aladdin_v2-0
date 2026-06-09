"""Tests for floor_1_connection/packet_envelope.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from junior_aladdin.floor_1_connection.packet_envelope import build_envelope
from junior_aladdin.shared.types import PacketEnvelope


# ------------------------------------------------------------------
# Basic envelope creation tests
# ------------------------------------------------------------------


class TestBuildEnvelope:
    """Tests for build_envelope()."""

    def test_returns_packet_envelope(self):
        env = build_envelope(
            raw_payload={"ltp": 19500.0},
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        assert isinstance(env, PacketEnvelope)

    def test_all_mandatory_fields_populated(self):
        env = build_envelope(
            raw_payload={"ltp": 19500.0},
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        assert env.source == "angel_one"
        assert env.feed_type == "spot_tick"
        assert env.connection_id == "conn_001"
        assert env.packet_id is not None and env.packet_id != ""
        assert env.routing_id == "angel_one::spot_tick"
        assert env.received_at is not None
        assert env.payload == {"ltp": 19500.0}

    def test_packet_id_has_pkt_prefix(self):
        env = build_envelope(
            raw_payload={},
            source="test",
            feed_type="test",
            connection_id="conn_001",
        )
        assert env.packet_id.startswith("pkt_")

    def test_packet_id_unique_per_call(self):
        ids = set()
        for _ in range(100):
            env = build_envelope(
                raw_payload={},
                source="test",
                feed_type="test",
                connection_id="conn_001",
            )
            ids.add(env.packet_id)
        assert len(ids) == 100

    def test_received_at_is_utcnow(self):
        before = datetime.now(timezone.utc)
        env = build_envelope(
            raw_payload={},
            source="test",
            feed_type="test",
            connection_id="conn_001",
        )
        after = datetime.now(timezone.utc)
        assert before <= env.received_at <= after

    def test_received_at_has_tz_info(self):
        env = build_envelope(
            raw_payload={},
            source="test",
            feed_type="test",
            connection_id="conn_001",
        )
        assert env.received_at.tzinfo is not None


# ------------------------------------------------------------------
# Payload preservation tests
# ------------------------------------------------------------------


class TestPayloadPreservation:
    """Tests that payload is unmodified (no interpretation)."""

    def test_payload_identical_to_input(self):
        raw = {"ltp": 19500.5, "volume": 25000, "symbol": "NIFTY"}
        env = build_envelope(
            raw_payload=raw,
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        assert env.payload == raw
        assert env.payload is not raw  # different object, same content

    def test_payload_preserves_nested_dicts(self):
        raw = {"option_chain": [{"strike": 19500, "oi": 100000}]}
        env = build_envelope(
            raw_payload=raw,
            source="angel_one",
            feed_type="options_snapshot",
            connection_id="conn_001",
        )
        assert env.payload == raw

    def test_payload_preserves_all_data_types(self):
        raw = {
            "ltp": 19500.5,
            "volume": 25000,
            "is_market_open": True,
            "tags": ["nifty", "options"],
            "metadata": None,
        }
        env = build_envelope(
            raw_payload=raw,
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        assert env.payload == raw


# ------------------------------------------------------------------
# Source timestamp tests
# ------------------------------------------------------------------


class TestSourceTimestamp:
    """Tests for source_timestamp handling."""

    def test_none_by_default(self):
        env = build_envelope(
            raw_payload={},
            source="test",
            feed_type="test",
            connection_id="conn_001",
        )
        assert env.source_timestamp is None

    def test_preserves_provided_timestamp(self):
        ts = datetime.now(timezone.utc)
        env = build_envelope(
            raw_payload={},
            source="test",
            feed_type="test",
            connection_id="conn_001",
            source_timestamp=ts,
        )
        assert env.source_timestamp == ts


# ------------------------------------------------------------------
# Routing ID tests
# ------------------------------------------------------------------


class TestRoutingId:
    """Tests for routing_id format."""

    def test_format(self):
        env = build_envelope(
            raw_payload={},
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        assert env.routing_id == "angel_one::spot_tick"

    def test_manual_source_routing(self):
        env = build_envelope(
            raw_payload={"event": "holiday"},
            source="manual",
            feed_type="MANUAL_CALENDAR",
            connection_id="conn_001",
        )
        assert env.routing_id == "manual::MANUAL_CALENDAR"

    def test_empty_source(self):
        env = build_envelope(
            raw_payload={},
            source="",
            feed_type="unknown",
            connection_id="conn_001",
        )
        assert env.routing_id == "::unknown"


# ------------------------------------------------------------------
# Architectural compliance tests
# ------------------------------------------------------------------


class TestArchitecturalCompliance:
    """Verify Floor 1 rules: NO interpretation, NO transformation."""

    def test_no_market_interpretation_in_fields(self):
        """PacketEnvelope fields must be operational metadata only."""
        env = build_envelope(
            raw_payload={"ltp": 19500.0},
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        # These fields should NOT exist in the envelope
        forbidden = {"bias", "signal", "setup", "confidence", "conviction", "direction"}
        env_dict = {k: v for k, v in env.__dict__.items() if not k.startswith("_")}
        for key in env_dict:
            assert key not in forbidden, (
                f"Floor 1 envelope must not contain '{key}' (intelligence field)"
            )

    def test_payload_is_raw_copy(self):
        """Payload is a copy, not a reference to the original (safer)."""
        raw = {"ltp": 19500.0}
        env = build_envelope(
            raw_payload=raw,
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
        )
        # Modifying original should NOT affect envelope payload
        raw["ltp"] = 99999.0
        assert env.payload["ltp"] == 19500.0
