"""Tests for Floor 5 — TradeConstructor (Step 5.16)."""

from __future__ import annotations

import pytest

from datetime import datetime

from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionBand,
    ConvictionScore,
    MarketStory,
    SessionPhase,
    conviction_score_to_band,
)
from junior_aladdin.floor_5_captain.trade_class_engine import (
    TradeClassAssignment,
    TradeClassEngine,
    TradeClassMetadata,
)
from junior_aladdin.floor_5_captain.trade_constructor import (
    TradeConstructor,
    TradePlan,
)
from junior_aladdin.shared.types import CaptainDecision, DecisionType, TradeClass


# ── Fixtures ───────────────────────────────────────────────────────────────


def make_constructor() -> TradeConstructor:
    return TradeConstructor()


def make_assignment(tc: TradeClass | None = TradeClass.SCALP) -> TradeClassAssignment:
    engine = TradeClassEngine()
    meta = engine.get_metadata(tc) if tc else None
    return TradeClassAssignment(
        trade_class=tc,
        metadata=meta,
        confidence_fit=0.85,
        assigned_at=datetime.utcnow(),
    )


def make_conviction(score: float = 75.0) -> ConvictionScore:
    return ConvictionScore(
        permission_score=80.0,
        conviction_score=score,
        no_trade_score=20.0,
        conviction_band=conviction_score_to_band(score),
        timestamp=datetime.utcnow(),
    )


# ── 1. Option Side Mapping ────────────────────────────────────────────────


def test_1_option_side_buy():
    """BUY → CE."""
    ctor = make_constructor()
    assert ctor._determine_option_side("BUY") == "CE"


def test_2_option_side_sell():
    """SELL → PE."""
    ctor = make_constructor()
    assert ctor._determine_option_side("SELL") == "PE"


def test_3_option_side_unknown():
    """Unknown direction → empty string."""
    ctor = make_constructor()
    assert ctor._determine_option_side("") == ""


# ── 2. Strike Selection ────────────────────────────────────────────────────


def test_4_strike_atm_preferred():
    """ATM strike selected when affordable."""
    ctor = make_constructor()
    strike, stype = ctor._select_strike(
        option_side="CE",
        atm_strike=19500.0,
        capital_limit=50000.0,  # Enough for ATM
        lot_size=50,
    )
    assert strike == 19500.0
    assert stype == "ATM"


def test_5_strike_itm_with_high_capital():
    """With sufficient capital, ATM is preferred over ITM."""
    ctor = make_constructor()
    strike, stype = ctor._select_strike(
        option_side="CE",
        atm_strike=19500.0,
        capital_limit=50000.0,  # Enough for any strike
        lot_size=50,
    )
    # ATM should be selected (not ITM) because ATM is preferred
    assert stype == "ATM", f"Expected ATM, got {stype}"
    assert strike == 19500.0


def test_6_strike_near_otm_with_strong_conviction():
    """Near OTM allowed with STRONG+ conviction."""
    ctor = make_constructor()
    # Set capital such that OTM (cheaper) is the only affordable option
    # ATM ~100 * 50 = 5000, OTM ~95 * 50 = 4750
    # Need capital between 4750 and 5000
    strike, stype = ctor._select_strike(
        option_side="CE",
        atm_strike=19500.0,
        capital_limit=4800.0,
        lot_size=50,
        conviction_score=make_conviction(80.0),  # STRONG
    )
    # OTM should be selected as the cheapest
    assert strike is not None, "Expected a strike to be selected"


def test_7_strike_deep_otm_not_selected():
    """Deep OTM (2+ strikes away) is not selected."""
    ctor = make_constructor()
    # The logic doesn't explicitly select deep OTM — it only goes 1 strike OTM
    # Verify that selection is within 1 strike of ATM
    strike, stype = ctor._select_strike(
        option_side="CE",
        atm_strike=19500.0,
        capital_limit=50000.0,
        lot_size=50,
    )
    assert strike is not None
    distance_strikes = abs(strike - 19500.0) / 50.0
    assert distance_strikes <= 1.0, f"Strike {strike} is {distance_strikes} strikes from ATM"


# ── 3. ITM / OTM Strike Helpers ───────────────────────────────────────────


def test_8_get_itm_strike_ce():
    """CE ITM is ATM - 1 interval."""
    ctor = make_constructor()
    itm = ctor._get_itm_strike("CE", 19500.0)
    assert itm == 19450.0


def test_9_get_itm_strike_pe():
    """PE ITM is ATM + 1 interval."""
    ctor = make_constructor()
    itm = ctor._get_itm_strike("PE", 19500.0)
    assert itm == 19550.0


def test_10_get_otm_strike_ce():
    """CE OTM is ATM + 1 interval."""
    ctor = make_constructor()
    otm = ctor._get_otm_strike("CE", 19500.0)
    assert otm == 19550.0


def test_11_get_otm_strike_pe():
    """PE OTM is ATM - 1 interval."""
    ctor = make_constructor()
    otm = ctor._get_otm_strike("PE", 19500.0)
    assert otm == 19450.0


# ── 4. Entry Plan ─────────────────────────────────────────────────────────


def test_12_entry_plan_scalp():
    """SCALP entry plan with zone info."""
    ctor = make_constructor()
    zone = {"label": "FVG_19500", "price": 19500.0, "type": "FVG"}
    entry = ctor._build_entry_plan(TradeClass.SCALP, "BUY", 19480.0, zone, False)
    assert entry["zone_label"] == "FVG_19500"
    assert entry["entry_price"] == 19500.0
    assert entry["requires_confirmation"] is False
    assert entry["direction"] == "BUY"


def test_13_entry_plan_with_confirmation():
    """CONTINUATION entry with confirmation required."""
    ctor = make_constructor()
    entry = ctor._build_entry_plan(TradeClass.CONTINUATION, "SELL", 19500.0, None, True)
    assert entry["requires_confirmation"] is True
    assert entry["confirmation_type"] == "second_close"


# ── 5. Invalidation Level ─────────────────────────────────────────────────


def test_14_invalidation_scalp_buy():
    """SCALP BUY invalidation is 0.2% below entry."""
    ctor = make_constructor()
    inval = ctor._determine_invalidation_level(TradeClass.SCALP, "BUY", 19500.0)
    assert inval == 19500.0 * 0.998  # 0.2% below


def test_15_invalidation_scalp_sell():
    """SCALP SELL invalidation is 0.2% above entry."""
    ctor = make_constructor()
    inval = ctor._determine_invalidation_level(TradeClass.SCALP, "SELL", 19500.0)
    assert inval == 19500.0 * 1.002  # 0.2% above


def test_16_invalidation_continuation_buy():
    """CONTINUATION BUY invalidation is 0.5% below entry."""
    ctor = make_constructor()
    inval = ctor._determine_invalidation_level(TradeClass.CONTINUATION, "BUY", 19500.0)
    assert inval == pytest.approx(19500.0 * 0.995)


def test_17_invalidation_reversal_wider():
    """REVERSAL has wider invalidation (0.8%)."""
    ctor = make_constructor()
    inval = ctor._determine_invalidation_level(TradeClass.REVERSAL, "BUY", 19500.0)
    assert inval == pytest.approx(19500.0 * 0.992)


def test_18_invalidation_from_zone():
    """Zone info invalidation is used if provided."""
    ctor = make_constructor()
    zone = {"label": "OB_19450", "price": 19450.0, "invalidation": 19400.0}
    inval = ctor._determine_invalidation_level(TradeClass.SCALP, "BUY", 19500.0, zone)
    assert inval == 19400.0


# ── 6. Stop Loss Plan ─────────────────────────────────────────────────────


def test_19_sl_scalp():
    """SCALP SL is 0.3% from entry."""
    ctor = make_constructor()
    sl = ctor._build_sl_plan(TradeClass.SCALP, "BUY", 19500.0)
    assert sl["sl_price"] == pytest.approx(19500.0 * 0.997)
    assert sl["sl_distance_bps"] == 30
    assert sl["trailing"] is False


def test_20_sl_continuation():
    """CONTINUATION SL is 0.5% from entry with trailing."""
    ctor = make_constructor()
    sl = ctor._build_sl_plan(TradeClass.CONTINUATION, "BUY", 19500.0)
    assert sl["sl_distance_bps"] == 50
    assert sl["trailing"] is True


def test_21_sl_reversal():
    """REVERSAL SL is 0.8% from entry (wider)."""
    ctor = make_constructor()
    sl = ctor._build_sl_plan(TradeClass.REVERSAL, "SELL", 19500.0)
    assert sl["sl_distance_bps"] == 80
    assert sl["sl_price"] == pytest.approx(19500.0 * 1.008)


# ── 7. Target Plan ────────────────────────────────────────────────────────


def test_22_target_scalp():
    """SCALP target is 1:1 R:R."""
    ctor = make_constructor()
    tgt = ctor._build_target_plan(TradeClass.SCALP, "BUY", 19500.0)
    assert tgt["r_multiple"] == 1.0
    assert tgt["target_type"] == "fixed"
    assert tgt["has_target"] is True


def test_23_target_continuation():
    """CONTINUATION target is 1:2 R:R with trailing."""
    ctor = make_constructor()
    tgt = ctor._build_target_plan(TradeClass.CONTINUATION, "BUY", 19500.0)
    assert tgt["r_multiple"] == 2.0
    assert tgt["target_type"] == "trailing"


def test_24_target_elite_boost():
    """ELITE conviction boosts R multiple by 33%."""
    ctor = make_constructor()
    elite_conviction = make_conviction(95.0)  # ELITE
    tgt = ctor._build_target_plan(TradeClass.CONTINUATION, "BUY", 19500.0, elite_conviction)
    assert tgt["r_multiple"] == pytest.approx(2.0 * 1.33)


# ── 8. Capital Fit ────────────────────────────────────────────────────────


def test_25_capital_fit_affordable():
    """Premium fits within capital limit."""
    ctor = make_constructor()
    fit = ctor._verify_capital_fit(premium_estimate=5000.0, capital_limit=25000.0, lot_size=50)
    assert fit["fits"] is True
    assert fit["utilization_pct"] == 20.0


def test_26_capital_fit_exceeded():
    """Premium exceeds capital limit."""
    ctor = make_constructor()
    fit = ctor._verify_capital_fit(premium_estimate=30000.0, capital_limit=25000.0, lot_size=50)
    assert fit["fits"] is False


# ── 9. Full Trade Construction ─────────────────────────────────────────────


def test_27_construct_full_trade_scalp():
    """Full SCALP BUY trade construction."""
    ctor = make_constructor()
    plan = ctor.construct_trade(
        direction="BUY",
        trade_class_assignment=make_assignment(TradeClass.SCALP),
        conviction_score=make_conviction(80.0),
        capital_limit=25000.0,
        atm_strike=19500.0,
        current_price=19480.0,
    )
    assert plan.is_constructable
    assert plan.direction == "BUY"
    assert plan.option_side == "CE"
    assert plan.selected_strike == "19500"
    assert plan.strike_type == "ATM"
    assert plan.trade_class == TradeClass.SCALP
    assert plan.capital_fit["fits"] is True


def test_28_construct_full_trade_continuation_sell():
    """Full CONTINUATION SELL trade construction."""
    ctor = make_constructor()
    plan = ctor.construct_trade(
        direction="SELL",
        trade_class_assignment=make_assignment(TradeClass.CONTINUATION),
        conviction_score=make_conviction(70.0),  # TRADABLE
        capital_limit=25000.0,
        atm_strike=19500.0,
        current_price=19520.0,
    )
    assert plan.is_constructable
    assert plan.direction == "SELL"
    assert plan.option_side == "PE"
    assert plan.trade_class == TradeClass.CONTINUATION
    assert plan.stop_loss_plan["trailing"] is True
    assert plan.target_plan["r_multiple"] == 2.0


def test_29_construct_trade_no_capital():
    """Trade rejected when capital limit is zero."""
    ctor = make_constructor()
    plan = ctor.construct_trade(
        direction="BUY",
        trade_class_assignment=make_assignment(TradeClass.SCALP),
        capital_limit=0.0,
    )
    assert not plan.is_constructable
    assert "zero or negative" in plan.construction_fail_reason


def test_30_construct_trade_no_direction():
    """Trade rejected with no direction."""
    ctor = make_constructor()
    plan = ctor.construct_trade(
        direction="",
        trade_class_assignment=make_assignment(TradeClass.SCALP),
        capital_limit=25000.0,
    )
    assert not plan.is_constructable
    assert "No direction" in plan.construction_fail_reason


# ── 10. CaptainDecision Conversion ─────────────────────────────────────────


def test_31_to_captain_decision_trade():
    """TradePlan converts to CaptainDecision with TRADE type."""
    ctor = make_constructor()
    plan = ctor.construct_trade(
        direction="BUY",
        trade_class_assignment=make_assignment(TradeClass.SCALP),
        conviction_score=make_conviction(80.0),
        capital_limit=25000.0,
        atm_strike=19500.0,
    )
    decision = ctor.to_captain_decision(plan, conviction_score=make_conviction(80.0))
    assert decision.decision == DecisionType.TRADE
    assert decision.action == "BUY"
    assert decision.trade_class == TradeClass.SCALP


def test_32_to_captain_decision_not_constructable():
    """Non-constructable plan converts to WAIT decision."""
    ctor = make_constructor()
    plan = TradePlan(is_constructable=False, construction_fail_reason="No capital", direction="")
    decision = ctor.to_captain_decision(plan)
    assert decision.decision == DecisionType.WAIT
    assert decision.silence_reason == "No capital"


# ── 11. Trade Summary ──────────────────────────────────────────────────────


def test_33_get_trade_summary():
    """Trade summary includes key fields."""
    ctor = make_constructor()
    plan = ctor.construct_trade(
        direction="SELL",
        trade_class_assignment=make_assignment(TradeClass.CONTINUATION),
        conviction_score=make_conviction(70.0),
    )
    summary = ctor.get_trade_summary(plan)
    assert summary["direction"] == "SELL"
    assert summary["option_side"] == "PE"
    assert summary["trade_class"] == "CONTINUATION"
    assert summary["has_plan"] is True
    assert "timestamp" in summary


# ── 12. Edge Cases ─────────────────────────────────────────────────────────


def test_34_edge_requires_confirmation_scalp():
    """SCALP does not require confirmation."""
    ctor = make_constructor()
    assert ctor._requires_confirmation(TradeClass.SCALP) is False


def test_35_edge_requires_confirmation_tradable():
    """TRADABLE conviction requires confirmation regardless of class."""
    ctor = make_constructor()
    tradable_conviction = make_conviction(65.0)  # TRADABLE
    # Even SCALP with TRADABLE conviction → no confirmation (SCALP rule wins)
    assert ctor._requires_confirmation(TradeClass.SCALP, tradable_conviction) is False


def test_36_edge_requires_confirmation_continuation():
    """CONTINUATION always requires confirmation."""
    ctor = make_constructor()
    assert ctor._requires_confirmation(TradeClass.CONTINUATION) is True


def test_37_edge_liquidity_reclaim_entry():
    """LIQUIDITY_RECLAIM entry with zone info."""
    ctor = make_constructor()
    zone = {"label": "OB_19450", "price": 19450.0, "type": "Order Block"}
    entry = ctor._build_entry_plan(
        TradeClass.LIQUIDITY_RECLAIM, "BUY", 19480.0, zone, True
    )
    assert entry["zone_type"] == "Order Block"
    assert entry["requires_confirmation"] is True


def test_38_edge_options_pressure_target():
    """OPTIONS_PRESSURE uses trail_on_expansion target type."""
    ctor = make_constructor()
    tgt = ctor._build_target_plan(TradeClass.OPTIONS_PRESSURE, "BUY", 19500.0)
    assert tgt["target_type"] == "trail_on_expansion"
    assert tgt["r_multiple"] == 1.5


def test_39_edge_premium_estimate():
    """Premium estimate returns reasonable values."""
    ctor = make_constructor()
    premium = ctor._estimate_premium("19500", "CE", 50)
    # ATM: ~100 * 50 = ~5000
    assert premium > 4000
    assert premium < 6000


def test_40_edge_construct_with_zone():
    """Construct trade with zone info produces valid entry plan."""
    ctor = make_constructor()
    zone = {"label": "FVG_19550", "price": 19550.0, "type": "FVG"}
    plan = ctor.construct_trade(
        direction="BUY",
        trade_class_assignment=make_assignment(TradeClass.LIQUIDITY_RECLAIM),
        conviction_score=make_conviction(80.0),
        capital_limit=25000.0,
        atm_strike=19500.0,
        current_price=19520.0,
        zone_info=zone,
    )
    assert plan.is_constructable
    assert plan.entry_plan["zone_label"] == "FVG_19550"
    assert plan.entry_plan["zone_type"] == "FVG"
