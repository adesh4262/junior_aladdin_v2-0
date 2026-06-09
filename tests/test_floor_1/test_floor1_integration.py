"""Floor 1 Full Integration Test (Step 1.10).

Exercises the complete Floor 1 chain end-to-end with mocked Angel One SDK:

    1. auth_manager.login() → token obtained
    2. source_adapters.AngelOneAdapter.connect() → connected, state = HEALTHY
    3. subscribe_feeds → feeds registered
    4. _receive_data → ingress_router.route_packet → feed adapter → envelope → handoff
    5. floor2_handoff.send_to_floor2 → all 5 families present
    6. Simulate disconnect → source_health: HEALTHY → DISCONNECTED
    7. Reconnect → DISCONNECTED → HEALTHY
    8. Manual ingress → manual packet with envelope
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from junior_aladdin.floor_1_connection.auth_manager import AuthManager
from junior_aladdin.floor_1_connection.feed_adapters import (
    CalendarFeedAdapter,
    MacroFeedAdapter,
    OptionsFeedAdapter,
    SpotFeedAdapter,
    VixFeedAdapter,
)
from junior_aladdin.floor_1_connection.floor2_handoff import Floor2HandoffService
from junior_aladdin.floor_1_connection.ingress_router import IngressRouter
from junior_aladdin.floor_1_connection.manual_ingress import (
    MANUAL_CALENDAR,
    MANUAL_EVENT,
    MANUAL_OVERRIDE,
)
from junior_aladdin.floor_1_connection.source_adapters import (
    AngelOneAdapter,
    ManualSourceAdapter,
)
from junior_aladdin.floor_1_connection.source_health import SourceHealthMonitor
from junior_aladdin.shared.errors import ConnectionError
from junior_aladdin.shared.types import FeedType, LifecycleState


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def mock_smart_connect():
    """Mock SmartApi.SmartConnect for all integration tests.

    Returns a (mock_class, mock_instance) tuple so tests can configure
    return values and side effects.
    """
    with patch("SmartApi.SmartConnect") as mock_smart:
        mock_instance = MagicMock()
        mock_smart.return_value = mock_instance

        # Default: successful login response
        mock_instance.generateSession.return_value = {
            "data": {
                "accessToken": "test_access_token_123",
                "refreshToken": "test_refresh_token_456",
                "feedToken": "test_feed_token_789",
                "userProfile": {
                    "clientID": "TEST001",
                    "name": "Test User",
                },
            }
        }
        # Default: successful token refresh
        mock_instance.generateToken.return_value = {
            "data": {
                "accessToken": "refreshed_token_abc",
            }
        }

        yield mock_smart, mock_instance


@pytest.fixture
def test_config(test_config):
    """Configure test config with mock Angel One credentials."""
    test_config._data["angel_one"] = {
        "client_id": "TEST001",
        "api_key": "test_api_key_12345",
        "pin": "test_pin_67890",
    }
    return test_config


@pytest.fixture
def auth_manager(test_config) -> AuthManager:
    """Create AuthManager with test config (mock credentials set)."""
    return AuthManager(config=test_config)


@pytest.fixture
def health_monitor() -> SourceHealthMonitor:
    """Create a real SourceHealthMonitor for testing."""
    return SourceHealthMonitor(connection_id="conn_integration_test")


@pytest.fixture
def angel_one_adapter(auth_manager, health_monitor) -> AngelOneAdapter:
    """Create a real AngelOneAdapter with mocked auth."""
    return AngelOneAdapter(auth_manager=auth_manager, health_monitor=health_monitor)


@pytest.fixture
def manual_adapter() -> ManualSourceAdapter:
    """Create a real ManualSourceAdapter."""
    return ManualSourceAdapter()


@pytest.fixture
def spot_feed() -> SpotFeedAdapter:
    return SpotFeedAdapter()


@pytest.fixture
def options_feed() -> OptionsFeedAdapter:
    return OptionsFeedAdapter()


@pytest.fixture
def vix_feed() -> VixFeedAdapter:
    return VixFeedAdapter()


@pytest.fixture
def macro_feed() -> MacroFeedAdapter:
    return MacroFeedAdapter()


@pytest.fixture
def calendar_feed() -> CalendarFeedAdapter:
    return CalendarFeedAdapter()


@pytest.fixture
def router(
    angel_one_adapter,
    manual_adapter,
    spot_feed,
    options_feed,
    vix_feed,
    macro_feed,
    calendar_feed,
) -> IngressRouter:
    """Create a real IngressRouter with all real adapters."""
    router = IngressRouter(
        source_adapters={
            "angel_one": angel_one_adapter,
            "manual": manual_adapter,
        },
        feed_adapters={
            "spot_tick": spot_feed,
            "options_snapshot": options_feed,
            "vix_tick": vix_feed,
            "macro_data": macro_feed,
            "calendar_event": calendar_feed,
        },
    )
    return router


@pytest.fixture
def handoff_service() -> Floor2HandoffService:
    """Create a real Floor2HandoffService."""
    return Floor2HandoffService()


@pytest.fixture
def integration_chain(router, handoff_service):
    """Wire up the full integration chain: router → handoff."""
    router.on_handoff(handoff_service.send_to_floor2)
    router.start_routing()
    return router, handoff_service


# =============================================================================
# Test: 1. Auth + Connect Chain
# =============================================================================


class TestAuthAndConnect:
    """AuthManager.login() + AngelOneAdapter.connect()."""

    def test_login_obtains_token(self, auth_manager):
        """auth_manager.login() returns a non-None token."""
        token = auth_manager.login()
        assert token is not None
        assert token == "test_access_token_123"
        assert auth_manager.is_authenticated() is True

    def test_connect_sets_healthy(self, angel_one_adapter):
        """AngelOneAdapter.connect() → state = HEALTHY."""
        connected = angel_one_adapter.connect()
        assert connected is True
        assert angel_one_adapter.is_connected() is True
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.HEALTHY

    def test_self_healing_state_machine(self, angel_one_adapter):
        """Full lifecycle: HEALTHY → DISCONNECTED → HEALTHY."""
        angel_one_adapter.connect()
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.HEALTHY

        angel_one_adapter.disconnect()
        assert angel_one_adapter.is_connected() is False
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.DISCONNECTED

        angel_one_adapter.reconnect()
        assert angel_one_adapter.is_connected() is True
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.HEALTHY


# =============================================================================
# Test: 2. Live Packet → Full Chain
# =============================================================================


class TestLiveSpotTickChain:
    """End-to-end: spot tick → route_packet → feed adapter → envelope → handoff."""

    def test_full_chain_produces_handoff(self, integration_chain):
        """A spot tick flows through the entire chain and produces a Floor2Handoff."""
        router, handoff = integration_chain
        mock_tick = {"ltp": 19500.0, "volume": 25000, "symbol": "NIFTY"}

        # First connect the adapter
        router._source_adapters["angel_one"].connect()

        # Route the packet
        router.route_packet("angel_one", "spot_tick", mock_tick)

        # Verify handoff was produced
        assert handoff.handoff_count == 1
        result = handoff.last_handoff
        assert result is not None

    def test_live_handoff_all_5_families(self, integration_chain):
        """Live handoff contains all 5 payload families."""
        router, handoff = integration_chain
        mock_tick = {"ltp": 19500.0, "volume": 25000}

        router._source_adapters["angel_one"].connect()
        router.route_packet("angel_one", "spot_tick", mock_tick)

        result = handoff.last_handoff

        # Family 1: original_raw_packet
        assert result.original_raw_packet == {"ltp": 19500.0, "volume": 25000}

        # Family 2: minimal_source_envelope
        env = result.minimal_source_envelope
        assert env["source"] == "angel_one"
        assert env["feed_type"] == "spot_tick"
        assert "packet_id" in env
        assert "routing_id" in env
        assert "received_at" in env

        # Family 3: feed_routing_identity
        assert result.feed_routing_identity == "SPOT_FEED"

        # Family 4: source_health_facts
        assert result.source_health_facts["lifecycle_state"] == "HEALTHY"

        # Family 5: manual_source_tags = None for live
        assert result.manual_source_tags is None

    def test_options_feed_routing_identity(self, integration_chain):
        """Options snapshot → routing_identity = OPTIONS_FEED."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()
        router.route_packet("angel_one", "options_snapshot", {"oi": 100000})

        result = handoff.last_handoff
        assert result.feed_routing_identity == "OPTIONS_FEED"

    def test_vix_feed_routing_identity(self, integration_chain):
        """VIX tick → routing_identity = VIX_FEED."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()
        router.route_packet("angel_one", "vix_tick", {"value": 14.5})

        result = handoff.last_handoff
        assert result.feed_routing_identity == "VIX_FEED"

    def test_envelope_packet_id_unique_per_packet(self, integration_chain):
        """Each routed packet gets a unique packet_id."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()

        ids = []
        for i in range(10):
            router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0 + i})
            ids.append(handoff.last_handoff.minimal_source_envelope["packet_id"])

        assert len(set(ids)) == 10

    def test_health_facts_after_disconnect(self, integration_chain):
        """Health facts from route_packet reflect disconnected state after disconnect."""
        router, handoff = integration_chain
        adapter = router._source_adapters["angel_one"]
        adapter.connect()
        adapter.disconnect()

        # route_packet reads live adapter state for health facts
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})

        result = handoff.last_handoff
        assert result.source_health_facts["is_connected"] is False
        assert result.source_health_facts["lifecycle_state"] == "DISCONNECTED"


# =============================================================================
# Test: 3. Manual Ingress Chain
# =============================================================================


class TestManualIngressChain:
    """Manual packets flow through the full chain."""

    def test_manual_calendar_all_5_families(self, integration_chain):
        """Manual CALENDAR packet → all 5 families with manual_source_tags populated."""
        router, handoff = integration_chain
        manual_data = {"date": "2026-06-10", "event": "NIFTY expiry"}

        router.route_packet("manual", MANUAL_CALENDAR, manual_data)

        assert handoff.handoff_count == 1
        result = handoff.last_handoff

        # Family 1
        assert result.original_raw_packet == manual_data

        # Family 2
        assert result.minimal_source_envelope["source"] == "manual"
        assert result.minimal_source_envelope["feed_type"] == MANUAL_CALENDAR

        # Family 3 — empty for manual
        assert result.feed_routing_identity == ""

        # Family 4 — empty for manual
        assert result.source_health_facts == {}

        # Family 5 — populated
        assert result.manual_source_tags == {"manual_source_tag": "manual_ingress"}

    @pytest.mark.parametrize(
        "event_type",
        [MANUAL_CALENDAR, MANUAL_EVENT, MANUAL_OVERRIDE],
    )
    def test_all_manual_types_work(self, integration_chain, event_type):
        """Each manual event type produces a valid handoff."""
        router, handoff = integration_chain
        router.route_packet("manual", event_type, {"test": True})

        assert handoff.handoff_count == 1
        result = handoff.last_handoff
        assert result.minimal_source_envelope["feed_type"] == event_type

    def test_manual_packets_have_unique_ids(self, integration_chain):
        """Each manual packet gets a unique packet_id."""
        router, handoff = integration_chain

        ids = []
        for _ in range(5):
            router.route_packet("manual", MANUAL_CALENDAR, {"i": _})
            ids.append(handoff.last_handoff.minimal_source_envelope["packet_id"])

        assert len(set(ids)) == 5


# =============================================================================
# Test: 4. Disconnect → Reconnect Chain
# =============================================================================


class TestGradualDegradation:
    """Gradual degradation path: HEALTHY → DEGRADED → STALE → DISCONNECTED."""

    def test_gradual_degradation_path(self, integration_chain):
        """HEALTHY → DEGRADED → STALE → DISCONNECTED via health monitor transitions."""
        router, handoff = integration_chain
        adapter = router._source_adapters["angel_one"]
        health = adapter._health

        # Start HEALTHY
        assert health.lifecycle_state == LifecycleState.HEALTHY

        # Degrade
        health.transition_to(LifecycleState.DEGRADED)
        assert health.lifecycle_state == LifecycleState.DEGRADED

        # Stale
        health.transition_to(LifecycleState.STALE)
        assert health.lifecycle_state == LifecycleState.STALE

        # Disconnected
        health.transition_to(LifecycleState.DISCONNECTED)
        assert health.lifecycle_state == LifecycleState.DISCONNECTED

        # Verify route_packet still works and reflects current health
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})
        result = handoff.last_handoff
        assert result.source_health_facts["lifecycle_state"] == "DISCONNECTED"

    def test_degradation_to_stale_to_disconnected_via_health_monitor(
        self, health_monitor
    ):
        """Real SourceHealthMonitor transitions through deterioration path."""
        assert health_monitor.lifecycle_state == LifecycleState.HEALTHY

        health_monitor.transition_to(LifecycleState.DEGRADED)
        assert health_monitor.lifecycle_state == LifecycleState.DEGRADED

        health_monitor.transition_to(LifecycleState.STALE)
        assert health_monitor.lifecycle_state == LifecycleState.STALE

        health_monitor.transition_to(LifecycleState.DISCONNECTED)
        assert health_monitor.lifecycle_state == LifecycleState.DISCONNECTED


class TestDisconnectReconnect:
    """Full disconnect/reconnect lifecycle."""

    def test_disconnect_changes_state(self, angel_one_adapter):
        """Disconnect → state = DISCONNECTED, is_connected = False."""
        angel_one_adapter.connect()
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.HEALTHY

        angel_one_adapter.disconnect()
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.DISCONNECTED
        assert angel_one_adapter.is_connected() is False

    def test_reconnect_restores_healthy(self, angel_one_adapter):
        """Reconnect after disconnect → state = HEALTHY."""
        angel_one_adapter.connect()
        angel_one_adapter.disconnect()
        angel_one_adapter.reconnect()

        assert angel_one_adapter.is_connected() is True
        assert angel_one_adapter.get_lifecycle_state() == LifecycleState.HEALTHY

    def test_packets_blocked_while_disconnected(self, integration_chain):
        """When adapter is disconnected, packets are blocked by _receive_data."""
        router, handoff = integration_chain
        adapter = router._source_adapters["angel_one"]
        adapter.connect()

        # Subscribe feeds so data would be forwarded
        adapter.subscribe_feeds(["spot_tick"])

        # Now disconnect
        adapter.disconnect()

        # Data received via adapter's _receive_data should be blocked
        # But route_packet called directly still works
        adapter._receive_data("spot_tick", {"ltp": 100.0})
        assert handoff.handoff_count == 0  # blocked by disconnected check

    def test_reconnect_restores_data_flow(self, integration_chain):
        """After reconnect, data flows through the chain normally."""
        router, handoff = integration_chain
        adapter = router._source_adapters["angel_one"]

        adapter.connect()
        adapter.disconnect()
        adapter.reconnect()

        # Now data should flow
        router.route_packet("angel_one", "spot_tick", {"ltp": 20000.0})
        assert handoff.handoff_count == 1
        assert handoff.last_handoff.original_raw_packet == {"ltp": 20000.0}


# =============================================================================
# Test: 5. Multiple Feed Types in One Chain
# =============================================================================


class TestMultiFeed:
    """Multiple feed types through the same chain."""

    def test_spot_and_options_both_work(self, integration_chain):
        """Spot tick and options snapshot both produce correct handoffs."""
        router, handoff = integration_chain
        adapter = router._source_adapters["angel_one"]
        adapter.connect()

        # Spot tick
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})
        assert handoff.last_handoff.feed_routing_identity == "SPOT_FEED"

        # Options snapshot
        router.route_packet("angel_one", "options_snapshot", {"oi": 100000})
        assert handoff.last_handoff.feed_routing_identity == "OPTIONS_FEED"

        # VIX tick
        router.route_packet("angel_one", "vix_tick", {"value": 14.5})
        assert handoff.last_handoff.feed_routing_identity == "VIX_FEED"

        assert handoff.handoff_count == 3

    def test_live_and_manual_interleaved(self, integration_chain):
        """Live and manual packets can be interleaved."""
        router, handoff = integration_chain
        adapter = router._source_adapters["angel_one"]
        adapter.connect()

        # Live spot
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})
        assert handoff.last_handoff.manual_source_tags is None

        # Manual override
        router.route_packet("manual", MANUAL_OVERRIDE, {"position": "entry"})
        assert handoff.last_handoff.manual_source_tags is not None

        # Live options
        router.route_packet("angel_one", "options_snapshot", {"oi": 50000})
        assert handoff.last_handoff.manual_source_tags is None

        assert handoff.handoff_count == 3


# =============================================================================
# Test: 6. Error Resilience
# =============================================================================


class TestErrorResilience:
    """The chain handles errors gracefully."""

    def test_unknown_feed_type_no_crash(self, integration_chain):
        """Unknown feed type → logged, no crash, no handoff."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()

        router.route_packet("angel_one", "unknown_feed", {"data": 1})
        assert handoff.handoff_count == 0

    def test_invalid_manual_type_no_crash(self, integration_chain):
        """Invalid manual type → logged, no crash, no handoff."""
        router, handoff = integration_chain

        router.route_packet("manual", "BAD_TYPE", {"data": 1})
        assert handoff.handoff_count == 0

    def test_empty_data_does_not_crash(self, integration_chain):
        """Empty raw data is handled without crashing."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()

        router.route_packet("angel_one", "spot_tick", {})
        assert handoff.handoff_count == 1

    def test_stop_routing_blocks_packets(self, integration_chain):
        """After stop_routing(), packets are ignored."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()

        router.stop_routing()
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})
        assert handoff.handoff_count == 0

        router.start_routing()
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})
        assert handoff.handoff_count == 1


# =============================================================================
# Test: 7. End-to-End Chain with Mock SmartConnect
# =============================================================================


class TestSmartConnectIntegration:
    """The full chain works with mocked SmartConnect SDK."""

    def test_mock_smart_connect_login_succeeds(
        self, mock_smart_connect, test_config
    ):
        """Mocked SmartConnect allows AuthManager to login successfully."""
        mock_class, mock_instance = mock_smart_connect
        am = AuthManager(config=test_config)
        token = am.login()
        assert token == "test_access_token_123"
        mock_class.assert_called_once_with(api_key="test_api_key_12345")
        mock_instance.generateSession.assert_called_once()

    def test_mock_smart_connect_auth_failure(
        self, mock_smart_connect, test_config
    ):
        """Mocked auth failure → ConnectionError."""
        mock_class, mock_instance = mock_smart_connect
        mock_instance.generateSession.side_effect = RuntimeError("API unreachable")

        am = AuthManager(config=test_config)
        with pytest.raises(ConnectionError):
            am.login()

    def test_connect_flow_through_mock_sdk(self, mock_smart_connect, angel_one_adapter):
        """Full connect flow works through mocked SmartConnect."""
        connected = angel_one_adapter.connect()
        assert connected is True
        assert angel_one_adapter.is_connected() is True


# =============================================================================
# Test: 8. PacketEnvelope Field Correctness
# =============================================================================


class TestEnvelopeFieldCorrectness:
    """PacketEnvelope fields are correctly populated end-to-end."""

    def test_received_at_is_utc(self, integration_chain):
        """received_at is ISO-formatted with UTC timezone info."""
        from datetime import datetime

        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})

        envelope = handoff.last_handoff.minimal_source_envelope
        received_at_str = envelope["received_at"]
        # Must be a parseable ISO datetime string with timezone
        parsed = datetime.fromisoformat(received_at_str)
        assert parsed.tzinfo is not None

    def test_routing_id_format(self, integration_chain):
        """routing_id = source::feed_type."""
        router, handoff = integration_chain
        router._source_adapters["angel_one"].connect()
        router.route_packet("angel_one", "spot_tick", {"ltp": 19500.0})

        env = handoff.last_handoff.minimal_source_envelope
        assert env["routing_id"] == "angel_one::spot_tick"

    def test_manual_routing_id_format(self, integration_chain):
        """Manual routing_id = manual::MANUAL_CALENDAR."""
        router, handoff = integration_chain
        router.route_packet("manual", MANUAL_CALENDAR, {"event": "test"})

        env = handoff.last_handoff.minimal_source_envelope
        assert env["routing_id"] == "manual::MANUAL_CALENDAR"
