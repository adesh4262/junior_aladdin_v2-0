"""Tests for position_manager.py — Primary owner of open trade management state.

Covers:
- calculate_pnl / calculate_unrealized_pnl helpers
- TrailingStopState / BreakevenState dataclasses
- PositionManager: open_position, update_fill, set_sl, set_target,
  activate_trail, update_trail, activate_breakeven, check_breakeven,
  partial_exit, close_position, get_position, get_active_positions,
  get_exposure, get_pnl, get_consistency_view
- One-trade rule enforcement
- Edge cases: invalid params, missing trades, duplicate operations
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.position_manager import (
    DEFAULT_BREAKEVEN_TICKS,
    DEFAULT_TRAIL_DISTANCE_TICKS,
    NIFTY_TICK_SIZE,
    BreakevenState,
    PositionManager,
    TrailingStopState,
    calculate_pnl,
    calculate_unrealized_pnl,
)
from junior_aladdin.side_a_execution.side_a_types import PositionState


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def pm():
    """PositionManager with a mock log callback."""
    log_mock = MagicMock()
    manager = PositionManager(on_log_callback=log_mock)
    return manager


@pytest.fixture
def buy_position(pm):
    """Open a standard BUY position."""
    return pm.open_position(
        trade_id="TRADE-001",
        direction="BUY",
        filled_qty=25,
        price=150.0,
    )


@pytest.fixture
def sell_position(pm):
    """Open a standard SELL position."""
    return pm.open_position(
        trade_id="TRADE-002",
        direction="SELL",
        filled_qty=25,
        price=150.0,
    )


# =============================================================================
# P&L Helper Tests
# =============================================================================


class TestPnLHelpers:
    """calculate_pnl and calculate_unrealized_pnl tests."""

    def test_buy_profit(self):
        """BUY position profit calculation."""
        pnl = calculate_pnl("BUY", entry_price=150.0, exit_price=155.0, quantity=25)
        assert pnl == 125.0  # (155 - 150) * 25 * 1

    def test_buy_loss(self):
        """BUY position loss calculation."""
        pnl = calculate_pnl("BUY", entry_price=150.0, exit_price=148.0, quantity=25)
        assert pnl == -50.0  # (148 - 150) * 25 * 1

    def test_sell_profit(self):
        """SELL position profit calculation."""
        pnl = calculate_pnl("SELL", entry_price=150.0, exit_price=145.0, quantity=25)
        assert pnl == 125.0  # (145 - 150) * 25 * -1

    def test_sell_loss(self):
        """SELL position loss calculation."""
        pnl = calculate_pnl("SELL", entry_price=150.0, exit_price=155.0, quantity=25)
        assert pnl == -125.0  # (155 - 150) * 25 * -1

    def test_zero_quantity(self):
        """Zero quantity results in zero P&L."""
        pnl = calculate_pnl("BUY", entry_price=150.0, exit_price=155.0, quantity=0)
        assert pnl == 0.0

    def test_unrealized_buy(self):
        """Unrealised P&L for BUY."""
        pnl = calculate_unrealized_pnl("BUY", entry_price=150.0, current_price=155.0, quantity=25)
        assert pnl == 125.0

    def test_unrealized_sell(self):
        """Unrealised P&L for SELL."""
        pnl = calculate_unrealized_pnl("SELL", entry_price=150.0, current_price=145.0, quantity=25)
        assert pnl == 125.0


# =============================================================================
# Open Position
# =============================================================================


class TestOpenPosition:
    """PositionManager.open_position tests."""

    def test_open_buy(self, pm):
        """Open a BUY position successfully."""
        pos = pm.open_position(trade_id="TRADE-001", direction="BUY",
                                filled_qty=25, price=150.0)
        assert pos.trade_id == "TRADE-001"
        assert pos.direction == "BUY"
        assert pos.filled_qty == 25
        assert pos.avg_price == 150.0
        assert pos.status == "OPEN"

    def test_open_sell(self, pm):
        """Open a SELL position successfully."""
        pos = pm.open_position(trade_id="TRADE-001", direction="SELL",
                                filled_qty=10, price=200.0)
        assert pos.direction == "SELL"
        assert pos.filled_qty == 10
        assert pos.avg_price == 200.0

    def test_open_empty_trade_id(self, pm):
        """Opening with empty trade_id raises."""
        with pytest.raises(ExecutionError, match="without trade_id"):
            pm.open_position(trade_id="", direction="BUY", filled_qty=25, price=150.0)

    def test_open_invalid_direction(self, pm):
        """Opening with invalid direction raises."""
        with pytest.raises(ExecutionError, match="Invalid direction"):
            pm.open_position(trade_id="TRADE-001", direction="LONG",
                              filled_qty=25, price=150.0)

    def test_open_zero_qty(self, pm):
        """Opening with zero qty raises."""
        with pytest.raises(ExecutionError, match="Invalid filled_qty"):
            pm.open_position(trade_id="TRADE-001", direction="BUY",
                              filled_qty=0, price=150.0)

    def test_open_negative_qty(self, pm):
        """Opening with negative qty raises."""
        with pytest.raises(ExecutionError, match="Invalid filled_qty"):
            pm.open_position(trade_id="TRADE-001", direction="BUY",
                              filled_qty=-5, price=150.0)

    def test_open_zero_price(self, pm):
        """Opening with zero price raises."""
        with pytest.raises(ExecutionError, match="Invalid price"):
            pm.open_position(trade_id="TRADE-001", direction="BUY",
                              filled_qty=25, price=0.0)

    def test_open_duplicate_trade_id(self, pm, buy_position):
        """Opening a position for an existing trade_id raises."""
        with pytest.raises(ExecutionError, match="Position already exists"):
            pm.open_position(trade_id="TRADE-001", direction="BUY",
                              filled_qty=10, price=155.0)

    def test_one_trade_rule(self, pm, buy_position):
        """Opening a second position while one is active raises."""
        with pytest.raises(ExecutionError, match="one active trade already exists"):
            pm.open_position(trade_id="TRADE-002", direction="SELL",
                              filled_qty=10, price=145.0)

    def test_open_allows_after_close(self, pm, buy_position):
        """Opening a new position after closing the previous one is allowed."""
        pm.close_position("TRADE-001", close_qty=25, close_price=155.0)
        pos2 = pm.open_position(trade_id="TRADE-002", direction="SELL",
                                 filled_qty=10, price=145.0)
        assert pos2.trade_id == "TRADE-002"
        assert pos2.status == "OPEN"


# =============================================================================
# Update Fill
# =============================================================================


class TestUpdateFill:
    """PositionManager.update_fill tests."""

    def test_update_fill(self, pm, buy_position):
        """Update fill with additional quantity."""
        pos = pm.update_fill("TRADE-001", additional_qty=10, price=155.0)
        assert pos.filled_qty == 35  # 25 + 10
        assert pos.avg_price == (25 * 150.0 + 10 * 155.0) / 35

    def test_update_fill_zero_additional(self, pm, buy_position):
        """Update fill with zero additional quantity is a no-op."""
        pos = pm.update_fill("TRADE-001", additional_qty=0, price=155.0)
        assert pos.filled_qty == 25  # unchanged
        assert pos.avg_price == 150.0  # unchanged

    def test_update_fill_weighted_average(self, pm):
        """Update fill correctly computes weighted average price."""
        pm.open_position(trade_id="TRADE-003", direction="BUY",
                          filled_qty=10, price=100.0)
        # Add 5 more at 110
        pos = pm.update_fill("TRADE-003", additional_qty=5, price=110.0)
        assert pos.filled_qty == 15
        # Weighted avg = (10*100 + 5*110) / 15 = (1000 + 550) / 15 = 1550/15 = 103.33
        assert round(pos.avg_price, 2) == 103.33

    def test_update_fill_unknown_trade(self, pm):
        """Update fill for unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.update_fill("UNKNOWN", additional_qty=10, price=150.0)

    def test_update_fill_negative_qty(self, pm, buy_position):
        """Update fill with negative qty raises."""
        with pytest.raises(ExecutionError, match="Invalid additional quantity"):
            pm.update_fill("TRADE-001", additional_qty=-5, price=150.0)


# =============================================================================
# SL / Target
# =============================================================================


class TestSLTarget:
    """set_sl and set_target tests."""

    def test_set_sl(self, pm, buy_position):
        """Set stop-loss price."""
        pos = pm.set_sl("TRADE-001", 148.0)
        assert pos.sl_price == 148.0

    def test_set_sl_unknown_trade(self, pm):
        """Set SL for unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.set_sl("UNKNOWN", 148.0)

    def test_set_sl_zero_price(self, pm, buy_position):
        """Set SL with zero price raises."""
        with pytest.raises(ExecutionError, match="Invalid SL price"):
            pm.set_sl("TRADE-001", 0.0)

    def test_set_sl_negative_price(self, pm, buy_position):
        """Set SL with negative price raises."""
        with pytest.raises(ExecutionError, match="Invalid SL price"):
            pm.set_sl("TRADE-001", -5.0)

    def test_set_target(self, pm, buy_position):
        """Set target price."""
        pos = pm.set_target("TRADE-001", 155.0)
        assert pos.target_price == 155.0

    def test_set_target_unknown_trade(self, pm):
        """Set target for unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.set_target("UNKNOWN", 155.0)

    def test_set_target_zero_price(self, pm, buy_position):
        """Set target with zero price raises."""
        with pytest.raises(ExecutionError, match="Invalid target price"):
            pm.set_target("TRADE-001", 0.0)

    def test_update_sl(self, pm, buy_position):
        """Update SL price multiple times."""
        pm.set_sl("TRADE-001", 148.0)
        pos = pm.set_sl("TRADE-001", 149.0)
        assert pos.sl_price == 149.0


# =============================================================================
# Trailing Stop
# =============================================================================


class TestTrailingStop:
    """Activate and update trailing stop tests."""

    def test_activate_trail_buy(self, pm, buy_position):
        """Activate trailing stop for BUY position."""
        trail = pm.activate_trail("TRADE-001", activation_price=152.0,
                                   trail_distance_ticks=10)
        assert trail.activation_price == 152.0
        assert trail.trail_distance_ticks == 10
        assert not trail.is_active  # Not yet active until price hits activation
        expected_stop = 152.0 - (10 * NIFTY_TICK_SIZE)  # 152.0 - 0.5 = 151.5
        assert trail.current_stop_price == expected_stop

    def test_activate_trail_sell(self, pm, sell_position):
        """Activate trailing stop for SELL position."""
        trail = pm.activate_trail("TRADE-002", activation_price=148.0,
                                   trail_distance_ticks=10)
        expected_stop = 148.0 + (10 * NIFTY_TICK_SIZE)  # 148.0 + 0.5 = 148.5
        assert trail.current_stop_price == expected_stop

    def test_activate_trail_unknown_trade(self, pm):
        """Activate trail for unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.activate_trail("UNKNOWN", activation_price=152.0)

    def test_activate_trail_invalid_distance(self, pm, buy_position):
        """Activate trail with invalid distance raises."""
        with pytest.raises(ExecutionError, match="Invalid trail distance"):
            pm.activate_trail("TRADE-001", activation_price=152.0,
                               trail_distance_ticks=0)

    def test_activate_trail_duplicate(self, pm, buy_position):
        """Activate trail twice on same trade raises."""
        pm.activate_trail("TRADE-001", activation_price=152.0)
        with pytest.raises(ExecutionError, match="already configured"):
            pm.activate_trail("TRADE-001", activation_price=153.0)

    def test_update_trail_no_activation_yet(self, pm, buy_position):
        """Update trail before activation price doesn't activate."""
        pm.activate_trail("TRADE-001", activation_price=152.0)
        trail = pm.update_trail("TRADE-001", current_market_price=151.0)
        assert not trail.is_active

    def test_update_trail_activates(self, pm, buy_position):
        """Update trail at or above activation price activates."""
        pm.activate_trail("TRADE-001", activation_price=152.0)
        trail = pm.update_trail("TRADE-001", current_market_price=152.5)
        assert trail.is_active

    def test_update_trail_moves_stop_up(self, pm, buy_position):
        """Trail stop moves up as price increases (BUY)."""
        pm.activate_trail("TRADE-001", activation_price=152.0,
                           trail_distance_ticks=10)
        # Activate it
        pm.update_trail("TRADE-001", current_market_price=152.5)
        trail = pm.update_trail("TRADE-001", current_market_price=155.0)

        expected_stop = 155.0 - (10 * NIFTY_TICK_SIZE)  # 155.0 - 0.5 = 154.5
        assert trail.current_stop_price == expected_stop
        assert trail.is_active

    def test_update_trail_no_trail_exists(self, pm):
        """Update trail for position without trail returns None."""
        result = pm.update_trail("TRADE-001", current_market_price=150.0)
        assert result is None

    def test_trail_syncs_sl_on_position(self, pm, buy_position):
        """Active trailing stop syncs SL price on position."""
        pm.activate_trail("TRADE-001", activation_price=152.0,
                           trail_distance_ticks=10)
        pm.update_trail("TRADE-001", current_market_price=155.0)
        pos = pm.get_position("TRADE-001")
        expected_sl = 155.0 - (10 * NIFTY_TICK_SIZE)
        assert pos.sl_price == expected_sl


# =============================================================================
# Breakeven
# =============================================================================


class TestBreakeven:
    """Breakeven activation tests."""

    def test_activate_breakeven(self, pm, buy_position):
        """Activate breakeven protection."""
        be = pm.activate_breakeven("TRADE-001", activation_ticks=15)
        assert be.activation_ticks == 15
        assert not be.is_active  # Not yet triggered

    def test_activate_breakeven_unknown_trade(self, pm):
        """Activate breakeven for unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.activate_breakeven("UNKNOWN")

    def test_activate_breakeven_invalid_ticks(self, pm, buy_position):
        """Activate breakeven with invalid ticks raises."""
        with pytest.raises(ExecutionError, match="Invalid activation ticks"):
            pm.activate_breakeven("TRADE-001", activation_ticks=0)

    def test_activate_breakeven_duplicate(self, pm, buy_position):
        """Activate breakeven twice raises."""
        pm.activate_breakeven("TRADE-001")
        with pytest.raises(ExecutionError, match="already configured"):
            pm.activate_breakeven("TRADE-001")

    def test_check_breakeven_not_triggered(self, pm, buy_position):
        """Check breakeven before profit threshold returns False."""
        pm.activate_breakeven("TRADE-001", activation_ticks=15)
        # 150.0 + (15 * 0.05) = 150.75 needed. Price at 150.5 is not enough.
        result = pm.check_breakeven("TRADE-001", current_market_price=150.5)
        assert result is False

    def test_check_breakeven_triggers(self, pm, buy_position):
        """Check breakeven at profit threshold returns True and moves SL."""
        pm.activate_breakeven("TRADE-001", activation_ticks=15)
        # 150.0 + (15 * 0.05) = 150.75. Price at 151.0 exceeds threshold.
        result = pm.check_breakeven("TRADE-001", current_market_price=151.0)
        assert result is True
        pos = pm.get_position("TRADE-001")
        assert pos.sl_price == 150.0  # SL moved to entry price
        assert pos.breakeven_activated is True

    def test_check_breakeven_no_breakeven_configured(self, pm, buy_position):
        """Check breakeven without activation returns False."""
        result = pm.check_breakeven("TRADE-001", current_market_price=200.0)
        assert result is False

    def test_check_breakeven_already_active(self, pm, buy_position):
        """Check breakeven when already active returns False."""
        pm.activate_breakeven("TRADE-001", activation_ticks=15)
        pm.check_breakeven("TRADE-001", current_market_price=151.0)
        # Second call should return False since already active
        result = pm.check_breakeven("TRADE-001", current_market_price=160.0)
        assert result is False


# =============================================================================
# Partial Exit
# =============================================================================


class TestPartialExit:
    """Partial position exit tests."""

    def test_partial_exit_buy(self, pm, buy_position):
        """Partial exit of BUY position."""
        pos = pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        assert pos.filled_qty == 15  # 25 - 10
        assert pos.partial_exit_qty == 10
        assert pos.status == "PARTIALLY_CLOSED"
        # P&L = (155 - 150) * 10 * 1 = 50
        assert pos.pnl == 50.0

    def test_partial_exit_sell(self, pm, sell_position):
        """Partial exit of SELL position."""
        pos = pm.partial_exit("TRADE-002", exit_qty=10, exit_price=145.0)
        assert pos.filled_qty == 15
        # P&L = (145 - 150) * 10 * -1 = 50
        assert pos.pnl == 50.0

    def test_partial_exit_unknown_trade(self, pm):
        """Partial exit of unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.partial_exit("UNKNOWN", exit_qty=10, exit_price=155.0)

    def test_partial_exit_invalid_qty(self, pm, buy_position):
        """Partial exit with invalid qty raises."""
        with pytest.raises(ExecutionError, match="Invalid exit quantity"):
            pm.partial_exit("TRADE-001", exit_qty=0, exit_price=155.0)

    def test_partial_exit_invalid_price(self, pm, buy_position):
        """Partial exit with invalid price raises."""
        with pytest.raises(ExecutionError, match="Invalid exit price"):
            pm.partial_exit("TRADE-001", exit_qty=10, exit_price=0.0)

    def test_partial_exit_exceeds_position(self, pm, buy_position):
        """Partial exit with qty exceeding position raises."""
        with pytest.raises(ExecutionError, match="exceeds position"):
            pm.partial_exit("TRADE-001", exit_qty=100, exit_price=155.0)

    def test_multiple_partial_exits(self, pm, buy_position):
        """Multiple partial exits accumulate P&L."""
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        pos = pm.partial_exit("TRADE-001", exit_qty=10, exit_price=152.0)
        assert pos.filled_qty == 5  # 25 - 10 - 10
        # P&L = (155-150)*10*1 + (152-150)*10*1 = 50 + 20 = 70
        assert pos.pnl == 70.0

    def test_partial_exit_preserves_avg_price(self, pm, buy_position):
        """Partial exit preserves original average price."""
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        pos = pm.get_position("TRADE-001")
        assert pos.avg_price == 150.0  # Unchanged


# =============================================================================
# Close Position
# =============================================================================


class TestClosePosition:
    """Position close tests."""

    def test_close_full_buy(self, pm, buy_position):
        """Close full BUY position."""
        pos = pm.close_position("TRADE-001", close_qty=25, close_price=155.0)
        assert pos.status == "CLOSED"
        assert pos.filled_qty == 0
        assert pos.pnl == 125.0  # (155-150)*25*1

    def test_close_full_sell(self, pm, sell_position):
        """Close full SELL position."""
        pos = pm.close_position("TRADE-002", close_qty=25, close_price=145.0)
        assert pos.status == "CLOSED"
        assert pos.pnl == 125.0  # (145-150)*25*-1

    def test_close_remaining_after_partial(self, pm, buy_position):
        """Close remaining position after partial exit."""
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        pos = pm.close_position("TRADE-001", close_qty=15, close_price=152.0)
        assert pos.status == "CLOSED"
        assert pos.filled_qty == 0
        # Total P&L = partial(50) + close(30) = 80
        assert pos.pnl == 80.0

    def test_close_default_qty(self, pm, buy_position):
        """Close with default qty (None) closes entire position."""
        pos = pm.close_position("TRADE-001", close_price=155.0)
        assert pos.status == "CLOSED"
        assert pos.filled_qty == 0

    def test_close_unknown_trade(self, pm):
        """Close unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.close_position("UNKNOWN", close_qty=10, close_price=155.0)

    def test_close_invalid_price(self, pm, buy_position):
        """Close with invalid price raises."""
        with pytest.raises(ExecutionError, match="Invalid close price"):
            pm.close_position("TRADE-001", close_qty=25, close_price=0.0)

    def test_close_exceeds_position(self, pm, buy_position):
        """Close with qty exceeding position raises."""
        with pytest.raises(ExecutionError, match="exceeds remaining"):
            pm.close_position("TRADE-001", close_qty=100, close_price=155.0)

    def test_close_cleans_up_trail(self, pm, buy_position):
        """Close cleans up trailing stop tracking."""
        pm.activate_trail("TRADE-001", activation_price=152.0)
        pm.update_trail("TRADE-001", current_market_price=155.0)
        pm.close_position("TRADE-001", close_qty=25, close_price=155.0)

        # After close, trail data should be cleaned up
        assert pm._trailing_stops.get("TRADE-001") is None
        assert pm._breakeven_states.get("TRADE-001") is None

    def test_close_cleans_up_breakeven(self, pm, buy_position):
        """Close cleans up breakeven tracking."""
        pm.activate_breakeven("TRADE-001")
        pm.check_breakeven("TRADE-001", current_market_price=151.0)
        pm.close_position("TRADE-001", close_qty=25, close_price=155.0)
        assert pm._breakeven_states.get("TRADE-001") is None


# =============================================================================
# Position Querying
# =============================================================================


class TestPositionQuerying:
    """Position retrieval tests."""

    def test_get_position_found(self, pm, buy_position):
        """get_position returns the position when found."""
        pos = pm.get_position("TRADE-001")
        assert pos is not None
        assert pos.trade_id == "TRADE-001"

    def test_get_position_not_found(self, pm):
        """get_position returns None when not found."""
        assert pm.get_position("UNKNOWN") is None

    def test_get_active_positions_single(self, pm, buy_position):
        """One active position."""
        active = pm.get_active_positions()
        assert len(active) == 1
        assert active[0].trade_id == "TRADE-001"

    def test_get_active_positions_after_close(self, pm, buy_position):
        """No active positions after close."""
        pm.close_position("TRADE-001", close_qty=25, close_price=155.0)
        active = pm.get_active_positions()
        assert len(active) == 0

    def test_get_active_positions_partial(self, pm, buy_position):
        """Partially closed position is still active."""
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        active = pm.get_active_positions()
        assert len(active) == 1
        assert active[0].status == "PARTIALLY_CLOSED"


# =============================================================================
# Exposure and P&L
# =============================================================================


class TestExposurePnL:
    """Exposure and P&L query tests."""

    def test_get_exposure(self, pm, buy_position):
        """Exposure = filled_qty * avg_price."""
        exposure = pm.get_exposure()
        assert exposure == 25 * 150.0

    def test_get_exposure_no_positions(self, pm):
        """Exposure with no positions is 0."""
        assert pm.get_exposure() == 0.0

    def test_get_pnl_found(self, pm, buy_position):
        """get_pnl returns 0 for new position."""
        pnl = pm.get_pnl("TRADE-001")
        assert pnl == 0.0

    def test_get_pnl_not_found(self, pm):
        """get_pnl returns None for unknown trade."""
        assert pm.get_pnl("UNKNOWN") is None

    def test_get_pnl_after_exit(self, pm, buy_position):
        """get_pnl reflects partial exit P&L."""
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        assert pm.get_pnl("TRADE-001") == 50.0

    def test_update_unrealized_pnl(self, pm, buy_position):
        """Update unrealised P&L."""
        pnl = pm.update_unrealized_pnl("TRADE-001", current_price=155.0)
        assert pnl == 125.0  # (155-150) * 25 = 125

    def test_update_unrealized_pnl_delta_only(self, pm, buy_position):
        """Unrealised P&L uses delta — calling twice with same price doesn't double-count."""
        pm.update_unrealized_pnl("TRADE-001", current_price=155.0)  # adds 125
        pnl = pm.update_unrealized_pnl("TRADE-001", current_price=155.0)  # delta = 0
        assert pnl == 125.0  # Still 125, not 250

    def test_update_unrealized_pnl_changing_price(self, pm, buy_position):
        """Unrealised P&L adjusts correctly when price changes."""
        pm.update_unrealized_pnl("TRADE-001", current_price=155.0)  # adds 125
        pnl = pm.update_unrealized_pnl("TRADE-001", current_price=160.0)  # adds another 125 (delta)
        assert pnl == 250.0  # 125 + (160-155)*25 = 125 + 125 = 250

    def test_update_unrealized_pnl_with_partial_exit(self, pm, buy_position):
        """Unrealised P&L stacks with realised from partial exits."""
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)  # +50 realised
        pnl = pm.update_unrealized_pnl("TRADE-001", current_price=152.0)
        # Realised: 50. Unrealised on remaining 15: (152-150)*15 = 30. Total: 80
        assert pnl == 80.0

    def test_update_unrealized_pnl_unknown(self, pm):
        """Update unrealised P&L for unknown trade raises."""
        with pytest.raises(ExecutionError, match="unknown trade"):
            pm.update_unrealized_pnl("UNKNOWN", current_price=155.0)

    def test_get_position_count(self, pm, buy_position):
        """get_position_count returns total tracked positions."""
        assert pm.get_position_count() == 1


# =============================================================================
# Consistency View
# =============================================================================


class TestConsistencyView:
    """Position consistency view tests."""

    def test_consistency_view_basic(self, pm, buy_position):
        """Basic consistency view includes position fields."""
        view = pm.get_consistency_view("TRADE-001")
        assert view["found"] is True
        assert view["trade_id"] == "TRADE-001"
        assert view["position"]["direction"] == "BUY"
        assert view["position"]["filled_qty"] == 25
        assert view["position"]["avg_price"] == 150.0

    def test_consistency_view_not_found(self, pm):
        """Consistency view for unknown trade returns found=False."""
        view = pm.get_consistency_view("UNKNOWN")
        assert view["found"] is False

    def test_consistency_view_with_sl_target(self, pm, buy_position):
        """Consistency view includes SL and target."""
        pm.set_sl("TRADE-001", 148.0)
        pm.set_target("TRADE-001", 155.0)
        view = pm.get_consistency_view("TRADE-001")
        assert view["position"]["sl_price"] == 148.0
        assert view["position"]["target_price"] == 155.0

    def test_consistency_view_with_trail(self, pm, buy_position):
        """Consistency view includes trailing stop state when active."""
        pm.activate_trail("TRADE-001", activation_price=152.0)
        pm.update_trail("TRADE-001", current_market_price=155.0)
        view = pm.get_consistency_view("TRADE-001")
        assert "trailing_stop" in view
        assert view["trailing_stop"]["current_stop_price"] > 0

    def test_consistency_view_with_breakeven(self, pm, buy_position):
        """Consistency view includes breakeven state when active."""
        pm.activate_breakeven("TRADE-001", activation_ticks=15)
        pm.check_breakeven("TRADE-001", current_market_price=151.0)
        view = pm.get_consistency_view("TRADE-001")
        assert "breakeven" in view
        assert view["breakeven"]["activated_at_price"] == 150.0


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases for PositionManager."""

    def test_no_log_callback(self):
        """PositionManager works without a log callback."""
        pm = PositionManager()
        pos = pm.open_position(trade_id="TRADE-001", direction="BUY",
                                filled_qty=25, price=150.0)
        assert pos.filled_qty == 25

    def test_logging_on_all_actions(self, pm, buy_position):
        """All major actions trigger log events."""
        count_before = pm._on_log_callback.call_count

        pm.set_sl("TRADE-001", 148.0)
        pm.set_target("TRADE-001", 155.0)
        pm.partial_exit("TRADE-001", exit_qty=10, exit_price=155.0)
        pm.close_position("TRADE-001", close_qty=15, close_price=152.0)

        # Should have logged at least POSITION_OPENED, SL_SET, TARGET_SET,
        # PARTIAL_EXIT, POSITION_CLOSED
        assert pm._on_log_callback.call_count > count_before
