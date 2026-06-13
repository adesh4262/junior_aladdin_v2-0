"""Tests: Every state machine transition table row validated individually.

Covers all valid and invalid transitions for the Side A execution
state machine.  Each row in the roadmap's transition table is tested
as an individual test case.
"""

from __future__ import annotations

import pytest

from junior_aladdin.side_a_execution.execution_state_machine import (
    ExecutionEvent,
    ExecutionStateMachine,
)
from junior_aladdin.side_a_execution.side_a_types import ExecutionMajorState


class TestTransitionTable:
    """Every valid transition from the locked state machine table."""

    def _make_sm(self) -> ExecutionStateMachine:
        return ExecutionStateMachine()

    # ── IDLE transitions ────────────────────────────────────────────────

    def test_idle_to_intent_received(self) -> None:
        sm = self._make_sm()
        assert sm.state == ExecutionMajorState.IDLE
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {"trade_id": "T001"})
        assert sm.state == ExecutionMajorState.INTENT_RECEIVED

    # ── INTENT_RECEIVED transitions ─────────────────────────────────────

    def test_intent_received_to_risk_passed(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        assert sm.state == ExecutionMajorState.RISK_PASSED

    def test_intent_received_to_failed(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_FAILED, {})
        assert sm.state == ExecutionMajorState.FAILED

    # ── RISK_PASSED transitions ─────────────────────────────────────────

    def test_risk_passed_to_order_pending(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {"order_id": "O001"})
        assert sm.state == ExecutionMajorState.ORDER_PENDING

    # ── ORDER_PENDING transitions ───────────────────────────────────────

    def test_order_pending_to_partial_fill(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.PARTIAL_FILL_RECEIVED, {})
        assert sm.state == ExecutionMajorState.PARTIAL_FILL

    def test_order_pending_to_filled(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.FULL_FILL, {})
        assert sm.state == ExecutionMajorState.FILLED

    def test_order_pending_to_failed_rejected(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.REJECTED, {})
        assert sm.state == ExecutionMajorState.FAILED

    def test_order_pending_to_unknown(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR, {})
        assert sm.state == ExecutionMajorState.UNKNOWN_PENDING_RECONCILE

    def test_order_pending_to_locked_emergency(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.CRITICAL_LOCK, {})
        assert sm.state == ExecutionMajorState.LOCKED

    # ── PARTIAL_FILL transitions ────────────────────────────────────────

    def test_partial_fill_to_protected(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.PARTIAL_FILL_RECEIVED, {})
        sm.transition(ExecutionEvent.PROTECTION_STAGED, {})
        assert sm.state == ExecutionMajorState.PROTECTED

    # ── FILLED transitions ──────────────────────────────────────────────

    def test_filled_to_protected(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.FULL_FILL, {})
        sm.transition(ExecutionEvent.PROTECTION_STAGED, {})
        assert sm.state == ExecutionMajorState.PROTECTED

    # ── PROTECTED transitions ───────────────────────────────────────────

    def test_protected_to_managing(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.FULL_FILL, {})
        sm.transition(ExecutionEvent.PROTECTION_STAGED, {})
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS, {})
        assert sm.state == ExecutionMajorState.MANAGING

    # ── MANAGING transitions ────────────────────────────────────────────

    def test_managing_to_exiting(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.FULL_FILL, {})
        sm.transition(ExecutionEvent.PROTECTION_STAGED, {})
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS, {})
        sm.transition(ExecutionEvent.EXIT_TRIGGERED, {})
        assert sm.state == ExecutionMajorState.EXITING

    # ── EXITING transitions ─────────────────────────────────────────────

    def test_exiting_to_closed(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.FULL_FILL, {})
        sm.transition(ExecutionEvent.PROTECTION_STAGED, {})
        sm.transition(ExecutionEvent.MANAGEMENT_BEGINS, {})
        sm.transition(ExecutionEvent.EXIT_TRIGGERED, {})
        sm.transition(ExecutionEvent.CLOSE_COMPLETE, {})
        assert sm.state == ExecutionMajorState.CLOSED

    # ── UNKNOWN transitions ─────────────────────────────────────────────

    def test_unknown_reconcile_success(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR, {})
        sm.transition(ExecutionEvent.RECONCILE_SUCCESS_MANAGING, {})
        assert sm.state == ExecutionMajorState.MANAGING

    def test_unknown_reconcile_fail(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.RISK_PASSED, {})
        sm.transition(ExecutionEvent.ORDER_SUBMITTED, {})
        sm.transition(ExecutionEvent.TIMEOUT_UNCLEAR, {})
        sm.transition(ExecutionEvent.RECONCILE_UNRECOVERABLE, {})
        assert sm.state == ExecutionMajorState.FAILED

    # ── ANY ACTIVE STATE → LOCKED / CLOSED ──────────────────────────────

    def test_emergency_flatten_from_active(self) -> None:
        sm = self._make_sm()
        # EMERGENCY_FLATTEN works from any active state (not IDLE)
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.EMERGENCY_FLATTEN, {})
        assert sm.state == ExecutionMajorState.CLOSED

    def test_critical_lock_from_active(self) -> None:
        sm = self._make_sm()
        # CRITICAL_LOCK works from any active state (not IDLE)
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        sm.transition(ExecutionEvent.CRITICAL_LOCK, {})
        assert sm.state == ExecutionMajorState.LOCKED

    # ── Invalid transitions ─────────────────────────────────────────────

    def test_invalid_transition_raises(self) -> None:
        sm = self._make_sm()
        with pytest.raises(Exception):
            sm.transition(ExecutionEvent.FULL_FILL, {})  # Can't fill from IDLE

    def test_reset(self) -> None:
        sm = self._make_sm()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        assert sm.state == ExecutionMajorState.INTENT_RECEIVED
        sm.reset()
        assert sm.state == ExecutionMajorState.IDLE

    # ── Query helpers ───────────────────────────────────────────────────

    def test_can_receive_new_intent_only_idle(self) -> None:
        sm = self._make_sm()
        assert sm.can_receive_new_intent() is True
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        assert sm.can_receive_new_intent() is False

    def test_is_active_in_active_state(self) -> None:
        sm = self._make_sm()
        assert sm.is_active() is False
        sm.transition(ExecutionEvent.CAPTAIN_INTENT, {})
        assert sm.is_active() is True
