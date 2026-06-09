"""Tests for floor2_handoff.py — Floor 1 → Floor 2 handoff (Step 1.9)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from junior_aladdin.floor_1_connection.floor2_handoff import (
    Floor2HandoffService,
    REQUIRED_KEYS,
)
from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.types import FeedType, Floor2Handoff, PacketEnvelope


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def service() -> Floor2HandoffService:
    """Fresh service instance per test."""
    return Floor2HandoffService()


@pytest.fixture
def sample_envelope() -> PacketEnvelope:
    """A sample PacketEnvelope for test payloads."""
    return PacketEnvelope(
        source="angel_one",
        feed_type="spot_tick",
        connection_id="conn_test_001",
        packet_id="pkt_test_abc123",
        routing_id="angel_one::spot_tick",
        received_at=datetime(2026, 6, 10, 9, 15, 0, tzinfo=timezone.utc),
        payload={"ltp": 19500.0, "volume": 25000},
    )


@pytest.fixture
def live_ingress_payload(sample_envelope) -> dict:
    """Simulated ingress payload for a live Angel One spot tick."""
    return {
        "source_name": "angel_one",
        "feed_type": "spot_tick",
        "raw_data": {"ltp": 19500.0, "volume": 25000},
        "envelope": sample_envelope,
        "routing_identity": FeedType.SPOT_FEED,
        "health_facts": {
            "lifecycle_state": "HEALTHY",
            "is_connected": True,
        },
        "manual_source_tag": None,
    }


@pytest.fixture
def manual_ingress_payload(sample_envelope) -> dict:
    """Simulated ingress payload for a MANUAL_CALENDAR packet."""
    return {
        "source_name": "manual",
        "feed_type": "MANUAL_CALENDAR",
        "raw_data": {"date": "2026-06-10", "event": "NIFTY expiry"},
        "envelope": PacketEnvelope(
            source="manual",
            feed_type="MANUAL_CALENDAR",
            connection_id="conn_manual_001",
            packet_id="pkt_manual_xyz",
            routing_id="manual::MANUAL_CALENDAR",
            received_at=datetime(2026, 6, 10, 9, 15, 0, tzinfo=timezone.utc),
            payload={"manual_source_tag": "manual_ingress", "date": "2026-06-10"},
        ),
        "routing_identity": None,
        "health_facts": None,
        "manual_source_tag": "manual_ingress",
    }


# =============================================================================
# Test: All 5 families — Live data
# =============================================================================


class TestLiveHandoff:
    """Live data handoff assembles all 5 families correctly."""

    def test_returns_floor2handoff_instance(self, service, live_ingress_payload):
        """send_to_floor2 returns a Floor2Handoff dataclass."""
        result = service.send_to_floor2(live_ingress_payload)
        assert isinstance(result, Floor2Handoff)

    def test_family_1_original_raw_packet(self, service, live_ingress_payload):
        """original_raw_packet preserves the raw data as-is."""
        result = service.send_to_floor2(live_ingress_payload)
        assert result.original_raw_packet == {"ltp": 19500.0, "volume": 25000}

    def test_family_2_minimal_source_envelope(self, service, live_ingress_payload):
        """minimal_source_envelope has all governance fields."""
        result = service.send_to_floor2(live_ingress_payload)
        env = result.minimal_source_envelope
        assert env["source"] == "angel_one"
        assert env["feed_type"] == "spot_tick"
        assert env["connection_id"] == "conn_test_001"
        assert env["packet_id"] == "pkt_test_abc123"
        assert env["routing_id"] == "angel_one::spot_tick"
        assert env["received_at"] is not None

    def test_family_3_feed_routing_identity(self, service, live_ingress_payload):
        """feed_routing_identity = 'SPOT_FEED' for spot_tick."""
        result = service.send_to_floor2(live_ingress_payload)
        assert result.feed_routing_identity == "SPOT_FEED"

    def test_family_4_source_health_facts(self, service, live_ingress_payload):
        """source_health_facts populated for live data."""
        result = service.send_to_floor2(live_ingress_payload)
        assert result.source_health_facts["lifecycle_state"] == "HEALTHY"
        assert result.source_health_facts["is_connected"] is True

    def test_family_5_manual_source_tags_none_for_live(self, service, live_ingress_payload):
        """manual_source_tags is None for live (non-manual) data."""
        result = service.send_to_floor2(live_ingress_payload)
        assert result.manual_source_tags is None

    def test_all_5_families_present_for_live(self, service, live_ingress_payload):
        """All 5 families are present and correctly typed in live handoff."""
        result = service.send_to_floor2(live_ingress_payload)
        assert isinstance(result.original_raw_packet, dict)
        assert isinstance(result.minimal_source_envelope, dict)
        assert isinstance(result.feed_routing_identity, str)
        assert isinstance(result.source_health_facts, dict)
        assert result.manual_source_tags is None or isinstance(result.manual_source_tags, dict)


# =============================================================================
# Test: All 5 families — Manual data
# =============================================================================


class TestManualHandoff:
    """Manual data handoff assembles all 5 families correctly."""

    def test_family_1_original_raw_packet(self, service, manual_ingress_payload):
        """original_raw_packet preserves the manual data as-is."""
        result = service.send_to_floor2(manual_ingress_payload)
        assert result.original_raw_packet == {"date": "2026-06-10", "event": "NIFTY expiry"}

    def test_family_2_minimal_source_envelope(self, service, manual_ingress_payload):
        """minimal_source_envelope shows manual source correctly."""
        result = service.send_to_floor2(manual_ingress_payload)
        env = result.minimal_source_envelope
        assert env["source"] == "manual"
        assert env["feed_type"] == "MANUAL_CALENDAR"

    def test_family_3_feed_routing_identity_empty_for_manual(self, service, manual_ingress_payload):
        """feed_routing_identity is empty string for manual packets."""
        result = service.send_to_floor2(manual_ingress_payload)
        assert result.feed_routing_identity == ""

    def test_family_4_source_health_facts_empty_for_manual(self, service, manual_ingress_payload):
        """source_health_facts is empty dict for manual packets."""
        result = service.send_to_floor2(manual_ingress_payload)
        assert result.source_health_facts == {}

    def test_family_5_manual_source_tags_populated(self, service, manual_ingress_payload):
        """manual_source_tags is populated for manual data."""
        result = service.send_to_floor2(manual_ingress_payload)
        assert result.manual_source_tags == {"manual_source_tag": "manual_ingress"}

    def test_all_5_families_present_for_manual(self, service, manual_ingress_payload):
        """All 5 families are present in manual handoff."""
        result = service.send_to_floor2(manual_ingress_payload)
        assert isinstance(result.original_raw_packet, dict)
        assert isinstance(result.minimal_source_envelope, dict)
        assert isinstance(result.feed_routing_identity, str)
        assert isinstance(result.source_health_facts, dict)
        assert isinstance(result.manual_source_tags, dict)


# =============================================================================
# Test: Validation — ContractViolationError
# =============================================================================


class TestValidation:
    """Missing or invalid fields raise ContractViolationError."""

    def test_missing_key_raises_error(self, service, live_ingress_payload):
        """Missing a required key → ContractViolationError."""
        incomplete = {k: v for k, v in live_ingress_payload.items() if k != "envelope"}
        with pytest.raises(ContractViolationError) as exc:
            service.send_to_floor2(incomplete)
        assert "missing" in str(exc.value).lower()

    def test_error_includes_missing_keys(self, service, live_ingress_payload):
        """Error message lists the missing keys."""
        incomplete = {k: v for k, v in live_ingress_payload.items() if k != "raw_data"}
        with pytest.raises(ContractViolationError) as exc:
            service.send_to_floor2(incomplete)
        assert "raw_data" in str(exc.value)

    def test_envelope_must_be_packetenvelope(self, service, live_ingress_payload):
        """Non-PacketEnvelope envelope → ContractViolationError."""
        bad_payload = dict(live_ingress_payload)
        bad_payload["envelope"] = {"source": "not_an_envelope"}
        with pytest.raises(ContractViolationError) as exc:
            service.send_to_floor2(bad_payload)
        assert "PacketEnvelope" in str(exc.value)

    def test_raw_data_must_be_dict(self, service, live_ingress_payload):
        """Non-dict raw_data → ContractViolationError."""
        bad_payload = dict(live_ingress_payload)
        bad_payload["raw_data"] = "not_a_dict"
        with pytest.raises(ContractViolationError):
            service.send_to_floor2(bad_payload)

    def test_empty_payload_raises_error(self, service):
        """Completely empty payload → ContractViolationError."""
        with pytest.raises(ContractViolationError):
            service.send_to_floor2({})

    def test_all_required_keys_defined(self):
        """REQUIRED_KEYS matches the 7 expected keys."""
        expected = {
            "source_name",
            "feed_type",
            "raw_data",
            "envelope",
            "routing_identity",
            "health_facts",
            "manual_source_tag",
        }
        assert REQUIRED_KEYS == expected


# =============================================================================
# Test: Feed routing identities
# =============================================================================


class TestFeedRoutingIdentity:
    """FeedType enum values mapped correctly to strings."""

    @pytest.mark.parametrize(
        ("feed_type", "feed_enum", "expected_string"),
        [
            ("spot_tick", FeedType.SPOT_FEED, "SPOT_FEED"),
            ("options_snapshot", FeedType.OPTIONS_FEED, "OPTIONS_FEED"),
            ("vix_tick", FeedType.VIX_FEED, "VIX_FEED"),
            ("macro_data", FeedType.MACRO_FEED, "MACRO_FEED"),
            ("calendar_event", FeedType.CALENDAR_FEED, "CALENDAR_FEED"),
        ],
    )
    def test_routing_identity_string(
        self,
        service,
        sample_envelope,
        feed_type,
        feed_enum,
        expected_string,
    ):
        """Each FeedType enum maps to its expected string value."""
        payload = {
            "source_name": "angel_one",
            "feed_type": feed_type,
            "raw_data": {},
            "envelope": PacketEnvelope(
                source="angel_one",
                feed_type=feed_type,
                connection_id="conn_test",
                packet_id="pkt_test",
                routing_id=f"angel_one::{feed_type}",
                received_at=datetime.now(timezone.utc),
            ),
            "routing_identity": feed_enum,
            "health_facts": {"lifecycle_state": "HEALTHY"},
            "manual_source_tag": None,
        }
        result = service.send_to_floor2(payload)
        assert result.feed_routing_identity == expected_string


# =============================================================================
# Test: Handoff tracking
# =============================================================================


class TestHandoffTracking:
    """Service tracks handoff history."""

    def test_handoff_count_increments(self, service, live_ingress_payload):
        """Each send_to_floor2 call increments handoff_count."""
        assert service.handoff_count == 0
        service.send_to_floor2(live_ingress_payload)
        assert service.handoff_count == 1
        service.send_to_floor2(live_ingress_payload)
        assert service.handoff_count == 2

    def test_last_handoff_returns_most_recent(self, service, live_ingress_payload, manual_ingress_payload):
        """last_handoff returns the most recently processed handoff."""
        service.send_to_floor2(live_ingress_payload)
        service.send_to_floor2(manual_ingress_payload)
        last = service.last_handoff
        assert last is not None
        assert last.manual_source_tags is not None  # it was the manual one

    def test_last_handoff_none_when_empty(self, service):
        """last_handoff is None when no handoffs have been processed."""
        assert service.last_handoff is None

    def test_no_store_when_disabled(self):
        """When store_handoffs=False, handoff_count stays 0 and last_handoff is None."""
        svc = Floor2HandoffService(store_handoffs=False)
        assert svc.handoff_count == 0
        assert svc.last_handoff is None


# =============================================================================
# Test: Integration — direct use as IngressRouter handoff callback
# =============================================================================


class TestAsIngressRouterCallback:
    """Floor2HandoffService.send_to_floor2 is compatible with IngressRouter.on_handoff."""

    def test_can_register_as_router_callback(self, service):
        """send_to_floor2 is a callable accepting a single dict argument."""
        # IngressRouter.on_handoff expects HandoffCallback = Callable[[dict], None]
        assert callable(service.send_to_floor2)

    def test_callable_accepts_dict_and_returns_floor2handoff(
        self, service, live_ingress_payload
    ):
        """When called as a callback, send_to_floor2 returns Floor2Handoff."""
        result = service.send_to_floor2(live_ingress_payload)
        assert isinstance(result, Floor2Handoff)


# =============================================================================
# Test: minimal_source_envelope timestamp format
# =============================================================================


class TestTimestampFormat:
    """Timestamps in minimal_source_envelope are ISO-formatted strings."""

    def test_received_at_is_iso_string(self, service, live_ingress_payload):
        """received_at is converted to ISO format string."""
        result = service.send_to_floor2(live_ingress_payload)
        received = result.minimal_source_envelope["received_at"]
        assert isinstance(received, str)
        # Should parse as valid ISO datetime
        parsed = datetime.fromisoformat(received)
        assert parsed is not None

    def test_source_timestamp_not_in_envelope(self, service, live_ingress_payload):
        """minimal_source_envelope does not include source_timestamp or payload."""
        envelope_dict = service.send_to_floor2(live_ingress_payload).minimal_source_envelope
        assert "source_timestamp" not in envelope_dict
        assert "payload" not in envelope_dict
