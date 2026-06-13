"""Tests for kill_switch.py — KillSwitch SOFT/CRITICAL module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from junior_aladdin.side_a_execution.kill_switch import KillSwitch
from junior_aladdin.side_a_execution.side_a_types import KillSwitchState


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def kill_switch() -> KillSwitch:
    """KillSwitch without callbacks."""
    return KillSwitch()


@pytest.fixture
def mock_callback() -> MagicMock:
    """Mock flatten callback."""
    return MagicMock(return_value=True)


@pytest.fixture
def kill_switch_with_callbacks(mock_callback) -> KillSwitch:
    """KillSwitch with mock callbacks."""
    return KillSwitch(on_activate_callback=mock_callback)


# =============================================================================
# Initial State Tests
# =============================================================================


class TestInitialState:
    """Verify KillSwitch initialises to NORMAL."""

    def test_initial_state_normal(self, kill_switch: KillSwitch):
        """Initial state is NORMAL."""
        assert kill_switch.get_active_switch() == KillSwitchState.NORMAL

    def test_entry_not_blocked_initially(self, kill_switch: KillSwitch):
        """Entry is not blocked initially."""
        assert kill_switch.is_entry_blocked() is False

    def test_flatten_not_active_initially(self, kill_switch: KillSwitch):
        """Flatten is not active initially."""
        assert kill_switch.is_flatten_active() is False

    def test_reason_empty_initially(self, kill_switch: KillSwitch):
        """Reason is empty initially."""
        assert kill_switch.get_reason() == ""

    def test_activated_at_none_initially(self, kill_switch: KillSwitch):
        """Activated at is None initially."""
        assert kill_switch.get_activated_at() is None

    def test_history_empty_initially(self, kill_switch: KillSwitch):
        """History is empty initially."""
        assert kill_switch.get_activation_history() == []


# =============================================================================
# SOFT Activation Tests
# =============================================================================


class TestSoftActivation:
    """Verify SOFT kill switch activation."""

    def test_activate_soft(self, kill_switch: KillSwitch):
        """SOFT activation changes state."""
        result = kill_switch.activate_soft("Test reason")
        assert result is True
        assert kill_switch.get_active_switch() == KillSwitchState.SOFT_ACTIVE

    def test_soft_blocks_entry(self, kill_switch: KillSwitch):
        """SOFT activation blocks new entries."""
        kill_switch.activate_soft()
        assert kill_switch.is_entry_blocked() is True

    def test_soft_does_not_flatten(self, kill_switch: KillSwitch):
        """SOFT activation does NOT set flatten flag."""
        kill_switch.activate_soft()
        assert kill_switch.is_flatten_active() is False

    def test_soft_reason_stored(self, kill_switch: KillSwitch):
        """SOFT activation reason is stored."""
        kill_switch.activate_soft("Data degraded")
        assert "Data degraded" in kill_switch.get_reason()

    def test_soft_activated_at_set(self, kill_switch: KillSwitch):
        """Activated at is set after SOFT activation."""
        kill_switch.activate_soft()
        assert kill_switch.get_activated_at() is not None

    def test_soft_double_activation_updates_reason(self, kill_switch: KillSwitch):
        """Double SOFT activation updates reason."""
        kill_switch.activate_soft("First reason")
        result = kill_switch.activate_soft("Updated reason")
        assert result is True
        assert "Updated reason" in kill_switch.get_reason()

    def test_soft_history_recorded(self, kill_switch: KillSwitch):
        """SOFT activation appears in history."""
        kill_switch.activate_soft("Test")
        history = kill_switch.get_activation_history()
        assert len(history) >= 1
        assert history[0]["event"] == "SOFT_ACTIVATED"


# =============================================================================
# CRITICAL Activation Tests
# =============================================================================


class TestCriticalActivation:
    """Verify CRITICAL kill switch activation."""

    def test_activate_critical(self, kill_switch: KillSwitch):
        """CRITICAL activation changes state."""
        result = kill_switch.activate_critical("Emergency")
        assert result is True
        assert kill_switch.get_active_switch() == KillSwitchState.CRITICAL_ACTIVE

    def test_critical_blocks_entry(self, kill_switch: KillSwitch):
        """CRITICAL activation blocks new entries."""
        kill_switch.activate_critical()
        assert kill_switch.is_entry_blocked() is True

    def test_critical_activates_flatten(self, kill_switch: KillSwitch):
        """CRITICAL activation sets flatten flag."""
        kill_switch.activate_critical()
        assert kill_switch.is_flatten_active() is True

    def test_critical_reason_stored(self, kill_switch: KillSwitch):
        """CRITICAL activation reason is stored."""
        kill_switch.activate_critical("Unprotected position")
        assert "Unprotected position" in kill_switch.get_reason()

    def test_critical_calls_flatten_callback(self, kill_switch_with_callbacks: KillSwitch, mock_callback: MagicMock):
        """CRITICAL activation calls flatten callback."""
        kill_switch_with_callbacks.activate_critical("Emergency")
        mock_callback.assert_called_once_with("FLATTEN")

    def test_critical_from_soft_works(self, kill_switch: KillSwitch):
        """Activating CRITICAL from SOFT works."""
        kill_switch.activate_soft()
        result = kill_switch.activate_critical("Escalation")
        assert result is True
        assert kill_switch.get_active_switch() == KillSwitchState.CRITICAL_ACTIVE

    def test_soft_from_critical_fails(self, kill_switch: KillSwitch):
        """Activating SOFT from CRITICAL fails."""
        kill_switch.activate_critical()
        result = kill_switch.activate_soft("Test")
        assert result is False
        assert kill_switch.get_active_switch() == KillSwitchState.CRITICAL_ACTIVE

    def test_critical_double_activation(self, kill_switch: KillSwitch):
        """Double CRITICAL activation returns True."""
        kill_switch.activate_critical("First")
        result = kill_switch.activate_critical("Second")
        assert result is True

    def test_critical_history_recorded(self, kill_switch: KillSwitch):
        """CRITICAL activation appears in history."""
        kill_switch.activate_critical("Emergency")
        history = kill_switch.get_activation_history()
        assert history[0]["event"] == "CRITICAL_ACTIVATED"


# =============================================================================
# Deactivation Tests
# =============================================================================


class TestDeactivation:
    """Verify kill switch deactivation."""

    def test_deactivate_soft(self, kill_switch: KillSwitch):
        """Deactivating SOFT returns to NORMAL."""
        kill_switch.activate_soft()
        result = kill_switch.deactivate("All clear")
        assert result is True
        assert kill_switch.get_active_switch() == KillSwitchState.NORMAL

    def test_deactivate_critical(self, kill_switch: KillSwitch):
        """Deactivating CRITICAL returns to NORMAL."""
        kill_switch.activate_critical()
        result = kill_switch.deactivate("Resolved")
        assert result is True
        assert kill_switch.get_active_switch() == KillSwitchState.NORMAL

    def test_deactivate_normal_noop(self, kill_switch: KillSwitch):
        """Deactivating when already NORMAL returns True."""
        result = kill_switch.deactivate("No action")
        assert result is True
        assert kill_switch.get_active_switch() == KillSwitchState.NORMAL

    def test_deactivate_unblocks_entry(self, kill_switch: KillSwitch):
        """Deactivation unblocks new entries."""
        kill_switch.activate_soft()
        kill_switch.deactivate()
        assert kill_switch.is_entry_blocked() is False

    def test_deactivate_clears_reason(self, kill_switch: KillSwitch):
        """Deactivation clears reason."""
        kill_switch.activate_soft("Test")
        kill_switch.deactivate()
        assert kill_switch.get_reason() == ""

    def test_deactivate_history_recorded(self, kill_switch: KillSwitch):
        """Deactivation appears in history."""
        kill_switch.activate_soft("Test")
        kill_switch.deactivate("Resolved")
        history = kill_switch.get_activation_history()
        assert history[0]["event"] == "DEACTIVATED"


# =============================================================================
# History Tests
# =============================================================================


class TestHistory:
    """Verify activation history."""

    def test_history_limit(self, kill_switch: KillSwitch):
        """History respects limit parameter."""
        for i in range(15):
            kill_switch.activate_soft(f"Reason {i}")
            kill_switch.deactivate()
        history = kill_switch.get_activation_history(limit=5)
        assert len(history) <= 5

    def test_history_chronological_order(self, kill_switch: KillSwitch):
        """History returns newest first."""
        kill_switch.activate_soft("First")
        kill_switch.deactivate()
        kill_switch.activate_soft("Second")
        history = kill_switch.get_activation_history()
        assert history[0]["event"] == "SOFT_ACTIVATED"
        assert "Second" in history[0]["reason"]


# =============================================================================
# Log Callback Tests
# =============================================================================


class TestLogCallback:
    """Verify log callback is invoked."""

    def test_soft_triggers_log(self):
        """SOFT activation triggers log callback."""
        log_mock = MagicMock()
        ks = KillSwitch(on_log_callback=log_mock)
        ks.activate_soft("Test")
        log_mock.assert_called_once()
        assert log_mock.call_args[0][0] == "KILL_SWITCH_SOFT"

    def test_critical_triggers_log(self):
        """CRITICAL activation triggers log callback."""
        log_mock = MagicMock()
        ks = KillSwitch(on_log_callback=log_mock)
        ks.activate_critical("Emergency")
        assert log_mock.call_args[0][0] == "KILL_SWITCH_CRITICAL"

    def test_deactivate_triggers_log(self):
        """Deactivation triggers log callback."""
        log_mock = MagicMock()
        ks = KillSwitch(on_log_callback=log_mock)
        ks.activate_soft("Test")
        log_mock.reset_mock()
        ks.deactivate("Resolved")
        assert log_mock.call_args[0][0] == "KILL_SWITCH_NORMAL"
