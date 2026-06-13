"""Side A — Execution State Machine: 13 major states with full transition table.

The behavioral backbone of Side A. Defines all valid state transitions
for the execution lifecycle. ALL state changes MUST go through this module.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.6):
- Every valid transition is enumerated in the transition table
- Invalid transitions raise ExecutionError
- ALL state changes go through ExecutionStateMachine.transition()
- CRITICAL_LOCK and EMERGENCY_FLATTEN are accessible from ANY active state
- UNKNOWN_PENDING_RECONCILE has bounded reconciliation paths
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.side_a_types import (
    ExecutionMajorState,
    can_receive_new_intent,
    is_execution_active,
)


# =============================================================================
# Execution Event Enum
# =============================================================================


class ExecutionEvent(Enum):
    """Events that trigger state transitions in the ExecutionStateMachine.

    18 events covering the full execution lifecycle from intent receipt
    through close, including exceptional paths (kill switch, reconcile).
    """
    # Intent lifecycle
    CAPTAIN_INTENT = "CAPTAIN_INTENT"
    RISK_PASSED = "RISK_PASSED"
    RISK_FAILED = "RISK_FAILED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"

    # Fill lifecycle
    PARTIAL_FILL_RECEIVED = "PARTIAL_FILL_RECEIVED"
    FULL_FILL = "FULL_FILL"
    REJECTED = "REJECTED"
    TIMEOUT_UNCLEAR = "TIMEOUT_UNCLEAR"

    # Protection & management
    PROTECTION_STAGED = "PROTECTION_STAGED"
    MANAGEMENT_BEGINS = "MANAGEMENT_BEGINS"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    CLOSE_COMPLETE = "CLOSE_COMPLETE"

    # Emergency / kill switch
    CRITICAL_LOCK = "CRITICAL_LOCK"
    EMERGENCY_FLATTEN = "EMERGENCY_FLATTEN"

    # Reconciliation paths from UNKNOWN_PENDING_RECONCILE
    RECONCILE_SUCCESS_MANAGING = "RECONCILE_SUCCESS_MANAGING"
    RECONCILE_SUCCESS_PROTECTED = "RECONCILE_SUCCESS_PROTECTED"
    RECONCILE_UNRECOVERABLE = "RECONCILE_UNRECOVERABLE"
    RECONCILE_FAILSAFE = "RECONCILE_FAILSAFE"


# =============================================================================
# Transition Table
# =============================================================================

# Active states that can be killed / flattened
_ACTIVE_STATES_FOR_KILL = {
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

_TRANSITION_TABLE: dict[tuple[ExecutionMajorState, ExecutionEvent], ExecutionMajorState] = {}

# ── IDLE ─────────────────────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.IDLE, ExecutionEvent.CAPTAIN_INTENT)] = (
    ExecutionMajorState.INTENT_RECEIVED
)

# ── INTENT_RECEIVED ──────────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.INTENT_RECEIVED, ExecutionEvent.RISK_PASSED)] = (
    ExecutionMajorState.RISK_PASSED
)
_TRANSITION_TABLE[(ExecutionMajorState.INTENT_RECEIVED, ExecutionEvent.RISK_FAILED)] = (
    ExecutionMajorState.FAILED
)

# ── RISK_PASSED ──────────────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.RISK_PASSED, ExecutionEvent.ORDER_SUBMITTED)] = (
    ExecutionMajorState.ORDER_PENDING
)

# ── ORDER_PENDING ────────────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.ORDER_PENDING, ExecutionEvent.PARTIAL_FILL_RECEIVED)] = (
    ExecutionMajorState.PARTIAL_FILL
)
_TRANSITION_TABLE[(ExecutionMajorState.ORDER_PENDING, ExecutionEvent.FULL_FILL)] = (
    ExecutionMajorState.FILLED
)
_TRANSITION_TABLE[(ExecutionMajorState.ORDER_PENDING, ExecutionEvent.REJECTED)] = (
    ExecutionMajorState.FAILED
)
_TRANSITION_TABLE[(ExecutionMajorState.ORDER_PENDING, ExecutionEvent.TIMEOUT_UNCLEAR)] = (
    ExecutionMajorState.UNKNOWN_PENDING_RECONCILE
)

# ── PARTIAL_FILL → PROTECTED ─────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.PARTIAL_FILL, ExecutionEvent.PROTECTION_STAGED)] = (
    ExecutionMajorState.PROTECTED
)

# ── FILLED → PROTECTED ───────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.FILLED, ExecutionEvent.PROTECTION_STAGED)] = (
    ExecutionMajorState.PROTECTED
)

# ── PROTECTED → MANAGING ─────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.PROTECTED, ExecutionEvent.MANAGEMENT_BEGINS)] = (
    ExecutionMajorState.MANAGING
)

# ── MANAGING → EXITING ───────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.MANAGING, ExecutionEvent.EXIT_TRIGGERED)] = (
    ExecutionMajorState.EXITING
)

# ── EXITING → CLOSED ─────────────────────────────────────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.EXITING, ExecutionEvent.CLOSE_COMPLETE)] = (
    ExecutionMajorState.CLOSED
)

# ── CRITICAL_LOCK from ANY active state ──────────────────────────────────────
for _s in _ACTIVE_STATES_FOR_KILL:
    _TRANSITION_TABLE[(_s, ExecutionEvent.CRITICAL_LOCK)] = ExecutionMajorState.LOCKED

# ── EMERGENCY_FLATTEN from ANY active state ──────────────────────────────────
for _s in _ACTIVE_STATES_FOR_KILL:
    _TRANSITION_TABLE[(_s, ExecutionEvent.EMERGENCY_FLATTEN)] = ExecutionMajorState.CLOSED

# ── UNKNOWN_PENDING_RECONCILE — reconciliation paths ─────────────────────────
_TRANSITION_TABLE[(ExecutionMajorState.UNKNOWN_PENDING_RECONCILE, ExecutionEvent.RECONCILE_SUCCESS_MANAGING)] = (
    ExecutionMajorState.MANAGING
)
_TRANSITION_TABLE[(ExecutionMajorState.UNKNOWN_PENDING_RECONCILE, ExecutionEvent.RECONCILE_SUCCESS_PROTECTED)] = (
    ExecutionMajorState.PROTECTED
)
_TRANSITION_TABLE[(ExecutionMajorState.UNKNOWN_PENDING_RECONCILE, ExecutionEvent.RECONCILE_UNRECOVERABLE)] = (
    ExecutionMajorState.FAILED
)
_TRANSITION_TABLE[(ExecutionMajorState.UNKNOWN_PENDING_RECONCILE, ExecutionEvent.RECONCILE_FAILSAFE)] = (
    ExecutionMajorState.CLOSED
)


# =============================================================================
# Transition History Record
# =============================================================================


@dataclass
class TransitionRecord:
    """Record of a single state machine transition.

    Fields:
        from_state: The previous ExecutionMajorState.
        event: The ExecutionEvent that triggered the transition.
        to_state: The new ExecutionMajorState.
        timestamp: When the transition occurred.
        details: Optional context dict for debugging/audit.
    """
    from_state: str
    event: str
    to_state: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# ExecutionStateMachine
# =============================================================================


class ExecutionStateMachine:
    """State machine governing Side A's execution lifecycle.

    ALL state changes go through this class. Direct mutation of
    ExecutionMajorState is forbidden — use transition() with a valid event.

    The transition table (``_TRANSITION_TABLE``) is immutable after module load.
    Every valid (current_state, event) → next_state mapping is enumerated.

    Usage::

        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)         # IDLE → INTENT_RECEIVED
        sm.transition(ExecutionEvent.RISK_PASSED)             # INTENT_RECEIVED → RISK_PASSED
        sm.transition(ExecutionEvent.ORDER_SUBMITTED)         # RISK_PASSED → ORDER_PENDING
        print(sm.state)                                       # ORDER_PENDING
    """

    def __init__(self, initial_state: ExecutionMajorState = ExecutionMajorState.IDLE) -> None:
        """Initialize the state machine.

        Args:
            initial_state: Starting state. Defaults to IDLE.
        """
        self._state = initial_state
        self._history: list[TransitionRecord] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ExecutionMajorState:
        """Get the current execution state."""
        return self._state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transition(
        self,
        event: ExecutionEvent,
        details: dict[str, Any] | None = None,
    ) -> ExecutionMajorState:
        """Attempt a state transition triggered by the given event.

        Args:
            event: The ExecutionEvent that should trigger the transition.
            details: Optional dict of context for the transition history.

        Returns:
            The new ExecutionMajorState after a successful transition.

        Raises:
            ExecutionError: If the transition is not in the table or
                event is None/invalid.
        """
        if not isinstance(event, ExecutionEvent):
            raise ExecutionError(
                message="Invalid event type — must be an ExecutionEvent",
                details={
                    "event": str(event),
                    "current_state": self._state.value,
                },
            )

        key = (self._state, event)
        if key not in _TRANSITION_TABLE:
            raise ExecutionError(
                message=f"Invalid transition: {self._state.value} → {event.value}",
                details={
                    "current_state": self._state.value,
                    "event": event.value,
                },
            )

        new_state = _TRANSITION_TABLE[key]

        # Record the transition
        record = TransitionRecord(
            from_state=self._state.value,
            event=event.value,
            to_state=new_state.value,
            details=details or {},
        )
        self._history.append(record)

        self._state = new_state
        return new_state

    def can_transition(self, event: ExecutionEvent) -> bool:
        """Check whether a transition is valid from the current state.

        Args:
            event: The ExecutionEvent to check.

        Returns:
            True if the transition exists in the table.
        """
        key = (self._state, event)
        return key in _TRANSITION_TABLE

    def is_active(self) -> bool:
        """Check whether the state machine is in an active execution state.

        Active states are those between INTENT_RECEIVED and CLOSED/FAILED/LOCKED.

        Returns:
            True if the current state represents an active execution lifecycle.
        """
        return is_execution_active(self._state)

    def can_receive_new_intent(self) -> bool:
        """Check whether a new Captain intent can be accepted.

        New intents are only accepted when the state machine is IDLE,
        or in a terminal state (CLOSED / FAILED).

        Returns:
            True if a new intent can be accepted.
        """
        return can_receive_new_intent(self._state)

    def is_safe_to_proceed(self) -> bool:
        """Check whether the execution flow can safely proceed.

        Returns False if the state machine is in an error or unrecoverable
        state (FAILED, LOCKED, UNKNOWN_PENDING_RECONCILE).

        Returns:
            True if it's safe to continue the current execution flow.
        """
        return self._state not in {
            ExecutionMajorState.FAILED,
            ExecutionMajorState.LOCKED,
            ExecutionMajorState.UNKNOWN_PENDING_RECONCILE,
        }

    def reset(self) -> None:
        """Reset the state machine back to IDLE.

        Clears transition history. Use with caution — only appropriate
        after a trade has fully closed or at the start of a new session.
        """
        self._state = ExecutionMajorState.IDLE
        self._history.clear()

    def get_transition_history(self) -> list[TransitionRecord]:
        """Get the full transition history for the current session.

        Returns:
            A list of TransitionRecord objects in chronological order.
        """
        return list(self._history)

    def get_transition_table_size(self) -> int:
        """Get the total number of entries in the transition table.

        Useful for validation and test completeness.

        Returns:
            The number of (state, event) → next_state entries.
        """
        return len(_TRANSITION_TABLE)

    def get_available_events(self) -> list[ExecutionEvent]:
        """Get all valid events from the current state.

        Returns:
            List of ExecutionEvent values that can be triggered now.
        """
        return [
            event
            for (state, event) in _TRANSITION_TABLE
            if state == self._state
        ]
