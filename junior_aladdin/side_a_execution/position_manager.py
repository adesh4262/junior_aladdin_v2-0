"""Side A — Position Manager: Primary owner of open trade management state.

The single source of truth for active position data. Manages fills, SL,
targets, trailing stops, breakeven, partial exits, P&L tracking, and
position consistency views.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.10 & Section 24):
- Position Manager = position truth owner
- Order Lifecycle Manager = order-state owner
- Execution Core = broker interaction owner
- Captain = rare strategic override authority
- ONE active live trade at a time (operationally enforced here)
- Side A NEVER increases size (reduce-only for safety)
- Broker truth = final live authority (consistency view aids reconciliation)

Ownership split (locked — see Section 24):
- Position Manager owns position truth, SL, targets, trail, breakeven
- Position Manager does NOT own order-state transitions (OLM does)
- Position Manager does NOT own broker interaction (Execution Core does)

Output contracts:
- PositionState → execution_orchestrator for ExecutionSnapshot
- PositionState → protection_model for SL/TGT staging
- PositionState → reconciliation_engine for consistency checks
- PositionState → execution_logging_layer for audit trail
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.side_a_types import PositionState


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TRAIL_DISTANCE_TICKS: int = 10
"""Default trailing stop distance in ticks when not specified."""

DEFAULT_BREAKEVEN_TICKS: int = 15
"""Default number of ticks in profit before SL moves to breakeven."""

NIFTY_TICK_SIZE: float = 0.05
"""NIFTY 50 minimum tick size (0.05 points)."""

MAX_ACTIVE_POSITIONS: int = 1
"""Maximum number of simultaneously active positions (one-trade rule)."""


# =============================================================================
# P&L Calculation Helper
# =============================================================================


def _direction_multiplier(direction: str) -> int:
    """Get the P&L direction multiplier for a position.

    BUY positions profit when price rises (+1).
    SELL positions profit when price falls (-1).

    Args:
        direction: "BUY" or "SELL".

    Returns:
        +1 for BUY, -1 for SELL.
    """
    return 1 if direction == "BUY" else -1


def calculate_pnl(
    direction: str,
    entry_price: float,
    exit_price: float,
    quantity: int,
) -> float:
    """Calculate realised P&L for a filled trade.

    Formula: (exit_price - entry_price) * quantity * direction_multiplier

    Args:
        direction: "BUY" or "SELL".
        entry_price: Average entry price.
        exit_price: Exit/fill price.
        quantity: Number of lots/units.

    Returns:
        The P&L amount (positive = profit, negative = loss).
    """
    multiplier = _direction_multiplier(direction)
    return (exit_price - entry_price) * quantity * multiplier


def calculate_unrealized_pnl(
    direction: str,
    entry_price: float,
    current_price: float,
    quantity: int,
) -> float:
    """Calculate unrealised P&L for an open position.

    Same formula as realised P&L but uses current market price
    instead of exit price.

    Args:
        direction: "BUY" or "SELL".
        entry_price: Average entry price.
        current_price: Current market price.
        quantity: Current position quantity.

    Returns:
        The unrealised P&L amount.
    """
    return calculate_pnl(direction, entry_price, current_price, quantity)


# =============================================================================
# Trailing Stop Dataclass
# =============================================================================


@dataclass
class TrailingStopState:
    """State of an active trailing stop.

    Once the activation price is hit, the stop-loss price starts trailing
    behind the market price by the configured trail distance.

    Fields:
        activation_price: Price level that triggers trail activation.
        trail_distance_ticks: Number of ticks the stop trails behind price.
        current_stop_price: Current trailing stop price.
        highest_price_since_activation: Highest price seen since activation
            (for BUY positions; lowest for SELL positions).
        is_active: Whether the trail has been activated.
    """
    activation_price: float
    trail_distance_ticks: int = DEFAULT_TRAIL_DISTANCE_TICKS
    current_stop_price: float = 0.0
    highest_price_since_activation: float = 0.0
    is_active: bool = False


@dataclass
class BreakevenState:
    """State of breakeven SL protection.

    Once the position is in profit by the configured number of ticks,
    the stop-loss is moved to the entry price (breakeven), ensuring
    the trade cannot result in a loss.

    Fields:
        activation_ticks: Number of ticks in profit to trigger breakeven.
        is_active: Whether breakeven has been activated.
        activated_at_price: The SL price after breakeven activation (entry price).
    """
    activation_ticks: int = DEFAULT_BREAKEVEN_TICKS
    is_active: bool = False
    activated_at_price: float = 0.0


# =============================================================================
# PositionManager
# =============================================================================


class PositionManager:
    """Primary owner of open trade management state.

    Manages the full lifecycle of a position from opening through fills,
    SL/target management, trailing stops, breakeven, partial exits, and
    final close. Enforces the one-trade rule.

    Usage::

        pm = PositionManager()

        # Open a new position
        pos = pm.open_position(trade_id=\"TRADE-001\", direction=\"BUY\",
                                filled_qty=25, price=150.0)

        # Update fill
        pm.update_fill(\"TRADE-001\", filled_qty=25, price=150.0)

        # Set SL and target
        pm.set_sl(\"TRADE-001\", 148.0)
        pm.set_target(\"TRADE-001\", 155.0)

        # Activate trailing stop
        pm.activate_trail(\"TRADE-001\", activation_price=152.0,
                           trail_distance_ticks=10)

        # Activate breakeven
        pm.activate_breakeven(\"TRADE-001\", activation_ticks=15)

        # Partial exit
        pm.partial_exit(\"TRADE-001\", exit_qty=10, exit_price=154.0)

        # Close position
        pm.close_position(\"TRADE-001\", close_qty=15, close_price=153.0)
    """

    def __init__(
        self,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the PositionManager.

        Args:
            on_log_callback: Called for all position events.
                Signature: (event_type: str, data: dict) -> None
                Expected to forward to execution_logging_layer.
        """
        self._on_log_callback = on_log_callback

        # Internal state
        self._positions: dict[str, PositionState] = {}
        self._trailing_stops: dict[str, TrailingStopState] = {}
        self._breakeven_states: dict[str, BreakevenState] = {}
        self._unrealized_cache: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Position Lifecycle
    # ------------------------------------------------------------------

    def open_position(
        self,
        trade_id: str,
        direction: str,
        filled_qty: int,
        price: float,
    ) -> PositionState:
        """Open a new position.

        Enforces the one-trade rule — only one active position at a time.

        Args:
            trade_id: Unique trade identifier.
            direction: \"BUY\" or \"SELL\".
            filled_qty: Initial filled quantity.
            price: Fill price.

        Returns:
            The newly created PositionState.

        Raises:
            ExecutionError: If a position already exists for this trade_id,
                or if another active position already exists (one-trade rule),
                or if any parameter is invalid.
        """
        if not trade_id:
            raise ExecutionError(
                message="Cannot open position without trade_id",
            )

        if direction not in ("BUY", "SELL"):
            raise ExecutionError(
                message=f"Invalid direction: {direction} (must be BUY or SELL)",
                details={"trade_id": trade_id},
            )

        if filled_qty <= 0:
            raise ExecutionError(
                message=f"Invalid filled_qty: {filled_qty} (must be > 0)",
                details={"trade_id": trade_id},
            )

        if price <= 0:
            raise ExecutionError(
                message=f"Invalid price: {price} (must be > 0)",
                details={"trade_id": trade_id},
            )

        # Check if position already exists for this trade
        if trade_id in self._positions:
            raise ExecutionError(
                message=f"Position already exists for trade: {trade_id}",
            )

        # Enforce one-trade rule
        active_positions = self.get_active_positions()
        if len(active_positions) >= MAX_ACTIVE_POSITIONS:
            existing = active_positions[0]
            raise ExecutionError(
                message="Cannot open position — one active trade already exists",
                details={
                    "existing_trade_id": existing.trade_id,
                    "new_trade_id": trade_id,
                },
            )

        position = PositionState(
            trade_id=trade_id,
            direction=direction,
            filled_qty=filled_qty,
            pending_qty=0,
            avg_price=price,
        )
        self._positions[trade_id] = position

        self._log("POSITION_OPENED", {
            "trade_id": trade_id,
            "direction": direction,
            "filled_qty": filled_qty,
            "price": price,
        })

        return position

    def update_fill(
        self,
        trade_id: str,
        additional_qty: int,
        price: float,
    ) -> PositionState:
        """Update position fill data with a new fill event.

        Adds additional_qty to the position and recalculates the
        weighted average entry price.

        Args:
            trade_id: The trade to update.
            additional_qty: Additional quantity being filled (must be >= 0).
            price: Fill price for this fill event.

        Returns:
            The updated PositionState.

        Raises:
            ExecutionError: If position not found or additional_qty is invalid.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot update fill for unknown trade: {trade_id}",
            )

        if additional_qty < 0:
            raise ExecutionError(
                message=f"Invalid additional quantity: {additional_qty}",
                details={"trade_id": trade_id, "additional_qty": additional_qty},
            )

        position = self._positions[trade_id]

        if additional_qty > 0:
            # Weighted average: (old_total + new_addition) / new_total_qty
            old_total = position.filled_qty * position.avg_price
            new_total_qty = position.filled_qty + additional_qty
            position.avg_price = (
                (old_total + (additional_qty * price)) / new_total_qty
            )
            position.filled_qty = new_total_qty

        position.updated_at = datetime.utcnow()

        self._log("POSITION_FILL_UPDATED", {
            "trade_id": trade_id,
            "filled_qty": position.filled_qty,
            "avg_price": position.avg_price,
            "latest_price": price,
        })

        return position

    # ------------------------------------------------------------------
    # SL / Target Management
    # ------------------------------------------------------------------

    def set_sl(self, trade_id: str, sl_price: float) -> PositionState:
        """Set or update the stop-loss price for a position.

        Args:
            trade_id: The trade to update.
            sl_price: The new stop-loss price. Must be > 0.

        Returns:
            The updated PositionState.

        Raises:
            ExecutionError: If position not found or sl_price invalid.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot set SL for unknown trade: {trade_id}",
            )

        if sl_price <= 0:
            raise ExecutionError(
                message=f"Invalid SL price: {sl_price} (must be > 0)",
                details={"trade_id": trade_id, "sl_price": sl_price},
            )

        position = self._positions[trade_id]
        position.sl_price = sl_price
        position.updated_at = datetime.utcnow()

        self._log("SL_SET", {
            "trade_id": trade_id,
            "sl_price": sl_price,
            "direction": position.direction,
        })

        return position

    def set_target(self, trade_id: str, target_price: float) -> PositionState:
        """Set or update the target price for a position.

        Args:
            trade_id: The trade to update.
            target_price: The new target price. Must be > 0.

        Returns:
            The updated PositionState.

        Raises:
            ExecutionError: If position not found or target_price invalid.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot set target for unknown trade: {trade_id}",
            )

        if target_price <= 0:
            raise ExecutionError(
                message=f"Invalid target price: {target_price} (must be > 0)",
                details={"trade_id": trade_id, "target_price": target_price},
            )

        position = self._positions[trade_id]
        position.target_price = target_price
        position.updated_at = datetime.utcnow()

        self._log("TARGET_SET", {
            "trade_id": trade_id,
            "target_price": target_price,
            "direction": position.direction,
        })

        return position

    # ------------------------------------------------------------------
    # Trailing Stop
    # ------------------------------------------------------------------

    def activate_trail(
        self,
        trade_id: str,
        activation_price: float,
        trail_distance_ticks: int = DEFAULT_TRAIL_DISTANCE_TICKS,
    ) -> TrailingStopState:
        """Activate a trailing stop for a position.

        The trailing stop will start tracking after the activation price
        is reached. For BUY positions: the stop trails below the highest
        price seen. For SELL positions: the stop trails above the lowest
        price seen.

        Args:
            trade_id: The trade to activate trailing stop for.
            activation_price: The price level that triggers trail activation.
            trail_distance_ticks: Distance in ticks for the stop to trail.

        Returns:
            The created TrailingStopState.

        Raises:
            ExecutionError: If position not found or trail already active.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot activate trail for unknown trade: {trade_id}",
            )

        if trade_id in self._trailing_stops:
            raise ExecutionError(
                message=f"Trailing stop already configured for trade: {trade_id}",
            )

        if trail_distance_ticks <= 0:
            raise ExecutionError(
                message=f"Invalid trail distance: {trail_distance_ticks} (must be > 0)",
                details={"trade_id": trade_id},
            )

        position = self._positions[trade_id]

        # Initialise trail state
        trail = TrailingStopState(
            activation_price=activation_price,
            trail_distance_ticks=trail_distance_ticks,
            is_active=False,
            highest_price_since_activation=activation_price,
        )

        # Calculate initial stop price based on direction
        trail_distance = trail_distance_ticks * NIFTY_TICK_SIZE
        if position.direction == "BUY":
            trail.current_stop_price = activation_price - trail_distance
        else:
            trail.current_stop_price = activation_price + trail_distance

        self._trailing_stops[trade_id] = trail

        self._log("TRAIL_ACTIVATED", {
            "trade_id": trade_id,
            "activation_price": activation_price,
            "trail_distance_ticks": trail_distance_ticks,
            "initial_stop": trail.current_stop_price,
        })

        return trail

    def update_trail(
        self,
        trade_id: str,
        current_market_price: float,
    ) -> TrailingStopState | None:
        """Update the trailing stop with a new market price.

        If the activation price has been reached, the trail becomes active.
        The stop price is adjusted as the market price moves in the
        favourable direction.

        Args:
            trade_id: The trade to update.
            current_market_price: The current market price.

        Returns:
            The updated TrailingStopState, or None if no trail exists.
        """
        if trade_id not in self._trailing_stops:
            return None

        trail = self._trailing_stops[trade_id]
        position = self._positions.get(trade_id)
        if position is None:
            return None

        trail_distance = trail.trail_distance_ticks * NIFTY_TICK_SIZE

        if position.direction == "BUY":
            # Track highest price
            if current_market_price > trail.highest_price_since_activation:
                trail.highest_price_since_activation = current_market_price

            # Activate trail if activation price is hit
            if not trail.is_active and current_market_price >= trail.activation_price:
                trail.is_active = True

            # Update stop price (trails below highest price)
            if trail.is_active:
                new_stop = trail.highest_price_since_activation - trail_distance
                if new_stop > trail.current_stop_price:
                    trail.current_stop_price = new_stop

        else:  # SELL
            # Track lowest price
            if current_market_price < trail.highest_price_since_activation:
                trail.highest_price_since_activation = current_market_price  # Reused for lowest tracking

            # Activate trail if activation price is hit
            if not trail.is_active and current_market_price <= trail.activation_price:
                trail.is_active = True

            # Update stop price (trails above lowest price)
            if trail.is_active:
                new_stop = trail.highest_price_since_activation + trail_distance
                if new_stop < trail.current_stop_price:
                    trail.current_stop_price = new_stop

        # Sync SL price on the position
        if trail.is_active:
            position.sl_price = trail.current_stop_price
            position.updated_at = datetime.utcnow()

        self._log("TRAIL_UPDATED", {
            "trade_id": trade_id,
            "market_price": current_market_price,
            "stop_price": trail.current_stop_price,
            "is_active": trail.is_active,
        })

        return trail

    # ------------------------------------------------------------------
    # Breakeven
    # ------------------------------------------------------------------

    def activate_breakeven(
        self,
        trade_id: str,
        activation_ticks: int = DEFAULT_BREAKEVEN_TICKS,
    ) -> BreakevenState:
        """Activate breakeven protection for a position.

        Once the position is in profit by activation_ticks, the SL is
        moved to the entry price (breakeven). This guarantees the trade
        cannot result in a loss.

        Args:
            trade_id: The trade to activate breakeven for.
            activation_ticks: Number of ticks in profit to trigger.

        Returns:
            The created BreakevenState.

        Raises:
            ExecutionError: If position not found or breakeven already active.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot activate breakeven for unknown trade: {trade_id}",
            )

        if trade_id in self._breakeven_states:
            raise ExecutionError(
                message=f"Breakeven already configured for trade: {trade_id}",
            )

        if activation_ticks <= 0:
            raise ExecutionError(
                message=f"Invalid activation ticks: {activation_ticks} (must be > 0)",
                details={"trade_id": trade_id},
            )

        position = self._positions[trade_id]

        be = BreakevenState(
            activation_ticks=activation_ticks,
            is_active=False,
            activated_at_price=0.0,
        )
        self._breakeven_states[trade_id] = be

        self._log("BREAKEVEN_ACTIVATED", {
            "trade_id": trade_id,
            "activation_ticks": activation_ticks,
            "entry_price": position.avg_price,
        })

        return be

    def check_breakeven(
        self,
        trade_id: str,
        current_market_price: float,
    ) -> bool:
        """Check whether breakeven should be activated and apply if triggered.

        Breakeven triggers when unrealised profit >= activation_ticks.
        Once triggered, SL is moved to the entry price.

        Args:
            trade_id: The trade to check.
            current_market_price: Current market price.

        Returns:
            True if breakeven was just activated, False otherwise.
        """
        if trade_id not in self._breakeven_states:
            return False

        be = self._breakeven_states[trade_id]
        if be.is_active:
            return False  # Already activated

        position = self._positions.get(trade_id)
        if position is None:
            return False

        # Calculate unrealised profit in ticks
        tick_value = (current_market_price - position.avg_price) * _direction_multiplier(position.direction)
        profit_ticks = tick_value / NIFTY_TICK_SIZE

        if profit_ticks >= be.activation_ticks:
            # Activate breakeven
            be.is_active = True
            be.activated_at_price = position.avg_price

            # Move SL to entry price
            position.sl_price = position.avg_price
            position.breakeven_activated = True
            position.updated_at = datetime.utcnow()

            self._log("BREAKEVEN_TRIGGERED", {
                "trade_id": trade_id,
                "entry_price": position.avg_price,
                "current_price": current_market_price,
                "profit_ticks": profit_ticks,
            })

            return True

        return False

    # ------------------------------------------------------------------
    # Partial Exit
    # ------------------------------------------------------------------

    def partial_exit(
        self,
        trade_id: str,
        exit_qty: int,
        exit_price: float,
    ) -> PositionState:
        """Partially exit a position.

        Reduces the position quantity, records the partial exit P&L,
        and updates the position state accordingly.

        The P&L from the partial exit is added to position.pnl.
        The remaining position keeps its original average price.

        Args:
            trade_id: The trade to partially exit.
            exit_qty: Quantity to exit (must be <= current filled_qty).
            exit_price: Exit price.

        Returns:
            The updated PositionState.

        Raises:
            ExecutionError: If position not found, invalid params,
                or exit_qty exceeds position size.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot partially exit unknown trade: {trade_id}",
            )

        if exit_qty <= 0:
            raise ExecutionError(
                message=f"Invalid exit quantity: {exit_qty} (must be > 0)",
                details={"trade_id": trade_id},
            )

        if exit_price <= 0:
            raise ExecutionError(
                message=f"Invalid exit price: {exit_price} (must be > 0)",
                details={"trade_id": trade_id},
            )

        position = self._positions[trade_id]

        if exit_qty > position.filled_qty:
            raise ExecutionError(
                message=(
                    f"Exit quantity {exit_qty} exceeds position "
                    f"filled_qty {position.filled_qty}"
                ),
                details={"trade_id": trade_id},
            )

        # Calculate P&L for this partial exit
        exit_pnl = calculate_pnl(
            direction=position.direction,
            entry_price=position.avg_price,
            exit_price=exit_price,
            quantity=exit_qty,
        )

        # Update position
        position.pnl += exit_pnl
        position.partial_exit_qty += exit_qty
        position.filled_qty -= exit_qty
        position.status = "PARTIALLY_CLOSED"
        position.updated_at = datetime.utcnow()

        self._log("PARTIAL_EXIT", {
            "trade_id": trade_id,
            "exit_qty": exit_qty,
            "exit_price": exit_price,
            "exit_pnl": exit_pnl,
            "remaining_qty": position.filled_qty,
            "total_pnl": position.pnl,
        })

        return position

    # ------------------------------------------------------------------
    # Close Position
    # ------------------------------------------------------------------

    def close_position(
        self,
        trade_id: str,
        close_qty: int | None = None,
        close_price: float = 0.0,
    ) -> PositionState:
        """Close a position fully or partially.

        If close_qty is None, closes the entire remaining position.
        Calculates final P&L and sets status to CLOSED.

        Args:
            trade_id: The trade to close.
            close_qty: Quantity to close (defaults to remaining filled_qty).
            close_price: Close price.

        Returns:
            The finalised PositionState.

        Raises:
            ExecutionError: If position not found or invalid params.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot close unknown trade: {trade_id}",
            )

        position = self._positions[trade_id]

        if close_price <= 0:
            raise ExecutionError(
                message=f"Invalid close price: {close_price} (must be > 0)",
                details={"trade_id": trade_id},
            )

        close_qty = close_qty if close_qty is not None else position.filled_qty

        if close_qty <= 0:
            raise ExecutionError(
                message=f"Invalid close quantity: {close_qty}",
                details={"trade_id": trade_id},
            )

        if close_qty > position.filled_qty:
            raise ExecutionError(
                message=(
                    f"Close quantity {close_qty} exceeds remaining "
                    f"filled_qty {position.filled_qty}"
                ),
                details={"trade_id": trade_id},
            )

        # Calculate final P&L for this close
        close_pnl = calculate_pnl(
            direction=position.direction,
            entry_price=position.avg_price,
            exit_price=close_price,
            quantity=close_qty,
        )

        # Update position
        position.pnl += close_pnl
        position.filled_qty -= close_qty
        position.status = "CLOSED"
        position.updated_at = datetime.utcnow()

        # Clean up trailing stop and breakeven tracking
        self._trailing_stops.pop(trade_id, None)
        self._breakeven_states.pop(trade_id, None)

        self._log("POSITION_CLOSED", {
            "trade_id": trade_id,
            "close_qty": close_qty,
            "close_price": close_price,
            "close_pnl": close_pnl,
            "total_pnl": position.pnl,
            "direction": position.direction,
        })

        return position

    # ------------------------------------------------------------------
    # Position Querying
    # ------------------------------------------------------------------

    def get_position(self, trade_id: str) -> PositionState | None:
        """Get the current state of a position.

        Args:
            trade_id: The trade identifier.

        Returns:
            The PositionState, or None if not found.
        """
        return self._positions.get(trade_id)

    def get_active_positions(self) -> list[PositionState]:
        """Get all currently active (OPEN or PARTIALLY_CLOSED) positions.

        Enforces the one-trade rule — returns max 1 position.

        Returns:
            List of active PositionState objects.
        """
        return [
            pos
            for pos in self._positions.values()
            if pos.status in ("OPEN", "PARTIALLY_CLOSED")
        ]

    def get_exposure(self) -> float:
        """Get the total exposure value of all active positions.

        Exposure = filled_qty * avg_price for each active position.

        Returns:
            Total exposure as a float.
        """
        total = 0.0
        for pos in self.get_active_positions():
            total += pos.filled_qty * pos.avg_price
        return total

    def get_pnl(self, trade_id: str) -> float | None:
        """Get the current P&L for a specific trade.

        For active positions, this includes both realised (from partial
        exits) P&L.  Unrealised P&L is NOT included — use
        ``get_pnl_detail()`` with a ``current_price`` to include
        unrealised P&L.

        Args:
            trade_id: The trade identifier.

        Returns:
            The current realised P&L as a float, or None if position
            not found.
        """
        position = self._positions.get(trade_id)
        if position is None:
            return None
        return position.pnl

    def get_pnl_detail(
        self,
        trade_id: str,
        current_price: float | None = None,
    ) -> dict[str, Any] | None:
        """Get detailed P&L for a specific trade with staleness indicator.

        Provides realised P&L, optional unrealised P&L (if current_price
        is given), and a staleness flag.  Staleness is ``True`` when
        the position is open but ``current_price`` was not provided.

        Args:
            trade_id: The trade identifier.
            current_price: Optional current market price.  When provided,
                unrealised P&L is calculated and the returned P&L is
                (realised + unrealised).

        Returns:
            Dict with:
                - ``pnl``: float (realised + unrealised if current_price given)
                - ``realised_pnl``: float (from partial exits only)
                - ``unrealised_pnl``: float or None
                - ``market_price``: float or None
                - ``staleness``: bool (True if P&L may not reflect market)
                - ``trade_id``: str
            Or None if position not found.
        """
        position = self._positions.get(trade_id)
        if position is None:
            return None

        realised_pnl = position.pnl
        unrealised_pnl = None
        staleness = False

        if current_price is not None and current_price > 0 and position.filled_qty > 0:
            unrealised_pnl = calculate_unrealized_pnl(
                direction=position.direction,
                entry_price=position.avg_price,
                current_price=current_price,
                quantity=position.filled_qty,
            )
            total_pnl = realised_pnl + unrealised_pnl
        elif position.status in ("OPEN", "PARTIALLY_CLOSED") and position.filled_qty > 0:
            staleness = True
            total_pnl = realised_pnl
        else:
            total_pnl = realised_pnl

        return {
            "pnl": total_pnl,
            "realised_pnl": realised_pnl,
            "unrealised_pnl": unrealised_pnl,
            "market_price": current_price,
            "staleness": staleness,
            "trade_id": trade_id,
        }

    def update_unrealized_pnl(
        self,
        trade_id: str,
        current_price: float,
    ) -> float:
        """Update the unrealised P&L for an active position.

        Calculates total P&L as realised (from partial exits) plus
        current unrealised (from open position at current price).
        Uses delta-tracking to avoid double-counting on multiple calls.

        Args:
            trade_id: The trade to update.
            current_price: Current market price.

        Returns:
            The total P&L (realised + unrealised).

        Raises:
            ExecutionError: If position not found.
        """
        if trade_id not in self._positions:
            raise ExecutionError(
                message=f"Cannot update unrealised PnL for unknown trade: {trade_id}",
            )

        position = self._positions[trade_id]

        # Calculate current unrealized P&L
        current_unrealized = 0.0
        if position.filled_qty > 0 and current_price > 0:
            current_unrealized = calculate_unrealized_pnl(
                direction=position.direction,
                entry_price=position.avg_price,
                current_price=current_price,
                quantity=position.filled_qty,
            )

        # Get last tracked unrealized to compute delta
        last_unrealized = self._unrealized_cache.get(trade_id, 0.0)
        delta = current_unrealized - last_unrealized

        # Apply delta to position P&L
        position.pnl += delta
        self._unrealized_cache[trade_id] = current_unrealized

        position.updated_at = datetime.utcnow()

        return position.pnl

    # ------------------------------------------------------------------
    # Consistency View (for reconciliation)
    # ------------------------------------------------------------------

    def get_consistency_view(self, trade_id: str) -> dict[str, Any]:
        """Get a complete consistency view of a position for reconciliation.

        Produces a structured dict suitable for comparison with broker
        truth during reconciliation cycles.

        Args:
            trade_id: The trade to get consistency view for.

        Returns:
            Dict with all position fields, trailing stop state,
            and breakeven state.
        """
        position = self._positions.get(trade_id)
        if position is None:
            return {"trade_id": trade_id, "found": False}

        result: dict[str, Any] = {
            "trade_id": trade_id,
            "found": True,
            "position": {
                "direction": position.direction,
                "filled_qty": position.filled_qty,
                "avg_price": position.avg_price,
                "sl_price": position.sl_price,
                "target_price": position.target_price,
                "pnl": position.pnl,
                "status": position.status,
                "partial_exit_qty": position.partial_exit_qty,
                "trail_activated": position.trail_activated,
                "breakeven_activated": position.breakeven_activated,
            },
        }

        # Include trailing stop state if active
        trail = self._trailing_stops.get(trade_id)
        if trail and trail.is_active:
            result["trailing_stop"] = {
                "activation_price": trail.activation_price,
                "current_stop_price": trail.current_stop_price,
                "trail_distance_ticks": trail.trail_distance_ticks,
                "highest_price": trail.highest_price_since_activation,
            }

        # Include breakeven state if active
        be = self._breakeven_states.get(trade_id)
        if be and be.is_active:
            result["breakeven"] = {
                "activation_ticks": be.activation_ticks,
                "activated_at_price": be.activated_at_price,
            }

        return result

    # ------------------------------------------------------------------
    # Position Count
    # ------------------------------------------------------------------

    def get_position_count(self) -> int:
        """Get the total number of tracked positions (active + closed).

        Returns:
            Total position count.
        """
        return len(self._positions)

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
