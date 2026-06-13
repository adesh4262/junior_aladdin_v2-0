"""Side A — Execution Core: Broker/simulator-facing order actor.

This module is responsible for operational order actions. It sits between
the rest of Side A and the broker/simulator, handling order submission,
acknowledgement tracking, rejection handling, retry logic, and fill events.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.8 & Section 24):
- Execution Core = broker interaction owner
- Execution Core does NOT own strategy
- Execution Core does NOT own position truth (Position Manager does)
- Execution Core does NOT own order-state transitions (OLM does)
- Broker is INJECTED (paper_broker or real_broker) — same interface
- ALL state changes go through execution_state_machine
- Retry only on recoverable failures (defined constants below)
- Non-recoverable failures → fail immediately

Ownership split:
- Execution Core = broker interaction owner
- Order Lifecycle Manager = order-state owner
- Position Manager = position truth owner
- Captain = rare strategic override authority

Output contracts:
- To OrderLifecycleManager: state transition events (via callback)
- To PositionManager: fill quantity, price updates (via callback)
- To blocked_action_journal: rejection records (via callback)
- To execution_logging_layer: all events (via callback)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.execution_state_machine import (
    ExecutionEvent,
    ExecutionStateMachine,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_RETRIES: int = 3
"""Default maximum number of retry attempts for recoverable failures."""

DEFAULT_RETRY_BACKOFF_SECONDS: float = 1.0
"""Default delay between retry attempts (in seconds)."""

DEFAULT_CIRCUIT_BREAKER_THRESHOLD: int = 5
"""Number of consecutive failures before circuit breaker trips."""

DEFAULT_CIRCUIT_BREAKER_RESET_SECONDS: float = 300.0
"""Time after which circuit breaker resets (5 minutes default)."""

RECOVERABLE_REJECTION_REASONS: set[str] = {
    "TIMEOUT",
    "THROTTLED",
    "GATEWAY_ERROR",
    "NETWORK_ERROR",
    "INSUFFICIENT_BALANCE",  # Can retry after balance check
    "ORDER_TOO_SMALL",       # Can adjust qty and retry
}
"""Rejection reasons considered recoverable for automatic retry.

Non-recoverable reasons (fail immediately):
- REJECTED_INVALID_PRICE
- REJECTED_INVALID_QUANTITY
- REJECTED_INSTRUMENT_INACTIVE
- REJECTED_EXPIRED
- REJECTED_DUPLICATE_ORDER_ID
- REJECTED_MARKET_CLOSED
"""


# =============================================================================
# Broker Protocol — duck-typed interface for paper_broker / real_broker
# =============================================================================


class BrokerProtocol(Protocol):
    """Protocol defining the minimal broker/simulator interface.

    Both paper_broker and real_broker MUST implement this interface
    to maintain PAPER/REAL parity on core lifecycle behavior.

    Methods:
        place_order(order_data): Submit an order to the broker.
            Returns a dict with at minimum: order_id, status, timestamp.
        cancel_order(order_id): Cancel an existing order.
            Returns a dict with at minimum: order_id, status, timestamp.
        get_order_status(order_id): Get current status of an order.
            Returns a dict with at minimum: order_id, status, timestamp.
    """

    def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit an order to the broker.

        Args:
            order_data: Dict with order details (trade_id, action, quantity,
                       price, order_type, option_side, strike, etc.).

        Returns:
            Dict with at minimum: order_id, status, timestamp.
            May also include: filled_qty, avg_price, reject_reason.
        """
        ...

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an existing order.

        Args:
            order_id: The broker-assigned order identifier.

        Returns:
            Dict with at minimum: order_id, status, timestamp.
            status should be "CANCELLED" on success.
        """
        ...

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Get current status of an order.

        Args:
            order_id: The broker-assigned order identifier.

        Returns:
            Dict with at minimum: order_id, status, timestamp.
            status examples: "PENDING", "ACKNOWLEDGED", "PARTIAL_FILL",
            "FILLED", "REJECTED", "CANCELLED".
        """
        ...


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class OrderSubmission:
    """Data required to submit an order to the broker.

    Fields:
        trade_id: The trade this order belongs to.
        action: BUY or SELL.
        option_side: CE or PE.
        strike: The selected strike price.
        quantity: Number of lots.
        price: Limit price for the order.
        order_type: Order type (default "LIMIT").
        sl_price: Optional stop-loss trigger price.
        target_price: Optional target price.
        validity: Order validity (default "DAY").
        extra: Additional broker-specific fields.
    """
    trade_id: str
    action: str  # BUY / SELL
    option_side: str  # CE / PE
    strike: str
    quantity: int = 1
    price: float = 0.0
    order_type: str = "LIMIT"
    sl_price: float | None = None
    target_price: float | None = None
    validity: str = "DAY"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_execution_intent(
        cls,
        intent: Any,
        quantity: int = 1,
        order_type: str = "LIMIT",
    ) -> "OrderSubmission":
        """Build an OrderSubmission from an ExecutionIntent.

        Convenience constructor for the common case of converting
        a validated ExecutionIntent into a broker-ready order.

        Args:
            intent: An ExecutionIntent (or duck-typed equivalent with
                   trade_id, action, option_side, selected_strike,
                   entry_plan, stop_loss_plan, target_plan fields).
            quantity: Number of lots (default 1).
            order_type: Order type (default "LIMIT").

        Returns:
            An OrderSubmission populated from the intent fields.
        """
        return cls(
            trade_id=intent.trade_id,
            action=intent.action,
            option_side=intent.option_side,
            strike=intent.selected_strike,
            quantity=quantity,
            price=intent.entry_plan.get("price", 0.0),
            order_type=order_type,
            sl_price=intent.stop_loss_plan.get("price"),
            target_price=intent.target_plan.get("price"),
        )


@dataclass
class AckData:
    """Acknowledgement data received from broker after order submission.

    Fields:
        order_id: Broker-assigned order identifier.
        status: Current status (e.g., "ACKNOWLEDGED", "PENDING").
        timestamp: When the acknowledgement was received.
        broker_ref: Optional broker reference number.
        extra: Additional broker-specific acknowledgement fields.
    """
    order_id: str
    status: str = "ACKNOWLEDGED"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    broker_ref: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FillData:
    """Fill event data received from broker.

    Fields:
        order_id: The order that was filled.
        trade_id: The trade this fill belongs to.
        filled_qty: Quantity filled in this event.
        price: Fill price.
        timestamp: When the fill occurred.
        remaining_qty: Quantity still pending (0 if fully filled).
        is_partial: True if this is a partial fill (remaining_qty > 0).
        extra: Additional broker-specific fill fields.
    """
    order_id: str
    trade_id: str
    filled_qty: int
    price: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    remaining_qty: int = 0
    is_partial: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Auto-detect is_partial from remaining_qty if not explicitly set."""
        if self.remaining_qty > 0:
            self.is_partial = True


# =============================================================================
# ExecutionCore
# =============================================================================


class ExecutionCore:
    """Broker/simulator-facing order actor for Side A execution.

    Responsible for operational order actions — submitting orders to the
    injected broker, tracking acknowledgements, handling rejections with
    retry logic, processing fill events, and forwarding to downstream
    components via callbacks.

    The broker is INJECTED, allowing the same ExecutionCore to work with
    both paper_broker (simulated) and real_broker (Angel One live).

    Usage::

        core = ExecutionCore(
            state_machine=state_machine,
            broker=paper_broker,
            on_fill_callback=position_manager.update_fill,
            on_rejection_callback=blocked_action_journal.record,
        )

        order_sub = OrderSubmission.from_execution_intent(intent)
        order_id = core.submit_order(order_sub)
        # → state machine transitions to ORDER_PENDING
        # → broker receives order
        # → ack tracked

        core.handle_fill(order_id, FillData(...))
        # → on_fill_callback invoked
        # → state machine transitions to FILLED / PARTIAL_FILL
    """

    def __init__(
        self,
        state_machine: ExecutionStateMachine,
        broker: BrokerProtocol,
        on_fill_callback: Callable[[FillData], None] | None = None,
        on_rejection_callback: Callable[[str, str], None] | None = None,
        on_ack_callback: Callable[[str, AckData], None] | None = None,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
        on_circuit_breaker_callback: Callable[[dict[str, Any]], None] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        circuit_breaker_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
        circuit_breaker_reset_seconds: float = DEFAULT_CIRCUIT_BREAKER_RESET_SECONDS,
    ) -> None:
        """Initialize the ExecutionCore.

        Args:
            state_machine: The ExecutionStateMachine for state transitions.
            broker: Injected broker instance (paper_broker or real_broker).
            on_fill_callback: Called when a fill event is received.
                Signature: (fill_data: FillData) -> None
                Expected to forward to PositionManager + OLM.
            on_rejection_callback: Called when an order is rejected.
                Signature: (order_id: str, reason: str) -> None
                Expected to forward to blocked_action_journal.
            on_ack_callback: Called when an acknowledgement is received.
                Signature: (order_id: str, ack_data: AckData) -> None
                Expected to forward to OLM + logging.
            on_log_callback: Called for all execution events.
                Signature: (event_type: str, data: dict) -> None
                Expected to forward to execution_logging_layer.
            max_retries: Maximum retry attempts for recoverable failures.
            retry_backoff_seconds: Delay between retry attempts.
        """
        self._state_machine = state_machine
        self._broker = broker
        self._on_fill_callback = on_fill_callback
        self._on_rejection_callback = on_rejection_callback
        self._on_ack_callback = on_ack_callback
        self._on_log_callback = on_log_callback
        self._on_circuit_breaker_callback = on_circuit_breaker_callback
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_reset_seconds = circuit_breaker_reset_seconds

        # Runtime BrokerProtocol validation
        if not hasattr(broker, 'place_order') or not callable(broker.place_order):
            raise ExecutionError(
                message="Injected broker missing required method: place_order",
            )
        if not hasattr(broker, 'cancel_order') or not callable(broker.cancel_order):
            raise ExecutionError(
                message="Injected broker missing required method: cancel_order",
            )
        if not hasattr(broker, 'get_order_status') or not callable(broker.get_order_status):
            raise ExecutionError(
                message="Injected broker missing required method: get_order_status",
            )

        # Internal state: order_id -> order tracking
        self._orders: dict[str, OrderSubmission] = {}
        self._retry_counts: dict[str, int] = {}
        self._order_statuses: dict[str, str] = {}

        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_breaker_tripped_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_order(
        self,
        order: OrderSubmission,
        broker_override: BrokerProtocol | None = None,
    ) -> str:
        """Submit an order to the broker.

        Validates the state machine can transition to ORDER_PENDING,
        sends the order to the broker, processes the acknowledgement,
        and transitions the state machine.

        Args:
            order: The OrderSubmission with all required fields.
            broker_override: Optional alternative broker to use (for testing).

        Returns:
            The broker-assigned order_id.

        Raises:
            ExecutionError: If the state machine is not in RISK_PASSED state
                or the broker rejects the order with a non-recoverable error.
        """
        if order is None:
            raise ExecutionError(
                message="Cannot submit None order",
            )

        # Validate state machine readiness
        if not self._state_machine.can_transition(ExecutionEvent.ORDER_SUBMITTED):
            raise ExecutionError(
                message="Cannot submit order — state machine not ready for ORDER_SUBMITTED",
                details={
                    "current_state": self._state_machine.state.value,
                    "available_events": [e.value for e in self._state_machine.get_available_events()],
                },
            )

        # Select broker (use override for testing, injected broker otherwise)
        broker = broker_override if broker_override is not None else self._broker

        # Build order data dict for the broker
        order_data = self._build_order_data(order)

        # Submit to broker
        self._log("ORDER_SUBMIT", {"trade_id": order.trade_id, "action": order.action})

        try:
            broker_response = broker.place_order(order_data)
        except Exception as e:
            raise ExecutionError(
                message=f"Broker submission failed: {e}",
                details={
                    "trade_id": order.trade_id,
                    "order_type": order.order_type,
                },
                original_exception=e if isinstance(e, Exception) else None,
            )

        # Process broker response
        ack = self._parse_ack(broker_response)
        order_id = ack.order_id

        if not order_id:
            raise ExecutionError(
                message="Broker returned empty order_id",
                details={"trade_id": order.trade_id},
            )

        # Store order tracking
        self._orders[order_id] = order
        self._order_statuses[order_id] = ack.status
        self._retry_counts[order_id] = 0

        # Handle acknowledgement callback
        if self._on_ack_callback:
            self._on_ack_callback(order_id, ack)

        # Transition state machine to ORDER_PENDING first
        self._state_machine.transition(
            ExecutionEvent.ORDER_SUBMITTED,
            details={"order_id": order_id, "trade_id": order.trade_id},
        )

        # Check if broker already rejected — handle after ORDER_PENDING
        if ack.status == "REJECTED":
            reason = ack.extra.get("reject_reason", "Unknown rejection")
            self._handle_rejection_internal(order_id, reason)
            return order_id

        self._log("ORDER_ACKNOWLEDGED", {
            "order_id": order_id,
            "trade_id": order.trade_id,
            "status": ack.status,
        })

        return order_id

    def handle_acknowledgement(
        self,
        order_id: str,
        ack_data: dict[str, Any],
    ) -> AckData:
        """Process a broker acknowledgement for an existing order.

        Args:
            order_id: The broker-assigned order identifier.
            ack_data: Raw acknowledgement data from the broker.

        Returns:
            The parsed AckData.

        Raises:
            ExecutionError: If order_id is unknown.
        """
        if order_id not in self._orders:
            raise ExecutionError(
                message=f"Cannot handle acknowledgement for unknown order: {order_id}",
            )

        ack = self._parse_ack(ack_data)
        self._order_statuses[order_id] = ack.status

        if self._on_ack_callback:
            self._on_ack_callback(order_id, ack)

        self._log("ACKNOWLEDGEMENT", {
            "order_id": order_id,
            "status": ack.status,
        })

        return ack

    def handle_rejection(self, order_id: str, reason: str) -> None:
        """Handle an order rejection from the broker.

        Classifies the rejection as recoverable or non-recoverable.
        Recoverable rejections trigger automatic retry (up to max_retries).
        Non-recoverable rejections fail immediately and invoke the
        rejection callback.

        Args:
            order_id: The broker-assigned order identifier.
            reason: The rejection reason string.
        """
        self._handle_rejection_internal(order_id, reason)

    def handle_fill(self, order_id: str, fill_data: dict[str, Any]) -> FillData:
        """Process a fill event from the broker.

        Parses the fill data, determines if partial or full fill,
        invokes the fill callback (for PositionManager + OLM),
        and transitions the state machine.

        Args:
            order_id: The order that was filled.
            fill_data: Raw fill data from the broker.

        Returns:
            The parsed FillData.

        Raises:
            ExecutionError: If order_id is unknown or fill data is invalid.
        """
        if order_id not in self._orders:
            raise ExecutionError(
                message=f"Cannot handle fill for unknown order: {order_id}",
            )

        if fill_data is None:
            raise ExecutionError(
                message="Cannot handle None fill data",
                details={"order_id": order_id},
            )

        # Parse fill data
        order = self._orders[order_id]
        filled_qty = fill_data.get("filled_qty", 0)
        price = fill_data.get("price", 0.0)
        remaining_qty = fill_data.get("remaining_qty", 0)
        is_partial = fill_data.get("is_partial", remaining_qty > 0)

        if filled_qty <= 0:
            raise ExecutionError(
                message=f"Invalid fill quantity: {filled_qty}",
                details={"order_id": order_id, "filled_qty": filled_qty},
            )

        fill = FillData(
            order_id=order_id,
            trade_id=order.trade_id,
            filled_qty=filled_qty,
            price=price,
            remaining_qty=remaining_qty,
            is_partial=is_partial,
            timestamp=fill_data.get("timestamp", datetime.utcnow()),
            extra=fill_data.get("extra", {}),
        )

        # Update order status
        self._order_statuses[order_id] = "PARTIAL_FILL" if is_partial else "FILLED"

        # Invoke fill callback (forwards to PositionManager + OLM)
        if self._on_fill_callback:
            self._on_fill_callback(fill)

        # Transition state machine
        if is_partial:
            self._state_machine.transition(
                ExecutionEvent.PARTIAL_FILL_RECEIVED,
                details={
                    "order_id": order_id,
                    "filled_qty": filled_qty,
                    "remaining_qty": remaining_qty,
                },
            )
        else:
            self._state_machine.transition(
                ExecutionEvent.FULL_FILL,
                details={
                    "order_id": order_id,
                    "filled_qty": filled_qty,
                    "price": price,
                },
            )

        self._log("FILL", {
            "order_id": order_id,
            "trade_id": order.trade_id,
            "filled_qty": filled_qty,
            "price": price,
            "is_partial": is_partial,
        })

        return fill

    def retry_order(self, order_id: str) -> str | None:
        """Retry a failed order if the failure is recoverable.

        Resubmits the same order to the broker. Increments retry count.
        Returns None if max retries exceeded or order not found.

        Args:
            order_id: The original order identifier to retry.

        Returns:
            New order_id if retry was submitted, None if max retries exceeded.

        Raises:
            ExecutionError: If the retry fails with a non-recoverable error.
        """
        if order_id not in self._orders:
            self._log("RETRY_FAILED", {
                "order_id": order_id,
                "reason": "Order not found",
            })
            return None

        # Check retry limit
        current_retries = self._retry_counts.get(order_id, 0)
        if current_retries >= self._max_retries:
            self._log("RETRY_LIMIT_EXCEEDED", {
                "order_id": order_id,
                "max_retries": self._max_retries,
            })
            return None

        # Check circuit breaker
        if self._is_circuit_open():
            self._log("RETRY_CIRCUIT_OPEN", {
                "order_id": order_id,
                "consecutive_failures": self._consecutive_failures,
            })
            return None

        # Increment retry count
        self._retry_counts[order_id] = current_retries + 1

        # Exponential backoff: delay = base * (2 ^ attempt) with jitter
        backoff = self._retry_backoff_seconds * math.pow(2, current_retries)
        self._log("RETRY_BACKOFF", {
            "order_id": order_id,
            "attempt": current_retries + 1,
            "backoff_seconds": backoff,
        })
        if backoff > 0:
            time.sleep(backoff)

        # Resubmit the order
        order = self._orders[order_id]
        self._log("RETRY", {
            "order_id": order_id,
            "attempt": current_retries + 1,
            "max_retries": self._max_retries,
            "backoff_seconds": backoff,
        })

        # Submit via broker (bypass state machine — already in ORDER_PENDING)
        order_data = self._build_order_data(order)
        try:
            broker_response = self._broker.place_order(order_data)
        except Exception as e:
            self._consecutive_failures += 1
            self._check_circuit_breaker()
            raise ExecutionError(
                message=f"Retry submission failed: {e}",
                details={"order_id": order_id, "attempt": current_retries + 1},
                original_exception=e if isinstance(e, Exception) else None,
            )

        ack = self._parse_ack(broker_response)
        new_order_id = ack.order_id

        if not new_order_id:
            raise ExecutionError(
                message="Broker returned empty order_id on retry",
                details={"original_order_id": order_id},
            )

        # Track new order
        self._orders[new_order_id] = order
        self._order_statuses[new_order_id] = ack.status
        self._retry_counts[new_order_id] = 0

        if self._on_ack_callback:
            self._on_ack_callback(new_order_id, ack)

        return new_order_id

    def set_circuit_breaker_callback(
        self,
        callback: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        """Set or clear the circuit breaker callback for auto-kill-switch.

        When the circuit breaker trips (consecutive failures exceed
        threshold), this callback is invoked so the orchestrator can
        automatically activate the kill switch.

        Args:
            callback: Callable receiving a dict with ``reason``,
                ``threshold``, and ``consecutive_failures`` keys,
                or None to clear.
        """
        self._on_circuit_breaker_callback = callback

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Attempt to cancel an order via the broker.

        Returns a structured result dict with order_id, status, and
        optional error details for proper error handling downstream.

        Args:
            order_id: The broker-assigned order identifier to cancel.

        Returns:
            Dict with:
                - 'order_id': the order identifier
                - 'status': \"CANCELLED\", \"NOT_FOUND\", \"FAILED\"
                - 'error': error message (if status is FAILED)
                - 'previous_status': previous tracked status (if known)
        """
        if order_id not in self._orders:
            self._log("CANCEL_FAILED", {
                "order_id": order_id,
                "reason": "Order not found",
            })
            return {
                "order_id": order_id,
                "status": "NOT_FOUND",
            }

        previous_status = self._order_statuses.get(order_id, "UNKNOWN")
        self._log("CANCEL_REQUESTED", {"order_id": order_id})

        try:
            response = self._broker.cancel_order(order_id)
            status = response.get("status", "UNKNOWN")
            self._order_statuses[order_id] = status
            self._log("CANCEL_RESULT", {
                "order_id": order_id,
                "status": status,
            })
            return {
                "order_id": order_id,
                "status": "CANCELLED" if status == "CANCELLED" else status,
                "previous_status": previous_status,
            }
        except Exception as e:
            self._log("CANCEL_FAILED", {
                "order_id": order_id,
                "error": str(e),
            })
            return {
                "order_id": order_id,
                "status": "FAILED",
                "error": str(e),
                "previous_status": previous_status,
            }

    def get_order_status(self, order_id: str) -> str | None:
        """Get the current tracked status of an order.

        Args:
            order_id: The order identifier.

        Returns:
            The current status string, or None if order not found.
        """
        return self._order_statuses.get(order_id)

    def get_active_order_ids(self) -> list[str]:
        """Get all order IDs that are in a non-terminal state.

        Returns:
            List of order IDs for orders that are still active.
        """
        terminal_statuses = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
        return [
            oid for oid, status in self._order_statuses.items()
            if status not in terminal_statuses
        ]

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def max_retries(self) -> int:
        """Get the maximum number of retry attempts for recoverable failures."""
        return self._max_retries

    @max_retries.setter
    def max_retries(self, value: int) -> None:
        """Set the maximum number of retry attempts."""
        if value < 0:
            raise ExecutionError(
                message="max_retries must be non-negative",
                details={"value": value},
            )
        self._max_retries = value

    @property
    def retry_backoff_seconds(self) -> float:
        """Get the delay between retry attempts in seconds."""
        return self._retry_backoff_seconds

    @retry_backoff_seconds.setter
    def retry_backoff_seconds(self, value: float) -> None:
        """Set the delay between retry attempts in seconds."""
        if value < 0:
            raise ExecutionError(
                message="retry_backoff_seconds must be non-negative",
                details={"value": value},
            )
        self._retry_backoff_seconds = value

    # ------------------------------------------------------------------
    # Circuit Breaker
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        """Check whether the circuit breaker is currently open.

        When open, all retry attempts are rejected immediately to
        avoid hammering a failing broker.  The circuit auto-resets
        after ``circuit_breaker_reset_seconds``.

        Returns:
            True if circuit is open and retries should be blocked.
        """
        if self._circuit_breaker_tripped_at is None:
            return False

        # Check if enough time has passed to auto-reset
        elapsed = (datetime.utcnow() - self._circuit_breaker_tripped_at).total_seconds()
        if elapsed >= self._circuit_breaker_reset_seconds:
            self._reset_circuit_breaker()
            return False

        return True

    def _check_circuit_breaker(self) -> None:
        """Check consecutive failure count and trip circuit if threshold exceeded.

        Fires the circuit breaker callback (for auto-kill-switch) if
        the threshold is reached.
        """
        if self._circuit_breaker_tripped_at is not None:
            return  # Already tripped

        if self._consecutive_failures >= self._circuit_breaker_threshold:
            self._circuit_breaker_tripped_at = datetime.utcnow()

            self._log("CIRCUIT_BREAKER_TRIPPED", {
                "consecutive_failures": self._consecutive_failures,
                "threshold": self._circuit_breaker_threshold,
                "reset_after_seconds": self._circuit_breaker_reset_seconds,
            })

            # Fire callback for auto-kill-switch
            if self._on_circuit_breaker_callback:
                try:
                    self._on_circuit_breaker_callback({
                        "reason": f"Circuit breaker tripped after "
                                   f"{self._consecutive_failures} consecutive failures",
                        "threshold": self._circuit_breaker_threshold,
                        "consecutive_failures": self._consecutive_failures,
                    })
                except Exception as e:
                    self._log("CIRCUIT_BREAKER_CALLBACK_FAILED", {
                        "error": str(e),
                    })

    def _reset_circuit_breaker(self) -> None:
        """Reset the circuit breaker after cooldown period."""
        self._consecutive_failures = 0
        self._circuit_breaker_tripped_at = None
        self._log("CIRCUIT_BREAKER_RESET", {})

    def reset_consecutive_failures(self) -> None:
        """Reset the consecutive failure counter (e.g., after a successful fill)."""
        self._consecutive_failures = 0
        if self._circuit_breaker_tripped_at is not None:
            self._circuit_breaker_tripped_at = None

        self._log("CONSECUTIVE_FAILURES_RESET", {})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_order_data(self, order: OrderSubmission) -> dict[str, Any]:
        """Build a broker-compatible order data dict from an OrderSubmission.

        Args:
            order: The OrderSubmission to convert.

        Returns:
            Dict ready for broker.place_order().
        """
        data: dict[str, Any] = {
            "trade_id": order.trade_id,
            "action": order.action,
            "option_side": order.option_side,
            "strike": order.strike,
            "quantity": order.quantity,
            "price": order.price,
            "order_type": order.order_type,
            "validity": order.validity,
        }
        if order.sl_price is not None:
            data["sl_price"] = order.sl_price
        if order.target_price is not None:
            data["target_price"] = order.target_price
        if order.extra:
            data["extra"] = order.extra
        return data

    def _parse_ack(self, response: dict[str, Any]) -> AckData:
        """Parse a broker response into an AckData dataclass.

        Args:
            response: Raw response dict from the broker.

        Returns:
            An AckData instance with parsed fields.
        """
        return AckData(
            order_id=response.get("order_id", ""),
            status=response.get("status", "PENDING"),
            timestamp=response.get("timestamp", datetime.utcnow()),
            broker_ref=response.get("broker_ref", ""),
            extra=response.get("extra", {}),
        )

    def _is_recoverable(self, reason: str) -> bool:
        """Check whether a rejection reason is recoverable.

        Args:
            reason: The rejection reason string.

        Returns:
            True if the reason is in RECOVERABLE_REJECTION_REASONS.
        """
        return reason.upper() in RECOVERABLE_REJECTION_REASONS

    def _handle_rejection_internal(self, order_id: str, reason: str) -> None:
        """Internal rejection handler with retry logic and circuit breaker.

        Classifies the rejection and either retries (recoverable)
        or fails (non-recoverable).  Tracks consecutive failures for
        circuit breaker — after threshold, auto-tripped.

        If the order_id is not tracked, only invokes the callback
        and does NOT touch the state machine.

        Args:
            order_id: The rejected order identifier.
            reason: The rejection reason.
        """
        # Guard: skip state machine transition for unknown orders
        if order_id not in self._orders:
            self._log("REJECTION", {
                "order_id": order_id,
                "reason": reason,
                "warning": "Unknown order — rejection recorded but state machine not updated",
            })
            if self._on_rejection_callback:
                self._on_rejection_callback(order_id, reason)
            return

        self._order_statuses[order_id] = "REJECTED"

        # Increment consecutive failure counter
        self._consecutive_failures += 1
        self._check_circuit_breaker()

        # Log the rejection
        self._log("REJECTION", {
            "order_id": order_id,
            "reason": reason,
            "recoverable": self._is_recoverable(reason),
            "consecutive_failures": self._consecutive_failures,
        })

        # Invoke rejection callback
        if self._on_rejection_callback:
            self._on_rejection_callback(order_id, reason)

        # Attempt retry if recoverable AND circuit is not open
        if self._is_recoverable(reason) and not self._is_circuit_open():
            new_order_id = self.retry_order(order_id)
            if new_order_id:
                self._log("RETRY_SUBMITTED", {
                    "original_order_id": order_id,
                    "new_order_id": new_order_id,
                })
                return
            # Retry failed — fall through to fail

        # Non-recoverable, circuit open, or max retries exceeded
        self._state_machine.transition(
            ExecutionEvent.REJECTED,
            details={
                "order_id": order_id,
                "reason": reason,
                "recoverable": self._is_recoverable(reason),
                "retry_count": self._retry_counts.get(order_id, 0),
                "consecutive_failures": self._consecutive_failures,
                "circuit_open": self._is_circuit_open(),
            },
        )

        self._log("ORDER_FAILED", {
            "order_id": order_id,
            "reason": reason,
            "retry_count": self._retry_counts.get(order_id, 0),
            "consecutive_failures": self._consecutive_failures,
        })

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event being logged.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
