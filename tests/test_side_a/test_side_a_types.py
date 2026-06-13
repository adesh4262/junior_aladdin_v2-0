"""Tests for side_a_types — enums, dataclasses, and helper functions."""

from __future__ import annotations

from datetime import datetime

from junior_aladdin.shared.types import ExecutionIntent, ExecutionMode, Severity, TradeClass
from junior_aladdin.side_a_execution.side_a_types import (
    BlockedActionRecord,
    DataHealthExecutionResponse,
    EscalationLevel,
    ExecutionMajorState,
    ExecutionSnapshot,
    KillSwitchState,
    OrderRecord,
    OrderState,
    PositionState,
    ReconcileOutcome,
    ReconciliationRecord,
    RiskCheckResult,
    can_receive_new_intent,
    default_risk_check_result,
    is_execution_active,
)


# =============================================================================
# ExecutionMajorState tests
# =============================================================================

def test_execution_major_state_has_13_states() -> None:
    """ExecutionMajorState must have exactly 13 states."""
    assert len(ExecutionMajorState) == 13


def test_execution_major_state_idle_is_first() -> None:
    """IDLE should be the first (default) state."""
    assert ExecutionMajorState.IDLE.value == "IDLE"


def test_execution_major_state_all_values() -> None:
    """All 13 states have expected string values."""
    expected = {
        "IDLE", "INTENT_RECEIVED", "RISK_PASSED", "ORDER_PENDING",
        "PARTIAL_FILL", "FILLED", "PROTECTED", "MANAGING", "EXITING",
        "CLOSED", "FAILED", "LOCKED", "UNKNOWN_PENDING_RECONCILE",
    }
    actual = {s.value for s in ExecutionMajorState}
    assert actual == expected


# =============================================================================
# OrderState tests
# =============================================================================

def test_order_state_has_8_states() -> None:
    """OrderState must have exactly 8 states."""
    assert len(OrderState) == 8


def test_order_state_all_values() -> None:
    """All 8 order states have expected string values."""
    expected = {
        "PLACED", "ACKNOWLEDGED", "PARTIAL_FILL", "FILLED",
        "MODIFIED", "CANCELLED", "REJECTED", "EXPIRED",
    }
    actual = {s.value for s in OrderState}
    assert actual == expected


# =============================================================================
# KillSwitchState tests
# =============================================================================

def test_kill_switch_state_values() -> None:
    """KillSwitchState has 3 expected states."""
    assert KillSwitchState.NORMAL.value == "NORMAL"
    assert KillSwitchState.SOFT_ACTIVE.value == "SOFT_ACTIVE"
    assert KillSwitchState.CRITICAL_ACTIVE.value == "CRITICAL_ACTIVE"


# =============================================================================
# EscalationLevel tests
# =============================================================================

def test_escalation_level_values() -> None:
    """EscalationLevel has 4 expected levels."""
    assert EscalationLevel.NORMAL.value == "NORMAL"
    assert EscalationLevel.CAUTION.value == "CAUTION"
    assert EscalationLevel.SEVERE.value == "SEVERE"
    assert EscalationLevel.EMERGENCY.value == "EMERGENCY"


# =============================================================================
# ReconcileOutcome tests
# =============================================================================

def test_reconcile_outcome_values() -> None:
    """ReconcileOutcome has 3 expected outcomes."""
    assert ReconcileOutcome.MATCH.value == "MATCH"
    assert ReconcileOutcome.MISMATCH_RESOLVED.value == "MISMATCH_RESOLVED"
    assert ReconcileOutcome.MISMATCH_ESCALATED.value == "MISMATCH_ESCALATED"


# =============================================================================
# DataHealthExecutionResponse tests
# =============================================================================

def test_data_health_execution_response_values() -> None:
    """DataHealthExecutionResponse has 3 expected responses."""
    assert DataHealthExecutionResponse.ALLOW_STRICT.value == "ALLOW_STRICT"
    assert DataHealthExecutionResponse.BLOCK_NEW.value == "BLOCK_NEW"
    assert DataHealthExecutionResponse.ESCALATE_FLATTEN.value == "ESCALATE_FLATTEN"


# =============================================================================
# RiskCheckResult tests
# =============================================================================

def test_risk_check_result_default() -> None:
    """RiskCheckResult defaults to failed state."""
    result = RiskCheckResult()
    assert result.passed is False
    assert result.recommended_action == "BLOCK"
    assert len(result.checks) == 0


def test_risk_check_result_all_passed() -> None:
    """RiskCheckResult with all checks passed."""
    checks = [
        ("CAPITAL", True, "Capital sufficient"),
        ("MARGIN", True, "Margin OK"),
    ]
    result = RiskCheckResult(passed=True, checks=checks, recommended_action="PROCEED")
    assert result.passed is True
    assert result.recommended_action == "PROCEED"
    assert len(result.checks) == 2


def test_risk_check_result_some_failed() -> None:
    """RiskCheckResult with some failed checks."""
    checks = [
        ("CAPITAL", True, "Capital sufficient"),
        ("MARGIN", False, "Margin insufficient"),
    ]
    result = RiskCheckResult(passed=False, checks=checks, recommended_action="BLOCK")
    failed = result.get_failed_checks()
    assert len(failed) == 1
    assert failed[0] == ("MARGIN", "Margin insufficient")


def test_default_risk_check_result() -> None:
    """default_risk_check_result returns a passed result."""
    result = default_risk_check_result()
    assert result.passed is True
    assert result.recommended_action == "PROCEED"
    assert len(result.checks) == 1


# =============================================================================
# OrderRecord tests
# =============================================================================

def test_order_record_defaults() -> None:
    """OrderRecord creates with minimal required fields."""
    record = OrderRecord(order_id="ORD-001", trade_id="TRADE-001")
    assert record.order_id == "ORD-001"
    assert record.trade_id == "TRADE-001"
    assert record.state == OrderState.PLACED
    assert record.quantity == 0
    assert record.filled_qty == 0
    assert isinstance(record.created_at, datetime)


def test_order_record_with_fill() -> None:
    """OrderRecord with fill data."""
    record = OrderRecord(
        order_id="ORD-002",
        trade_id="TRADE-002",
        state=OrderState.FILLED,
        quantity=75,
        filled_qty=75,
        price=19500.0,
    )
    assert record.state == OrderState.FILLED
    assert record.filled_qty == 75
    assert record.price == 19500.0


# =============================================================================
# PositionState tests
# =============================================================================

def test_position_state_defaults() -> None:
    """PositionState creates with required trade_id."""
    pos = PositionState(trade_id="TRADE-001")
    assert pos.trade_id == "TRADE-001"
    assert pos.direction == "BUY"
    assert pos.status == "OPEN"
    assert pos.pnl == 0.0
    assert pos.trail_activated is False


def test_position_state_after_fill() -> None:
    """PositionState after a fill."""
    pos = PositionState(
        trade_id="TRADE-001",
        direction="BUY",
        filled_qty=75,
        avg_price=19500.0,
        sl_price=19450.0,
        target_price=19600.0,
    )
    assert pos.filled_qty == 75
    assert pos.avg_price == 19500.0
    assert pos.sl_price == 19450.0
    assert pos.target_price == 19600.0


def test_position_state_partial_exit() -> None:
    """PositionState with partial exit."""
    pos = PositionState(
        trade_id="TRADE-001",
        filled_qty=75,
        partial_exit_qty=25,
        pnl=500.0,
        status="PARTIALLY_CLOSED",
    )
    assert pos.partial_exit_qty == 25
    assert pos.pnl == 500.0
    assert pos.status == "PARTIALLY_CLOSED"


# =============================================================================
# ExecutionSnapshot tests
# =============================================================================

def test_execution_snapshot_defaults() -> None:
    """ExecutionSnapshot creates with IDLE state."""
    snap = ExecutionSnapshot()
    assert snap.state == ExecutionMajorState.IDLE
    assert snap.mode == ExecutionMode.ALERT
    assert snap.escalation_level == EscalationLevel.NORMAL
    assert snap.kill_switch_state == KillSwitchState.NORMAL
    assert snap.position is None
    assert len(snap.orders) == 0


def test_execution_snapshot_with_position() -> None:
    """ExecutionSnapshot with an active position."""
    pos = PositionState(trade_id="TRADE-001", filled_qty=75)
    snap = ExecutionSnapshot(
        state=ExecutionMajorState.FILLED,
        position=pos,
        mode=ExecutionMode.PAPER,
    )
    assert snap.state == ExecutionMajorState.FILLED
    assert snap.position is not None
    assert snap.position.trade_id == "TRADE-001"
    assert snap.mode == ExecutionMode.PAPER


# =============================================================================
# BlockedActionRecord tests
# =============================================================================

def test_blocked_action_record_defaults() -> None:
    """BlockedActionRecord creates with default severity INFO."""
    record = BlockedActionRecord()
    assert record.severity.name == "INFO"
    assert record.trade_id == ""
    assert record.block_reason == ""


def test_blocked_action_record_with_data() -> None:
    """BlockedActionRecord with full data."""
    record = BlockedActionRecord(
        trade_id="TRADE-001",
        block_reason="Insufficient capital",
        mode=ExecutionMode.REAL,
        severity=Severity.SEVERE,
        details={"available": 5000, "required": 10000},
    )
    assert record.trade_id == "TRADE-001"
    assert record.block_reason == "Insufficient capital"
    assert record.severity == Severity.SEVERE


# =============================================================================
# ReconciliationRecord tests
# =============================================================================

def test_reconciliation_record_defaults() -> None:
    """ReconciliationRecord creates with MATCH outcome."""
    record = ReconciliationRecord()
    assert record.outcome == ReconcileOutcome.MATCH
    assert record.trade_id == ""


def test_reconciliation_record_mismatch() -> None:
    """ReconciliationRecord with mismatch."""
    record = ReconciliationRecord(
        trade_id="TRADE-001",
        mismatches=["Quantity mismatch: local=75, broker=50"],
        outcome=ReconcileOutcome.MISMATCH_RESOLVED,
        resolved_action="Adjusted local qty to 50",
    )
    assert len(record.mismatches) == 1
    assert record.outcome == ReconcileOutcome.MISMATCH_RESOLVED
    assert record.resolved_action == "Adjusted local qty to 50"


# =============================================================================
# Helper function tests
# =============================================================================

def test_is_execution_active_idle() -> None:
    """IDLE should NOT be considered active."""
    assert is_execution_active(ExecutionMajorState.IDLE) is False


def test_is_execution_active_active_states() -> None:
    """Active states should return True."""
    assert is_execution_active(ExecutionMajorState.INTENT_RECEIVED) is True
    assert is_execution_active(ExecutionMajorState.ORDER_PENDING) is True
    assert is_execution_active(ExecutionMajorState.FILLED) is True
    assert is_execution_active(ExecutionMajorState.MANAGING) is True


def test_is_execution_active_terminal_states() -> None:
    """Terminal states should return False."""
    assert is_execution_active(ExecutionMajorState.CLOSED) is False
    assert is_execution_active(ExecutionMajorState.FAILED) is False
    assert is_execution_active(ExecutionMajorState.LOCKED) is False


def test_can_receive_new_intent_idle() -> None:
    """IDLE should accept new intents."""
    assert can_receive_new_intent(ExecutionMajorState.IDLE) is True


def test_can_receive_new_intent_active() -> None:
    """Active states should NOT accept new intents."""
    assert can_receive_new_intent(ExecutionMajorState.ORDER_PENDING) is False
    assert can_receive_new_intent(ExecutionMajorState.FILLED) is False
    assert can_receive_new_intent(ExecutionMajorState.MANAGING) is False


def test_can_receive_new_intent_terminal() -> None:
    """Terminal states should accept new intents."""
    assert can_receive_new_intent(ExecutionMajorState.CLOSED) is True
    assert can_receive_new_intent(ExecutionMajorState.FAILED) is True


# =============================================================================
# Cross-module contract tests (shared/types.py + side_a_types.py)
# =============================================================================

def test_execution_intent_has_fingerprint() -> None:
    """ExecutionIntent must have intent_fingerprint field."""
    intent = ExecutionIntent(
        trade_id="T-001",
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        mode=ExecutionMode.ALERT,
    )
    assert intent.intent_fingerprint == ""
    assert isinstance(intent.timestamp, datetime)


def test_execution_intent_with_fingerprint() -> None:
    """ExecutionIntent with explicit fingerprint."""
    intent = ExecutionIntent(
        trade_id="T-001",
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        intent_fingerprint="fp_t001_buy_ce_19500_1234567890",
    )
    assert intent.intent_fingerprint == "fp_t001_buy_ce_19500_1234567890"
