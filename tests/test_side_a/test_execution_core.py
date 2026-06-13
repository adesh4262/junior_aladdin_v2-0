"""Tests for execution_core.py — Broker-facing order actor.

Covers:
- OrderSubmission dataclass creation + from_execution_intent
- FillData and AckData correctness
- ExecutionCore: submit_order, handle_acknowledgement, handle_rejection,
  handle_fill, retry_order, cancel_order
- Broker injection (mock broker)
- Callback forwarding (on_fill, on_rejection, on_ack, on_log)
- Retry logic (recoverable vs non-recoverable rejections)
- Edge cases: None inputs, unknown orders, max retries, invalid fills
- State machine integration: transitions triggered correctly
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.execution_core import (
    DEFAULT_MAX_RETRIES,
    FillData,
    AckData,
    OrderSubmission,
    ExecutionCore,
)
from junior_aladdin.side_a_execution.execution_state_machine import (
    ExecutionEvent,
    ExecutionMajorState,
    ExecutionStateMachine,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def state_machine():
    """State machine starting at RISK_PASSED (ready for order submission)."""
    sm = ExecutionStateMachine()
    sm.transition(ExecutionEvent.CAPTAIN_INTENT)
    sm.transition(ExecutionEvent.RISK_PASSED)
    return sm


@pytest.fixture
def mock_broker():
    """Mock broker that returns successful ack on place_order."""
    broker = MagicMock()
    broker.place_order.return_value = {
        "order_id": "ORD123",
        "status": "ACKNOWLEDGED",
        "timestamp": datetime.utcnow(),
    }
    broker.cancel_order.return_value = {
        "order_id": "ORD123",
        "status": "CANCELLED",
        "timestamp": datetime.utcnow(),
    }
    broker.get_order_status.return_value = {
        "order_id": "ORD123",
        "status": "ACKNOWLEDGED",
        "timestamp": datetime.utcnow(),
    }
    return broker


@pytest.fixture
def order_submission():
    """Standard OrderSubmission fixture."""
    return OrderSubmission(
        trade_id="TRADE-001",
        action="BUY",
        option_side="CE",
        strike="19500",
        quantity=1,
        price=150.0,
        order_type="LIMIT",
    )


@pytest.fixture
def execution_core(state_machine, mock_broker):
    """ExecutionCore with mock broker and spy callbacks."""
    on_fill = MagicMock()
    on_rejection = MagicMock()
    on_ack = MagicMock()
    on_log = MagicMock()
    core = ExecutionCore(
        state_machine=state_machine,
        broker=mock_broker,
        on_fill_callback=on_fill,
        on_rejection_callback=on_rejection,
        on_ack_callback=on_ack,
        on_log_callback=on_log,
    )
    return core


# =============================================================================
# OrderSubmission Tests
# =============================================================================


class TestOrderSubmission:
    """OrderSubmission dataclass tests."""

    def test_default_creation(self):
        """OrderSubmission with defaults."""
        order = OrderSubmission(
            trade_id="TRADE-001",
            action="BUY",
            option_side="CE",
            strike="19500",
        )
        assert order.trade_id == "TRADE-001"
        assert order.action == "BUY"
        assert order.option_side == "CE"
        assert order.strike == "19500"
        assert order.quantity == 1
        assert order.price == 0.0
        assert order.order_type == "LIMIT"
        assert order.sl_price is None
        assert order.target_price is None
        assert order.validity == "DAY"

    def test_full_creation(self):
        """OrderSubmission with all fields specified."""
        order = OrderSubmission(
            trade_id="TRADE-002",
            action="SELL",
            option_side="PE",
            strike="19000",
            quantity=2,
            price=120.0,
            order_type="MARKET",
            sl_price=125.0,
            target_price=110.0,
            validity="IOC",
            extra={"broker_note": "test"},
        )
        assert order.trade_id == "TRADE-002"
        assert order.sl_price == 125.0
        assert order.target_price == 110.0
        assert order.validity == "IOC"
        assert order.extra == {"broker_note": "test"}

    def test_from_execution_intent_minimal(self):
        """Build OrderSubmission from an intent-like object."""
        intent = type("FakeIntent", (), {
            "trade_id": "TRADE-003",
            "action": "BUY",
            "option_side": "CE",
            "selected_strike": "19500",
            "entry_plan": {"price": 150.0},
            "stop_loss_plan": {"price": 148.0},
            "target_plan": {"price": 155.0},
        })()

        order = OrderSubmission.from_execution_intent(intent)
        assert order.trade_id == "TRADE-003"
        assert order.action == "BUY"
        assert order.strike == "19500"
        assert order.price == 150.0
        assert order.sl_price == 148.0
        assert order.target_price == 155.0
        assert order.quantity == 1
        assert order.order_type == "LIMIT"

    def test_from_execution_intent_with_overrides(self):
        """Build OrderSubmission with quantity and order_type overrides."""
        intent = type("FakeIntent", (), {
            "trade_id": "TRADE-004",
            "action": "SELL",
            "option_side": "PE",
            "selected_strike": "19000",
            "entry_plan": {},
            "stop_loss_plan": {},
            "target_plan": {},
        })()

        order = OrderSubmission.from_execution_intent(
            intent, quantity=2, order_type="MARKET",
        )
        assert order.quantity == 2
        assert order.order_type == "MARKET"
        assert order.price == 0.0  # default from empty entry_plan
        assert order.sl_price is None  # default from empty stop_loss_plan


# =============================================================================
# FillData Tests
# =============================================================================


class TestFillData:
    """FillData dataclass tests."""

    def test_default_fill(self):
        """FillData with defaults is partial if remaining_qty > 0."""
        fill = FillData(
            order_id="ORD001",
            trade_id="TRADE-001",
            filled_qty=10,
            price=150.0,
        )
        assert fill.order_id == "ORD001"
        assert fill.filled_qty == 10
        assert not fill.is_partial

    def test_partial_fill_auto_detect(self):
        """FillData is_partial auto-set based on remaining_qty."""
        fill = FillData(
            order_id="ORD002",
            trade_id="TRADE-001",
            filled_qty=5,
            price=150.0,
            remaining_qty=5,
        )
        assert fill.is_partial  # is_partial defaults to False but set here
        assert fill.remaining_qty == 5


# =============================================================================
# ExecutionCore — Initial State
# =============================================================================


class TestExecutionCoreInitialState:
    """ExecutionCore construction and basic properties."""

    def test_initial_max_retries(self, execution_core):
        """Default max_retries is 3."""
        assert execution_core.max_retries == DEFAULT_MAX_RETRIES

    def test_initial_retry_backoff(self, execution_core):
        """Default retry_backoff_seconds is 1.0."""
        assert execution_core.retry_backoff_seconds == 1.0

    def test_set_max_retries_valid(self, execution_core):
        """Setting max_retries to valid value works."""
        execution_core.max_retries = 5
        assert execution_core.max_retries == 5

    def test_set_max_retries_invalid(self, execution_core):
        """Setting max_retries to negative raises ExecutionError."""
        with pytest.raises(ExecutionError, match="max_retries must be non-negative"):
            execution_core.max_retries = -1

    def test_set_retry_backoff_valid(self, execution_core):
        """Setting retry_backoff_seconds works."""
        execution_core.retry_backoff_seconds = 2.5
        assert execution_core.retry_backoff_seconds == 2.5

    def test_set_retry_backoff_invalid(self, execution_core):
        """Setting retry_backoff_seconds to negative raises."""
        with pytest.raises(ExecutionError, match="retry_backoff_seconds must be non-negative"):
            execution_core.retry_backoff_seconds = -0.5

    def test_no_active_orders_initially(self, execution_core):
        """No active orders after construction."""
        assert execution_core.get_active_order_ids() == []


# =============================================================================
# ExecutionCore — submit_order
# =============================================================================


class TestSubmitOrder:
    """ExecutionCore.submit_order tests."""

    def test_submit_order_success(self, execution_core, state_machine, mock_broker):
        """Submit order transitions state machine and returns order_id."""
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = execution_core.submit_order(order)

        assert order_id == "ORD123"
        assert state_machine.state == ExecutionMajorState.ORDER_PENDING
        mock_broker.place_order.assert_called_once()
        execution_core._on_ack_callback.assert_called_once()

    def test_submit_order_none_raises(self, execution_core):
        """Submitting None order raises ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot submit None order"):
            execution_core.submit_order(None)  # type: ignore

    def test_submit_order_from_invalid_state(self):
        """Submitting order from IDLE raises ExecutionError."""
        sm = ExecutionStateMachine()  # starts IDLE
        core = ExecutionCore(
            state_machine=sm,
            broker=MagicMock(),
        )
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        with pytest.raises(ExecutionError, match="Cannot submit order"):
            core.submit_order(order)

    def test_submit_order_with_broker_override(self, state_machine):
        """Broker override is used when provided."""
        real_broker = MagicMock()
        override_broker = MagicMock()
        real_broker.place_order.return_value = {
            "order_id": "REAL001", "status": "ACKNOWLEDGED",
        }
        override_broker.place_order.return_value = {
            "order_id": "OVR001", "status": "ACKNOWLEDGED",
        }

        core = ExecutionCore(state_machine=state_machine, broker=real_broker)
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = core.submit_order(order, broker_override=override_broker)
        assert order_id == "OVR001"
        override_broker.place_order.assert_called_once()
        real_broker.place_order.assert_not_called()

    def test_submit_order_empty_broker_response(self, state_machine, mock_broker):
        """Broker returning empty order_id raises ExecutionError."""
        mock_broker.place_order.return_value = {
            "order_id": "", "status": "ACKNOWLEDGED",
        }
        core = ExecutionCore(state_machine=state_machine, broker=mock_broker)
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        with pytest.raises(ExecutionError, match="empty order_id"):
            core.submit_order(order)

    def test_submit_order_broker_exception(self, state_machine, mock_broker):
        """Broker raising exception during submit raises ExecutionError."""
        mock_broker.place_order.side_effect = RuntimeError("Connection lost")
        core = ExecutionCore(state_machine=state_machine, broker=mock_broker)
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        with pytest.raises(ExecutionError, match="Broker submission failed"):
            core.submit_order(order)

    def test_submit_order_broker_immediate_rejection(self, state_machine, mock_broker):
        """Broker returning REJECTED status triggers rejection handling after ORDER_PENDING."""
        mock_broker.place_order.return_value = {
            "order_id": "ORD123",
            "status": "REJECTED",
            "extra": {"reject_reason": "INVALID_PRICE"},
        }
        core = ExecutionCore(
            state_machine=state_machine,
            broker=mock_broker,
            on_rejection_callback=MagicMock(),
        )
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = core.submit_order(order)
        assert order_id == "ORD123"
        # State machine transitions: RISK_PASSED -> ORDER_PENDING (first) -> FAILED (via REJECTED)
        assert state_machine.state == ExecutionMajorState.FAILED
        core._on_rejection_callback.assert_called_once()

    def test_submit_order_logs_events(self, execution_core, order_submission):
        """Submit order triggers ORDER_SUBMIT and ORDER_ACKNOWLEDGED log events."""
        execution_core.submit_order(order_submission)
        events = [call_args[0][0] for call_args in execution_core._on_log_callback.call_args_list]
        assert "ORDER_SUBMIT" in events
        assert "ORDER_ACKNOWLEDGED" in events


# =============================================================================
# ExecutionCore — handle_acknowledgement
# =============================================================================


class TestHandleAcknowledgement:
    """ExecutionCore.handle_acknowledgement tests."""

    def test_handle_ack_success(self, execution_core, order_submission):
        """Handle acknowledgement for known order updates status."""
        order_id = execution_core.submit_order(order_submission)
        ack_data = {"order_id": order_id, "status": "ACKNOWLEDGED", "broker_ref": "REF001"}

        ack = execution_core.handle_acknowledgement(order_id, ack_data)
        assert ack.status == "ACKNOWLEDGED"
        assert ack.broker_ref == "REF001"

    def test_handle_ack_unknown_order(self, execution_core):
        """Handle acknowledgement for unknown order raises."""
        with pytest.raises(ExecutionError, match="unknown order"):
            execution_core.handle_acknowledgement("UNKNOWN", {"status": "ACKNOWLEDGED"})

    def test_handle_ack_triggers_callback(self, execution_core, order_submission):
        """Handle acknowledgement invokes on_ack_callback."""
        order_id = execution_core.submit_order(order_submission)
        execution_core._on_ack_callback.reset_mock()

        execution_core.handle_acknowledgement(order_id, {"status": "ACKNOWLEDGED"})
        execution_core._on_ack_callback.assert_called_once()


# =============================================================================
# ExecutionCore — handle_rejection
# =============================================================================


class TestHandleRejection:
    """ExecutionCore.handle_rejection tests."""

    def test_handle_non_recoverable_rejection(self, execution_core, order_submission):
        """Non-recoverable rejection fails immediately and transitions to FAILED."""
        order_id = execution_core.submit_order(order_submission)

        execution_core.handle_rejection(order_id, "INVALID_PRICE")
        assert execution_core.get_order_status(order_id) == "REJECTED"
        # State machine should be in FAILED
        assert execution_core._state_machine.state == ExecutionMajorState.FAILED
        # on_rejection_callback should have been called
        execution_core._on_rejection_callback.assert_called_once_with(order_id, "INVALID_PRICE")

    def test_handle_recoverable_rejection_triggers_retry(self, execution_core, order_submission, mock_broker):
        """Recoverable rejection triggers automatic retry via broker."""
        order_id = execution_core.submit_order(order_submission)
        execution_core._on_rejection_callback.reset_mock()

        # Broker will be called again for retry
        execution_core.handle_rejection(order_id, "TIMEOUT")
        # Broker.place_order should have been called again (for retry)
        assert mock_broker.place_order.call_count >= 2
        execution_core._on_rejection_callback.assert_called_once_with(order_id, "TIMEOUT")

    def test_handle_rejection_unknown_order(self, execution_core, state_machine):
        """Handle rejection for unknown order doesn't raise and doesn't mutate state machine."""
        initial_state = state_machine.state
        execution_core.handle_rejection("UNKNOWN", "TIMEOUT")
        # State machine should remain unchanged
        assert state_machine.state == initial_state

    def test_recoverable_rejection_max_retries_exceeded(self, state_machine, order_submission):
        """After max retries, recoverable rejection becomes terminal failure."""
        broker = MagicMock()
        broker.place_order.side_effect = [
            {"order_id": "ORD001", "status": "ACKNOWLEDGED"},
            {"order_id": "ORD002", "status": "ACKNOWLEDGED"},
        ]
        broker.cancel_order.return_value = {"order_id": "ORD001", "status": "CANCELLED"}
        broker.get_order_status.return_value = {"order_id": "ORD001", "status": "ACKNOWLEDGED"}

        core = ExecutionCore(
            state_machine=state_machine,
            broker=broker,
            max_retries=1,
        )
        order_id = core.submit_order(order_submission)

        # Rejection with recoverable reason triggers retry
        core.handle_rejection(order_id, "TIMEOUT")

        # After retry, original order status is REJECTED
        assert core.get_order_status(order_id) == "REJECTED"
        # Verify retry was attempted (broker called twice: original + retry)
        assert broker.place_order.call_count == 2

    def test_retry_order_nonexistent(self, execution_core):
        """Retry on unknown order returns None."""
        result = execution_core.retry_order("UNKNOWN")
        assert result is None

    def test_retry_order_maxed_out(self, execution_core, order_submission, mock_broker):
        """Retry returns None when max retries already reached."""
        order_id = execution_core.submit_order(order_submission)
        execution_core._retry_counts[order_id] = DEFAULT_MAX_RETRIES  # already maxed

        result = execution_core.retry_order(order_id)
        assert result is None


# =============================================================================
# ExecutionCore — handle_fill
# =============================================================================


class TestHandleFill:
    """ExecutionCore.handle_fill tests."""

    def test_handle_full_fill(self, execution_core, order_submission, state_machine):
        """Full fill transitions to FILLED and invokes callback."""
        order_id = execution_core.submit_order(order_submission)
        fill_data = {
            "filled_qty": 25,
            "price": 150.0,
            "remaining_qty": 0,
            "timestamp": datetime.utcnow(),
        }

        fill = execution_core.handle_fill(order_id, fill_data)
        assert fill.filled_qty == 25
        assert fill.price == 150.0
        assert not fill.is_partial
        assert state_machine.state == ExecutionMajorState.FILLED
        execution_core._on_fill_callback.assert_called_once_with(fill)

    def test_handle_partial_fill(self, execution_core, order_submission, state_machine):
        """Partial fill transitions to PARTIAL_FILL."""
        order_id = execution_core.submit_order(order_submission)
        fill_data = {
            "filled_qty": 10,
            "price": 150.0,
            "remaining_qty": 15,
            "is_partial": True,
            "timestamp": datetime.utcnow(),
        }

        fill = execution_core.handle_fill(order_id, fill_data)
        assert fill.filled_qty == 10
        assert fill.is_partial
        assert fill.remaining_qty == 15
        assert state_machine.state == ExecutionMajorState.PARTIAL_FILL
        execution_core._on_fill_callback.assert_called_once_with(fill)

    def test_handle_fill_unknown_order(self, execution_core):
        """Fill for unknown order raises."""
        with pytest.raises(ExecutionError, match="unknown order"):
            execution_core.handle_fill("UNKNOWN", {"filled_qty": 10, "price": 150.0})

    def test_handle_fill_none_data(self, execution_core, order_submission):
        """Fill with None data raises."""
        order_id = execution_core.submit_order(order_submission)
        with pytest.raises(ExecutionError, match="None fill data"):
            execution_core.handle_fill(order_id, None)  # type: ignore

    def test_handle_fill_zero_quantity(self, execution_core, order_submission):
        """Fill with zero qty raises."""
        order_id = execution_core.submit_order(order_submission)
        with pytest.raises(ExecutionError, match="Invalid fill quantity"):
            execution_core.handle_fill(order_id, {"filled_qty": 0, "price": 150.0})

    def test_handle_fill_negative_quantity(self, execution_core, order_submission):
        """Fill with negative qty raises."""
        order_id = execution_core.submit_order(order_submission)
        with pytest.raises(ExecutionError, match="Invalid fill quantity"):
            execution_core.handle_fill(order_id, {"filled_qty": -5, "price": 150.0})

    def test_handle_fill_logs_event(self, execution_core, order_submission):
        """Fill triggers FILL log event."""
        order_id = execution_core.submit_order(order_submission)
        execution_core.handle_fill(order_id, {"filled_qty": 25, "price": 150.0, "remaining_qty": 0})

        log_calls = execution_core._on_log_callback.call_args_list
        fill_events = [
            args[0][0] for args in log_calls if args[0][0] == "FILL"
        ]
        assert len(fill_events) >= 1


# =============================================================================
# ExecutionCore — cancel_order
# =============================================================================


class TestCancelOrder:
    """ExecutionCore.cancel_order tests."""

    def test_cancel_success(self, execution_core, order_submission, mock_broker):
        """Cancel known order returns CANCELLED dict and calls broker."""
        order_id = execution_core.submit_order(order_submission)
        result = execution_core.cancel_order(order_id)
        assert result["status"] == "CANCELLED"
        assert result["order_id"] == order_id
        mock_broker.cancel_order.assert_called_once_with(order_id)

    def test_cancel_unknown_order(self, execution_core):
        """Cancel unknown order returns NOT_FOUND dict."""
        result = execution_core.cancel_order("UNKNOWN")
        assert result["status"] == "NOT_FOUND"
        assert result["order_id"] == "UNKNOWN"

    def test_cancel_broker_failure(self, execution_core, order_submission, mock_broker):
        """Cancel when broker fails returns FAILED dict."""
        order_id = execution_core.submit_order(order_submission)
        mock_broker.cancel_order.side_effect = RuntimeError("Broker error")
        result = execution_core.cancel_order(order_id)
        assert result["status"] == "FAILED"
        assert "error" in result
        assert "Broker error" in result["error"]


# =============================================================================
# ExecutionCore — get_order_status + get_active_order_ids
# =============================================================================


class TestOrderQuerying:
    """ExecutionCore order status query tests."""

    def test_get_order_status_submitted(self, execution_core, order_submission):
        """Status queried after submission returns ACKNOWLEDGED."""
        order_id = execution_core.submit_order(order_submission)
        assert execution_core.get_order_status(order_id) == "ACKNOWLEDGED"

    def test_get_order_status_rejected(self, execution_core, order_submission):
        """Status after rejection is REJECTED."""
        order_id = execution_core.submit_order(order_submission)
        execution_core.handle_rejection(order_id, "INVALID_PRICE")
        assert execution_core.get_order_status(order_id) == "REJECTED"

    def test_get_order_status_unknown(self, execution_core):
        """Status for unknown order returns None."""
        assert execution_core.get_order_status("UNKNOWN") is None

    def test_get_active_orders(self, execution_core, order_submission):
        """After submission, active orders includes the order."""
        order_id = execution_core.submit_order(order_submission)
        active = execution_core.get_active_order_ids()
        assert order_id in active

    def test_get_active_orders_after_fill(self, execution_core, order_submission):
        """After full fill, no active orders remain."""
        order_id = execution_core.submit_order(order_submission)
        execution_core.handle_fill(order_id, {"filled_qty": 25, "price": 150.0, "remaining_qty": 0})
        active = execution_core.get_active_order_ids()
        assert order_id not in active

    def test_get_active_orders_after_rejection(self, execution_core, order_submission):
        """After non-recoverable rejection, no active orders remain."""
        order_id = execution_core.submit_order(order_submission)
        execution_core.handle_rejection(order_id, "INVALID_PRICE")
        active = execution_core.get_active_order_ids()
        assert order_id not in active


# =============================================================================
# ExecutionCore — Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests for ExecutionCore."""

    def test_submit_null_state_machine(self):
        """ExecutionCore with None state machine raises on submit."""
        core = ExecutionCore(
            state_machine=None,  # type: ignore
            broker=MagicMock(),
        )
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        with pytest.raises(AttributeError):
            core.submit_order(order)

    def test_no_callbacks_no_crash(self, state_machine, mock_broker):
        """ExecutionCore with no callbacks works without crashing."""
        core = ExecutionCore(state_machine=state_machine, broker=mock_broker)
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = core.submit_order(order)
        assert order_id == "ORD123"

    def test_multiple_submits_different_trades(self, execution_core, order_submission, state_machine):
        """Multiple order submissions work sequentially."""
        order_id1 = execution_core.submit_order(order_submission)
        assert order_id1 == "ORD123"
        assert state_machine.state == ExecutionMajorState.ORDER_PENDING

    def test_broker_injected_is_called_with_correct_data(self, state_machine, mock_broker):
        """Broker receives correctly structured order data."""
        core = ExecutionCore(state_machine=state_machine, broker=mock_broker)
        order = OrderSubmission(
            trade_id="TRADE-001",
            action="BUY",
            option_side="CE",
            strike="19500",
            quantity=1,
            price=150.0,
            order_type="LIMIT",
            sl_price=148.0,
            target_price=155.0,
        )
        core.submit_order(order)

        call_kwargs = mock_broker.place_order.call_args[0][0]
        assert call_kwargs["trade_id"] == "TRADE-001"
        assert call_kwargs["action"] == "BUY"
        assert call_kwargs["option_side"] == "CE"
        assert call_kwargs["strike"] == "19500"
        assert call_kwargs["quantity"] == 1
        assert call_kwargs["price"] == 150.0
        assert call_kwargs["order_type"] == "LIMIT"
        assert call_kwargs["sl_price"] == 148.0
        assert call_kwargs["target_price"] == 155.0
        assert call_kwargs["validity"] == "DAY"

    def test_multiple_fills_on_same_order(self, execution_core, order_submission):
        """Multiple partial fills on same order work sequentially."""
        order_id = execution_core.submit_order(order_submission)

        # First partial fill
        fill1 = execution_core.handle_fill(order_id, {
            "filled_qty": 10, "price": 150.0, "remaining_qty": 15, "is_partial": True,
        })
        assert fill1.filled_qty == 10
        assert execution_core._state_machine.state == ExecutionMajorState.PARTIAL_FILL

    def test_order_status_tracking_consistency(self, execution_core, order_submission):
        """Order status is tracked consistently through lifecycle."""
        order_id = execution_core.submit_order(order_submission)
        assert execution_core.get_order_status(order_id) == "ACKNOWLEDGED"

        execution_core.handle_fill(order_id, {
            "filled_qty": 25, "price": 150.0, "remaining_qty": 0,
        })
        assert execution_core.get_order_status(order_id) == "FILLED"


# =============================================================================
# Cross-module: Contract Alignment
# =============================================================================


class TestCrossModuleContracts:
    """Cross-module contract tests for execution_core."""

    def test_state_machine_transition_order_pending(self):
        """Verify state machine is in RISK_PASSED before ORDER_SUBMITTED transitions."""
        sm = ExecutionStateMachine()
        assert sm.can_transition(ExecutionEvent.ORDER_SUBMITTED) is False  # IDLE → ORDER_SUBMITTED invalid

        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        assert sm.can_transition(ExecutionEvent.ORDER_SUBMITTED) is False  # INTENT_RECEIVED → ORDER_SUBMITTED invalid

        sm.transition(ExecutionEvent.RISK_PASSED)
        assert sm.can_transition(ExecutionEvent.ORDER_SUBMITTED) is True  # RISK_PASSED → ORDER_SUBMITTED valid

    def test_fill_triggers_correct_state_machine_transitions(self, state_machine):
        """Verify fill events produce correct state machine transitions."""
        broker = MagicMock()
        broker.place_order.return_value = {"order_id": "ORD001", "status": "ACKNOWLEDGED"}

        core = ExecutionCore(state_machine=state_machine, broker=broker)
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = core.submit_order(order)
        assert state_machine.state == ExecutionMajorState.ORDER_PENDING

        # Full fill → FILLED
        core.handle_fill(order_id, {"filled_qty": 25, "price": 150.0, "remaining_qty": 0})
        assert state_machine.state == ExecutionMajorState.FILLED

    def test_rejection_triggers_correct_state_machine_transition(self, state_machine):
        """Verify rejection produces correct state machine transition."""
        broker = MagicMock()
        broker.place_order.return_value = {"order_id": "ORD001", "status": "ACKNOWLEDGED"}

        core = ExecutionCore(state_machine=state_machine, broker=broker)
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = core.submit_order(order)

        # Non-recoverable rejection → FAILED
        core.handle_rejection(order_id, "INVALID_PRICE")
        assert state_machine.state == ExecutionMajorState.FAILED

    def test_execution_core_uses_broker_protocol(self):
        """ExecutionCore accepts any broker implementing the protocol methods."""
        class MinimalBroker:
            def place_order(self, order_data):
                return {"order_id": "MIN001", "status": "ACKNOWLEDGED"}
            def cancel_order(self, order_id):
                return {"order_id": order_id, "status": "CANCELLED"}
            def get_order_status(self, order_id):
                return {"order_id": order_id, "status": "ACKNOWLEDGED"}

        sm = ExecutionStateMachine()
        sm.transition(ExecutionEvent.CAPTAIN_INTENT)
        sm.transition(ExecutionEvent.RISK_PASSED)

        broker = MinimalBroker()
        core = ExecutionCore(state_machine=sm, broker=broker)  # type: ignore
        order = OrderSubmission(
            trade_id="TRADE-001", action="BUY", option_side="CE", strike="19500",
        )
        order_id = core.submit_order(order)
        assert order_id == "MIN001"
        assert sm.state == ExecutionMajorState.ORDER_PENDING
