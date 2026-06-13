"""Tests for order_lifecycle_manager.py — Order state tracking with SL/TGT linkage.

Covers:
- is_order_terminal, is_transition_valid helpers
- OrderLifecycleManager: register_order, update_state, get_order,
  get_trade_orders, get_active_orders, get_active_orders_for_trade
- SL/TGT linkage: link_sl_tgt, adjust_sl_tgt_quantities, get_linkage,
  update_linkage_order_state, get_all_linkages
- Partial fill handling: handle_partial_fill
- Batch ops: cancel_all_active_orders, get_orders_in_state, get_summary
- Edge cases: None inputs, unknown orders, duplicate registration,
  invalid transitions, terminal state transitions
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    DEFAULT_MAX_ACTIVE_ORDERS_PER_TRADE,
    OrderLifecycleManager,
    SLTGTLinkage,
    is_order_terminal,
    is_transition_valid,
)
from junior_aladdin.side_a_execution.side_a_types import (
    OrderRecord,
    OrderState,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def olm():
    """OrderLifecycleManager with a mock log callback."""
    log_mock = MagicMock()
    manager = OrderLifecycleManager(on_log_callback=log_mock)
    return manager


@pytest.fixture
def basic_order():
    """Standard OrderRecord fixture."""
    return OrderRecord(
        order_id="ORD001",
        trade_id="TRADE-001",
        side="BUY",
        quantity=25,
        price=150.0,
    )


@pytest.fixture
def second_order():
    """Second OrderRecord for multi-order tests."""
    return OrderRecord(
        order_id="ORD002",
        trade_id="TRADE-001",
        side="SELL",
        quantity=10,
        price=155.0,
    )


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """is_order_terminal and is_transition_valid tests."""

    def test_is_order_terminal(self):
        """Terminal states are correctly identified."""
        assert is_order_terminal(OrderState.FILLED) is True
        assert is_order_terminal(OrderState.CANCELLED) is True
        assert is_order_terminal(OrderState.REJECTED) is True
        assert is_order_terminal(OrderState.EXPIRED) is True

    def test_is_order_not_terminal(self):
        """Non-terminal states are correctly identified."""
        assert is_order_terminal(OrderState.PLACED) is False
        assert is_order_terminal(OrderState.ACKNOWLEDGED) is False
        assert is_order_terminal(OrderState.PARTIAL_FILL) is False
        assert is_order_terminal(OrderState.MODIFIED) is False

    def test_is_transition_valid_acknowledged(self):
        """PLACED → ACKNOWLEDGED is valid."""
        assert is_transition_valid(OrderState.PLACED, OrderState.ACKNOWLEDGED) is True

    def test_is_transition_valid_rejected_from_placed(self):
        """PLACED → REJECTED is valid."""
        assert is_transition_valid(OrderState.PLACED, OrderState.REJECTED) is True

    def test_is_transition_valid_ack_to_fill(self):
        """ACKNOWLEDGED → FILLED is valid."""
        assert is_transition_valid(OrderState.ACKNOWLEDGED, OrderState.FILLED) is True

    def test_is_transition_valid_ack_to_partial(self):
        """ACKNOWLEDGED → PARTIAL_FILL is valid."""
        assert is_transition_valid(OrderState.ACKNOWLEDGED, OrderState.PARTIAL_FILL) is True

    def test_is_transition_valid_ack_to_cancelled(self):
        """ACKNOWLEDGED → CANCELLED is valid."""
        assert is_transition_valid(OrderState.ACKNOWLEDGED, OrderState.CANCELLED) is True

    def test_is_transition_valid_partial_to_full(self):
        """PARTIAL_FILL → FILLED is valid."""
        assert is_transition_valid(OrderState.PARTIAL_FILL, OrderState.FILLED) is True

    def test_is_transition_valid_partial_to_modified(self):
        """PARTIAL_FILL → MODIFIED is valid."""
        assert is_transition_valid(OrderState.PARTIAL_FILL, OrderState.MODIFIED) is True

    def test_is_transition_valid_invalid(self):
        """PLACED → FILLED (skip ack) is INVALID."""
        assert is_transition_valid(OrderState.PLACED, OrderState.FILLED) is False

    def test_is_transition_valid_from_terminal(self):
        """FILLED → any is INVALID (terminal)."""
        assert is_transition_valid(OrderState.FILLED, OrderState.ACKNOWLEDGED) is False

    def test_is_transition_valid_same_state(self):
        """Same state transition is always valid (no-op)."""
        assert is_transition_valid(OrderState.PLACED, OrderState.PLACED) is True
        assert is_transition_valid(OrderState.FILLED, OrderState.FILLED) is True


# =============================================================================
# Order Registration
# =============================================================================


class TestRegisterOrder:
    """OrderLifecycleManager.register_order tests."""

    def test_register_basic_order(self, olm, basic_order):
        """Register a basic order returns the order_id."""
        result = olm.register_order(basic_order)
        assert result == "ORD001"

    def test_register_none_raises(self, olm):
        """Registering None raises ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot register None order"):
            olm.register_order(None)  # type: ignore

    def test_register_duplicate_raises(self, olm, basic_order):
        """Registering the same order twice raises."""
        olm.register_order(basic_order)
        with pytest.raises(ExecutionError, match="already registered"):
            olm.register_order(basic_order)

    def test_register_empty_order_id_raises(self, olm):
        """Registering order with empty order_id raises."""
        order = OrderRecord(order_id="", trade_id="TRADE-001", side="BUY")
        with pytest.raises(ExecutionError, match="without order_id"):
            olm.register_order(order)

    def test_register_empty_trade_id_raises(self, olm):
        """Registering order with empty trade_id raises."""
        order = OrderRecord(order_id="ORD001", trade_id="", side="BUY")
        with pytest.raises(ExecutionError, match="without trade_id"):
            olm.register_order(order)

    def test_register_multiple_orders(self, olm, basic_order, second_order):
        """Multiple orders can be registered for the same trade."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        assert olm.get_order_count() == 2

    def test_register_triggers_log(self, olm, basic_order):
        """Registering triggers ORDER_REGISTERED log event."""
        olm.register_order(basic_order)
        olm._on_log_callback.assert_any_call("ORDER_REGISTERED", {
            "order_id": "ORD001",
            "trade_id": "TRADE-001",
            "state": "PLACED",
        })

    def test_register_enforces_order_limit(self, olm, basic_order):
        """Warning logged when order count exceeds safety limit."""
        # Register many orders for the same trade
        for i in range(DEFAULT_MAX_ACTIVE_ORDERS_PER_TRADE + 1):
            order = OrderRecord(
                order_id=f"ORD{i:03d}",
                trade_id="TRADE-001",
                side="BUY",
            )
            olm.register_order(order)

        # Should have logged an ORDER_LIMIT_WARNING
        warning_found = any(
            call_args[0][0] == "ORDER_LIMIT_WARNING"
            for call_args in olm._on_log_callback.call_args_list
        )
        assert warning_found


# =============================================================================
# State Transitions
# =============================================================================


class TestUpdateState:
    """OrderLifecycleManager.update_state tests."""

    def test_placed_to_acknowledged(self, olm, basic_order):
        """PLACED → ACKNOWLEDGED is valid."""
        olm.register_order(basic_order)
        record = olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        assert record.state == OrderState.ACKNOWLEDGED

    def test_placed_to_rejected(self, olm, basic_order):
        """PLACED → REJECTED is valid."""
        olm.register_order(basic_order)
        record = olm.update_state("ORD001", OrderState.REJECTED)
        assert record.state == OrderState.REJECTED

    def test_full_happy_path(self, olm, basic_order):
        """Full order lifecycle: PLACED → ACK → FILLED."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.FILLED)
        assert olm.get_order("ORD001").state == OrderState.FILLED

    def test_partial_fill_path(self, olm, basic_order):
        """PLACED → ACK → PARTIAL → FILLED."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.PARTIAL_FILL)
        assert olm.get_order("ORD001").state == OrderState.PARTIAL_FILL
        olm.update_state("ORD001", OrderState.FILLED)
        assert olm.get_order("ORD001").state == OrderState.FILLED

    def test_placed_to_filled_invalid(self, olm, basic_order):
        """PLACED → FILLED (skip ack) is INVALID."""
        olm.register_order(basic_order)
        with pytest.raises(ExecutionError, match="Invalid order state transition"):
            olm.update_state("ORD001", OrderState.FILLED)

    def test_update_unknown_order(self, olm):
        """Updating unknown order raises."""
        with pytest.raises(ExecutionError, match="unknown order"):
            olm.update_state("UNKNOWN", OrderState.ACKNOWLEDGED)

    def test_update_none_state(self, olm, basic_order):
        """Updating with None state raises."""
        olm.register_order(basic_order)
        with pytest.raises(ExecutionError, match="Invalid new_state"):
            olm.update_state("ORD001", None)  # type: ignore

    def test_update_from_terminal_state(self, olm, basic_order):
        """Transitioning from FILLED raises."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.FILLED)
        with pytest.raises(ExecutionError, match="terminal state"):
            olm.update_state("ORD001", OrderState.CANCELLED)

    def test_same_state_noop(self, olm, basic_order):
        """Transitioning to same state is a no-op (no error)."""
        olm.register_order(basic_order)
        record = olm.update_state("ORD001", OrderState.PLACED)
        assert record.state == OrderState.PLACED

    def test_ack_to_cancelled(self, olm, basic_order):
        """ACKNOWLEDGED → CANCELLED is valid."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        record = olm.update_state("ORD001", OrderState.CANCELLED)
        assert record.state == OrderState.CANCELLED
        assert is_order_terminal(record.state)

    def test_ack_to_rejected(self, olm, basic_order):
        """ACKNOWLEDGED → REJECTED is valid."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        record = olm.update_state("ORD001", OrderState.REJECTED)
        assert record.state == OrderState.REJECTED

    def test_partial_to_cancelled(self, olm, basic_order):
        """PARTIAL_FILL → CANCELLED is valid."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.PARTIAL_FILL)
        record = olm.update_state("ORD001", OrderState.CANCELLED)
        assert record.state == OrderState.CANCELLED

    def test_partial_to_modified(self, olm, basic_order):
        """PARTIAL_FILL → MODIFIED is valid."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.PARTIAL_FILL)
        record = olm.update_state("ORD001", OrderState.MODIFIED)
        assert record.state == OrderState.MODIFIED

    def test_event_logging(self, olm, basic_order):
        """State transitions append events to the order record."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        record = olm.get_order("ORD001")
        assert len(record.events) >= 1
        assert record.events[0]["type"] == "STATE_TRANSITION"
        assert record.events[0]["from"] == "PLACED"
        assert record.events[0]["to"] == "ACKNOWLEDGED"

    def test_event_data_included(self, olm, basic_order):
        """Extra event_data is appended to the transition event."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED,
                          event_data={"broker_ref": "REF001"})
        record = olm.get_order("ORD001")
        assert record.events[0].get("broker_ref") == "REF001"


# =============================================================================
# Order Querying
# =============================================================================


class TestOrderQuerying:
    """Order retrieval tests."""

    def test_get_order_found(self, olm, basic_order):
        """get_order returns the order when found."""
        olm.register_order(basic_order)
        record = olm.get_order("ORD001")
        assert record is not None
        assert record.order_id == "ORD001"

    def test_get_order_not_found(self, olm):
        """get_order returns None when not found."""
        assert olm.get_order("UNKNOWN") is None

    def test_get_trade_orders(self, olm, basic_order, second_order):
        """get_trade_orders returns all orders for a trade."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        orders = olm.get_trade_orders("TRADE-001")
        assert len(orders) == 2
        assert orders[0].order_id == "ORD001"
        assert orders[1].order_id == "ORD002"

    def test_get_trade_orders_empty(self, olm):
        """get_trade_orders returns empty list for unknown trade."""
        assert olm.get_trade_orders("UNKNOWN") == []

    def test_get_active_orders_all_active(self, olm, basic_order, second_order):
        """All non-terminal orders are returned as active."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        active = olm.get_active_orders()
        assert len(active) == 2

    def test_get_active_orders_some_terminal(self, olm, basic_order, second_order):
        """Terminal orders are excluded from active."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.FILLED)
        active = olm.get_active_orders()
        assert len(active) == 1
        assert active[0].order_id == "ORD002"

    def test_get_active_orders_for_trade(self, olm, basic_order, second_order):
        """Active orders filtered by trade."""
        third = OrderRecord(order_id="ORD003", trade_id="TRADE-002", side="BUY")
        olm.register_order(basic_order)
        olm.register_order(second_order)
        olm.register_order(third)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.FILLED)
        active = olm.get_active_orders_for_trade("TRADE-001")
        assert len(active) == 1
        assert active[0].order_id == "ORD002"

    def test_get_order_count(self, olm, basic_order, second_order):
        """get_order_count returns total tracked orders."""
        assert olm.get_order_count() == 0
        olm.register_order(basic_order)
        assert olm.get_order_count() == 1
        olm.register_order(second_order)
        assert olm.get_order_count() == 2

    def test_get_trade_count(self, olm, basic_order):
        """get_trade_count returns unique trade count."""
        assert olm.get_trade_count() == 0
        olm.register_order(basic_order)
        assert olm.get_trade_count() == 1
        third = OrderRecord(order_id="ORD003", trade_id="TRADE-002", side="BUY")
        olm.register_order(third)
        assert olm.get_trade_count() == 2


# =============================================================================
# SL/TGT Linkage
# =============================================================================


class TestSLTGTLinkage:
    """SL/TGT linkage tests."""

    def test_link_sl_tgt_success(self, olm, basic_order):
        """Link SL and TGT orders to a primary order."""
        sl_order = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt_order = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl_order)
        olm.register_order(tgt_order)

        linkage = olm.link_sl_tgt("ORD001", "SL001", "TGT001", filled_qty=25)
        assert linkage.primary_order_id == "ORD001"
        assert linkage.sl_order_id == "SL001"
        assert linkage.tgt_order_id == "TGT001"
        assert linkage.sl_quantity == 25
        assert linkage.tgt_quantity == 25

    def test_link_primary_not_found(self, olm):
        """Linking to unknown primary raises."""
        with pytest.raises(ExecutionError, match="primary order not found"):
            olm.link_sl_tgt("UNKNOWN", "SL001", "TGT001")

    def test_link_empty_sl_tgt(self, olm, basic_order):
        """Linking with empty SL or TGT ID raises."""
        olm.register_order(basic_order)
        with pytest.raises(ExecutionError, match="must not be empty"):
            olm.link_sl_tgt("ORD001", "", "TGT001")

    def test_link_duplicate(self, olm, basic_order):
        """Linking the same primary twice raises."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001")
        with pytest.raises(ExecutionError, match="already exists"):
            olm.link_sl_tgt("ORD001", "SL002", "TGT002")

    def test_link_sl_not_registered(self, olm, basic_order):
        """Linking with unregistered SL order raises."""
        olm.register_order(basic_order)
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(tgt)
        with pytest.raises(ExecutionError, match="SL order not registered"):
            olm.link_sl_tgt("ORD001", "SL001", "TGT001")

    def test_adjust_sl_tgt_quantities(self, olm, basic_order):
        """Adjust SL/TGT quantities for partial fill."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001", filled_qty=25)

        linkage = olm.adjust_sl_tgt_quantities("ORD001", new_filled_qty=10)
        assert linkage is not None
        assert linkage.sl_quantity == 10
        assert linkage.tgt_quantity == 10

    def test_adjust_no_linkage(self, olm):
        """Adjust on order without linkage returns None."""
        result = olm.adjust_sl_tgt_quantities("ORD001", new_filled_qty=10)
        assert result is None

    def test_get_linkage_found(self, olm, basic_order):
        """get_linkage returns linkage when it exists."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001")

        linkage = olm.get_linkage("ORD001")
        assert linkage is not None
        assert linkage.sl_order_id == "SL001"

    def test_get_linkage_not_found(self, olm):
        """get_linkage returns None when no linkage exists."""
        assert olm.get_linkage("ORD001") is None

    def test_update_linkage_order_state_sl(self, olm, basic_order):
        """Update SL order state within linkage."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001")

        olm.update_linkage_order_state("SL001", OrderState.FILLED)
        linkage = olm.get_linkage("ORD001")
        assert linkage.sl_order_state == OrderState.FILLED

    def test_update_linkage_order_state_tgt(self, olm, basic_order):
        """Update TGT order state within linkage."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001")

        olm.update_linkage_order_state("TGT001", OrderState.CANCELLED)
        linkage = olm.get_linkage("ORD001")
        assert linkage.tgt_order_state == OrderState.CANCELLED

    def test_update_linkage_order_state_untracked(self, olm):
        """Update state for order not in any linkage is a no-op."""
        # Should not raise
        olm.update_linkage_order_state("UNKNOWN", OrderState.FILLED)

    def test_get_all_linkages(self, olm, basic_order):
        """get_all_linkages returns all linkage records."""
        sl1 = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt1 = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        order2 = OrderRecord(order_id="ORD002", trade_id="TRADE-002", side="BUY")
        sl2 = OrderRecord(order_id="SL002", trade_id="TRADE-002", side="SELL")
        tgt2 = OrderRecord(order_id="TGT002", trade_id="TRADE-002", side="SELL")

        for o in [basic_order, sl1, tgt1, order2, sl2, tgt2]:
            olm.register_order(o)

        olm.link_sl_tgt("ORD001", "SL001", "TGT001")
        olm.link_sl_tgt("ORD002", "SL002", "TGT002")

        linkages = olm.get_all_linkages()
        assert len(linkages) == 2


# =============================================================================
# Partial Fill Handling
# =============================================================================


class TestPartialFill:
    """OrderLifecycleManager.handle_partial_fill tests."""

    def test_full_fill_via_handle(self, olm, basic_order):
        """handle_partial_fill with remaining=0 transitions to FILLED."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        record = olm.handle_partial_fill("ORD001", filled_qty=25, price=150.0)
        assert record.state == OrderState.FILLED
        assert record.filled_qty == 25

    def test_partial_fill(self, olm, basic_order):
        """handle_partial_fill with remaining>0 transitions to PARTIAL_FILL."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        record = olm.handle_partial_fill("ORD001", filled_qty=10, price=150.0)
        assert record.state == OrderState.PARTIAL_FILL
        assert record.filled_qty == 10

    def test_partial_fill_unknown_order(self, olm):
        """handle_partial_fill for unknown order raises."""
        with pytest.raises(ExecutionError, match="unknown order"):
            olm.handle_partial_fill("UNKNOWN", filled_qty=10, price=150.0)

    def test_partial_fill_negative_qty(self, olm, basic_order):
        """handle_partial_fill with negative qty raises."""
        olm.register_order(basic_order)
        with pytest.raises(ExecutionError, match="Invalid filled quantity"):
            olm.handle_partial_fill("ORD001", filled_qty=-5, price=150.0)

    def test_partial_fill_exceeds_quantity(self, olm, basic_order):
        """handle_partial_fill that exceeds order qty raises."""
        olm.register_order(basic_order)
        with pytest.raises(ExecutionError, match="exceeds order quantity"):
            olm.handle_partial_fill("ORD001", filled_qty=100, price=150.0)

    def test_partial_fill_adjusts_sl_tgt(self, olm, basic_order):
        """handle_partial_fill adjusts linked SL/TGT quantities."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001", filled_qty=25)

        olm.handle_partial_fill("ORD001", filled_qty=10, price=150.0)
        linkage = olm.get_linkage("ORD001")
        assert linkage.sl_quantity == 10
        assert linkage.tgt_quantity == 10

    def test_partial_fill_event_logged(self, olm, basic_order):
        """handle_partial_fill adds FILL event to order events."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.handle_partial_fill("ORD001", filled_qty=10, price=150.0)
        record = olm.get_order("ORD001")
        fill_events = [e for e in record.events if e["type"] == "FILL"]
        assert len(fill_events) == 1
        assert fill_events[0]["filled_qty"] == 10
        assert fill_events[0]["price"] == 150.0


# =============================================================================
# Batch Operations
# =============================================================================


class TestBatchOperations:
    """Batch operation tests."""

    def test_cancel_all_active_orders(self, olm, basic_order, second_order):
        """cancel_all_active_orders cancels all non-terminal orders (PLACED and ACK)."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)

        count = olm.cancel_all_active_orders()
        assert count == 2  # Both PLACED and ACKNOWLEDGED can now be cancelled
        assert olm.get_order("ORD001").state == OrderState.CANCELLED
        assert olm.get_order("ORD002").state == OrderState.CANCELLED

    def test_cancel_all_active_none(self, olm):
        """cancel_all_active_orders when none active returns 0."""
        count = olm.cancel_all_active_orders()
        assert count == 0

    def test_get_orders_in_state(self, olm, basic_order, second_order):
        """get_orders_in_state filters by state."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)

        placed = olm.get_orders_in_state(OrderState.PLACED)
        acked = olm.get_orders_in_state(OrderState.ACKNOWLEDGED)

        assert len(placed) == 1
        assert placed[0].order_id == "ORD002"
        assert len(acked) == 1
        assert acked[0].order_id == "ORD001"

    def test_get_summary_all(self, olm, basic_order, second_order):
        """get_summary for all trades."""
        olm.register_order(basic_order)
        olm.register_order(second_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.FILLED)

        summary = olm.get_summary()
        assert summary["total_orders"] == 2
        assert summary["active_orders"] == 1
        assert summary["terminal_orders"] == 1
        assert summary["by_state"]["FILLED"] == 1
        assert summary["by_state"]["PLACED"] == 1

    def test_get_summary_by_trade(self, olm, basic_order):
        """get_summary scoped to a single trade."""
        olm.register_order(basic_order)
        second_trade = OrderRecord(
            order_id="ORD003", trade_id="TRADE-002", side="BUY",
        )
        olm.register_order(second_trade)

        summary = olm.get_summary(trade_id="TRADE-001")
        assert summary["total_orders"] == 1
        assert summary["trade_id"] == "TRADE-001"

    def test_get_summary_includes_linkage_count(self, olm, basic_order):
        """get_summary includes linkage count."""
        sl = OrderRecord(order_id="SL001", trade_id="TRADE-001", side="SELL")
        tgt = OrderRecord(order_id="TGT001", trade_id="TRADE-001", side="SELL")
        olm.register_order(basic_order)
        olm.register_order(sl)
        olm.register_order(tgt)
        olm.link_sl_tgt("ORD001", "SL001", "TGT001")

        summary = olm.get_summary()
        assert summary["linkage_count"] == 1


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases for OrderLifecycleManager."""

    def test_no_log_callback(self):
        """OrderLifecycleManager works without a log callback."""
        manager = OrderLifecycleManager()
        order = OrderRecord(order_id="ORD001", trade_id="TRADE-001", side="BUY")
        manager.register_order(order)
        manager.update_state("ORD001", OrderState.ACKNOWLEDGED)
        assert manager.get_order("ORD001").state == OrderState.ACKNOWLEDGED

    def test_orders_in_multiple_trades(self, olm):
        """Orders in different trades are tracked correctly."""
        t1 = OrderRecord(order_id="ORD001", trade_id="TRADE-A", side="BUY")
        t2 = OrderRecord(order_id="ORD002", trade_id="TRADE-B", side="SELL")
        olm.register_order(t1)
        olm.register_order(t2)

        assert len(olm.get_trade_orders("TRADE-A")) == 1
        assert len(olm.get_trade_orders("TRADE-B")) == 1
        assert olm.get_trade_count() == 2

    def test_updated_at_changes_on_transition(self, olm, basic_order):
        """updated_at timestamp changes on state transition."""
        olm.register_order(basic_order)
        original = basic_order.updated_at
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        updated = olm.get_order("ORD001").updated_at
        assert updated >= original

    def test_get_active_orders_empty(self, olm):
        """Active orders returns empty list when no orders exist."""
        assert olm.get_active_orders() == []

    def test_modified_to_filled(self, olm, basic_order):
        """MODIFIED → FILLED is a valid transition."""
        olm.register_order(basic_order)
        olm.update_state("ORD001", OrderState.ACKNOWLEDGED)
        olm.update_state("ORD001", OrderState.PARTIAL_FILL)
        olm.update_state("ORD001", OrderState.MODIFIED)
        record = olm.update_state("ORD001", OrderState.FILLED)
        assert record.state == OrderState.FILLED
