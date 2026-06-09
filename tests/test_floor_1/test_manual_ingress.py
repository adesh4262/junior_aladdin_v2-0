"""Tests for manual_ingress.py — Manual ingress lane (Step 1.7)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from junior_aladdin.floor_1_connection.manual_ingress import (
    MANUAL_CALENDAR,
    MANUAL_EVENT,
    MANUAL_OVERRIDE,
    VALID_EVENT_TYPES,
    build_manual_envelope,
    create_manual_packet,
)
from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.types import PacketEnvelope


class TestCreateManualPacket:
    """Tests for create_manual_packet()."""

    def test_manual_calendar_returns_correct_fields(self):
        """MANUAL_CALENDAR packet → source='manual', feed_type='MANUAL_CALENDAR'."""
        data = {"date": "2026-06-10", "event": "NIFTY expiry"}
        result = create_manual_packet(
            event_type=MANUAL_CALENDAR,
            data=data,
            source_tag="operator",
            connection_id="conn_manual_001",
        )
        assert result["source"] == "manual"
        assert result["feed_type"] == MANUAL_CALENDAR
        assert result["manual_source_tag"] == "operator"
        assert result["payload"] == data

    def test_manual_event_returns_correct_fields(self):
        """MANUAL_EVENT packet → source='manual', feed_type='MANUAL_EVENT'."""
        data = {"type": "holiday", "name": "Diwali"}
        result = create_manual_packet(
            event_type=MANUAL_EVENT,
            data=data,
            source_tag="admin",
            connection_id="conn_manual_002",
        )
        assert result["source"] == "manual"
        assert result["feed_type"] == MANUAL_EVENT
        assert result["manual_source_tag"] == "admin"
        assert result["payload"] == data

    def test_manual_override_returns_correct_fields(self):
        """MANUAL_OVERRIDE packet → source='manual', feed_type='MANUAL_OVERRIDE'."""
        data = {"symbol": "NIFTY", "override_type": "position_size"}
        result = create_manual_packet(
            event_type=MANUAL_OVERRIDE,
            data=data,
            source_tag="supervisor",
            connection_id="conn_manual_003",
        )
        assert result["source"] == "manual"
        assert result["feed_type"] == MANUAL_OVERRIDE
        assert result["manual_source_tag"] == "supervisor"
        assert result["payload"] == data

    def test_payload_is_copied_not_referenced(self):
        """Modifying original data dict does NOT affect the envelope-ready dict."""
        original = {"key": "value", "number": 42}
        result = create_manual_packet(
            event_type=MANUAL_CALENDAR,
            data=original,
            source_tag="test",
            connection_id="conn_test",
        )
        original["key"] = "modified"
        assert result["payload"]["key"] == "value"

    def test_empty_data_returns_empty_payload(self):
        """Empty data dict → payload = {}."""
        result = create_manual_packet(
            event_type=MANUAL_CALENDAR,
            data={},
            source_tag="test",
            connection_id="conn_test",
        )
        assert result["payload"] == {}

    def test_none_data_returns_empty_payload(self):
        """None data → payload = {}."""
        result = create_manual_packet(
            event_type=MANUAL_EVENT,
            data=None,  # type: ignore[arg-type]
            source_tag="test",
            connection_id="conn_test",
        )
        assert result["payload"] == {}

    def test_invalid_event_type_raises_validation_error(self):
        """Unknown event_type → ValidationError."""
        with pytest.raises(ValidationError) as exc:
            create_manual_packet(
                event_type="INVALID_TYPE",
                data={},
                source_tag="test",
                connection_id="conn_test",
            )
        assert "INVALID_TYPE" in str(exc.value)

    def test_invalid_event_type_message_includes_valid_types(self):
        """Error message lists all valid event types."""
        with pytest.raises(ValidationError) as exc:
            create_manual_packet(
                event_type="UNKNOWN",
                data={},
                source_tag="test",
                connection_id="conn_test",
            )
        msg = str(exc.value)
        for t in sorted(VALID_EVENT_TYPES):
            assert t in msg

    def test_all_event_types_accepted(self):
        """Each of the 3 valid event types is accepted without error."""
        for event_type in [MANUAL_CALENDAR, MANUAL_EVENT, MANUAL_OVERRIDE]:
            result = create_manual_packet(
                event_type=event_type,
                data={"test": True},
                source_tag="validator",
                connection_id="conn_test",
            )
            assert result["feed_type"] == event_type

    def test_source_tag_preserved(self):
        """source_tag is preserved exactly as passed."""
        result = create_manual_packet(
            event_type=MANUAL_CALENDAR,
            data={},
            source_tag="my-custom-tag-v1",
            connection_id="conn_test",
        )
        assert result["manual_source_tag"] == "my-custom-tag-v1"


class TestBuildManualEnvelope:
    """Tests for build_manual_envelope() — full envelope integration."""

    def test_returns_packet_envelope_instance(self):
        """build_manual_envelope returns a PacketEnvelope."""
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={"event": "test"},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert isinstance(envelope, PacketEnvelope)

    def test_envelope_source_is_manual(self):
        """Envelope source field = 'manual'."""
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={"event": "test"},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert envelope.source == "manual"

    def test_envelope_feed_type_matches_event_type(self):
        """Envelope feed_type matches the event_type argument."""
        envelope = build_manual_envelope(
            event_type=MANUAL_EVENT,
            data={"event": "test"},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert envelope.feed_type == MANUAL_EVENT

    def test_envelope_connection_id_preserved(self):
        """Envelope connection_id matches the argument."""
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={"event": "test"},
            source_tag="operator",
            connection_id="conn_custom_007",
        )
        assert envelope.connection_id == "conn_custom_007"

    def test_envelope_has_packet_id(self):
        """Envelope has a non-empty packet_id."""
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert isinstance(envelope.packet_id, str)
        assert len(envelope.packet_id) > 0
        assert envelope.packet_id.startswith("pkt_")

    def test_envelope_has_received_at(self):
        """Envelope received_at is a UTC datetime close to now."""
        before = datetime.now(timezone.utc)
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={},
            source_tag="operator",
            connection_id="conn_test",
        )
        after = datetime.now(timezone.utc)
        assert before <= envelope.received_at <= after
        assert envelope.received_at.tzinfo is not None

    def test_envelope_has_routing_id(self):
        """Envelope routing_id = 'manual::<event_type>'."""
        envelope = build_manual_envelope(
            event_type=MANUAL_OVERRIDE,
            data={},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert envelope.routing_id == "manual::MANUAL_OVERRIDE"

    def test_envelope_payload_contains_manual_source_tag(self):
        """Envelope payload has manual_source_tag for downstream traceability."""
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={"event": "expiry"},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert envelope.payload["manual_source_tag"] == "operator"

    def test_envelope_payload_preserves_original_data(self):
        """Original data fields are preserved inside the envelope payload."""
        data = {"date": "2026-06-10", "event": "NIFTY expiry", "source": "NSE"}
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data=data,
            source_tag="operator",
            connection_id="conn_test",
        )
        assert envelope.payload["date"] == "2026-06-10"
        assert envelope.payload["event"] == "NIFTY expiry"
        assert envelope.payload["source"] == "NSE"

    def test_invalid_event_type_raises_validation_error(self):
        """build_manual_envelope with invalid event_type → ValidationError."""
        with pytest.raises(ValidationError):
            build_manual_envelope(
                event_type="BAD_TYPE",
                data={},
                source_tag="operator",
                connection_id="conn_test",
            )

    def test_source_timestamp_preserved(self):
        """source_timestamp is preserved in the envelope."""
        ts = datetime(2026, 6, 10, 9, 15, 0, tzinfo=timezone.utc)
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={"event": "test"},
            source_tag="operator",
            connection_id="conn_test",
            source_timestamp=ts,
        )
        assert envelope.source_timestamp == ts

    def test_source_timestamp_none_by_default(self):
        """source_timestamp is None when not provided."""
        envelope = build_manual_envelope(
            event_type=MANUAL_CALENDAR,
            data={"event": "test"},
            source_tag="operator",
            connection_id="conn_test",
        )
        assert envelope.source_timestamp is None

    def test_packet_id_unique_per_call(self):
        """Each call to build_manual_envelope produces a unique packet_id."""
        ids = set()
        for _ in range(100):
            envelope = build_manual_envelope(
                event_type=MANUAL_CALENDAR,
                data={"i": _},
                source_tag="uniq_test",
                connection_id="conn_test",
            )
            ids.add(envelope.packet_id)
        assert len(ids) == 100
