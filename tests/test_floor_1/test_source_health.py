"""Tests for floor_1_connection/source_health.py."""

from __future__ import annotations

import pytest

from junior_aladdin.floor_1_connection.source_health import SourceHealthMonitor
from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.types import LifecycleState


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def monitor() -> SourceHealthMonitor:
    return SourceHealthMonitor(connection_id="conn_test_001")


# ------------------------------------------------------------------
# Initial state tests
# ------------------------------------------------------------------


class TestInitialState:
    """Tests for SourceHealthMonitor initial state."""

    def test_initial_state_is_healthy(self, monitor):
        assert monitor.lifecycle_state == LifecycleState.HEALTHY

    def test_initial_latency_zero(self, monitor):
        state = monitor.get_state()
        assert state.latency_ms == 0.0

    def test_initial_heartbeat_age_zero(self, monitor):
        state = monitor.get_state()
        assert state.heartbeat_age_s == 0.0

    def test_initial_reconnect_count_zero(self, monitor):
        state = monitor.get_state()
        assert state.reconnect_count == 0

    def test_connection_id_set(self, monitor):
        assert monitor.connection_id == "conn_test_001"


# ------------------------------------------------------------------
# Latency tests
# ------------------------------------------------------------------


class TestLatency:
    """Tests for update_latency()."""

    def test_update_latency(self, monitor):
        monitor.update_latency(15.5)
        assert monitor.get_state().latency_ms == 15.5

    def test_update_latency_rounds(self, monitor):
        # Use a value that clearly rounds up (Python uses banker's rounding)
        monitor.update_latency(15.556)
        assert monitor.get_state().latency_ms == 15.56

    def test_update_latency_zero(self, monitor):
        monitor.update_latency(0.0)
        assert monitor.get_state().latency_ms == 0.0

    def test_negative_latency_raises(self, monitor):
        with pytest.raises(ValidationError, match="Latency cannot be negative"):
            monitor.update_latency(-1.0)


# ------------------------------------------------------------------
# Heartbeat tests
# ------------------------------------------------------------------


class TestHeartbeat:
    """Tests for update_heartbeat() and tick_heartbeat_age()."""

    def test_update_heartbeat_resets_age(self, monitor):
        monitor.update_heartbeat()
        assert monitor.get_state().heartbeat_age_s == 0.0

    def test_tick_heartbeat_age_updates(self, monitor):
        """tick_heartbeat_age() calculates elapsed time since last heartbeat."""
        # Set last_heartbeat to 5 seconds ago
        from datetime import timedelta
        monitor._last_heartbeat -= timedelta(seconds=5)
        monitor.tick_heartbeat_age()
        age = monitor.get_state().heartbeat_age_s
        assert age >= 4.9  # should be ~5 seconds

    def test_update_heartbeat_after_tick_resets(self, monitor):
        monitor.update_heartbeat()
        monitor.tick_heartbeat_age()
        monitor.update_heartbeat()
        assert monitor.get_state().heartbeat_age_s == 0.0


# ------------------------------------------------------------------
# State transition tests
# ------------------------------------------------------------------


class TestStateTransitions:
    """Tests for transition_to()."""

    def test_healthy_to_degraded(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        assert monitor.lifecycle_state == LifecycleState.DEGRADED

    def test_healthy_to_auth_failed(self, monitor):
        monitor.transition_to(LifecycleState.AUTH_FAILED)
        assert monitor.lifecycle_state == LifecycleState.AUTH_FAILED

    def test_degraded_to_healthy(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.HEALTHY)
        assert monitor.lifecycle_state == LifecycleState.HEALTHY

    def test_degraded_to_stale(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        assert monitor.lifecycle_state == LifecycleState.STALE

    def test_stale_to_disconnected(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        assert monitor.lifecycle_state == LifecycleState.DISCONNECTED

    def test_stale_to_degraded(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DEGRADED)
        assert monitor.lifecycle_state == LifecycleState.DEGRADED

    def test_auth_failed_to_disconnected(self, monitor):
        monitor.transition_to(LifecycleState.AUTH_FAILED)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        assert monitor.lifecycle_state == LifecycleState.DISCONNECTED

    def test_auth_failed_to_healthy(self, monitor):
        """After re-auth, AUTH_FAILED → HEALTHY."""
        monitor.transition_to(LifecycleState.AUTH_FAILED)
        monitor.transition_to(LifecycleState.HEALTHY)
        assert monitor.lifecycle_state == LifecycleState.HEALTHY

    def test_disconnected_to_healthy(self, monitor):
        """After reconnect, DISCONNECTED → HEALTHY."""
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        monitor.transition_to(LifecycleState.HEALTHY)
        assert monitor.lifecycle_state == LifecycleState.HEALTHY

    def test_same_state_transition_is_noop(self, monitor):
        """Transitioning to the same state does nothing."""
        monitor.transition_to(LifecycleState.HEALTHY)
        assert monitor.lifecycle_state == LifecycleState.HEALTHY


# ------------------------------------------------------------------
# Invalid transition tests
# ------------------------------------------------------------------


class TestInvalidTransitions:
    """Tests that invalid transitions raise ValidationError."""

    def test_healthy_to_stale_invalid(self, monitor):
        with pytest.raises(ValidationError):
            monitor.transition_to(LifecycleState.STALE)

    def test_auth_failed_to_stale_invalid(self, monitor):
        monitor.transition_to(LifecycleState.AUTH_FAILED)
        with pytest.raises(ValidationError):
            monitor.transition_to(LifecycleState.STALE)

    def test_disconnected_to_degraded_invalid(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        with pytest.raises(ValidationError):
            monitor.transition_to(LifecycleState.DEGRADED)

    def test_disconnected_to_stale_invalid(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        with pytest.raises(ValidationError):
            monitor.transition_to(LifecycleState.STALE)

    def test_stale_to_healthy_invalid(self, monitor):
        with pytest.raises(ValidationError, match="Invalid state transition"):
            monitor.transition_to(LifecycleState.DEGRADED)
            monitor.transition_to(LifecycleState.STALE)
            # Can't skip DISCONNECTED and go straight back to HEALTHY
            monitor.transition_to(LifecycleState.HEALTHY)

    def test_disconnected_to_auth_failed_invalid(self, monitor):
        """DISCONNECTED → AUTH_FAILED is not allowed."""
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        with pytest.raises(ValidationError):
            monitor.transition_to(LifecycleState.AUTH_FAILED)

    def test_transition_error_message(self, monitor):
        with pytest.raises(ValidationError) as exc:
            monitor.transition_to(LifecycleState.DEGRADED)
            monitor.transition_to(LifecycleState.STALE)
            monitor.transition_to(LifecycleState.DISCONNECTED)
            # Try invalid: DISCONNECTED → stale (not allowed)
            monitor.transition_to(LifecycleState.DEGRADED)
        assert "DEGRADED" in str(exc.value)
        assert "DISCONNECTED" in str(exc.value)


# ------------------------------------------------------------------
# Reconnect count tests
# ------------------------------------------------------------------


class TestReconnectCount:
    """Tests for reconnect_count tracking."""

    def test_disconnect_increments_count(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        assert monitor.get_state().reconnect_count == 1

    def test_reconnect_after_disconnect(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        monitor.transition_to(LifecycleState.STALE)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        monitor.transition_to(LifecycleState.HEALTHY)
        assert monitor.lifecycle_state == LifecycleState.HEALTHY

    def test_auth_failed_then_disconnect(self, monitor):
        """AUTH_FAILED → DISCONNECTED should NOT increment reconnect_count
        since it already failed auth, not a new connection loss."""
        monitor.transition_to(LifecycleState.AUTH_FAILED)
        monitor.transition_to(LifecycleState.DISCONNECTED)
        assert monitor.get_state().reconnect_count == 0


# ------------------------------------------------------------------
# Health facts tests
# ------------------------------------------------------------------


class TestHealthFacts:
    """Tests for get_health_facts()."""

    def test_health_facts_contains_all_keys(self, monitor):
        facts = monitor.get_health_facts()
        assert "lifecycle_state" in facts
        assert "latency_ms" in facts
        assert "heartbeat_age_s" in facts
        assert "reconnect_count" in facts

    def test_health_facts_lifecycle_state(self, monitor):
        facts = monitor.get_health_facts()
        assert facts["lifecycle_state"] == "HEALTHY"

    def test_health_facts_updated_after_transition(self, monitor):
        monitor.transition_to(LifecycleState.DEGRADED)
        facts = monitor.get_health_facts()
        assert facts["lifecycle_state"] == "DEGRADED"

    def test_health_facts_after_latency_update(self, monitor):
        monitor.update_latency(25.5)
        facts = monitor.get_health_facts()
        assert facts["latency_ms"] == 25.5


# ------------------------------------------------------------------
# Full lifecycle test
# ------------------------------------------------------------------


class TestFullLifecycle:
    """Simulate a realistic connection lifecycle."""

    def test_healthy_to_disconnect_to_reconnect(self, monitor):
        monitor.update_latency(5.0)
        assert monitor.get_state().latency_ms == 5.0

        # Degrade
        monitor.transition_to(LifecycleState.DEGRADED)
        assert monitor.lifecycle_state == LifecycleState.DEGRADED

        # Stale
        monitor.transition_to(LifecycleState.STALE)
        assert monitor.lifecycle_state == LifecycleState.STALE

        # Disconnect
        monitor.transition_to(LifecycleState.DISCONNECTED)
        assert monitor.lifecycle_state == LifecycleState.DISCONNECTED

        # Reconnect
        monitor.transition_to(LifecycleState.HEALTHY)
        assert monitor.lifecycle_state == LifecycleState.HEALTHY
        assert monitor.get_state().reconnect_count == 1
        # Heartbeat should reset after reconnect
        assert monitor.get_state().heartbeat_age_s == 0.0
