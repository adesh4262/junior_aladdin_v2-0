"""Tests for protection_model.py — Entry fill → immediate SL/TGT staging.

Covers:
- Default SL/TGT price calculation (_calculate_default_sl,
  _calculate_default_target)
- stage_protection: from position sl/target, from offsets, validation
- adjust_for_partial_fill: quantity sync via OLM
- adjust_for_reconcile: price/qty mismatch resolution
- get_protection_status: full status dict
- is_protected: quick check
- Edge cases: None position, missing prices, zero quantity, duplicate staging,
  OLM integration verification
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    OrderLifecycleManager,
    SLTGTLinkage,
)
from junior_aladdin.side_a_execution.position_manager import PositionManager
from junior_aladdin.side_a_execution.protection_model import (
    DEFAULT_SL_OFFSET_TICKS,
    DEFAULT_TARGET_OFFSET_TICKS,
    NIFTY_TICK_SIZE,
    ProtectionModel,
)
from junior_aladdin.side_a_execution.side_a_types import (
    OrderRecord,
    OrderState,
    PositionState,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def olm():
    """OLM with mock log callback."""
    return OrderLifecycleManager(on_log_callback=MagicMock())


@pytest.fixture
def pm():
    """PM with mock log callback."""
    return PositionManager(on_log_callback=MagicMock())


@pytest.fixture
def prot_model(olm, pm):
    """ProtectionModel wired to real OLM and PM."""
    return ProtectionModel(
        order_lifecycle_manager=olm,
        position_manager=pm,
        on_log_callback=MagicMock(),
    )


@pytest.fixture
def buy_position(pm):
    """Open a standard BUY position with SL and target set."""
    pos = pm.open_position(
        trade_id="TRADE-001", direction="BUY",
        filled_qty=25, price=150.0,
    )
    pm.set_sl("TRADE-001", 148.0)
    pm.set_target("TRADE-001", 155.0)
    return pos


@pytest.fixture
def sell_position(pm):
    """Open a standard SELL position with SL and target set."""
    pos = pm.open_position(
        trade_id="TRADE-002", direction="SELL",
        filled_qty=25, price=150.0,
    )
    pm.set_sl("TRADE-002", 152.0)
    pm.set_target("TRADE-002", 145.0)
    return pos


@pytest.fixture
def primary_order(olm):
    """Register a primary entry order in OLM."""
    order = OrderRecord(
        order_id="ORD001", trade_id="TRADE-001",
        side="BUY", quantity=25, price=150.0,
    )
    olm.register_order(order)
    return order


# =============================================================================
# Default Price Calculation Tests
# =============================================================================


class TestDefaultPriceCalculation:
    """_calculate_default_sl and _calculate_default_target tests."""

    def test_default_sl_buy(self, prot_model):
        """BUY default SL is offset_ticks below entry."""
        sl = prot_model._calculate_default_sl("BUY", 150.0, 10)
        expected = round(150.0 - (10 * NIFTY_TICK_SIZE), 2)
        assert sl == expected

    def test_default_sl_sell(self, prot_model):
        """SELL default SL is offset_ticks above entry."""
        sl = prot_model._calculate_default_sl("SELL", 150.0, 10)
        expected = round(150.0 + (10 * NIFTY_TICK_SIZE), 2)
        assert sl == expected

    def test_default_target_buy(self, prot_model):
        """BUY default target is offset_ticks above entry."""
        tgt = prot_model._calculate_default_target("BUY", 150.0, 30)
        expected = round(150.0 + (30 * NIFTY_TICK_SIZE), 2)
        assert tgt == expected

    def test_default_target_sell(self, prot_model):
        """SELL default target is offset_ticks below entry."""
        tgt = prot_model._calculate_default_target("SELL", 150.0, 30)
        expected = round(150.0 - (30 * NIFTY_TICK_SIZE), 2)
        assert tgt == expected

    def test_custom_offset(self, prot_model):
        """Custom offset ticks are respected."""
        sl = prot_model._calculate_default_sl("BUY", 150.0, 20)
        expected = round(150.0 - (20 * NIFTY_TICK_SIZE), 2)
        assert sl == expected


# =============================================================================
# Stage Protection Tests
# =============================================================================


class TestStageProtection:
    """ProtectionModel.stage_protection tests."""

    def test_stage_from_position_sl_target(
        self, prot_model, buy_position, primary_order, olm,
    ):
        """Stage protection using position's SL and target prices."""
        result = prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )
        assert "linkage" in result
        assert "sl_order" in result
        assert "tgt_order" in result

        linkage = result["linkage"]
        sl_order = result["sl_order"]
        tgt_order = result["tgt_order"]

        # SL order at 148.0
        assert sl_order.price == 148.0
        assert sl_order.side == "SELL"
        assert sl_order.quantity == 25

        # TGT order at 155.0
        assert tgt_order.price == 155.0
        assert tgt_order.side == "SELL"
        assert tgt_order.quantity == 25

        # Linkage registered in OLM
        assert olm.get_linkage("ORD001") is not None

    def test_stage_from_explicit_prices(
        self, prot_model, buy_position, primary_order, olm,
    ):
        """Stage protection with explicit price overrides."""
        result = prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
            sl_price=147.0,
            target_price=156.0,
        )
        assert result["sl_order"].price == 147.0
        assert result["tgt_order"].price == 156.0

    def test_stage_without_position_prices(
        self, prot_model, olm, pm, primary_order,
    ):
        """Stage protection using default offsets when no SL/target set."""
        pos = pm.open_position(
            trade_id="TRADE-003", direction="BUY",
            filled_qty=25, price=150.0,
        )
        result = prot_model.stage_protection(
            position=pos,
            trade_id="TRADE-003",
            primary_order_id="ORD001",
        )
        # Expect default SL = 150 - (10 * 0.05) = 149.50
        assert result["sl_order"].price == round(150.0 - (10 * 0.05), 2)
        # Expect default target = 150 + (30 * 0.05) = 151.50
        assert result["tgt_order"].price == round(150.0 + (30 * 0.05), 2)

    def test_stage_sell_position(
        self, prot_model, sell_position, olm,
    ):
        """Stage protection for SELL position."""
        # Register primary order
        order = OrderRecord(
            order_id="ORD002", trade_id="TRADE-002",
            side="SELL", quantity=25, price=150.0,
        )
        olm.register_order(order)

        result = prot_model.stage_protection(
            position=sell_position,
            trade_id="TRADE-002",
            primary_order_id="ORD002",
        )
        # SL at 152.0 (above entry for SELL), side=BUY
        assert result["sl_order"].price == 152.0
        assert result["sl_order"].side == "BUY"
        # TGT at 145.0 (below entry for SELL), side=BUY
        assert result["tgt_order"].price == 145.0
        assert result["tgt_order"].side == "BUY"

    def test_stage_none_position(self, prot_model):
        """Staging with None position raises."""
        with pytest.raises(ExecutionError, match="None position"):
            prot_model.stage_protection(
                position=None, trade_id="T1",
                primary_order_id="ORD001",  # type: ignore
            )

    def test_stage_empty_trade_id(self, prot_model, buy_position):
        """Staging with empty trade_id raises."""
        with pytest.raises(ExecutionError, match="without trade_id"):
            prot_model.stage_protection(
                position=buy_position, trade_id="",
                primary_order_id="ORD001",
            )

    def test_stage_zero_quantity(self, prot_model, pm):
        """Staging for zero-quantity position raises."""
        pos = PositionState(trade_id="TRADE-004", direction="BUY",
                             filled_qty=0, avg_price=150.0)
        with pytest.raises(ExecutionError, match="zero-quantity"):
            prot_model.stage_protection(
                position=pos, trade_id="TRADE-004",
                primary_order_id="ORD001",
            )

    def test_stage_olm_integration(self, prot_model, buy_position,
                                    primary_order, olm):
        """Verify orders are registered and linked in OLM."""
        result = prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        # SL and TGT orders should be registered in OLM
        sl_record = olm.get_order(result["sl_order"].order_id)
        tgt_record = olm.get_order(result["tgt_order"].order_id)
        assert sl_record is not None
        assert tgt_record is not None

        # Linkage should exist
        linkage = olm.get_linkage("ORD001")
        assert linkage is not None
        assert linkage.sl_order_id == result["sl_order"].order_id
        assert linkage.tgt_order_id == result["tgt_order"].order_id


# =============================================================================
# Adjust for Partial Fill Tests
# =============================================================================


class TestAdjustForPartialFill:
    """ProtectionModel.adjust_for_partial_fill tests."""

    def test_adjust_after_partial_fill(
        self, prot_model, buy_position, primary_order, olm,
    ):
        """Partial fill adjusts SL/TGT quantities via OLM."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        linkage = prot_model.adjust_for_partial_fill(
            trade_id="TRADE-001", filled_qty=10,
        )
        assert linkage is not None
        assert linkage.sl_quantity == 10
        assert linkage.tgt_quantity == 10

    def test_adjust_no_linkage(self, prot_model):
        """Adjust when no linkage exists returns None."""
        result = prot_model.adjust_for_partial_fill(
            trade_id="UNKNOWN", filled_qty=10,
        )
        assert result is None

    def test_adjust_empty_trade_id(self, prot_model):
        """Adjust with empty trade_id raises."""
        with pytest.raises(ExecutionError, match="without trade_id"):
            prot_model.adjust_for_partial_fill(trade_id="", filled_qty=10)

    def test_adjust_negative_qty(self, prot_model):
        """Adjust with negative qty raises."""
        with pytest.raises(ExecutionError, match="Invalid filled_qty"):
            prot_model.adjust_for_partial_fill(trade_id="T1", filled_qty=-5)


# =============================================================================
# Adjust for Reconcile Tests
# =============================================================================


class TestAdjustForReconcile:
    """ProtectionModel.adjust_for_reconcile tests."""

    def test_reconcile_qty_mismatch(
        self, prot_model, buy_position, primary_order, olm,
    ):
        """Reconcile adjusts SL/TGT quantities."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        result = prot_model.adjust_for_reconcile(
            trade_id="TRADE-001",
            reconcile_data={
                "qty_mismatch": True,
                "resolved_qty": 15,
            },
        )
        assert result["adjusted"] is True
        assert any("15" in action for action in result["actions"])

    def test_reconcile_sl_price_mismatch(
        self, prot_model, buy_position, primary_order, olm,
    ):
        """Reconcile adjusts SL price."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        result = prot_model.adjust_for_reconcile(
            trade_id="TRADE-001",
            reconcile_data={
                "sl_mismatch": True,
                "resolved_sl_price": 147.5,
            },
        )
        assert result["adjusted"] is True
        assert any("147.5" in action for action in result["actions"])

    def test_reconcile_tgt_price_mismatch(
        self, prot_model, buy_position, primary_order, olm,
    ):
        """Reconcile adjusts TGT price."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        result = prot_model.adjust_for_reconcile(
            trade_id="TRADE-001",
            reconcile_data={
                "tgt_mismatch": True,
                "resolved_tgt_price": 156.0,
            },
        )
        assert result["adjusted"] is True

    def test_reconcile_no_mismatch(
        self, prot_model, buy_position, primary_order,
    ):
        """Reconcile with no mismatches returns no actions."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        result = prot_model.adjust_for_reconcile(
            trade_id="TRADE-001",
            reconcile_data={},
        )
        assert result["adjusted"] is False
        assert result["actions"] == []

    def test_reconcile_no_linkage(self, prot_model):
        """Reconcile with no linkage returns adjusted=False."""
        result = prot_model.adjust_for_reconcile(
            trade_id="UNKNOWN",
            reconcile_data={"qty_mismatch": True, "resolved_qty": 10},
        )
        assert result["adjusted"] is False

    def test_reconcile_empty_trade_id(self, prot_model):
        """Reconcile with empty trade_id raises."""
        with pytest.raises(ExecutionError, match="without trade_id"):
            prot_model.adjust_for_reconcile(trade_id="", reconcile_data={})

    def test_reconcile_none_data(self, prot_model):
        """Reconcile with None data raises."""
        with pytest.raises(ExecutionError, match="None reconcile_data"):
            prot_model.adjust_for_reconcile(
                trade_id="TRADE-001", reconcile_data=None,
            )


# =============================================================================
# Protection Status Tests
# =============================================================================


class TestProtectionStatus:
    """get_protection_status and is_protected tests."""

    def test_status_after_stage(
        self, prot_model, buy_position, primary_order,
    ):
        """Status shows protected=True after staging."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )

        status = prot_model.get_protection_status("TRADE-001")
        assert status["protected"] is True
        assert status["sl_order"] is not None
        assert status["tgt_order"] is not None
        assert status["linkage"] is not None

    def test_status_no_protection(self, prot_model, pm):
        """Status shows protected=False before staging."""
        pm.open_position(
            trade_id="TRADE-001", direction="BUY",
            filled_qty=25, price=150.0,
        )
        status = prot_model.get_protection_status("TRADE-001")
        assert status["protected"] is False

    def test_status_no_position(self, prot_model):
        """Status for unknown trade shows protected=False."""
        status = prot_model.get_protection_status("UNKNOWN")
        assert status["protected"] is False
        assert status["sl_order"] is None

    def test_is_protected_true(
        self, prot_model, buy_position, primary_order,
    ):
        """is_protected returns True after staging."""
        prot_model.stage_protection(
            position=buy_position,
            trade_id="TRADE-001",
            primary_order_id="ORD001",
        )
        assert prot_model.is_protected("TRADE-001") is True

    def test_is_protected_false_no_position(self, prot_model):
        """is_protected returns False for unknown trade."""
        assert prot_model.is_protected("UNKNOWN") is False

    def test_is_protected_false_no_sl(self, prot_model, pm):
        """is_protected returns False when position has no SL."""
        pos = pm.open_position(
            trade_id="TRADE-001", direction="BUY",
            filled_qty=25, price=150.0,
        )
        # No SL set — only staged protection without SL
        # But stage_protection would still work via defaults
        # So we test that a position without any SL price is not protected
        assert pos.sl_price is None
        # Since no staging was done, is_protected is False
        assert prot_model.is_protected("TRADE-001") is False


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases for ProtectionModel."""

    def test_no_log_callback(self, olm, pm):
        """ProtectionModel works without a log callback."""
        model = ProtectionModel(
            order_lifecycle_manager=olm,
            position_manager=pm,
        )
        pos = pm.open_position(
            trade_id="TRADE-001", direction="BUY",
            filled_qty=25, price=150.0,
        )
        pm.set_sl("TRADE-001", 148.0)
        order = OrderRecord(
            order_id="ORD001", trade_id="TRADE-001",
            side="BUY", quantity=25, price=150.0,
        )
        olm.register_order(order)

        result = model.stage_protection(
            position=pos, trade_id="TRADE-001",
            primary_order_id="ORD001",
        )
        assert result["linkage"] is not None

    def test_build_order_ids(self, prot_model):
        """Order ID builders produce expected strings."""
        assert prot_model._build_sl_order_id("TRADE-001") == "SL_TRADE-001"
        assert prot_model._build_tgt_order_id("TRADE-001") == "TGT_TRADE-001"

    def test_find_linkage_no_trade_orders(self, prot_model):
        """_find_linkage_for_trade returns None for trade with no orders."""
        result = prot_model._find_linkage_for_trade("UNKNOWN")
        assert result is None

    def test_prices_rounded_to_two_decimals(self, prot_model, pm, olm):
        """Default SL/TGT prices are rounded to 2 decimal places."""
        pos = pm.open_position(
            trade_id="TRADE-001", direction="BUY",
            filled_qty=25, price=150.0,
        )
        order = OrderRecord(
            order_id="ORD001", trade_id="TRADE-001",
            side="BUY", quantity=25, price=150.0,
        )
        olm.register_order(order)

        result = prot_model.stage_protection(
            position=pos, trade_id="TRADE-001",
            primary_order_id="ORD001",
        )
        sl_price = result["sl_order"].price
        tgt_price = result["tgt_order"].price
        # Check rounded to 2 decimal places
        assert round(sl_price, 2) == sl_price
        assert round(tgt_price, 2) == tgt_price
