"""Side A — Execution-specific types and dataclasses.

Defines enums and dataclasses used exclusively by the Side A execution layer.
Shared types (ExecutionMode, TradeClass, ExecutionIntent, Severity, etc.)
live in ``shared/types.py`` — this file extends them with Side A specifics.

Architecture rules (LOCKED — see ROADMAP_SIDE_A):
- Side A executes, it does NOT decide
- Side A never creates trades (receives approved intent only)
- Side A never increases size (reduce-only for safety)
- Broker truth = final live authority
- ONE active live trade at a time
- ALERT always active, PAPER / REAL execution switch
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from junior_aladdin.shared.types import (
    ExecutionMode,
    Severity,
    TradeClass,
)


# =============================================================================
# ENUMS — Execution States
# =============================================================================


class ExecutionMajorState(Enum):
    """Major execution states for Side A's state machine.

    13 major states covering the full execution lifecycle from IDLE to CLOSED,
    including exceptional paths (FAILED, LOCKED, UNKNOWN_PENDING_RECONCILE).

    State transition table is owned by ``execution_state_machine.py``.
    """
    IDLE = "IDLE"
    INTENT_RECEIVED = "INTENT_RECEIVED"
    RISK_PASSED = "RISK_PASSED"
    ORDER_PENDING = "ORDER_PENDING"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    PROTECTED = "PROTECTED"
    MANAGING = "MANAGING"
    EXITING = "EXITING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"
    UNKNOWN_PENDING_RECONCILE = "UNKNOWN_PENDING_RECONCILE"


#: Alias matching the roadmap's ``UNKNOWN / PENDING_RECONCILE`` notation.
#: Both spellings work interchangeably in code.
UNKNOWN_PENDING_RECONCILE = ExecutionMajorState.UNKNOWN_PENDING_RECONCILE


class OrderState(Enum):
    """Lifecycle states for a single order.

    Tracks order progression from placement through acknowledgement,
    fills, modifications, and terminal states (filled / cancelled /
    rejected / expired).

    Managed by ``order_lifecycle_manager.py``.
    """
    PLACED = "PLACED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    MODIFIED = "MODIFIED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class KillSwitchState(Enum):
    """Current kill-switch activation state.

    Governed by ``kill_switch.py``:
    - NORMAL: No kill switch active. Normal operation.
    - SOFT_ACTIVE: Blocks new entries. Existing protected trades continue.
    - CRITICAL_ACTIVE: Flatten path + freeze execution. Emergency only.
    """
    NORMAL = "NORMAL"
    SOFT_ACTIVE = "SOFT_ACTIVE"
    CRITICAL_ACTIVE = "CRITICAL_ACTIVE"


class EscalationLevel(Enum):
    """Escalation level for execution safety states.

    Used by ``execution_logging_layer.py`` and dashboard visibility.
    """
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    SEVERE = "SEVERE"
    EMERGENCY = "EMERGENCY"


class ReconcileOutcome(Enum):
    """Outcome of a reconciliation cycle.

    MATCH: Local state matches broker truth.
    MISMATCH_RESOLVED: Mismatch detected and safely resolved.
    MISMATCH_ESCALATED: Mismatch could not be resolved — escalated.
    """
    MATCH = "MATCH"
    MISMATCH_RESOLVED = "MISMATCH_RESOLVED"
    MISMATCH_ESCALATED = "MISMATCH_ESCALATED"


# BlockedActionSeverity uses the same values as Severity but is semantically distinct.
# Re-exported here for documentation clarity per the roadmap specification.
BlockedActionSeverity = Severity


class DataHealthExecutionResponse(Enum):
    """Execution behavior determined from data health state.

    Mapped by ``data_health_policy.py``:
    - ALLOW_NORMAL: Normal execution — no restriction (GOOD / CAUTION health).
    - ALLOW_STRICT: Allow execution with stricter caution/risk checks.
    - BLOCK_NEW: Block new entries; existing protected trades continue.
    - ESCALATE_FLATTEN: Safety escalation / lock path / flatten policy.
    """
    ALLOW_NORMAL = "ALLOW_NORMAL"
    ALLOW_STRICT = "ALLOW_STRICT"
    BLOCK_NEW = "BLOCK_NEW"
    ESCALATE_FLATTEN = "ESCALATE_FLATTEN"



# =============================================================================
# DATACLASSES — Risk Gate
# =============================================================================


@dataclass
class RiskCheckResult:
    """Result of Side A's pre-order risk gate evaluation.

    The risk gate runs 12 pre-order checks. If ANY check fails,
    ``passed`` is False and the blocked action must be journaled.

    Fields:
        passed: Whether ALL checks passed.
        checks: List of (check_name, passed, reason) tuples.
        recommended_action: Suggested action (e.g., "BLOCK", "WAIT", "PROCEED").
        timestamp: When the risk check was performed.
    """
    passed: bool = False
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    recommended_action: str = "BLOCK"
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get_failed_checks(self) -> list[tuple[str, str]]:
        """Return list of (check_name, reason) for all failed checks."""
        return [(name, reason) for name, ok, reason in self.checks if not ok]


# =============================================================================
# DATACLASSES — Order & Position Lifecycle
# =============================================================================


@dataclass
class OrderRecord:
    """Full lifecycle record for a single order.

    Managed by ``order_lifecycle_manager.py``. Tracks the complete
    state history of an order from placement to terminal state.

    Fields:
        order_id: Unique order identifier.
        trade_id: The trade this order belongs to.
        state: Current OrderState.
        side: BUY or SELL.
        quantity: Requested quantity.
        filled_qty: Quantity filled so far.
        price: Order price.
        sl_price: Stop-loss price (if linked).
        target_price: Target price (if linked).
        created_at: When the order was created.
        updated_at: When the order was last updated.
        events: Chronological list of order lifecycle events.
    """
    order_id: str
    trade_id: str
    state: OrderState = OrderState.PLACED
    side: str = "BUY"
    quantity: int = 0
    filled_qty: int = 0
    price: float = 0.0
    sl_price: float | None = None
    target_price: float | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PositionState:
    """Current state of an active or recently closed position.

    Primary owner of position truth. Managed by ``position_manager.py``.
    Reflects the combined state from fills, protection, and management actions.

    Fields:
        trade_id: Unique trade identifier.
        direction: BUY or SELL.
        filled_qty: Total filled quantity.
        pending_qty: Quantity still pending fill.
        avg_price: Average fill price.
        sl_price: Current stop-loss price.
        target_price: Current target price.
        trail_activated: Whether trailing stop is active.
        breakeven_activated: Whether SL moved to breakeven.
        partial_exit_qty: Quantity already partially exited.
        pnl: Current realised P&L (partial) or total (closed).
        status: Position status (OPEN / CLOSED / PARTIALLY_CLOSED).
        updated_at: When the position was last updated.
    """
    trade_id: str
    direction: str = "BUY"
    filled_qty: int = 0
    pending_qty: int = 0
    avg_price: float = 0.0
    sl_price: float | None = None
    target_price: float | None = None
    trail_activated: bool = False
    breakeven_activated: bool = False
    partial_exit_qty: int = 0
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN / CLOSED / PARTIALLY_CLOSED
    updated_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# DATACLASSES — Snapshots & Records
# =============================================================================


@dataclass
class ExecutionSnapshot:
    """Complete snapshot of Side A's current execution state.

    Produced by ``execution_orchestrator.get_state()`` for consumption
    by Side B (Dashboard) and Side C (Memory).

    Fields:
        state: Current major execution state.
        position: Current position state (None if no active position).
        orders: List of active orders.
        risk_status: Dict summarising risk gate status.
        mode: Current execution mode.
        escalation_level: Current escalation level.
        kill_switch_state: Current kill-switch activation state.
        blocked_actions: Recent blocked action records.
        timestamp: Snapshot timestamp.
    """
    state: ExecutionMajorState = ExecutionMajorState.IDLE
    position: PositionState | None = None
    orders: list[OrderRecord] = field(default_factory=list)
    risk_status: dict[str, Any] = field(default_factory=dict)
    mode: ExecutionMode = ExecutionMode.ALERT
    escalation_level: EscalationLevel = EscalationLevel.NORMAL
    kill_switch_state: KillSwitchState = KillSwitchState.NORMAL
    blocked_actions: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BlockedActionRecord:
    """Record of a blocked action for the blocked action journal.

    Every time Side A blocks an action for safety/rule reasons,
    a BlockedActionRecord MUST be created and journaled.

    Severity taxonomy:
    - INFO: Routine informational block.
    - CAUTION: Notable block (e.g., duplicate intent).
    - SEVERE: Significant block (e.g., risk gate failure).
    - CRITICAL: Emergency block (e.g., kill switch active).

    Fields:
        timestamp: When the block occurred.
        trade_id: Which trade was blocked.
        block_reason: Why the action was blocked.
        mode: Execution mode at time of block.
        severity: Severity classification.
        details: Additional context dict.
    """
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trade_id: str = ""
    block_reason: str = ""
    mode: ExecutionMode = ExecutionMode.ALERT
    severity: Severity = Severity.INFO
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconciliationRecord:
    """Record of a reconciliation cycle outcome.

    Produced by ``reconciliation_engine.py`` when comparing local
    state against broker truth.

    Fields:
        timestamp: When reconciliation occurred.
        trade_id: Which trade was reconciled.
        local_state: Snapshot of local state at reconcile time.
        broker_state: Snapshot of broker state at reconcile time.
        mismatches: List of mismatch descriptions.
        outcome: The reconcile outcome.
        resolved_action: Action taken to resolve (if any).
        details: Additional context dict.
    """
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trade_id: str = ""
    local_state: dict[str, Any] = field(default_factory=dict)
    broker_state: dict[str, Any] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)
    outcome: ReconcileOutcome = ReconcileOutcome.MATCH
    resolved_action: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def default_risk_check_result() -> RiskCheckResult:
    """Create a default (all-passed) RiskCheckResult.

    Returns:
        RiskCheckResult with passed=True and a single PASSED check entry.
    """
    return RiskCheckResult(
        passed=True,
        checks=[("ALL_CHECKS", True, "All 12 checks passed")],
        recommended_action="PROCEED",
    )


def is_execution_active(state: ExecutionMajorState) -> bool:
    """Check whether the execution state machine is in an active state.

    Active states are those between INTENT_RECEIVED and CLOSED/FAILED/LOCKED.

    Args:
        state: The current execution major state.

    Returns:
        True if the state represents an active execution lifecycle.
    """
    active_states = {
        ExecutionMajorState.INTENT_RECEIVED,
        ExecutionMajorState.RISK_PASSED,
        ExecutionMajorState.ORDER_PENDING,
        ExecutionMajorState.PARTIAL_FILL,
        ExecutionMajorState.FILLED,
        ExecutionMajorState.PROTECTED,
        ExecutionMajorState.MANAGING,
        ExecutionMajorState.EXITING,
        ExecutionMajorState.UNKNOWN_PENDING_RECONCILE,
    }
    return state in active_states


def can_receive_new_intent(state: ExecutionMajorState) -> bool:
    """Check whether a new Captain intent can be accepted.

    New intents are only accepted when the state machine is IDLE,
    or in a terminal state (CLOSED / FAILED).

    Args:
        state: The current execution major state.

    Returns:
        True if a new intent can be accepted.
    """
    return state in {
        ExecutionMajorState.IDLE,
        ExecutionMajorState.CLOSED,
        ExecutionMajorState.FAILED,
    }
