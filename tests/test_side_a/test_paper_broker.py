"""Tests for paper_broker.py — PaperBroker realistic simulator."""

from __future__ import annotations

import pytest

from junior_aladdin.side_a_execution.paper_broker import (
    PaperBroker,
    PaperPosition,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_SLIPPAGE_MIN,
    DEFAULT_SLIPPAGE_MAX,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def broker() -> PaperBroker:
    """PaperBroker with zero rejection rate for deterministic tests."""
    return PaperBroker(
        random_seed=42,
        auto_fill=False,
        rejection_rate=0.0,
    )


@pytest.fixture
def auto_broker() -> PaperBroker:
    """PaperBroker with auto_fill and zero rejection."""
    return PaperBroker(
        random_seed=42,
        auto_fill=True,
        rejection_rate=0.0,
    )


@pytest.fixture
def order_data() -> dict:
    """Standard order data for testing."""
    return {
        "trade_id": "T001",
        "action": "BUY",
        "option_side": "CE",
        "strike": "18500",
        "quantity": 1,
        "price": 150.0,
        "order_type": "LIMIT",
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInit:
    """Verify PaperBroker initialisation."""

    def test_default_initialization(self):
        """Default params create broker with standard values."""
        b = PaperBroker()
        assert b.balance == DEFAULT_INITIAL_CAPITAL
        assert b.total_brokerage == 0.0
        assert b.total_slippage == 0.0
        assert b.positions == {}

    def test_custom_initial_capital(self):
        """Custom initial capital is used."""
        b = PaperBroker(initial_capital=1_000_000.0)
        assert b.balance == 1_000_000.0

    def test_seed_gives_deterministic_results(self):
        """Same seed gives same results."""
        b1 = PaperBroker(random_seed=123)
        b2 = PaperBroker(random_seed=123)
        r1 = b1.place_order({"trade_id": "T1", "quantity": 1, "price": 100.0})
        r2 = b2.place_order({"trade_id": "T1", "quantity": 1, "price": 100.0})
        assert r1["status"] == r2["status"]


# =============================================================================
# Place Order Tests
# =============================================================================


class TestPlaceOrder:
    """Verify order placement behaviour."""

    def test_acknowledges_order(self, broker: PaperBroker, order_data: dict):
        """Order is acknowledged with order_id."""
        result = broker.place_order(order_data)
        assert "order_id" in result
        assert result["status"] == "ACKNOWLEDGED"

    def test_order_id_format(self, broker: PaperBroker, order_data: dict):
        """Order ID has expected format."""
        result = broker.place_order(order_data)
        assert result["order_id"].startswith("ORD_")

    def test_tracks_order(self, broker: PaperBroker, order_data: dict):
        """Order is tracked internally."""
        result = broker.place_order(order_data)
        status = broker.get_order_status(result["order_id"])
        assert status["status"] == "ACKNOWLEDGED"

    def test_auto_fill_fills_immediately(self, auto_broker: PaperBroker, order_data: dict):
        """Auto-fill returns fill data instead of ack."""
        result = auto_broker.place_order(order_data)
        assert result["status"] in ("FILLED", "PARTIAL_FILL")

    def test_sell_order_acknowledged(self, broker: PaperBroker):
        """SELL orders are also acknowledged."""
        data = {"trade_id": "T1", "action": "SELL", "quantity": 1, "price": 150.0}
        result = broker.place_order(data)
        assert result["status"] == "ACKNOWLEDGED"


# =============================================================================
# Cancel Order Tests
# =============================================================================


class TestCancelOrder:
    """Verify order cancellation."""

    def test_cancel_existing_order(self, broker: PaperBroker, order_data: dict):
        """Cancel an existing order returns CANCELLED."""
        placed = broker.place_order(order_data)
        result = broker.cancel_order(placed["order_id"])
        assert result["status"] == "CANCELLED"

    def test_cancel_nonexistent_order(self, broker: PaperBroker):
        """Cancel non-existent order returns NOT_FOUND."""
        result = broker.cancel_order("NONEXISTENT")
        assert result["status"] == "NOT_FOUND"

    def test_cancelled_order_status(self, broker: PaperBroker, order_data: dict):
        """Cancelled order shows CANCELLED in status."""
        placed = broker.place_order(order_data)
        broker.cancel_order(placed["order_id"])
        status = broker.get_order_status(placed["order_id"])
        assert status["status"] == "CANCELLED"


# =============================================================================
# Order Status Tests
# =============================================================================


class TestGetOrderStatus:
    """Verify order status queries."""

    def test_unknown_order(self, broker: PaperBroker):
        """Unknown order returns NOT_FOUND."""
        result = broker.get_order_status("UNKNOWN")
        assert result["status"] == "NOT_FOUND"

    def test_acknowledged_status(self, broker: PaperBroker, order_data: dict):
        """Acknowledged order has correct status."""
        placed = broker.place_order(order_data)
        status = broker.get_order_status(placed["order_id"])
        assert status["status"] == "ACKNOWLEDGED"

    def test_timestamp_present(self, broker: PaperBroker, order_data: dict):
        """Status response includes timestamp."""
        placed = broker.place_order(order_data)
        status = broker.get_order_status(placed["order_id"])
        assert "timestamp" in status


# =============================================================================
# Simulate Fill Tests
# =============================================================================


class TestSimulateFill:
    """Verify fill simulation."""

    def test_fill_acknowledged_order(self, broker: PaperBroker, order_data: dict):
        """Filling an acknowledged order returns fill data."""
        placed = broker.place_order(order_data)
        fill = broker.simulate_fill(placed["order_id"])
        assert fill["status"] in ("FILLED", "PARTIAL_FILL")
        assert fill["filled_qty"] > 0
        assert fill["price"] > 0

    def test_fill_unknown_order(self, broker: PaperBroker):
        """Filling unknown order returns NOT_FOUND."""
        fill = broker.simulate_fill("UNKNOWN")
        assert fill["status"] == "NOT_FOUND"

    def test_fill_applies_slippage(self, broker: PaperBroker, order_data: dict):
        """Fill price differs from base price due to slippage."""
        placed = broker.place_order(order_data)
        fill = broker.simulate_fill(placed["order_id"])
        # BUY slippage = price goes up
        assert fill["price"] > order_data["price"]

    def test_force_full_fill(self, broker: PaperBroker, order_data: dict):
        """Force full fill fills requested qty completely."""
        placed = broker.place_order(order_data)
        fill = broker.simulate_fill(placed["order_id"], force_full=True)
        assert fill["remaining_qty"] == 0
        assert fill["is_partial"] is False

    def test_force_price(self, broker: PaperBroker, order_data: dict):
        """Force price overrides simulated price."""
        placed = broker.place_order(order_data)
        fill = broker.simulate_fill(placed["order_id"], force_price=155.0)
        assert abs(fill["price"] - 155.0) < 0.5  # Close to forced price

    def test_fill_creates_position(self, broker: PaperBroker, order_data: dict):
        """Fill creates a PaperPosition."""
        placed = broker.place_order(order_data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        assert "T001" in broker.positions
        assert broker.positions["T001"].status == "OPEN"

    def test_sell_fill_applies_slippage_down(self, broker: PaperBroker):
        """SELL fill price goes down due to slippage."""
        data = {"trade_id": "T1", "action": "SELL", "quantity": 1, "price": 200.0}
        placed = broker.place_order(data)
        fill = broker.simulate_fill(placed["order_id"])
        assert fill["price"] < data["price"]  # SELL slippage = price down

    def test_fill_deducts_balance(self, broker: PaperBroker, order_data: dict):
        """BUY fill deducts cost from balance."""
        initial = broker.balance
        placed = broker.place_order(order_data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        assert broker.balance < initial


# =============================================================================
# Settle Position Tests
# =============================================================================


class TestSettlePosition:
    """Verify position settlement."""

    def test_settle_buy_position_adds_pnl(self, broker: PaperBroker, order_data: dict):
        """Settling a winning BUY position adds P&L."""
        placed = broker.place_order(order_data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        # Use exit price well above entry to cover brokerage (₹20/lot)
        result = broker.settle_position("T001", exit_price=200.0)
        assert result["pnl"] > 0
        assert result["trade_id"] == "T001"

    def test_settle_sell_position(self, broker: PaperBroker):
        """Settling a winning SELL position adds P&L."""
        data = {"trade_id": "T1", "action": "SELL", "quantity": 1, "price": 200.0}
        placed = broker.place_order(data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        # Buy back at a price well below entry to cover brokerage (₹20/lot)
        result = broker.settle_position("T1", exit_price=150.0)
        assert result["pnl"] > 0  # Sold at ~200, bought back at 150

    def test_settle_unknown_position(self, broker: PaperBroker):
        """Settling unknown position returns error."""
        result = broker.settle_position("UNKNOWN", 100.0)
        assert "error" in result

    def test_settle_marks_position_closed(self, broker: PaperBroker, order_data: dict):
        """Settling marks position as CLOSED."""
        placed = broker.place_order(order_data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        broker.settle_position("T001", 155.0)
        assert broker.positions["T001"].status == "CLOSED"


# =============================================================================
# Account Management Tests
# =============================================================================


class TestAccountManagement:
    """Verify account management."""

    def test_account_summary_initial(self, broker: PaperBroker):
        """Initial account summary has expected values."""
        summary = broker.get_account_summary()
        assert summary["balance"] == DEFAULT_INITIAL_CAPITAL
        assert summary["active_positions"] == 0
        assert summary["closed_positions"] == 0

    def test_account_summary_after_trade(self, broker: PaperBroker, order_data: dict):
        """Account summary reflects trades."""
        placed = broker.place_order(order_data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        broker.settle_position("T001", 155.0)
        summary = broker.get_account_summary()
        assert summary["active_positions"] == 0
        assert summary["closed_positions"] == 1

    def test_reset_account(self, broker: PaperBroker, order_data: dict):
        """Reset restores initial state."""
        placed = broker.place_order(order_data)
        broker.simulate_fill(placed["order_id"], force_full=True)
        balance_before = broker.balance
        broker.reset_account()
        assert broker.balance == DEFAULT_INITIAL_CAPITAL
        assert broker.total_brokerage == 0.0
        assert broker.positions == {}


# =============================================================================
# Configuration Tests
# =============================================================================


class TestConfiguration:
    """Verify configurable realism factors."""

    def test_zero_slippage_gives_exact_price(self):
        """Zero slippage and zero spread means fill at base price."""
        b = PaperBroker(
            slippage_min=0.0, slippage_max=0.0,
            spread_fraction=0.0,
            rejection_rate=0.0,
            random_seed=42,
        )
        result = b.place_order({"trade_id": "T1", "action": "BUY", "quantity": 1, "price": 100.0})
        fill = b.simulate_fill(result["order_id"], force_full=True)
        assert abs(fill["price"] - 100.0) < 0.01

    def test_zero_rejection_rate(self):
        """Zero rejection means every order is acknowledged."""
        b = PaperBroker(rejection_rate=0.0, random_seed=42)
        for i in range(10):
            result = b.place_order({"trade_id": f"T{i}", "quantity": 1, "price": 100.0})
            assert result["status"] == "ACKNOWLEDGED"

    def test_100_rejection_rate(self):
        """100% rejection means every order is rejected."""
        b = PaperBroker(rejection_rate=1.0, random_seed=42)
        result = b.place_order({"trade_id": "T1", "quantity": 1, "price": 100.0})
        assert result["status"] == "REJECTED"

    def test_zero_partial_fill_rate(self):
        """Zero partial fill means every fill is full."""
        b = PaperBroker(
            partial_fill_rate=0.0,
            rejection_rate=0.0,
            random_seed=42,
            auto_fill=True,
        )
        result = b.place_order({"trade_id": "T1", "quantity": 1, "price": 100.0})
        assert result["status"] == "FILLED"
