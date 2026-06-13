"""Side A — Paper Broker: Realistic simulator implementing BrokerProtocol.

Simulates broker behaviour with configurable realism factors: slippage, delay,
brokerage, spread, rejection, and partial fills.  Paper mode must NOT give
perfect fills — that creates dangerous false confidence.

Implements the ``BrokerProtocol`` duck-typed interface, maintaining parity with
the eventual real_broker.py on core lifecycle behaviour.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.13):
- PAPER/REAL parity on core lifecycle behaviour (order → ack → fill → manage)
- Selected advanced realism can remain lighter in paper where justified
- Default rolling paper account with optional reset
- Realism factors are configurable for testability

Simulation features:
    - Slippage: configurable percentage (default 0.05-0.1% of price)
    - Brokerage/charges: realistic NSE rates
    - Spread effect: bid-ask spread simulation
    - Delay: simulate network latency (50-500ms)
    - Rejection: configurable probability (1-5%)
    - Partial fill: configurable probability
    - Rolling capital: tracks balance, P&L, positions
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_INITIAL_CAPITAL: float = 500_000.0
"""Default starting paper capital (₹5,00,000)."""

DEFAULT_SLIPPAGE_MIN: float = 0.0005
"""Minimum slippage as fraction of price (0.05%)."""

DEFAULT_SLIPPAGE_MAX: float = 0.001
"""Maximum slippage as fraction of price (0.1%)."""

DEFAULT_BROKERAGE_PER_LOT: float = 20.0
"""Brokerage per lot (₹20 — approximate NSE rates)."""

DEFAULT_DELAY_MIN: float = 0.05
"""Minimum simulated delay in seconds (50ms)."""

DEFAULT_DELAY_MAX: float = 0.5
"""Maximum simulated delay in seconds (500ms)."""

DEFAULT_REJECTION_RATE: float = 0.03
"""Probability of order rejection (3%)."""

DEFAULT_PARTIAL_FILL_RATE: float = 0.1
"""Probability of partial fill (10% of fills)."""

DEFAULT_SPREAD_FRACTION: float = 0.0002
"""Bid-ask spread as fraction of price (0.02%)."""


# =============================================================================
# PaperPosition
# =============================================================================


@dataclass
class PaperPosition:
    """Simulated position tracked by PaperBroker.

    Fields:
        trade_id: The trade this position belongs to.
        action: BUY or SELL.
        option_side: CE or PE.
        strike: Strike price.
        quantity: Number of lots.
        entry_price: Average entry price.
        filled_qty: Total filled quantity.
        status: OPEN / CLOSED.
        pnl: Realised P&L.
    """
    trade_id: str = ""
    action: str = "BUY"
    option_side: str = "CE"
    strike: str = ""
    quantity: int = 0
    entry_price: float = 0.0
    filled_qty: int = 0
    status: str = "OPEN"
    pnl: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# PaperBroker
# =============================================================================


class PaperBroker:
    """Realistic broker simulator implementing BrokerProtocol.

    Simulates order placement, cancellation, and status queries with
    configurable realism factors.  Maintains a rolling paper account
    with balance, positions, and P&L tracking.

    Usage::

        broker = PaperBroker(
            initial_capital=500000.0,
            slippage_min=0.0005,
            slippage_max=0.001,
            rejection_rate=0.03,
            partial_fill_rate=0.1,
        )

        # Place an order (matches BrokerProtocol.place_order)
        response = broker.place_order({
            "trade_id": "T001",
            "action": "BUY",
            "option_side": "CE",
            "strike": "18500",
            "quantity": 1,
            "price": 150.0,
            "order_type": "LIMIT",
        })
        # Returns: {"order_id": "...", "status": "ACKNOWLEDGED", ...}

        # Later, simulate fill (or use auto_fill=True in place_order)
        fill = broker.simulate_fill("ORD001")
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        slippage_min: float = DEFAULT_SLIPPAGE_MIN,
        slippage_max: float = DEFAULT_SLIPPAGE_MAX,
        brokerage_per_lot: float = DEFAULT_BROKERAGE_PER_LOT,
        delay_min: float = DEFAULT_DELAY_MIN,
        delay_max: float = DEFAULT_DELAY_MAX,
        rejection_rate: float = DEFAULT_REJECTION_RATE,
        partial_fill_rate: float = DEFAULT_PARTIAL_FILL_RATE,
        spread_fraction: float = DEFAULT_SPREAD_FRACTION,
        auto_fill: bool = False,
        random_seed: int | None = None,
    ) -> None:
        """Initialize the PaperBroker with configurable realism factors.

        Args:
            initial_capital: Starting paper account balance.
            slippage_min: Minimum slippage fraction (default 0.05%).
            slippage_max: Maximum slippage fraction (default 0.1%).
            brokerage_per_lot: Brokerage charged per lot.
            delay_min: Minimum simulated delay in seconds.
            delay_max: Maximum simulated delay in seconds.
            rejection_rate: Probability of order rejection (0.0-1.0).
            partial_fill_rate: Probability of partial fill (0.0-1.0).
            spread_fraction: Bid-ask spread as fraction of price.
            auto_fill: If True, fills order immediately after place_order.
            random_seed: Optional seed for deterministic simulation.
        """
        self._initial_capital = initial_capital
        self._slippage_min = slippage_min
        self._slippage_max = slippage_max
        self._brokerage_per_lot = brokerage_per_lot
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._rejection_rate = rejection_rate
        self._partial_fill_rate = partial_fill_rate
        self._spread_fraction = spread_fraction
        self._auto_fill = auto_fill

        if random_seed is not None:
            random.seed(random_seed)

        # Account state
        self._balance: float = initial_capital
        self._positions: dict[str, PaperPosition] = {}
        self._orders: dict[str, dict[str, Any]] = {}
        self._filled_orders: list[str] = []
        self._total_brokerage: float = 0.0
        self._total_slippage: float = 0.0

    # ------------------------------------------------------------------
    # BrokerProtocol Implementation
    # ------------------------------------------------------------------

    def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit an order to the simulated broker.

        Applies configurable delay, then either acknowledges or rejects
        based on rejection_rate.

        Args:
            order_data: Dict with trade_id, action, option_side, strike,
                       quantity, price, order_type, etc.

        Returns:
            Dict with order_id, status, timestamp.
            Status ACKNOWLEDGED or REJECTED.
        """
        # --- Step 1: Simulate network delay ---
        delay = random.uniform(self._delay_min, self._delay_max)
        if delay > 0:
            time.sleep(delay)

        # --- Step 2: Roll for rejection ---
        if random.random() < self._rejection_rate:
            reject_reasons = [
                "INSUFFICIENT_BALANCE",
                "ORDER_TOO_SMALL",
                "THROTTLED",
                "GATEWAY_ERROR",
            ]
            reason = random.choice(reject_reasons)
            order_id = f"ORD_{uuid.uuid4().hex[:8].upper()}"
            self._orders[order_id] = {
                "order_data": order_data,
                "status": "REJECTED",
                "reason": reason,
                "created_at": datetime.utcnow(),
            }
            logger.info(
                "Paper broker rejected order",
                extra={"order_id": order_id, "reason": reason},
            )
            return {
                "order_id": order_id,
                "status": "REJECTED",
                "timestamp": datetime.utcnow().isoformat(),
                "extra": {"reject_reason": reason},
            }

        # --- Step 3: Acknowledge the order ---
        order_id = f"ORD_{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow()

        self._orders[order_id] = {
            "order_data": order_data,
            "status": "ACKNOWLEDGED",
            "filled_qty": 0,
            "created_at": now,
            "updated_at": now,
        }

        # --- Step 4: Auto-fill if configured ---
        if self._auto_fill:
            return self.simulate_fill(order_id)

        logger.info(
            "Paper broker acknowledged order",
            extra={"order_id": order_id, "trade_id": order_data.get("trade_id", "")},
        )

        return {
            "order_id": order_id,
            "status": "ACKNOWLEDGED",
            "timestamp": now.isoformat(),
        }

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an existing order.

        Args:
            order_id: The order identifier to cancel.

        Returns:
            Dict with order_id, status, timestamp.
        """
        delay = random.uniform(self._delay_min, self._delay_max)
        if delay > 0:
            time.sleep(delay)

        if order_id not in self._orders:
            return {
                "order_id": order_id,
                "status": "NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat(),
            }

        self._orders[order_id]["status"] = "CANCELLED"
        self._orders[order_id]["updated_at"] = datetime.utcnow()

        logger.info("Paper broker cancelled order", extra={"order_id": order_id})

        return {
            "order_id": order_id,
            "status": "CANCELLED",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Get current status of an order.

        Args:
            order_id: The order identifier.

        Returns:
            Dict with order_id, status, timestamp.
        """
        if order_id not in self._orders:
            return {
                "order_id": order_id,
                "status": "NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat(),
            }

        order = self._orders[order_id]
        return {
            "order_id": order_id,
            "status": order["status"],
            "filled_qty": order.get("filled_qty", 0),
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Simulation Methods
    # ------------------------------------------------------------------

    def simulate_fill(
        self,
        order_id: str,
        force_full: bool = False,
        force_price: float | None = None,
    ) -> dict[str, Any]:
        """Simulate a fill event for an acknowledged order.

        Applies slippage, brokerage, spread effect, and optional partial fill.

        Args:
            order_id: The order to fill.
            force_full: If True, skip partial fill simulation.
            force_price: If set, use this price instead of simulated price.

        Returns:
            Dict matching broker fill event format:
            order_id, status, filled_qty, price, timestamp, remaining_qty, is_partial.
        """
        if order_id not in self._orders:
            return {
                "order_id": order_id,
                "status": "NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat(),
            }

        order = self._orders[order_id]
        order_data = order["order_data"]
        requested_qty = order_data.get("quantity", 1)
        base_price = force_price if force_price is not None else order_data.get("price", 0.0)

        # --- Determine fill quantity ---
        if force_full:
            fill_qty = requested_qty
            is_partial = False
        elif random.random() < self._partial_fill_rate:
            fill_qty = max(1, requested_qty // 2)
            is_partial = True
        else:
            fill_qty = requested_qty
            is_partial = False

        remaining_qty = requested_qty - fill_qty if is_partial else 0

        # --- Apply slippage ---
        slippage_pct = random.uniform(self._slippage_min, self._slippage_max)
        action = order_data.get("action", "BUY")
        if action == "BUY":
            fill_price = base_price * (1 + slippage_pct)  # Buy higher
        else:
            fill_price = base_price * (1 - slippage_pct)  # Sell lower

        # --- Apply spread effect ---
        spread = fill_price * self._spread_fraction
        fill_price += spread if action == "BUY" else -spread

        # --- Calculate brokerage ---
        num_lots = fill_qty
        brokerage = num_lots * self._brokerage_per_lot

        # --- Update order state ---
        order["status"] = "PARTIAL_FILL" if is_partial else "FILLED"
        order["filled_qty"] = fill_qty
        order["remaining_qty"] = remaining_qty
        order["fill_price"] = fill_price
        order["brokerage"] = brokerage
        order["updated_at"] = datetime.utcnow()

        # --- Update account ---
        slippage_amount = abs(fill_price - base_price) * fill_qty
        self._total_slippage += slippage_amount
        self._total_brokerage += brokerage

        # Track position
        trade_id = order_data.get("trade_id", "")
        if trade_id and trade_id not in self._positions:
            self._positions[trade_id] = PaperPosition(
                trade_id=trade_id,
                action=action,
                option_side=order_data.get("option_side", "CE"),
                strike=order_data.get("strike", ""),
                quantity=fill_qty,
                filled_qty=fill_qty,
                entry_price=fill_price,
            )
        elif trade_id:
            pos = self._positions[trade_id]
            total_qty = pos.filled_qty + fill_qty
            if total_qty > 0:
                pos.entry_price = ((pos.entry_price * pos.filled_qty) + (fill_price * fill_qty)) / total_qty
            pos.filled_qty = total_qty
            pos.quantity = total_qty

        # Update balance based on action
        if action == "BUY":
            cost = (fill_price * fill_qty) + brokerage
            self._balance -= cost
        elif action == "SELL":
            proceeds = (fill_price * fill_qty) - brokerage
            self._balance += proceeds

        self._filled_orders.append(order_id)

        logger.info(
            "Paper broker simulated fill",
            extra={
                "order_id": order_id,
                "filled_qty": fill_qty,
                "price": round(fill_price, 2),
                "is_partial": is_partial,
                "brokerage": round(brokerage, 2),
            },
        )

        return {
            "order_id": order_id,
            "status": order["status"],
            "filled_qty": fill_qty,
            "price": round(fill_price, 2),
            "remaining_qty": remaining_qty,
            "is_partial": is_partial,
            "brokerage": round(brokerage, 2),
            "slippage": round(slippage_amount, 2),
            "timestamp": datetime.utcnow().isoformat(),
            "extra": {
                "brokerage": round(brokerage, 2),
                "slippage": round(slippage_amount, 2),
                "base_price": base_price,
            },
        }

    def settle_position(self, trade_id: str, exit_price: float) -> dict[str, Any]:
        """Close a position and calculate realised P&L.

        Args:
            trade_id: The trade to settle.
            exit_price: The exit price per unit.

        Returns:
            Dict with trade_id, pnl, balance, brokerage info.
        """
        if trade_id not in self._positions:
            return {"trade_id": trade_id, "pnl": 0.0, "error": "Position not found"}

        pos = self._positions[trade_id]

        if pos.action == "BUY":
            pnl_per_unit = exit_price - pos.entry_price
        else:
            pnl_per_unit = pos.entry_price - exit_price

        gross_pnl = pnl_per_unit * pos.filled_qty
        total_brokerage = pos.filled_qty * self._brokerage_per_lot
        net_pnl = gross_pnl - total_brokerage

        # Update account
        if pos.action == "BUY":
            # BUY: balance was debited during fill, now add P&L
            # net_pnl = (exit - entry) * qty - brokerage (sell side)
            self._balance += net_pnl
        elif pos.action == "SELL":
            # SELL: balance was credited during fill (sale proceeds), now deduct buyback
            # Buyback cost = exit_price * qty + brokerage
            buyback_cost = (exit_price * pos.filled_qty) + total_brokerage
            self._balance -= buyback_cost

        pos.status = "CLOSED"
        pos.pnl = round(net_pnl, 2)

        self._total_brokerage += total_brokerage

        logger.info(
            "Paper broker settled position",
            extra={
                "trade_id": trade_id,
                "pnl": round(net_pnl, 2),
                "balance": round(self._balance, 2),
            },
        )

        return {
            "trade_id": trade_id,
            "pnl": round(net_pnl, 2),
            "gross_pnl": round(gross_pnl, 2),
            "brokerage": round(total_brokerage, 2),
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "quantity": pos.filled_qty,
            "balance": round(self._balance, 2),
        }

    # ------------------------------------------------------------------
    # Account Management
    # ------------------------------------------------------------------

    def get_account_summary(self) -> dict[str, Any]:
        """Get the current paper account summary.

        Returns:
            Dict with balance, positions count, total P&L, etc.
        """
        active_positions = [p for p in self._positions.values() if p.status == "OPEN"]
        closed_positions = [p for p in self._positions.values() if p.status == "CLOSED"]
        total_pnl = sum(p.pnl for p in closed_positions)

        return {
            "balance": round(self._balance, 2),
            "initial_capital": self._initial_capital,
            "total_pnl": round(total_pnl, 2),
            "active_positions": len(active_positions),
            "closed_positions": len(closed_positions),
            "total_brokerage": round(self._total_brokerage, 2),
            "total_slippage": round(self._total_slippage, 2),
        }

    def reset_account(self) -> None:
        """Reset the paper account to initial state."""
        self._balance = self._initial_capital
        self._positions.clear()
        self._orders.clear()
        self._filled_orders.clear()
        self._total_brokerage = 0.0
        self._total_slippage = 0.0
        logger.info("Paper broker account reset")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def balance(self) -> float:
        """Current account balance."""
        return self._balance

    @property
    def positions(self) -> dict[str, PaperPosition]:
        """All positions keyed by trade_id."""
        return dict(self._positions)

    @property
    def total_brokerage(self) -> float:
        """Total brokerage charged so far."""
        return self._total_brokerage

    @property
    def total_slippage(self) -> float:
        """Total slippage incurred so far."""
        return self._total_slippage
