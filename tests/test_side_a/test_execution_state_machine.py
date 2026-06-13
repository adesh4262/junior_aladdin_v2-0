"""Tests for execution_state_machine.py — ExecutionStateMachine.

Covers:
- All 18 events from all valid source states
- Invalid transitions raise ExecutionError
- Helper methods: is_active, can_receive_new_intent, is_safe_to_proceed, reset
- can_transition(), get_available_events(), get_transition_history()
- Edge cases: None event, wrong type
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.execution_state_machine import (
    ExecutionEvent,
    ExecutionStateMachine,
    TransitionRecord,
)
from junior_aladdin.side_a_execution.side_a_types import (
    ExecutionMajorState,
    can_receive_new_intent,
    is_execution_active,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sm() -> ExecutionStateMachine:
    """Fresh state machine starting at IDLE."""
    return ExecutionStateMachine()


# =============================================================================
# Initial State Tests
# =============================================================================


class TestInitialState:
    """Verify the state machine starts in the correct state."""

    def test_starts_at_idle(self, sm: ExecutionStateMachine) -> None:
        assert sm.state == ExecutionMajorState.IDLE

    def test_not_active_at_idle(self, sm: ExecutionStateMachine) -> None:
        assert not sm.is_active()

    def test_can_receive_intent_at_idle(self, sm: ExecutionStateMachine) -> None:
        assert sm.can_receive_new_intent()

    def test_safe_to_proceed_at_idle(self, sm: ExecutionStateMachine) -> None:
        assert sm.is_safe_to_proceed()

    def test_empty_history(self, sm: ExecutionStateMachine) -> None:
        assert sm.get_transition_history() == []

    def test_get_available_events_at_idle(self, sm: ExecutionStateMachine) -> None:
        events = sm.get_available_events()
        assert ExecutionEvent.CAPTAIN_INTENT in events
        assert len(events) == 1

    def test_initial_state_override(self) -> None:
        sm = ExecutionStateMachine(initial_state=ExecutionMajorState.FAILED)
        assert sm.state == ExecutionMajorState.FAILED


# =============================================================================
# Main Happy-Path Transition Tests
# =============================================================================


class TestMainHappyPath:
    """Test the ideal execution flow from IDLE through CLOSED."""

    def test_full_happy_path(self, sm: ExecutionStateMachine) -> None:
        """IDLE → INTENT_RECEIVED → RISK_PASSED → ORDER_PENDING → FILLED
        → PROTECTED → MANAGING → EXITING → CLOSED"""
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.state == ExecutionMajorState.INTENT_RECEIVED

        sm.transition(ExecutionEvent.RISK_PASSED)
        assert sm.state == ExecutionMajorState.RISK_PASSED

        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        assert sm.state == ExecutionMajorState.ORDER_PENDING

        sm.transition(ExecutionEvent.FULL_FILL)
        assert sm.state == ExecutionMajorState.FILLED

        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        assert sm.state == ExecutionMajorState.PROTECTED

        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        assert sm.state == ExecutionMajorState.MANAGING

        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        assert sm.state == ExecutionMajorState.EXITING

        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        assert sm.state == ExecutionMajorState.CLOSED

    def test_happy_path_with_partial_fill(self, sm: ExecutionStateMachine) -> None:
        """Test the path that goes through PARTIAL_FILL."""
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.PARTIAL_FILL_RECEIVED)
        assert sm.state == ExecutionMajorState.PARTIAL_FILL

        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        assert sm.state == ExecutionMajorState.PROTECTED


# =============================================================================
# Individual Transition Tests
# =============================================================================


class TestIndividualTransitions:
    """Test each transition individually."""

    def _setup_and_transition(
        self,
        setup_events: list[ExecutionEvent],
        target_event: ExecutionEvent,
        expected_state: ExecutionMajorState,
    ) -> None:
        sm = ExecutionStateMachine()
        for evt in setup_events:
            sm.transition(evt)
        sm.transition(target_event)
        assert sm.state == expected_state

    # IDLE transitions
    def test_idle_to_intent_received(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.state == ExecutionMajorState.INTENT_RECEIVED

    # INTENT_RECEIVED transitions
    def test_intent_received_to_risk_passed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        assert sm.state == ExecutionMajorState.RISK_PASSED

    def test_intent_received_to_failed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        assert sm.state == ExecutionMajorState.FAILED

    # RISK_PASSED transitions
    def test_risk_passed_to_order_pending(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        assert sm.state == ExecutionMajorState.ORDER_PENDING

    # ORDER_PENDING transitions
    def test_order_pending_to_partial_fill(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.PARTIAL_FILL_RECEIVED)
        assert sm.state == ExecutionMajorState.PARTIAL_FILL

    def test_order_pending_to_filled(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        assert sm.state == ExecutionMajorState.FILLED

    def test_order_pending_to_failed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.REJECTED)
        assert sm.state == ExecutionMajorState.FAILED

    def test_order_pending_to_unknown(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR)
        assert sm.state == ExecutionMajorState.UNKNOWN_PENDING_RECONCILE

    # Protection from PARTIAL_FILL
    def test_partial_fill_to_protected(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.PARTIAL_FILL_RECEIVED)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        assert sm.state == ExecutionMajorState.PROTECTED

    # Protection from FILLED
    def test_filled_to_protected(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        assert sm.state == ExecutionMajorState.PROTECTED

    # PROTECTED → MANAGING
    def test_protected_to_managing(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        assert sm.state == ExecutionMajorState.MANAGING

    # MANAGING → EXITING
    def test_managing_to_exiting(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        assert sm.state == ExecutionMajorState.EXITING

    # EXITING → CLOSED
    def test_exiting_to_closed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        assert sm.state == ExecutionMajorState.CLOSED


# =============================================================================
# Kill Switch Transition Tests
# =============================================================================


class TestKillSwitchTransitions:
    """Test CRITICAL_LOCK and EMERGENCY_FLATTEN from every active state."""

    @pytest.mark.parametrize(
        "setup_events",
        [
            [ExecutionEvent.CAPTAIN_INTENT],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.PARTIAL_FILL_RECEIVED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL, ExecutionEvent.PROTECTION_STAGED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL, ExecutionEvent.PROTECTION_STAGED, ExecutionEvent.MANAGEMENT_BEGINS],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL, ExecutionEvent.PROTECTION_STAGED, ExecutionEvent.MANAGEMENT_BEGINS, ExecutionEvent.EXIT_TRIGGERED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.TIMEOUT_UNCLEAR],
        ],
    )
    def test_critical_lock_from_active_states(
        self, setup_events: list[ExecutionEvent],
    ) -> None:
        """CRITICAL_LOCK should work from any active state → LOCKED."""
        sm = ExecutionStateMachine()
        for evt in setup_events:
            sm.transition(evt)
        sm.transition(ExecutionEvent.CRITICAL_LOCK)
        assert sm.state == ExecutionMajorState.LOCKED

    @pytest.mark.parametrize(
        "setup_events",
        [
            [ExecutionEvent.CAPTAIN_INTENT],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.PARTIAL_FILL_RECEIVED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL, ExecutionEvent.PROTECTION_STAGED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL, ExecutionEvent.PROTECTION_STAGED, ExecutionEvent.MANAGEMENT_BEGINS],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.FULL_FILL, ExecutionEvent.PROTECTION_STAGED, ExecutionEvent.MANAGEMENT_BEGINS, ExecutionEvent.EXIT_TRIGGERED],
            [ExecutionEvent.CAPTAIN_INTENT, ExecutionEvent.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED, ExecutionEvent.TIMEOUT_UNCLEAR],
        ],
    )
    def test_emergency_flatten_from_active_states(
        self, setup_events: list[ExecutionEvent],
    ) -> None:
        """EMERGENCY_FLATTEN should work from any active state → CLOSED."""
        sm = ExecutionStateMachine()
        for evt in setup_events:
            sm.transition(evt)
        sm.transition(ExecutionEvent.EMERGENCY_FLATTEN)
        assert sm.state == ExecutionMajorState.CLOSED


# =============================================================================
# UNKNOWN State Reconciliation Path Tests
# =============================================================================


class TestUnknownStateTransitions:
    """Test all 4 reconciliation paths from UNKNOWN_PENDING_RECONCILE."""

    def _enter_unknown(self) -> ExecutionStateMachine:
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR)
        assert sm.state == ExecutionMajorState.UNKNOWN_PENDING_RECONCILE
        return sm

    def test_reconcile_success_managing(self) -> None:
        sm = self._enter_unknown()
        sm.transition(ExecutionEvent.RECONCILE_SUCCESS_MANAGING)
        assert sm.state == ExecutionMajorState.MANAGING

    def test_reconcile_success_protected(self) -> None:
        sm = self._enter_unknown()
        sm.transition(ExecutionEvent.RECONCILE_SUCCESS_PROTECTED)
        assert sm.state == ExecutionMajorState.PROTECTED

    def test_reconcile_unrecoverable(self) -> None:
        sm = self._enter_unknown()
        sm.transition(ExecutionEvent.RECONCILE_UNRECOVERABLE)
        assert sm.state == ExecutionMajorState.FAILED

    def test_reconcile_failsafe(self) -> None:
        sm = self._enter_unknown()
        sm.transition(ExecutionEvent.RECONCILE_FAILSAFE)
        assert sm.state == ExecutionMajorState.CLOSED


# =============================================================================
# Invalid Transition Tests
# =============================================================================


class TestInvalidTransitions:
    """Test that invalid transitions raise ExecutionError."""

    def test_cannot_transition_none_event(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid event type"):
            sm.transition(None)  # type: ignore[arg-type]

    def test_cannot_transition_wrong_type(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid event type"):
            sm.transition("INVALID")  # type: ignore[arg-type]

    def test_cannot_risk_passed_from_idle(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.RISK_PASSED)

    def test_cannot_order_submitted_from_idle(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.ORDER_SUBMITTED)

    def test_cannot_captain_intent_from_risk_passed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.CAPTAIN_INTENT)

    def test_cannot_close_from_idle(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.CLOSE_COMPLETE)

    def test_cannot_protect_before_fill(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.PROTECTION_STAGED)

    def test_cannot_manage_before_protection(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)

    def test_cannot_exit_before_manage(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.EXIT_TRIGGERED)

    def test_cannot_reconcile_from_idle(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.RECONCILE_SUCCESS_MANAGING)

    def test_cannot_reconcile_from_filled(self) -> None:
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.RECONCILE_SUCCESS_MANAGING)

    def test_cannot_full_fill_from_idle(self, sm: ExecutionStateMachine) -> None:
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.FULL_FILL)

    def test_cannot_kill_lock_from_closed(self) -> None:
        # Go through full flow to CLOSED
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        # CLOSED is not an active state
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.CRITICAL_LOCK)

    def test_cannot_flatten_from_closed(self) -> None:
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        with pytest.raises(ExecutionError, match="Invalid transition"):
            sm.transition(ExecutionEvent.EMERGENCY_FLATTEN)


# =============================================================================
# Helper Methods Tests
# =============================================================================


class TestHelperMethods:
    """Test is_active, can_receive_new_intent, is_safe_to_proceed states."""

    def test_is_active_during_execution(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.is_active()

    def test_is_active_after_risk_passed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        assert sm.is_active()

    def test_is_active_in_unknown(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR)
        assert sm.is_active()

    def test_not_active_when_closed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        assert not sm.is_active()

    def test_not_active_when_failed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        assert not sm.is_active()

    def test_not_active_when_locked(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.CRITICAL_LOCK)
        assert not sm.is_active()

    def test_can_receive_intent_at_closed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        assert sm.can_receive_new_intent()

    def test_can_receive_intent_at_failed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        assert sm.can_receive_new_intent()

    def test_cannot_receive_intent_when_active(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert not sm.can_receive_new_intent()

    def test_cannot_receive_intent_when_locked(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.CRITICAL_LOCK)
        assert not sm.can_receive_new_intent()

    def test_safe_to_proceed_normal_path(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.is_safe_to_proceed()

    def test_safe_to_proceed_at_closed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        assert sm.is_safe_to_proceed()

    def test_not_safe_when_failed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        assert not sm.is_safe_to_proceed()

    def test_not_safe_when_locked(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.CRITICAL_LOCK)
        assert not sm.is_safe_to_proceed()

    def test_not_safe_when_unknown_pending_reconcile(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR)
        assert not sm.is_safe_to_proceed()


# =============================================================================
# Reset Tests
# =============================================================================


class TestReset:
    """Test reset() returns state machine to IDLE."""

    def test_reset_from_active_state(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.reset()
        assert sm.state == ExecutionMajorState.IDLE
        assert sm.get_transition_history() == []

    def test_reset_from_closed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        sm.reset()
        assert sm.state == ExecutionMajorState.IDLE

    def test_reset_from_failed(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        sm.reset()
        assert sm.state == ExecutionMajorState.IDLE

    def test_reset_clears_history(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        assert len(sm.get_transition_history()) == 2
        sm.reset()
        assert sm.get_transition_history() == []


# =============================================================================
# Transition History Tests
# =============================================================================


class TestTransitionHistory:
    """Test that history is recorded correctly."""

    def test_history_records_events(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_FAILED)
        history = sm.get_transition_history()
        assert len(history) == 2

        record1 = history[0]
        assert isinstance(record1, TransitionRecord)
        assert record1.from_state == ExecutionMajorState.IDLE.value
        assert record1.event == ExecutionEvent.CAPTAIN_INTENT.value
        assert record1.to_state == ExecutionMajorState.INTENT_RECEIVED.value

        record2 = history[1]
        assert record2.from_state == ExecutionMajorState.INTENT_RECEIVED.value
        assert record2.event == ExecutionEvent.RISK_FAILED.value
        assert record2.to_state == ExecutionMajorState.FAILED.value

    def test_history_timestamps(self, sm: ExecutionStateMachine) -> None:
        before = datetime.utcnow()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        after = datetime.utcnow()
        record = sm.get_transition_history()[0]
        assert before <= record.timestamp <= after

    def test_history_with_details(self, sm: ExecutionStateMachine) -> None:
        sm.transition(
            ExecutionEvent.CAPTAIN_INTENT,
            details={"reason": "Captain approved"},
        )
        record = sm.get_transition_history()[0]
        assert record.details == {"reason": "Captain approved"}

    def test_history_empty_after_reset(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert len(sm.get_transition_history()) == 1
        sm.reset()
        assert sm.get_transition_history() == []


# =============================================================================
# can_transition Tests
# =============================================================================


class TestCanTransition:
    """Test can_transition() returns correct booleans."""

    def test_can_transition_valid_event(self, sm: ExecutionStateMachine) -> None:
        assert sm.can_transition(ExecutionEvent.CAPTAIN_INTENT)

    def test_cannot_transition_invalid_event(self, sm: ExecutionStateMachine) -> None:
        assert not sm.can_transition(ExecutionEvent.FULL_FILL)

    def test_can_transition_after_state_change(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.can_transition(ExecutionEvent.RISK_PASSED)
        assert not sm.can_transition(ExecutionEvent.CAPTAIN_INTENT)

    def test_can_transition_kill_switch(self) -> None:
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.can_transition(ExecutionEvent.CRITICAL_LOCK)
        assert sm.can_transition(ExecutionEvent.EMERGENCY_FLATTEN)

    def test_cannot_transition_kill_switch_from_idle(self, sm: ExecutionStateMachine) -> None:
        assert not sm.can_transition(ExecutionEvent.CRITICAL_LOCK)


# =============================================================================
# get_available_events Tests
# =============================================================================


class TestGetAvailableEvents:
    """Test get_available_events() returns correct event lists."""

    def test_available_events_from_intent_received(self, sm: ExecutionStateMachine) -> None:
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        events = sm.get_available_events()
        assert ExecutionEvent.RISK_PASSED in events
        assert ExecutionEvent.RISK_FAILED in events
        assert ExecutionEvent.CRITICAL_LOCK in events
        assert ExecutionEvent.EMERGENCY_FLATTEN in events
        assert len(events) == 4

    def test_available_events_from_order_pending(self) -> None:
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        events = sm.get_available_events()
        assert ExecutionEvent.PARTIAL_FILL_RECEIVED in events
        assert ExecutionEvent.FULL_FILL in events
        assert ExecutionEvent.REJECTED in events
        assert ExecutionEvent.TIMEOUT_UNCLEAR in events
        assert ExecutionEvent.CRITICAL_LOCK in events
        assert ExecutionEvent.EMERGENCY_FLATTEN in events
        assert len(events) == 6

    def test_no_available_events_from_closed(self) -> None:
        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)
        sm.transition(ExecutionEvent.FULL_FILL)
        sm.transition(ExecutionEvent.PROTECTION_STAGED)
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS)
        sm.transition(ExecutionEvent.EXIT_TRIGGERED)
        sm.transition(ExecutionEvent.CLOSE_COMPLETE)
        events = sm.get_available_events()
        # CLOSED is not in the transition table as a source state
        assert len(events) == 0


# =============================================================================
# Transition Table Size Test
# =============================================================================


class TestTransitionTableSize:
    """Validate the transition table has the expected number of entries."""

    def test_transition_table_size(self, sm: ExecutionStateMachine) -> None:
        # Count entries manually:
        # 1 (IDLE) + 2 (INTENT_RECEIVED) + 1 (RISK_PASSED) + 4 (ORDER_PENDING)
        # + 1 (PARTIAL_FILL) + 1 (FILLED) + 1 (PROTECTED) + 1 (MANAGING)
        # + 1 (EXITING) + 9 (CRITICAL_LOCK: 9 active states)
        # + 9 (EMERGENCY_FLATTEN: 9 active states)
        # + 4 (UNKNOWN_PENDING_RECONCILE)
        # = 1 + 2 + 1 + 4 + 1 + 1 + 1 + 1 + 1 + 9 + 9 + 4 = 35
        assert sm.get_transition_table_size() == 35


# =============================================================================
# Cross-module Contract Tests
# =============================================================================


class TestCrossModuleContracts:
    """Verify state machine helpers match the standalone helpers."""

    def test_is_active_matches_standalone(self, sm: ExecutionStateMachine) -> None:
        for state in ExecutionMajorState:
            expected = is_execution_active(state)
            # Create a machine in each state
            s = ExecutionStateMachine(initial_state=state)
            assert s.is_active() == expected, f"Mismatch for {state}"

    def test_can_receive_intent_matches_standalone(self, sm: ExecutionStateMachine) -> None:
        for state in ExecutionMajorState:
            expected = can_receive_new_intent(state)
            s = ExecutionStateMachine(initial_state=state)
            assert s.can_receive_new_intent() == expected, f"Mismatch for {state}"
