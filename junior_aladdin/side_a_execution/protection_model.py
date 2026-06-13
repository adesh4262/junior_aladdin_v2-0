"""Side A — Protection Model: Entry fill → immediate SL/TGT staging.

Protects positions immediately after fill. Implements the "Protect First,
Then Optimize" philosophy — protection is the first tactical duty of
execution. SL and TGT orders are created and linked via OLM's OCO-style
linkage immediately upon fill.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.11 & Section 14):
- Protection must be established as early as practical
- Protect First, Then Optimize
- unprotected live exposure is dangerous
- optimisation must wait behind protection
- SL/TGT linkage is OCO-style logical + position quantity sync

Ownership split:
- Protection Model orchestrates SL/TGT order creation
- Order Lifecycle Manager tracks order states + maintains linkage
- Position Manager holds the position truth that drives SL/TGT pricing
- Execution Core submits the SL/TGT orders to the broker

Output contracts:
- OrderRecords for SL/TGT → OrderLifecycleManager.register_order()
- SLTGTLinkage → OrderLifecycleManager.link_sl_tgt()
- Protection status → execution_logging_layer, execution_orchestrator
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    OrderLifecycleManager,
    SLTGTLinkage,
)
from junior_aladdin.side_a_execution.position_manager import PositionManager
from junior_aladdin.side_a_execution.side_a_types import (
    OrderRecord,
    OrderState,
    PositionState,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_SL_OFFSET_TICKS: int = 10
"""Default offset for initial SL price from entry (in ticks). Used when
PositionState.sl_price is not set — sets SL at this many ticks away."""

DEFAULT_TARGET_OFFSET_TICKS: int = 30
"""Default offset for initial target price from entry (in ticks). Used when
PositionState.target_price is not set."""

NIFTY_TICK_SIZE: float = 0.05
"""NIFTY 50 minimum tick size (0.05 points)."""


# =============================================================================
# ProtectionModel
# =============================================================================


class ProtectionModel:
    """Stages SL/TGT protection immediately after a position is filled.

    Responsible for creating and linking stop-loss and target orders
    based on position data. Integrates with OrderLifecycleManager for
    order tracking and linkage management.

    Usage::

        pmodel = ProtectionModel(
            order_lifecycle_manager=olm,
            position_manager=pm,
        )

        # Stage protection after fill
        result = pmodel.stage_protection(
            position=position_state,
            trade_id=\"TRADE-001\",
            primary_order_id=\"ORD001\",
        )
        # result = { \"linkage\": ..., \"sl_order\": ..., \"tgt_order\": ... }

        # Adjust for partial fill
        pmodel.adjust_for_partial_fill(trade_id=\"TRADE-001\",
                                        filled_qty=10)

        # Check status
        status = pmodel.get_protection_status(trade_id=\"TRADE-001\")
        protected = pmodel.is_protected(trade_id=\"TRADE-001\")
    """

    def __init__(
        self,
        order_lifecycle_manager: OrderLifecycleManager,
        position_manager: PositionManager,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the ProtectionModel.

        Args:
            order_lifecycle_manager: The OLM instance for order tracking
                and SL/TGT linkage management.
            position_manager: The PositionManager instance for position
                truth queries.
            on_log_callback: Called for all protection events.
                Signature: (event_type: str, data: dict) -> None
                Expected to forward to execution_logging_layer.
        """
        self._olm = order_lifecycle_manager
        self._pm = position_manager
        self._on_log_callback = on_log_callback

    # ------------------------------------------------------------------
    # Stage Protection
    # ------------------------------------------------------------------

    def stage_protection(
        self,
        position: PositionState,
        trade_id: str,
        primary_order_id: str,
        sl_price: float | None = None,
        target_price: float | None = None,
        sl_offset_ticks: int = DEFAULT_SL_OFFSET_TICKS,
        target_offset_ticks: int = DEFAULT_TARGET_OFFSET_TICKS,
    ) -> dict[str, Any]:
        """Create and link SL/TGT orders for a position.

        Uses the position's sl_price and target_price if available.
        Falls back to configured offsets from entry price if not set.

        The SL order side is opposite to the position direction
        (BUY position → SL order is SELL, and vice versa).
        The TGT order side is also opposite to the position direction.

        Args:
            position: The PositionState to protect.
            trade_id: The trade identifier.
            primary_order_id: The order_id of the filled entry order.
            sl_price: Optional explicit SL price. Overrides position.sl_price.
            target_price: Optional explicit target price. Overrides
                position.target_price.
            sl_offset_ticks: Default SL offset from entry when not set.
            target_offset_ticks: Default target offset from entry when not set.

        Returns:
            Dict with keys:
                - 'linkage': The created SLTGTLinkage
                - 'sl_order': The created SL OrderRecord
                - 'tgt_order': The created TGT OrderRecord

        Raises:
            ExecutionError: If position is None, trade_id is invalid,
                or protection already exists for this trade.
        """
        if position is None:
            raise ExecutionError(
                message="Cannot stage protection for None position",
            )

        if not trade_id:
            raise ExecutionError(
                message="Cannot stage protection without trade_id",
            )

        if not primary_order_id:
            raise ExecutionError(
                message="Cannot stage protection without primary_order_id",
            )

        if position.filled_qty <= 0:
            raise ExecutionError(
                message=f"Cannot stage protection for zero-quantity position",
                details={
                    "trade_id": trade_id,
                    "filled_qty": position.filled_qty,
                },
            )

        # Determine SL and target prices
        final_sl_price = (
            sl_price
            if sl_price is not None
            else position.sl_price
        )
        final_target_price = (
            target_price
            if target_price is not None
            else position.target_price
        )

        # Fall back to default offsets if still not set
        if final_sl_price is None or final_sl_price <= 0:
            final_sl_price = self._calculate_default_sl(
                direction=position.direction,
                entry_price=position.avg_price,
                offset_ticks=sl_offset_ticks,
            )

        if final_target_price is None or final_target_price <= 0:
            final_target_price = self._calculate_default_target(
                direction=position.direction,
                entry_price=position.avg_price,
                offset_ticks=target_offset_ticks,
            )

        # Determine the opposite side for SL/TGT orders
        opposite_side = "SELL" if position.direction == "BUY" else "BUY"

        # Create SL and TGT order IDs
        sl_order_id = self._build_sl_order_id(trade_id)
        tgt_order_id = self._build_tgt_order_id(trade_id)

        # Create OrderRecords
        sl_order = OrderRecord(
            order_id=sl_order_id,
            trade_id=trade_id,
            state=OrderState.PLACED,
            side=opposite_side,
            quantity=position.filled_qty,
            price=final_sl_price,
            sl_price=None,  # SL of an SL doesn't make sense
            target_price=final_target_price,
        )

        tgt_order = OrderRecord(
            order_id=tgt_order_id,
            trade_id=trade_id,
            state=OrderState.PLACED,
            side=opposite_side,
            quantity=position.filled_qty,
            price=final_target_price,
            sl_price=final_sl_price,
            target_price=None,  # TGT of a TGT doesn't make sense
        )

        # Register with OLM
        self._olm.register_order(sl_order)
        self._olm.register_order(tgt_order)

        # Create linkage
        linkage = self._olm.link_sl_tgt(
            primary_order_id=primary_order_id,
            sl_order_id=sl_order_id,
            tgt_order_id=tgt_order_id,
            filled_qty=position.filled_qty,
        )

        self._log("PROTECTION_STAGED", {
            "trade_id": trade_id,
            "primary_order_id": primary_order_id,
            "sl_order_id": sl_order_id,
            "tgt_order_id": tgt_order_id,
            "sl_price": final_sl_price,
            "target_price": final_target_price,
            "quantity": position.filled_qty,
            "direction": position.direction,
        })

        return {
            "linkage": linkage,
            "sl_order": sl_order,
            "tgt_order": tgt_order,
        }

    # ------------------------------------------------------------------
    # Adjust for Partial Fill
    # ------------------------------------------------------------------

    def adjust_for_partial_fill(
        self,
        trade_id: str,
        filled_qty: int,
    ) -> SLTGTLinkage | None:
        """Adjust SL/TGT quantities after a partial fill event.

        Delegates to OLM's adjust_sl_tgt_quantities to sync the
        protection quantities to the new position quantity.

        Args:
            trade_id: The trade identifier.
            filled_qty: The updated filled quantity.

        Returns:
            The updated SLTGTLinkage, or None if no linkage exists.
        """
        if not trade_id:
            raise ExecutionError(
                message="Cannot adjust protection without trade_id",
            )

        if filled_qty < 0:
            raise ExecutionError(
                message=f"Invalid filled_qty for protection adjustment: {filled_qty}",
                details={"trade_id": trade_id},
            )

        # Find the primary order for this trade via OLM
        linkage = self._find_linkage_for_trade(trade_id)
        if linkage is None:
            self._log("ADJUST_SKIPPED", {
                "trade_id": trade_id,
                "reason": "No protection linkage found for trade",
            })
            return None

        result = self._olm.adjust_sl_tgt_quantities(
            primary_order_id=linkage.primary_order_id,
            new_filled_qty=filled_qty,
        )

        if result:
            self._log("PROTECTION_ADJUSTED", {
                "trade_id": trade_id,
                "filled_qty": filled_qty,
                "sl_quantity": result.sl_quantity,
                "tgt_quantity": result.tgt_quantity,
            })

        return result

    # ------------------------------------------------------------------
    # SL/TGT Tie-Breaker (both hit simultaneously)
    # ------------------------------------------------------------------

    def detect_tiebreaker_needed(
        self,
        trade_id: str,
        current_price: float,
    ) -> dict[str, Any]:
        """Check whether SL and TGT would both be triggered at current price.

        In gap/flash crash scenarios, market price can jump past both
        SL and TGT levels simultaneously.  This detector identifies
        the situation so the orchestrator can apply the tie-breaker
        rule: **protection first** — if both hit, the SL (capital
        protection) wins over TGT (optimisation).

        Args:
            trade_id: The trade to check.
            current_price: Current market price.

        Returns:
            Dict with:
                - 'tiebreaker_needed': bool
                - 'sl_hit': bool
                - 'tgt_hit': bool
                - 'winner': str ("SL", "TGT", or "NONE")
                - 'position_direction': str
        """
        position = self._pm.get_position(trade_id)
        if position is None:
            return {
                "tiebreaker_needed": False,
                "sl_hit": False,
                "tgt_hit": False,
                "winner": "NONE",
                "position_direction": "",
            }

        sl_price = position.sl_price
        tgt_price = position.target_price
        if sl_price is None or tgt_price is None or sl_price <= 0 or tgt_price <= 0:
            return {
                "tiebreaker_needed": False,
                "sl_hit": False,
                "tgt_hit": False,
                "winner": "NONE",
                "position_direction": position.direction,
            }

        # Determine if both SL and TGT would be hit at current price
        # BUY: SL below, TGT above. Both hit when price moves past both levels.
        # SELL: SL above, TGT below. Both hit when price moves past both levels.
        sl_hit = False
        tgt_hit = False

        if position.direction == "BUY":
            # For BUY: SL is below entry, TGT is above entry
            # Gap down: price < SL → SL hit. If also < TGT? No, TGT is above entry for BUY.
            # Gap up: price > TGT → TGT hit. If also > SL? Yes, SL is below entry.
            if current_price <= sl_price:
                sl_hit = True
            if current_price >= tgt_price:
                tgt_hit = True
        else:  # SELL
            # For SELL: SL is above entry, TGT is below entry
            if current_price >= sl_price:
                sl_hit = True
            if current_price <= tgt_price:
                tgt_hit = True

        tiebreaker_needed = sl_hit and tgt_hit

        # Tie-breaker rule: PROTECT FIRST → SL wins
        winner = "SL" if tiebreaker_needed else "NONE"

        if tiebreaker_needed:
            self._log("TIEBREAKER_TRIGGERED", {
                "trade_id": trade_id,
                "current_price": current_price,
                "sl_price": sl_price,
                "tgt_price": tgt_price,
                "direction": position.direction,
                "winner": winner,
            })

        return {
            "tiebreaker_needed": tiebreaker_needed,
            "sl_hit": sl_hit,
            "tgt_hit": tgt_hit,
            "winner": winner,
            "position_direction": position.direction,
        }

    # ------------------------------------------------------------------
    # Adjust for Reconciliation
    # ------------------------------------------------------------------

    def adjust_for_reconcile(
        self,
        trade_id: str,
        reconcile_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Adjust protection based on reconciliation data.

        Updates SL/TGT order prices or quantities to match the
        reconciled state. Handles:
        - SL/TGT price adjustments (if broker shows different prices)
        - Quantity sync (if broker shows different fill)
        - Cancel and restage (if protection orders are in wrong state)

        Args:
            trade_id: The trade identifier.
            reconcile_data: Dict from reconciliation engine containing
                mismatches and resolved state. Expected keys:
                - 'sl_mismatch': bool, whether SL price differs
                - 'tgt_mismatch': bool, whether TGT price differs
                - 'qty_mismatch': bool, whether quantity differs
                - 'resolved_sl_price': float, resolved SL price
                - 'resolved_tgt_price': float, resolved TGT price
                - 'resolved_qty': int, resolved quantity

        Returns:
            Dict with:
                - 'adjusted': bool, whether any adjustment was made
                - 'actions': list of action descriptions taken
        """
        if not trade_id:
            raise ExecutionError(
                message="Cannot adjust protection without trade_id",
            )

        if reconcile_data is None:
            raise ExecutionError(
                message="Cannot adjust protection with None reconcile_data",
            )

        actions: list[str] = []
        linkage = self._find_linkage_for_trade(trade_id)

        if linkage is None:
            self._log("RECONCILE_SKIPPED", {
                "trade_id": trade_id,
                "reason": "No protection linkage found",
            })
            return {"adjusted": False, "actions": actions}

        # Check quantity mismatch
        if reconcile_data.get("qty_mismatch", False):
            resolved_qty = reconcile_data.get("resolved_qty")
            if resolved_qty is not None and resolved_qty >= 0:
                self._olm.adjust_sl_tgt_quantities(
                    primary_order_id=linkage.primary_order_id,
                    new_filled_qty=resolved_qty,
                )
                actions.append(f"SL/TGT quantities adjusted to {resolved_qty}")

        # Check SL price mismatch
        if reconcile_data.get("sl_mismatch", False):
            resolved_sl = reconcile_data.get("resolved_sl_price")
            if resolved_sl is not None and resolved_sl > 0:
                # Update SL order record price via OLM
                sl_record = self._olm.get_order(linkage.sl_order_id)
                if sl_record:
                    sl_record.price = resolved_sl
                    sl_record.updated_at = datetime.utcnow()
                actions.append(f"SL price adjusted to {resolved_sl}")

        # Check TGT price mismatch
        if reconcile_data.get("tgt_mismatch", False):
            resolved_tgt = reconcile_data.get("resolved_tgt_price")
            if resolved_tgt is not None and resolved_tgt > 0:
                tgt_record = self._olm.get_order(linkage.tgt_order_id)
                if tgt_record:
                    tgt_record.price = resolved_tgt
                    tgt_record.updated_at = datetime.utcnow()
                actions.append(f"TGT price adjusted to {resolved_tgt}")

        self._log("PROTECTION_RECONCILED", {
            "trade_id": trade_id,
            "actions": actions,
        })

        return {"adjusted": len(actions) > 0, "actions": actions}

    # ------------------------------------------------------------------
    # Status Queries
    # ------------------------------------------------------------------

    def get_protection_status(self, trade_id: str) -> dict[str, Any]:
        """Get the current protection status for a trade.

        Args:
            trade_id: The trade identifier.

        Returns:
            Dict with:
                - 'protected': bool, whether protection is active
                - 'sl_order': dict with SL order details or None
                - 'tgt_order': dict with TGT order details or None
                - 'linkage': SLTGTLinkage dict or None
        """
        position = self._pm.get_position(trade_id)
        linkage = self._find_linkage_for_trade(trade_id)

        sl_info = None
        tgt_info = None
        linkage_info = None

        if linkage:
            linkage_info = {
                "primary_order_id": linkage.primary_order_id,
                "sl_order_id": linkage.sl_order_id,
                "tgt_order_id": linkage.tgt_order_id,
                "sl_state": linkage.sl_order_state.value,
                "tgt_state": linkage.tgt_order_state.value,
                "sl_quantity": linkage.sl_quantity,
                "tgt_quantity": linkage.tgt_quantity,
            }

            sl_record = self._olm.get_order(linkage.sl_order_id)
            if sl_record:
                sl_info = {
                    "order_id": sl_record.order_id,
                    "state": sl_record.state.value,
                    "price": sl_record.price,
                    "quantity": sl_record.quantity,
                }

            tgt_record = self._olm.get_order(linkage.tgt_order_id)
            if tgt_record:
                tgt_info = {
                    "order_id": tgt_record.order_id,
                    "state": tgt_record.state.value,
                    "price": tgt_record.price,
                    "quantity": tgt_record.quantity,
                }

        # Determine if protected: position exists with SL and TGT set
        has_position_sl = position is not None and position.sl_price is not None
        has_linkage = linkage is not None

        return {
            "protected": has_position_sl and has_linkage,
            "sl_order": sl_info,
            "tgt_order": tgt_info,
            "linkage": linkage_info,
            "position_sl_price": position.sl_price if position else None,
            "position_target_price": position.target_price if position else None,
        }

    def is_protected(self, trade_id: str) -> bool:
        """Quick check: is a trade currently protected?

        A trade is considered protected if:
        1. A position exists with an SL price set on the PositionState
        2. An SL/TGT linkage exists in the OLM

        Args:
            trade_id: The trade identifier.

        Returns:
            True if the trade has active protection.
        """
        position = self._pm.get_position(trade_id)
        if position is None:
            return False

        has_sl_price = position.sl_price is not None and position.sl_price > 0
        linkage = self._find_linkage_for_trade(trade_id)

        return has_sl_price and linkage is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calculate_default_sl(
        self,
        direction: str,
        entry_price: float,
        offset_ticks: int,
    ) -> float:
        """Calculate a default SL price based on direction and offset.

        For BUY: SL is offset_ticks below entry (protection against downside).
        For SELL: SL is offset_ticks above entry (protection against upside).

        Args:
            direction: "BUY" or "SELL".
            entry_price: The average entry price.
            offset_ticks: Number of ticks for the offset.

        Returns:
            The calculated SL price.
        """
        offset = offset_ticks * NIFTY_TICK_SIZE
        if direction == "BUY":
            return round(entry_price - offset, 2)
        else:
            return round(entry_price + offset, 2)

    def _calculate_default_target(
        self,
        direction: str,
        entry_price: float,
        offset_ticks: int,
    ) -> float:
        """Calculate a default target price based on direction and offset.

        For BUY: target is offset_ticks above entry (profit target).
        For SELL: target is offset_ticks below entry (profit target).

        Args:
            direction: "BUY" or "SELL".
            entry_price: The average entry price.
            offset_ticks: Number of ticks for the offset.

        Returns:
            The calculated target price.
        """
        offset = offset_ticks * NIFTY_TICK_SIZE
        if direction == "BUY":
            return round(entry_price + offset, 2)
        else:
            return round(entry_price - offset, 2)

    def _build_sl_order_id(self, trade_id: str) -> str:
        """Build a standardized SL order ID from a trade ID.

        Args:
            trade_id: The trade identifier.

        Returns:
            An order ID string like "SL_{trade_id}".
        """
        return f"SL_{trade_id}"

    def _build_tgt_order_id(self, trade_id: str) -> str:
        """Build a standardized TGT order ID from a trade ID.

        Args:
            trade_id: The trade identifier.

        Returns:
            An order ID string like "TGT_{trade_id}".
        """
        return f"TGT_{trade_id}"

    def _find_linkage_for_trade(self, trade_id: str) -> SLTGTLinkage | None:
        """Find an SL/TGT linkage for a given trade.

        Searches through all OLM linkages to find one whose primary
        order belongs to the specified trade.

        Args:
            trade_id: The trade identifier.

        Returns:
            The SLTGTLinkage if found, None otherwise.
        """
        # Get all orders for this trade from OLM
        trade_orders = self._olm.get_trade_orders(trade_id)

        # Find which order has a linkage
        for order_record in trade_orders:
            linkage = self._olm.get_linkage(order_record.order_id)
            if linkage is not None:
                return linkage

        return None

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event being logged.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
