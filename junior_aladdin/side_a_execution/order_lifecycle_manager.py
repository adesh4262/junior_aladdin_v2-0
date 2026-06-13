"""Side A — Order Lifecycle Manager: Order state tracking with SL/TGT linkage.

Tracks and manages order states through their full lifecycle from placement
through terminal states (filled / cancelled / rejected / expired). Provides
SL/TGT OCO-style logical linkage with position quantity synchronisation.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.9 & Section 9):
- Order Lifecycle Manager = order-state owner
- Position Manager = position truth owner (separate — related but not identical)
- Execution Core = broker interaction owner
- SL/TGT linkage is OCO-style logical + position quantity sync
- SL/TGT are NOT independent — both linked to position quantity
- ALL order state transitions go through update_state() for validation

Ownership split (locked — see Section 24):
- Order Lifecycle Manager owns order-state transitions
- Position Manager owns position truth
- Execution Core owns broker interaction
- Protection Model uses OLM to stage SL/TGT orders

Output contracts:
- OrderRecord updates → PositionManager (fill qty, price)
- OrderRecord updates → execution_logging_layer
- SLTGTLinkage → reconciliation_engine for mismatch detection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.side_a_types import (
    OrderRecord,
    OrderState,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_ACTIVE_ORDERS_PER_TRADE: int = 10
"""Maximum number of concurrently tracked orders per trade (safety limit)."""


# =============================================================================
# SL/TGT Linkage Dataclass
# =============================================================================


@dataclass
class SLTGTLinkage:
    """OCO-style logical linkage between a primary order and its SL/TGT orders.

    SL and TGT orders are linked to the primary order (not independently).
    When the primary position quantity changes (e.g., partial fill), both
    SL and TGT quantities are adjusted proportionally.

    Fields:
        primary_order_id: The order this SL/TGT protects.
        sl_order_id: The stop-loss order ID.
        tgt_order_id: The target/profit order ID.
        linked_at: When the linkage was established.
        sl_order_state: Current OrderState of the SL order.
        tgt_order_state: Current OrderState of the TGT order.
        sl_quantity: SL order quantity (adjusted for partial fills).
        tgt_quantity: TGT order quantity (adjusted for partial fills).
    """
    primary_order_id: str
    sl_order_id: str
    tgt_order_id: str
    linked_at: datetime = field(default_factory=datetime.utcnow)
    sl_order_state: OrderState = OrderState.PLACED
    tgt_order_state: OrderState = OrderState.PLACED
    sl_quantity: int = 0
    tgt_quantity: int = 0


# =============================================================================
# Transition Validation Table
# =============================================================================

# Valid state transitions for OrderState:
# PLACED → ACKNOWLEDGED (broker confirmed receipt)
# PLACED → REJECTED (broker rejected immediately)
# ACKNOWLEDGED → PARTIAL_FILL (partial fill received)
# ACKNOWLEDGED → FILLED (full fill received)
# ACKNOWLEDGED → REJECTED (broker rejected after ack)
# ACKNOWLEDGED → CANCELLED (operator/system cancelled)
# PARTIAL_FILL → FILLED (remaining quantity filled)
# PARTIAL_FILL → MODIFIED (order modified and re-acked)
# PARTIAL_FILL → CANCELLED (cancelled after partial fill)
# FILLED → CANCELLED (unlikely but possible if broker error)
# MODIFIED → PARTIAL_FILL (modified order partially fills)
# MODIFIED → FILLED (modified order fully fills)
# MODIFIED → CANCELLED (cancelled after modification)
# MODIFIED → REJECTED (broker rejected modification)
# Any terminal state → no transitions allowed

_VALID_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.PLACED: {OrderState.ACKNOWLEDGED, OrderState.REJECTED,
                         OrderState.CANCELLED},  # Cancellable before broker ack
    OrderState.ACKNOWLEDGED: {OrderState.PARTIAL_FILL, OrderState.FILLED,
                               OrderState.REJECTED, OrderState.CANCELLED,
                               OrderState.EXPIRED},  # Timeout after ack
    OrderState.PARTIAL_FILL: {OrderState.FILLED, OrderState.MODIFIED,
                               OrderState.CANCELLED},
    OrderState.FILLED: {OrderState.CANCELLED},
    OrderState.MODIFIED: {OrderState.PARTIAL_FILL, OrderState.FILLED,
                           OrderState.CANCELLED, OrderState.REJECTED},
}

_TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
})


# =============================================================================
# Helper Functions
# =============================================================================


def is_order_terminal(state: OrderState) -> bool:
    """Check whether an OrderState is terminal (no further transitions).

    Args:
        state: The OrderState to check.

    Returns:
        True if the state is terminal (FILLED, CANCELLED, REJECTED, EXPIRED).
    """
    return state in _TERMINAL_ORDER_STATES


def is_transition_valid(current: OrderState, target: OrderState) -> bool:
    """Check whether a transition between two OrderStates is valid.

    Args:
        current: The current OrderState.
        target: The target OrderState.

    Returns:
        True if the transition is in the validation table.
    """
    if current == target:
        return True
    allowed = _VALID_TRANSITIONS.get(current)
    if allowed is None:
        return False
    return target in allowed


# =============================================================================
# OrderLifecycleManager
# =============================================================================


class OrderLifecycleManager:
    """Tracks and manages order states through their full lifecycle.

    Provides order registration, validated state transitions, SL/TGT
    linkage management, partial fill handling, and order querying.

    Usage::

        olm = OrderLifecycleManager(on_log_callback=logging_layer.log)

        # Register a new order
        record = OrderRecord(order_id=\"ORD001\", trade_id=\"TRADE-001\",
                             side=\"BUY\", quantity=25, price=150.0)
        olm.register_order(record)

        # Acknowledge
        olm.update_state(\"ORD001\", OrderState.ACKNOWLEDGED)

        # Handle fill
        olm.handle_partial_fill(\"ORD001\", filled_qty=10, price=150.0)

        # Link SL/TGT for protection
        olm.link_sl_tgt(\"ORD001\", sl_order_id=\"SL001\",
                         tgt_order_id=\"TGT001\", filled_qty=10)

        # Get active orders
        active = olm.get_active_orders()
    """

    def __init__(
        self,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the OrderLifecycleManager.

        Args:
            on_log_callback: Called for all lifecycle events.
                Signature: (event_type: str, data: dict) -> None
                Expected to forward to execution_logging_layer.
        """
        self._on_log_callback = on_log_callback

        # Internal stores
        self._orders: dict[str, OrderRecord] = {}
        self._trade_orders: dict[str, list[str]] = {}
        self._linkages: dict[str, SLTGTLinkage] = {}

    # ------------------------------------------------------------------
    # Order Registration
    # ------------------------------------------------------------------

    def register_order(self, order: OrderRecord) -> str:
        """Register a new order for lifecycle tracking.

        Args:
            order: An OrderRecord with at minimum order_id, trade_id, side.

        Returns:
            The registered order_id.

        Raises:
            ExecutionError: If order is None, missing required fields,
                or order_id already registered.
        """
        if order is None:
            raise ExecutionError(
                message="Cannot register None order",
            )

        if not order.order_id:
            raise ExecutionError(
                message="Cannot register order without order_id",
            )

        if order.order_id in self._orders:
            raise ExecutionError(
                message=f"Order {order.order_id} already registered",
            )

        if not order.trade_id:
            raise ExecutionError(
                message="Cannot register order without trade_id",
                details={"order_id": order.order_id},
            )

        # Store order
        self._orders[order.order_id] = order

        # Index by trade
        if order.trade_id not in self._trade_orders:
            self._trade_orders[order.trade_id] = []
        self._trade_orders[order.trade_id].append(order.order_id)

        # Enforce safety limit
        if len(self._trade_orders[order.trade_id]) > DEFAULT_MAX_ACTIVE_ORDERS_PER_TRADE:
            self._log("ORDER_LIMIT_WARNING", {
                "trade_id": order.trade_id,
                "order_count": len(self._trade_orders[order.trade_id]),
                "max_allowed": DEFAULT_MAX_ACTIVE_ORDERS_PER_TRADE,
            })

        self._log("ORDER_REGISTERED", {
            "order_id": order.order_id,
            "trade_id": order.trade_id,
            "state": order.state.value,
        })

        return order.order_id

    # ------------------------------------------------------------------
    # State Transitions
    # ------------------------------------------------------------------

    def update_state(
        self,
        order_id: str,
        new_state: OrderState,
        event_data: dict[str, Any] | None = None,
    ) -> OrderRecord:
        """Transition an order to a new state with validation.

        Validates the transition against the allowed transition table.
        Rejects transitions from terminal states.

        Args:
            order_id: The order to update.
            new_state: The target OrderState.
            event_data: Optional context dict to append to order events log.

        Returns:
            The updated OrderRecord.

        Raises:
            ExecutionError: If order not found, transition invalid,
                or new_state is None/invalid type.
        """
        if order_id not in self._orders:
            raise ExecutionError(
                message=f"Cannot update state for unknown order: {order_id}",
            )

        if new_state is None or not isinstance(new_state, OrderState):
            raise ExecutionError(
                message="Invalid new_state — must be an OrderState enum value",
                details={
                    "order_id": order_id,
                    "new_state": str(new_state),
                },
            )

        record = self._orders[order_id]
        current_state = record.state

        # Allow no-op (same state)
        if current_state == new_state:
            self._log("STATE_NOOP", {
                "order_id": order_id,
                "state": current_state.value,
            })
            return record

        # Prevent transitions from terminal states
        if is_order_terminal(current_state):
            raise ExecutionError(
                message=f"Cannot transition from terminal state {current_state.value}",
                details={
                    "order_id": order_id,
                    "current_state": current_state.value,
                    "target_state": new_state.value,
                },
            )

        # Validate transition
        if not is_transition_valid(current_state, new_state):
            raise ExecutionError(
                message=(
                    f"Invalid order state transition: "
                    f"{current_state.value} → {new_state.value}"
                ),
                details={
                    "order_id": order_id,
                    "trade_id": record.trade_id,
                    "current_state": current_state.value,
                    "target_state": new_state.value,
                },
            )

        # Apply transition
        old_state = record.state
        record.state = new_state
        record.updated_at = datetime.utcnow()

        # Record event
        event: dict[str, Any] = {
            "type": "STATE_TRANSITION",
            "from": old_state.value,
            "to": new_state.value,
            "timestamp": record.updated_at.isoformat(),
        }
        if event_data:
            event.update(event_data)
        record.events.append(event)

        self._log("STATE_TRANSITION", {
            "order_id": order_id,
            "trade_id": record.trade_id,
            "from": old_state.value,
            "to": new_state.value,
        })

        return record

    # ------------------------------------------------------------------
    # Order Querying
    # ------------------------------------------------------------------

    def get_order(self, order_id: str) -> OrderRecord | None:
        """Get the full OrderRecord for a given order_id.

        Args:
            order_id: The order identifier to look up.

        Returns:
            The OrderRecord, or None if not found.
        """
        return self._orders.get(order_id)

    def get_trade_orders(self, trade_id: str) -> list[OrderRecord]:
        """Get all orders belonging to a trade.

        Args:
            trade_id: The trade identifier.

        Returns:
            List of OrderRecord objects in registration order.
        """
        order_ids = self._trade_orders.get(trade_id, [])
        return [self._orders[oid] for oid in order_ids if oid in self._orders]

    def get_active_orders(self) -> list[OrderRecord]:
        """Get all orders that are in a non-terminal state.

        Terminal states: FILLED, CANCELLED, REJECTED, EXPIRED.

        Returns:
            List of OrderRecord objects that are still active.
        """
        return [
            record
            for record in self._orders.values()
            if not is_order_terminal(record.state)
        ]

    def get_active_orders_for_trade(self, trade_id: str) -> list[OrderRecord]:
        """Get all active (non-terminal) orders for a specific trade.

        Args:
            trade_id: The trade identifier.

        Returns:
            List of active OrderRecord objects for the trade.
        """
        return [
            record
            for record in self.get_trade_orders(trade_id)
            if not is_order_terminal(record.state)
        ]

    def get_order_count(self) -> int:
        """Get the total number of tracked orders.

        Returns:
            Total order count (active + terminal).
        """
        return len(self._orders)

    def get_trade_count(self) -> int:
        """Get the number of unique trades with tracked orders.

        Returns:
            Number of unique trade IDs.
        """
        return len(self._trade_orders)

    # ------------------------------------------------------------------
    # SL/TGT Linkage
    # ------------------------------------------------------------------

    def link_sl_tgt(
        self,
        primary_order_id: str,
        sl_order_id: str,
        tgt_order_id: str,
        filled_qty: int = 0,
    ) -> SLTGTLinkage:
        """Link SL and TGT orders to a primary order (OCO-style).

        Creates an SLTGTLinkage record. The SL and TGT quantities are
        initialised to the filled_qty of the primary order. When the
        primary position quantity changes (partial fill), the linkage
        should be updated via adjust_sl_tgt_quantities().

        Args:
            primary_order_id: The order being protected.
            sl_order_id: The stop-loss order ID.
            tgt_order_id: The target/profit order ID.
            filled_qty: Initial filled quantity for SL/TGT sizing.

        Returns:
            The created SLTGTLinkage record.

        Raises:
            ExecutionError: If primary order not found, either SL or TGT
                order_id is empty, or linkage already exists.
        """
        if primary_order_id not in self._orders:
            raise ExecutionError(
                message=f"Cannot link SL/TGT — primary order not found: {primary_order_id}",
            )

        if not sl_order_id or not tgt_order_id:
            raise ExecutionError(
                message="SL and TGT order IDs must not be empty",
                details={
                    "primary_order_id": primary_order_id,
                    "sl_order_id": sl_order_id,
                    "tgt_order_id": tgt_order_id,
                },
            )

        if primary_order_id in self._linkages:
            raise ExecutionError(
                message=f"SL/TGT linkage already exists for order: {primary_order_id}",
            )

        # Validate the SL/TGT orders are registered
        if sl_order_id not in self._orders:
            raise ExecutionError(
                message=f"SL order not registered: {sl_order_id}",
            )
        if tgt_order_id not in self._orders:
            raise ExecutionError(
                message=f"TGT order not registered: {tgt_order_id}",
            )

        linkage = SLTGTLinkage(
            primary_order_id=primary_order_id,
            sl_order_id=sl_order_id,
            tgt_order_id=tgt_order_id,
            sl_quantity=filled_qty,
            tgt_quantity=filled_qty,
        )
        self._linkages[primary_order_id] = linkage

        self._log("SL_TGT_LINKED", {
            "primary_order_id": primary_order_id,
            "sl_order_id": sl_order_id,
            "tgt_order_id": tgt_order_id,
            "filled_qty": filled_qty,
        })

        return linkage

    def adjust_sl_tgt_quantities(
        self,
        primary_order_id: str,
        new_filled_qty: int,
    ) -> SLTGTLinkage | None:
        """Adjust SL/TGT quantities for a partial fill on the primary order.

        Synced to the new filled quantity of the primary position.
        SL and TGT quantities are always equal to the position quantity.

        Args:
            primary_order_id: The primary order whose fill qty changed.
            new_filled_qty: The updated filled quantity.

        Returns:
            The updated SLTGTLinkage, or None if no linkage exists.
        """
        if primary_order_id not in self._linkages:
            return None

        linkage = self._linkages[primary_order_id]
        linkage.sl_quantity = new_filled_qty
        linkage.tgt_quantity = new_filled_qty

        self._log("SL_TGT_ADJUSTED", {
            "primary_order_id": primary_order_id,
            "new_filled_qty": new_filled_qty,
            "sl_quantity": linkage.sl_quantity,
            "tgt_quantity": linkage.tgt_quantity,
        })

        return linkage

    def get_linkage(self, primary_order_id: str) -> SLTGTLinkage | None:
        """Get the SL/TGT linkage for a primary order.

        Args:
            primary_order_id: The primary order identifier.

        Returns:
            The SLTGTLinkage, or None if no linkage exists.
        """
        return self._linkages.get(primary_order_id)

    def update_linkage_order_state(
        self,
        order_id: str,
        new_state: OrderState,
    ) -> None:
        """Update the state of an SL or TGT order within its linkage.

        Looks up which linkage (if any) contains the given order_id
        and updates the corresponding SL or TGT state.

        Args:
            order_id: The SL or TGT order ID whose state changed.
            new_state: The new OrderState.
        """
        for linkage in self._linkages.values():
            if linkage.sl_order_id == order_id:
                linkage.sl_order_state = new_state
                return
            elif linkage.tgt_order_id == order_id:
                linkage.tgt_order_state = new_state
                return

        # Not in any linkage — no-op (order may be standalone)
        self._log("LINKAGE_UPDATE_SKIPPED", {
            "order_id": order_id,
            "reason": "Order not found in any SL/TGT linkage",
        })

    def get_all_linkages(self) -> list[SLTGTLinkage]:
        """Get all SL/TGT linkages.

        Returns:
            List of all SLTGTLinkage records.
        """
        return list(self._linkages.values())

    # ------------------------------------------------------------------
    # Partial Fill Handling
    # ------------------------------------------------------------------

    def handle_partial_fill(
        self,
        order_id: str,
        filled_qty: int,
        price: float,
    ) -> OrderRecord:
        """Handle a partial fill event on an order.

        Updates the order's filled_qty, determines whether the order
        is now fully filled (remaining = 0), and transitions state
        accordingly (PARTIAL_FILL if remaining > 0, FILLED if 0).

        Also adjusts any linked SL/TGT quantities to match the new
        filled quantity.

        Args:
            order_id: The order being filled.
            filled_qty: The total filled quantity so far (cumulative).
            price: The fill price.

        Returns:
            The updated OrderRecord.

        Raises:
            ExecutionError: If order not found or filled_qty exceeds quantity.
        """
        if order_id not in self._orders:
            raise ExecutionError(
                message=f"Cannot handle partial fill for unknown order: {order_id}",
            )

        if filled_qty < 0:
            raise ExecutionError(
                message=f"Invalid filled quantity (negative): {filled_qty}",
                details={"order_id": order_id},
            )

        record = self._orders[order_id]

        if filled_qty > record.quantity:
            raise ExecutionError(
                message=(
                    f"Fill quantity {filled_qty} exceeds order quantity "
                    f"{record.quantity}"
                ),
                details={
                    "order_id": order_id,
                    "filled_qty": filled_qty,
                    "order_quantity": record.quantity,
                },
            )

        # Guard: prevent filling orders in terminal state
        if is_order_terminal(record.state):
            raise ExecutionError(
                message=f"Cannot fill order in terminal state {record.state.value}",
                details={
                    "order_id": order_id,
                    "current_state": record.state.value,
                    "filled_qty": filled_qty,
                },
            )

        # Update fill tracking
        record.filled_qty = filled_qty
        record.price = price
        record.updated_at = datetime.utcnow()

        # Log the fill event
        record.events.append({
            "type": "FILL",
            "filled_qty": filled_qty,
            "price": price,
            "remaining": record.quantity - filled_qty,
            "timestamp": record.updated_at.isoformat(),
        })

        self._log("PARTIAL_FILL", {
            "order_id": order_id,
            "trade_id": record.trade_id,
            "filled_qty": filled_qty,
            "price": price,
            "remaining": record.quantity - filled_qty,
        })

        # Determine next state
        remaining = record.quantity - filled_qty
        if remaining == 0:
            # Fully filled
            self.update_state(order_id, OrderState.FILLED, {
                "filled_qty": filled_qty,
                "final_price": price,
            })
        else:
            # Partially filled
            current_state = record.state
            # Only transition if currently in a pre-fill state
            if current_state in {OrderState.PLACED, OrderState.ACKNOWLEDGED,
                                  OrderState.MODIFIED}:
                self.update_state(order_id, OrderState.PARTIAL_FILL, {
                    "filled_qty": filled_qty,
                    "remaining": remaining,
                })

        # Adjust SL/TGT quantities to match new filled quantity
        self.adjust_sl_tgt_quantities(order_id, filled_qty)

        return record

    # ------------------------------------------------------------------
    # Batch Utilities
    # ------------------------------------------------------------------

    def cancel_all_active_orders(self) -> int:
        """Cancel all currently active (non-terminal) orders.

        Transitions each active order to CANCELLED state.

        Returns:
            The number of orders that were cancelled.
        """
        active = self.get_active_orders()
        count = 0
        for record in active:
            try:
                self.update_state(record.order_id, OrderState.CANCELLED, {
                    "reason": "Bulk cancel initiated",
                })
                count += 1
            except ExecutionError:
                # Log and skip orders that can't transition to CANCELLED
                self._log("CANCEL_SKIPPED", {
                    "order_id": record.order_id,
                    "state": record.state.value,
                    "reason": "Cannot transition to CANCELLED from current state",
                })
        return count

    def get_orders_in_state(self, state: OrderState) -> list[OrderRecord]:
        """Get all orders currently in a specific state.

        Args:
            state: The OrderState to filter by.

        Returns:
            List of OrderRecord objects in the given state.
        """
        return [
            record
            for record in self._orders.values()
            if record.state == state
        ]

    def get_summary(self, trade_id: str | None = None) -> dict[str, Any]:
        """Get a summary of order lifecycle state.

        Args:
            trade_id: Optional trade ID to scope the summary.

        Returns:
            Dict with total orders, counts by state, active vs terminal.
        """
        target_orders = (
            self._orders.values()
            if trade_id is None
            else self.get_trade_orders(trade_id)
        )

        state_counts: dict[str, int] = {}
        active_count = 0
        terminal_count = 0

        for record in target_orders:
            state_name = record.state.value
            state_counts[state_name] = state_counts.get(state_name, 0) + 1
            if is_order_terminal(record.state):
                terminal_count += 1
            else:
                active_count += 1

        return {
            "trade_id": trade_id or "ALL",
            "total_orders": len(target_orders),
            "active_orders": active_count,
            "terminal_orders": terminal_count,
            "by_state": state_counts,
            "linkage_count": len(self._linkages),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event being logged.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
