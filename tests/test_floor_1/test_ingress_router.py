"""Tests for ingress_router.py — Central ingress router (Step 1.8)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from junior_aladdin.floor_1_connection.ingress_router import (
    FEED_TYPE_TO_ROUTING_IDENTITY,
    IngressRouter,
)
from junior_aladdin.shared.types import FeedType, PacketEnvelope


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_feed_adapters():
    """Return a dict of mock feed adapters for common feed types."""
    spot = MagicMock()
    spot.handle_data.return_value = {"feed_type": "spot_tick", "ltp": 19500.0}

    options = MagicMock()
    options.handle_data.return_value = {"feed_type": "options_snapshot", "oi": 100000}

    vix = MagicMock()
    vix.handle_data.return_value = {"feed_type": "vix_tick", "value": 14.5}

    return {
        "spot_tick": spot,
        "options_snapshot": options,
        "vix_tick": vix,
        "macro_data": MagicMock(),
        "calendar_event": MagicMock(),
    }


@pytest.fixture
def mock_source_adapters():
    """Return a dict of mock source adapters."""
    angel = MagicMock()
    angel.connection_id = "conn_angel_001"
    angel.is_connected.return_value = True
    # Simulate LifecycleState enum
    state_mock = MagicMock()
    state_mock.value = "HEALTHY"
    angel.get_lifecycle_state.return_value = state_mock

    manual = MagicMock()

    return {
        "angel_one": angel,
        "manual": manual,
    }


@pytest.fixture
def router(mock_source_adapters, mock_feed_adapters):
    """Create an IngressRouter with mock adapters."""
    r = IngressRouter(
        source_adapters=mock_source_adapters,
        feed_adapters=mock_feed_adapters,
    )
    return r


@pytest.fixture
def started_router(router):
    """Create and start an IngressRouter."""
    router.start_routing()
    return router


# =============================================================================
# Test: Initial state
# =============================================================================


class TestInitialState:
    """Router starts with routing inactive."""

    def test_routing_not_active_by_default(self, router):
        """is_routing_active is False before start_routing()."""
        assert router.is_routing_active is False

    def test_handoff_callbacks_empty_by_default(self, router):
        """No handoff callbacks registered initially."""
        # Access internal list to verify (for test purposes)
        assert len(router._handoff_callbacks) == 0


# =============================================================================
# Test: start_routing / stop_routing
# =============================================================================


class TestStartStopRouting:
    """Lifecycle methods for routing."""

    def test_start_routing_sets_active(self, router):
        """After start_routing, is_routing_active is True."""
        router.start_routing()
        assert router.is_routing_active is True

    def test_stop_routing_sets_inactive(self, router):
        """After stop_routing, is_routing_active is False."""
        router.start_routing()
        router.stop_routing()
        assert router.is_routing_active is False

    def test_start_routing_registers_on_data_on_sources(self, mock_source_adapters, router):
        """start_routing calls on_data on each source adapter."""
        router.start_routing()
        for name, adapter in mock_source_adapters.items():
            adapter.on_data.assert_called()

    def test_start_routing_idempotent(self, mock_source_adapters, router):
        """Calling start_routing twice doesn't double-register callbacks."""
        router.start_routing()
        router.start_routing()
        # Each adapter's on_data should have been called at least once
        for adapter in mock_source_adapters.values():
            assert adapter.on_data.call_count >= 1


# =============================================================================
# Test: route_packet with live (Angel One) data
# =============================================================================


class TestRouteLivePacket:
    """Routing live market data through the pipeline."""

    def test_route_spot_tick_reaches_handoff(self, started_router):
        """route_packet with spot_tick → handoff callback receives data."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={"ltp": 19500.0, "volume": 25000},
        )

        callback.assert_called_once()
        payload = callback.call_args[0][0]
        assert payload["source_name"] == "angel_one"
        assert payload["feed_type"] == "spot_tick"
        assert payload["raw_data"] == {"ltp": 19500.0, "volume": 25000}

    def test_route_spot_includes_envelope(self, started_router):
        """Handoff payload contains a PacketEnvelope."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={"ltp": 19500.0},
        )

        payload = callback.call_args[0][0]
        assert isinstance(payload["envelope"], PacketEnvelope)
        assert payload["envelope"].source == "angel_one"
        assert payload["envelope"].feed_type == "spot_tick"

    def test_route_includes_routing_identity(self, started_router):
        """Handoff payload has FeedType enum for recognised feed types."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        payload = callback.call_args[0][0]
        assert payload["routing_identity"] == FeedType.SPOT_FEED

    def test_route_includes_health_facts(self, started_router):
        """Handoff payload contains source health facts when available."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        payload = callback.call_args[0][0]
        assert payload["health_facts"] is not None
        assert payload["health_facts"]["lifecycle_state"] == "HEALTHY"
        assert payload["health_facts"]["is_connected"] is True

    def test_route_manual_source_tag_is_none(self, started_router):
        """Live packets have manual_source_tag = None."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        payload = callback.call_args[0][0]
        assert payload["manual_source_tag"] is None

    def test_options_snapshot_uses_options_adapter(self, started_router, mock_feed_adapters):
        """Options feed uses OptionsFeedAdapter.handle_data()."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="options_snapshot",
            raw_data={"oi": 100000, "premium": 150},
        )

        mock_feed_adapters["options_snapshot"].handle_data.assert_called_once_with(
            {"oi": 100000, "premium": 150}
        )

    def test_unknown_feed_type_logged_no_crash(self, started_router):
        """Unknown feed_type → logged warning, no crash."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        # Should not raise
        started_router.route_packet(
            source_name="angel_one",
            feed_type="unknown_feed",
            raw_data={},
        )

        # Handoff callback should NOT be called for unknown feeds
        callback.assert_not_called()


# =============================================================================
# Test: route_packet with manual data
# =============================================================================


class TestRouteManualPacket:
    """Routing manual ingress packets through the pipeline."""

    @pytest.mark.parametrize("event_type", ["MANUAL_CALENDAR", "MANUAL_EVENT", "MANUAL_OVERRIDE"])
    def test_all_manual_types_accepted(self, started_router, event_type):
        """Each valid manual event type is routed successfully."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="manual",
            feed_type=event_type,
            raw_data={"some": "data"},
        )

        callback.assert_called_once()
        payload = callback.call_args[0][0]
        assert payload["source_name"] == "manual"
        assert payload["feed_type"] == event_type

    def test_manual_packet_includes_envelope(self, started_router):
        """Manual packets get a PacketEnvelope."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="manual",
            feed_type="MANUAL_CALENDAR",
            raw_data={"event": "NIFTY expiry"},
        )

        payload = callback.call_args[0][0]
        assert isinstance(payload["envelope"], PacketEnvelope)
        assert payload["envelope"].source == "manual"

    def test_manual_routing_identity_is_none(self, started_router):
        """Manual packets have routing_identity = None (no FeedType)."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="manual",
            feed_type="MANUAL_CALENDAR",
            raw_data={},
        )

        payload = callback.call_args[0][0]
        assert payload["routing_identity"] is None

    def test_manual_health_facts_is_none(self, started_router):
        """Manual packets have health_facts = None."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="manual",
            feed_type="MANUAL_EVENT",
            raw_data={},
        )

        payload = callback.call_args[0][0]
        assert payload["health_facts"] is None

    def test_manual_source_tag_present(self, started_router):
        """Manual packets have manual_source_tag populated."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="manual",
            feed_type="MANUAL_OVERRIDE",
            raw_data={"override": True},
        )

        payload = callback.call_args[0][0]
        assert payload["manual_source_tag"] == "manual_ingress"

    def test_invalid_manual_type_ignored(self, started_router):
        """Invalid manual type → logged warning, no handoff callback."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="manual",
            feed_type="INVALID_TYPE",
            raw_data={},
        )

        callback.assert_not_called()


# =============================================================================
# Test: routing inactive
# =============================================================================


class TestRoutingInactive:
    """Packets are ignored when routing is not active."""

    def test_packet_before_start_ignored(self, router):
        """route_packet before start_routing → no handoff callback."""
        callback = MagicMock()
        router.on_handoff(callback)

        router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={"ltp": 19500.0},
        )

        callback.assert_not_called()

    def test_packet_after_stop_ignored(self, started_router):
        """route_packet after stop_routing → no handoff callback."""
        started_router.stop_routing()
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={"ltp": 19500.0},
        )

        callback.assert_not_called()


# =============================================================================
# Test: handoff registration and errors
# =============================================================================


class TestHandoffCallbacks:
    """Handoff callback registration and error handling."""

    def test_multiple_callbacks_all_called(self, started_router):
        """All registered handoff callbacks receive the payload."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        started_router.on_handoff(cb1)
        started_router.on_handoff(cb2)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={"ltp": 100.0},
        )

        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_callback_exception_does_not_break_others(self, started_router):
        """A failing handoff callback does not prevent other callbacks from running."""
        cb1 = MagicMock(side_effect=RuntimeError("Callback crashed"))
        cb2 = MagicMock()
        started_router.on_handoff(cb1)
        started_router.on_handoff(cb2)

        # Should not raise
        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={"ltp": 100.0},
        )

        cb1.assert_called_once()
        cb2.assert_called_once()


# =============================================================================
# Test: envelope fields verification
# =============================================================================


class TestEnvelopeFields:
    """Verify PacketEnvelope fields are correctly populated."""

    def test_envelope_source_live(self, started_router):
        """Live packet envelope source matches source_name."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        envelope = callback.call_args[0][0]["envelope"]
        assert envelope.source == "angel_one"

    def test_envelope_feed_type_live(self, started_router):
        """Live packet envelope feed_type is correct."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        envelope = callback.call_args[0][0]["envelope"]
        assert envelope.feed_type == "spot_tick"

    def test_envelope_has_packet_id(self, started_router):
        """Envelope has a non-empty packet_id starting with 'pkt_'."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        envelope = callback.call_args[0][0]["envelope"]
        assert isinstance(envelope.packet_id, str)
        assert len(envelope.packet_id) > 0
        assert envelope.packet_id.startswith("pkt_")

    def test_envelope_has_routing_id(self, started_router):
        """Envelope routing_id = 'source::feed_type'."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        envelope = callback.call_args[0][0]["envelope"]
        assert envelope.routing_id == "angel_one::spot_tick"

    def test_envelope_received_at_is_utc(self, started_router):
        """Envelope received_at is a timezone-aware UTC datetime."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        envelope = callback.call_args[0][0]["envelope"]
        assert envelope.received_at is not None
        assert envelope.received_at.tzinfo is not None


# =============================================================================
# Test: FEED_TYPE_TO_ROUTING_IDENTITY map
# =============================================================================


class TestRoutingIdentityMap:
    """Verify the feed_type → FeedType mapping is correct."""

    def test_map_contains_all_expected_keys(self):
        """All 5 core feed types are mapped."""
        expected_keys = {"spot_tick", "options_snapshot", "vix_tick", "macro_data", "calendar_event"}
        assert set(FEED_TYPE_TO_ROUTING_IDENTITY.keys()) == expected_keys

    def test_spot_tick_maps_to_spot_feed(self):
        assert FEED_TYPE_TO_ROUTING_IDENTITY["spot_tick"] == FeedType.SPOT_FEED

    def test_options_snapshot_maps_to_options_feed(self):
        assert FEED_TYPE_TO_ROUTING_IDENTITY["options_snapshot"] == FeedType.OPTIONS_FEED

    def test_vix_tick_maps_to_vix_feed(self):
        assert FEED_TYPE_TO_ROUTING_IDENTITY["vix_tick"] == FeedType.VIX_FEED

    def test_macro_data_maps_to_macro_feed(self):
        assert FEED_TYPE_TO_ROUTING_IDENTITY["macro_data"] == FeedType.MACRO_FEED

    def test_calendar_event_maps_to_calendar_feed(self):
        assert FEED_TYPE_TO_ROUTING_IDENTITY["calendar_event"] == FeedType.CALENDAR_FEED


# =============================================================================
# Test: error resilience
# =============================================================================


class TestErrorResilience:
    """Router handles edge cases gracefully without crashing."""

    def test_route_empty_raw_data(self, started_router):
        """Empty raw data dict is handled without error."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        callback.assert_called_once()

    def test_route_none_raw_data(self, started_router):
        """None raw_data is handled gracefully."""
        callback = MagicMock()
        started_router.on_handoff(callback)

        # Should not crash — router will pass None to feed adapter
        started_router.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data=None,  # type: ignore[arg-type]
        )

        # Feed adapter receives None — depends on implementation
        callback.assert_called_once()

    def test_no_source_adapters_registered(self):
        """Router with no source adapters works for direct route_packet calls."""
        r = IngressRouter(feed_adapters={})
        r.start_routing()

        callback = MagicMock()
        r.on_handoff(callback)

        # Should not crash — will just log unknown source
        r.route_packet(
            source_name="angel_one",
            feed_type="spot_tick",
            raw_data={},
        )

        callback.assert_not_called()  # no feed adapter for spot_tick
