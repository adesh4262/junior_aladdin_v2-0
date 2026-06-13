"""Pytest tests for Side B command handlers.

Tests all 6 handlers for:
    - Success path (valid params → CommandAck with ACK status)
    - Validation errors (invalid params → ValueError)
    - Cache interaction (command stored in cache with correct key)

Each test uses InMemoryStore as a mock cache fixture.

Reference: ROADMAP_SIDE_B Step 8.9 — Command handlers
"""

from __future__ import annotations

from typing import Any

import pytest

from junior_aladdin.side_b_api.command_handlers import (
    handle_account_reset_request,
    handle_capital_request,
    handle_kill_switch_request,
    handle_mode_request,
    handle_override_request,
    handle_reconnect_request,
)
from junior_aladdin.side_b_api.data_contracts import CommandAck
from junior_aladdin.shared.testing import InMemoryStore


# =============================================================================
# Test Cache — wraps InMemoryStore with a .set() method
# Command handlers call cache.set(key, value) which maps to InMemoryStore.put()
# =============================================================================


class _TestCache:
    """Adapter that wraps InMemoryStore to provide .set() for command handlers.

    Command handlers call cache.set(key, value) which maps to InMemoryStore.put().
    """

    def __init__(self) -> None:
        self._store = InMemoryStore()

    def set(self, key: str, value: object) -> None:
        self._store.put(key, value)

    def get(self, key: str) -> object | None:
        return self._store.get(key)

    def keys(self) -> list[str]:
        return self._store.keys()

    def __len__(self) -> int:
        return len(self._store)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cache() -> _TestCache:
    """Provide a fresh _TestCache for each test."""
    return _TestCache()


# =============================================================================
# Test: handle_mode_request
# =============================================================================


class TestHandleModeRequest:
    """handle_mode_request — mode change (ALERT / PAPER / REAL)."""

    VALID_MODES = ["ALERT", "PAPER", "REAL", "alert", "Paper", "  REAL  "]
    INVALID_MODES = ["INVALID", "PRODUCTION", "", "123"]

    def test_success_alert(self, cache: InMemoryStore) -> None:
        """ALERT mode returns ACK and stores in cache."""
        ack = handle_mode_request(cache, "ALERT", "Testing alert mode")
        assert isinstance(ack, CommandAck)
        assert ack.status == "ACK"
        assert ack.command_type == "request_mode"
        assert "ALERT" in ack.message

        cmd = cache.get("control:mode")
        assert cmd is not None
        assert cmd["params"]["mode"] == "ALERT"
        assert cmd["target"] == "side_a.mode_router"

    def test_success_paper(self, cache: InMemoryStore) -> None:
        """PAPER mode stores correct params."""
        ack = handle_mode_request(cache, "PAPER", "Paper mode test")
        assert ack.owner_response["requested_mode"] == "PAPER"

        cmd = cache.get("control:mode")
        assert cmd["params"]["mode"] == "PAPER"

    def test_success_real(self, cache: InMemoryStore) -> None:
        """REAL mode with reason works."""
        ack = handle_mode_request(cache, "REAL", "Going live")
        assert ack.status == "ACK"
        cmd = cache.get("control:mode")
        assert cmd["params"]["mode"] == "REAL"
        assert cmd["params"]["reason"] == "Going live"

    def test_success_case_insensitive(self, cache: InMemoryStore) -> None:
        """Lowercase and mixed-case modes are normalized to uppercase."""
        ack = handle_mode_request(cache, "paper", "test")
        assert ack.owner_response["requested_mode"] == "PAPER"

        ack2 = handle_mode_request(cache, "  REAL  ", "test")
        assert ack2.owner_response["requested_mode"] == "REAL"

    def test_invalid_mode_raises_value_error(self, cache: InMemoryStore) -> None:
        """Invalid mode string raises ValueError."""
        for mode in self.INVALID_MODES:
            with pytest.raises(ValueError, match="Invalid mode"):
                handle_mode_request(cache, mode, "test")

    def test_cache_key_is_control_mode(self, cache: InMemoryStore) -> None:
        """Cache key 'control:mode' matches data_aggregator expectations."""
        handle_mode_request(cache, "ALERT")
        assert cache.get("control:mode") is not None
        assert cache.get("control:capital") is None

    def test_empty_reason_does_not_fail(self, cache: InMemoryStore) -> None:
        """Empty reason is allowed (defaults to '')."""
        ack = handle_mode_request(cache, "ALERT")
        assert ack.status == "ACK"
        cmd = cache.get("control:mode")
        assert cmd["params"]["reason"] == ""


# =============================================================================
# Test: handle_capital_request
# =============================================================================


class TestHandleCapitalRequest:
    """handle_capital_request — capital limit update."""

    def test_success_positive_integer(self, cache: InMemoryStore) -> None:
        """Positive integer capital limit returns ACK."""
        ack = handle_capital_request(cache, 500000, "Setting capital")
        assert ack.status == "ACK"
        assert ack.command_type == "request_capital"
        assert ack.owner_response["capital_limit"] == 500000.0

        cmd = cache.get("control:capital")
        assert cmd is not None
        assert cmd["params"]["capital_limit"] == 500000.0
        assert cmd["target"] == "side_a.risk_gate"

    def test_success_positive_float(self, cache: InMemoryStore) -> None:
        """Float capital limit is accepted."""
        ack = handle_capital_request(cache, 250000.50, "test")
        assert ack.owner_response["capital_limit"] == 250000.50

    def test_success_string_number(self, cache: InMemoryStore) -> None:
        """String convertible to float is accepted."""
        ack = handle_capital_request(cache, "100000", "test")
        assert ack.owner_response["capital_limit"] == 100000.0

    def test_zero_raises_value_error(self, cache: InMemoryStore) -> None:
        """Zero capital limit raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            handle_capital_request(cache, 0, "test")

    def test_negative_raises_value_error(self, cache: InMemoryStore) -> None:
        """Negative capital limit raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            handle_capital_request(cache, -1000, "test")

    def test_invalid_string_raises_value_error(self, cache: InMemoryStore) -> None:
        """Non-numeric string raises ValueError from float()."""
        with pytest.raises(ValueError):
            handle_capital_request(cache, "abc", "test")

    def test_none_raises_type_error(self, cache: InMemoryStore) -> None:
        """None raises TypeError from float()."""
        with pytest.raises(TypeError):
            handle_capital_request(cache, None, "test")  # type: ignore[arg-type]

    def test_cache_key_is_control_capital(self, cache: InMemoryStore) -> None:
        """Cache key 'control:capital' matches data_aggregator expectations."""
        handle_capital_request(cache, 100000)
        assert cache.get("control:capital") is not None
        assert cache.get("control:mode") is None


# =============================================================================
# Test: handle_kill_switch_request
# =============================================================================


class TestHandleKillSwitchRequest:
    """handle_kill_switch_request — kill-switch state change."""

    VALID_STATES = ["SOFT", "CRITICAL", "OFF", "soft", "Critical", "  OFF  "]
    INVALID_STATES = ["HARD", "NORMAL", "", "123", "maybe"]

    def test_success_soft_with_reason(self, cache: InMemoryStore) -> None:
        """SOFT kill switch with reason returns ACK."""
        ack = handle_kill_switch_request(cache, "SOFT", "Testing soft kill")
        assert ack.status == "ACK"
        assert ack.command_type == "request_kill_switch"
        assert ack.owner_response["kill_switch_state"] == "SOFT"

        cmd = cache.get("control:kill_switch")
        assert cmd is not None
        assert cmd["params"]["state"] == "SOFT"
        assert cmd["target"] == "side_a.kill_switch"

    def test_success_critical_with_reason(self, cache: InMemoryStore) -> None:
        """CRITICAL kill switch with reason."""
        ack = handle_kill_switch_request(cache, "CRITICAL", "Emergency")
        assert ack.status == "ACK"
        cmd = cache.get("control:kill_switch")
        assert cmd["params"]["state"] == "CRITICAL"

    def test_success_off(self, cache: InMemoryStore) -> None:
        """OFF does not require a reason."""
        ack = handle_kill_switch_request(cache, "OFF", "")
        assert ack.status == "ACK"
        cmd = cache.get("control:kill_switch")
        assert cmd["params"]["state"] == "OFF"

    def test_soft_missing_reason_raises(self, cache: InMemoryStore) -> None:
        """SOFT without reason raises ValueError."""
        with pytest.raises(ValueError, match="Reason required"):
            handle_kill_switch_request(cache, "SOFT", "")

    def test_critical_missing_reason_raises(self, cache: InMemoryStore) -> None:
        """CRITICAL without reason raises ValueError."""
        with pytest.raises(ValueError, match="Reason required"):
            handle_kill_switch_request(cache, "CRITICAL", "   ")

    def test_invalid_state_raises(self, cache: InMemoryStore) -> None:
        """Invalid state raises ValueError."""
        for state in self.INVALID_STATES:
            with pytest.raises(ValueError, match="Invalid kill"):
                handle_kill_switch_request(cache, state, "reason")

    def test_cache_key_is_control_kill_switch(self, cache: InMemoryStore) -> None:
        """Cache key 'control:kill_switch' matches data_aggregator."""
        handle_kill_switch_request(cache, "OFF", "")
        assert cache.get("control:kill_switch") is not None


# =============================================================================
# Test: handle_override_request
# =============================================================================


class TestHandleOverrideRequest:
    """handle_override_request — operator override confirmation."""

    def test_success_with_reason(self, cache: InMemoryStore) -> None:
        """Override with reason returns ACK."""
        ack = handle_override_request(cache, "Override required", "trade_123")
        assert ack.status == "ACK"
        assert ack.command_type == "request_override"
        assert ack.owner_response["override_confirmed"] is True
        assert ack.owner_response["trade_id"] == "trade_123"

        cmd = cache.get("control:override")
        assert cmd is not None
        assert cmd["params"]["override_confirmation"] is True
        assert cmd["params"]["trade_id"] == "trade_123"
        assert cmd["target"] == "floor_5.override_guard"

    def test_success_without_trade_id(self, cache: InMemoryStore) -> None:
        """Override without trade_id works (trade_id defaults to None)."""
        ack = handle_override_request(cache, "System override")
        assert ack.owner_response["trade_id"] is None

        cmd = cache.get("control:override")
        assert cmd["params"]["trade_id"] is None

    def test_empty_reason_raises(self, cache: InMemoryStore) -> None:
        """Empty reason raises ValueError."""
        with pytest.raises(ValueError, match="Reason required"):
            handle_override_request(cache, "")

    def test_whitespace_only_reason_raises(self, cache: InMemoryStore) -> None:
        """Whitespace-only reason raises ValueError."""
        with pytest.raises(ValueError, match="Reason required"):
            handle_override_request(cache, "   ")


# =============================================================================
# Test: handle_reconnect_request
# =============================================================================


class TestHandleReconnectRequest:
    """handle_reconnect_request — broker reconnect."""

    def test_success_default_broker(self, cache: InMemoryStore) -> None:
        """Default target_broker is 'primary'."""
        ack = handle_reconnect_request(cache)
        assert ack.status == "ACK"
        assert ack.owner_response["target_broker"] == "primary"

        cmd = cache.get("control:reconnect")
        assert cmd is not None
        assert cmd["params"]["target_broker"] == "primary"
        assert cmd["target"] == "side_a.execution_core"

    def test_success_custom_broker(self, cache: InMemoryStore) -> None:
        """Custom broker name is stored."""
        ack = handle_reconnect_request(cache, "angel_one", "Reconnecting")
        assert ack.owner_response["target_broker"] == "angel_one"

        cmd = cache.get("control:reconnect")
        assert cmd["params"]["target_broker"] == "angel_one"
        assert cmd["params"]["reason"] == "Reconnecting"

    def test_empty_broker_defaults_to_primary(self, cache: InMemoryStore) -> None:
        """Empty broker string defaults to 'primary'."""
        ack = handle_reconnect_request(cache, "  ", "test")
        assert ack.owner_response["target_broker"] == "primary"

    def test_empty_reason_allowed(self, cache: InMemoryStore) -> None:
        """Empty reason is allowed for reconnect."""
        ack = handle_reconnect_request(cache, "primary", "")
        assert ack.status == "ACK"
        cmd = cache.get("control:reconnect")
        assert cmd["params"]["reason"] == ""


# =============================================================================
# Test: handle_account_reset_request
# =============================================================================


class TestHandleAccountResetRequest:
    """handle_account_reset_request — paper account reset."""

    def test_success_default_balance(self, cache: InMemoryStore) -> None:
        """Default new_balance is 100000."""
        ack = handle_account_reset_request(cache, "Resetting account")
        assert ack.status == "ACK"
        assert ack.owner_response["new_balance"] == 100000.0

        cmd = cache.get("control:account_reset")
        assert cmd is not None
        assert cmd["params"]["new_balance"] == 100000.0
        assert cmd["params"]["reason"] == "Resetting account"
        assert cmd["target"] == "side_a.account_manager"

    def test_success_custom_balance(self, cache: InMemoryStore) -> None:
        """Custom positive balance is accepted."""
        ack = handle_account_reset_request(cache, "Fresh start", 50000.0)
        assert ack.owner_response["new_balance"] == 50000.0

        cmd = cache.get("control:account_reset")
        assert cmd["params"]["new_balance"] == 50000.0

    def test_success_balance_as_string(self, cache: InMemoryStore) -> None:
        """String convertible to float is accepted."""
        ack = handle_account_reset_request(cache, "test", "250000")
        assert ack.owner_response["new_balance"] == 250000.0

    def test_empty_reason_raises(self, cache: InMemoryStore) -> None:
        """Empty reason raises ValueError."""
        with pytest.raises(ValueError, match="Reason required"):
            handle_account_reset_request(cache, "")

    def test_negative_balance_raises(self, cache: InMemoryStore) -> None:
        """Negative balance raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            handle_account_reset_request(cache, "test", -1000)

    def test_zero_balance_raises(self, cache: InMemoryStore) -> None:
        """Zero balance raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            handle_account_reset_request(cache, "test", 0)


# =============================================================================
# Test: Cross-handler integration
# =============================================================================


class TestCrossHandlerIntegration:
    """Multiple handlers interacting with the same cache."""

    def test_cache_keys_are_independent(self, cache: InMemoryStore) -> None:
        """Each handler writes to its own cache key without collision."""
        handle_mode_request(cache, "ALERT", "")

        # All handlers can run without overwriting each other
        handle_capital_request(cache, 500000, "")
        handle_kill_switch_request(cache, "OFF", "")
        handle_override_request(cache, "test")
        handle_reconnect_request(cache, "primary")
        handle_account_reset_request(cache, "test", 100000)

        # Verify all keys exist
        assert cache.get("control:mode")["params"]["mode"] == "ALERT"
        assert cache.get("control:capital")["params"]["capital_limit"] == 500000.0
        assert cache.get("control:kill_switch")["params"]["state"] == "OFF"
        assert cache.get("control:override")["params"]["override_confirmation"] is True
        assert cache.get("control:reconnect")["params"]["target_broker"] == "primary"
        assert cache.get("control:account_reset")["params"]["new_balance"] == 100000.0
        assert len(cache.keys()) == 6

    def test_all_acks_have_expected_structure(self, cache: InMemoryStore) -> None:
        """All CommandAck objects have the expected fields."""
        handlers = [
            (handle_mode_request, (cache, "ALERT", "")),
            (handle_capital_request, (cache, 100000, "")),
            (handle_kill_switch_request, (cache, "OFF", "")),
            (handle_override_request, (cache, "test")),
            (handle_reconnect_request, (cache,)),
            (handle_account_reset_request, (cache, "test")),
        ]

        for handler, args in handlers:
            ack = handler(*args)
            assert ack.status == "ACK"
            assert ack.command_type.startswith("request_")
            assert isinstance(ack.message, str)
            assert isinstance(ack.owner_response, dict)
            assert hasattr(ack, "timestamp")
