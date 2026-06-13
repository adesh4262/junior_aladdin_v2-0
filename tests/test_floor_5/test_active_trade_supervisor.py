"""Tests for Floor 5 — ActiveTradeSupervisor (Step 5.19)."""

from __future__ import annotations

from datetime import datetime

from junior_aladdin.floor_5_captain.active_trade_supervisor import (
    ActiveTradeSupervisor,
)
from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    MarketStory,
    SessionPhase,
)
from junior_aladdin.shared.types import (
    CaptainDecision,
    DecisionType,
    TradeClass,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


def make_supervisor() -> ActiveTradeSupervisor:
    return ActiveTradeSupervisor()


def make_trade(
    action: str = "BUY",
    trade_class: TradeClass = TradeClass.CONTINUATION,
    strike: str = "19500",
) -> CaptainDecision:
    return CaptainDecision(
        decision=DecisionType.TRADE,
        action=action,
        option_side="CE" if action == "BUY" else "PE",
        selected_strike=strike,
        trade_class=trade_class,
        permission_score=80.0,
        conviction_score=75.0,
        no_trade_score=20.0,
        entry_plan={"zone": "FVG_19500", "price": 19500.0},
        invalidation_level=19400.0,
        stop_loss_plan={"sl_price": 19450.0},
        target_plan={"target_price": 19600.0},
        reason_summary="Test trade",
        timestamp=datetime.utcnow(),
    )


def make_story(
    regime: str = "TREND_UP",
    bias: str = "BULLISH",
    session: SessionPhase = SessionPhase.GOLDEN_MORNING,
) -> MarketStory:
    return MarketStory(
        regime=regime,
        session_phase=session,
        bias=bias,
        summary=f"{regime} market with {bias} bias",
        timestamp=datetime.utcnow(),
    )


def make_confluence(
    direction: str = "BULLISH",
    quality: float = 0.8,
) -> ConfluenceResult:
    return ConfluenceResult(
        confluence_quality=quality,
        conflict_present=False,
        aligned_heads=["smc", "ict"],
        opposing_heads=[],
        dominant_direction=direction,
        timestamp=datetime.utcnow(),
    )


# ── 1. Zone Validity ──────────────────────────────────────────────────────


def test_1_zone_valid_buy_within_threshold():
    """BUY zone valid when price within 0.5%."""
    sup = make_supervisor()
    valid = sup._check_zone_validity("BUY", 19500.0, 19550.0)
    assert valid is True


def test_2_zone_valid_buy_beyond_threshold():
    """BUY zone invalid when price beyond 0.5%."""
    sup = make_supervisor()
    valid = sup._check_zone_validity("BUY", 19500.0, 19700.0)
    # (19700 - 19500) / 19500 = 0.01025 > 0.005 → invalid
    assert valid is False


def test_3_zone_valid_scalp_tight_threshold():
    """SCALP has tighter zone tolerance (0.3%)."""
    sup = make_supervisor()
    valid = sup._check_zone_validity("BUY", 19500.0, 19555.0, TradeClass.SCALP)
    # (19555 - 19500) / 19500 = 0.00282 < 0.003 → valid
    assert valid is True


def test_4_zone_valid_scalp_beyond():
    """SCALP invalid beyond 0.3%."""
    sup = make_supervisor()
    valid = sup._check_zone_validity("BUY", 19500.0, 19560.0, TradeClass.SCALP)
    # (19560 - 19500) / 19500 = 0.00308 > 0.003 → invalid
    assert valid is False


def test_5_zone_valid_zero_price():
    """Zero price → zone considered valid (no data)."""
    sup = make_supervisor()
    assert sup._check_zone_validity("BUY", 19500.0, 0.0) is True
    assert sup._check_zone_validity("BUY", 0.0, 19500.0) is True


# ── 2. Market Story Support ───────────────────────────────────────────────


def test_6_market_story_supports_buy():
    """BUY trade supported by BULLISH story."""
    sup = make_supervisor()
    assert sup._check_market_story_support("BUY", make_story("TREND_UP", "BULLISH")) is True


def test_7_market_story_opposes_buy():
    """BUY trade NOT supported by BEARISH story."""
    sup = make_supervisor()
    assert sup._check_market_story_support("BUY", make_story("TREND_DOWN", "BEARISH")) is False


def test_8_market_story_chop_unsupported():
    """CHOP regime does not support any trade."""
    sup = make_supervisor()
    assert sup._check_market_story_support("BUY", make_story("CHOP", "NEUTRAL")) is False
    assert sup._check_market_story_support("SELL", make_story("CHOP", "NEUTRAL")) is False


# ── 3. Macro Shift ────────────────────────────────────────────────────────


def test_9_macro_shift_chop():
    """CHOP regime detected as macro shift."""
    sup = make_supervisor()
    assert sup._check_macro_shift(make_story("CHOP")) is True


def test_10_macro_shift_strong_trend():
    """Strong trend is NOT a macro shift."""
    sup = make_supervisor()
    assert sup._check_macro_shift(make_story("TREND_UP")) is False


def test_11_macro_shift_unclear():
    """UNCLEAR regime is a macro shift."""
    sup = make_supervisor()
    assert sup._check_macro_shift(make_story("UNCLEAR")) is True


# ── 4. Opposite Case ──────────────────────────────────────────────────────


def test_12_opposite_case_direction_flip():
    """Direction flip (BULLISH→BEARISH) detected."""
    sup = make_supervisor()
    conf = make_confluence("BEARISH")
    assert sup._check_opposite_case(conf, "BUY") is True
    assert sup._check_opposite_case(conf, "BULLISH") is True


def test_13_opposite_case_no_flip():
    """Same direction → no opposite case."""
    sup = make_supervisor()
    conf = make_confluence("BULLISH")
    assert sup._check_opposite_case(conf, "BUY") is False


def test_14_opposite_case_low_confluence():
    """Confluence quality < 0.3 suggests opposite strengthening."""
    sup = make_supervisor()
    conf = make_confluence("BULLISH", quality=0.2)
    assert sup._check_opposite_case(conf, "BUY") is True


# ── 5. Full Thesis Review ─────────────────────────────────────────────────


def test_15_review_thesis_intact():
    """Full review with intact thesis."""
    sup = make_supervisor()
    review = sup.review_thesis(
        active_trade=make_trade("BUY"),
        current_market_story=make_story("TREND_UP", "BULLISH"),
        current_price=19530.0,
        zone_price=19500.0,
        zone_label="FVG_19500",
        current_confluence=make_confluence("BULLISH"),
        original_confluence_direction="BULLISH",
    )
    assert review.thesis_intact is True
    assert len(review.concerns) == 0
    assert review.recommendation == "THESIS_INTACT"


def test_16_review_zone_invalid():
    """Zone invalidation detected."""
    sup = make_supervisor()
    review = sup.review_thesis(
        active_trade=make_trade("BUY", TradeClass.SCALP),
        current_market_story=make_story("TREND_UP", "BULLISH"),
        current_price=19600.0,  # >0.3% from 19500
        zone_price=19500.0,
    )
    assert not review.zone_valid
    assert "no longer valid" in review.concerns[0].lower()
    assert review.thesis_intact is False


def test_17_review_direction_flip():
    """Direction flip detected via confluence."""
    sup = make_supervisor()
    review = sup.review_thesis(
        active_trade=make_trade("BUY"),
        current_market_story=make_story("TREND_DOWN", "BEARISH"),
        current_price=19400.0,
        zone_price=19500.0,
        current_confluence=make_confluence("BEARISH"),
        original_confluence_direction="BULLISH",
    )
    assert review.opposite_case_strengthened is True
    assert not review.market_story_supports
    assert review.thesis_intact is False


# ── 6. Recommendations ────────────────────────────────────────────────────


def test_18_recommendation_intact():
    """No concerns → THESIS_INTACT."""
    sup = make_supervisor()
    rec, label = sup._determine_recommendation([], True, False, False)
    assert rec == "THESIS_INTACT"


def test_19_recommendation_monitor():
    """1 concern → MONITOR_CLOSELY."""
    sup = make_supervisor()
    rec, label = sup._determine_recommendation(["Minor issue"], True, False, False)
    assert rec == "MONITOR_CLOSELY"


def test_20_recommendation_prepare_exit():
    """Zone invalid → PREPARE_EXIT."""
    sup = make_supervisor()
    rec, label = sup._determine_recommendation(["Zone invalid"], False, False, False)
    assert rec == "PREPARE_EXIT"


def test_21_recommendation_intervention():
    """Zone invalid + opposite stronger → INTERVENTION_REQUIRED."""
    sup = make_supervisor()
    rec, label = sup._determine_recommendation(
        ["Zone invalid", "Opposite stronger"], False, True, False
    )
    assert rec == "INTERVENTION_REQUIRED"


# ── 7. should_intervene ───────────────────────────────────────────────────


def test_22_should_intervene_false_no_review():
    """No reviews → should_intervene is False."""
    sup = make_supervisor()
    assert sup.should_intervene() is False


def test_23_should_intervene_false_intact():
    """Intact thesis → should_intervene is False."""
    sup = make_supervisor()
    sup.review_thesis(
        active_trade=make_trade(),
        current_market_story=make_story(),
        current_price=19530.0,
        zone_price=19500.0,
    )
    assert sup.should_intervene() is False


def test_24_should_intervene_true():
    """Multiple critical failures → should_intervene is True."""
    sup = make_supervisor()
    sup.review_thesis(
        active_trade=make_trade("BUY", TradeClass.SCALP),
        current_market_story=make_story("CHOP", "NEUTRAL"),
        current_price=19700.0,  # Far from zone
        zone_price=19500.0,
        current_confluence=make_confluence("BEARISH"),
        original_confluence_direction="BULLISH",
    )
    assert sup.should_intervene() is True


# ── 8. Supervision State ──────────────────────────────────────────────────


def test_25_supervision_state_empty():
    """Empty state has no active trade."""
    sup = make_supervisor()
    state = sup.get_supervision_state()
    assert state["has_active_trade"] is False
    assert state["total_reviews"] == 0


def test_26_supervision_state_after_review():
    """State populated after review."""
    sup = make_supervisor()
    sup.review_thesis(
        active_trade=make_trade(),
        current_market_story=make_story(),
        current_price=19530.0,
        zone_price=19500.0,
    )
    state = sup.get_supervision_state()
    assert state["has_active_trade"] is True
    assert state["total_reviews"] == 1
    assert state["thesis_intact"] is True


# ── 9. Session Management ─────────────────────────────────────────────────


def test_27_clear_active_trade():
    """Clearing active trade removes reference."""
    sup = make_supervisor()
    sup.review_thesis(active_trade=make_trade(), current_price=19500.0, zone_price=19500.0)
    sup.clear_active_trade()
    state = sup.get_supervision_state()
    assert state["has_active_trade"] is False
    # Reviews are preserved
    assert state["total_reviews"] == 1


def test_28_clear_session():
    """Clear removes everything."""
    sup = make_supervisor()
    sup.review_thesis(active_trade=make_trade(), current_price=19500.0, zone_price=19500.0)
    sup.clear_session()
    assert sup.get_latest_review() is None
    assert len(sup.get_review_history()) == 0
    assert sup.should_intervene() is False


# ── 9b. Review History ────────────────────────────────────────────────────


def test_28b_review_history_returns_all():
    """get_review_history returns reviews in chronological order."""
    sup = make_supervisor()
    r1 = sup.review_thesis(active_trade=make_trade("BUY"), current_price=19500.0, zone_price=19500.0)
    r2 = sup.review_thesis(current_price=19550.0, zone_price=19500.0)
    history = sup.get_review_history()
    assert len(history) == 2
    assert history[0] is r1
    assert history[1] is r2


# ── 10. Edge Cases ────────────────────────────────────────────────────────


def test_29_edge_no_trade_provided():
    """Review without providing trade uses stored trade."""
    sup = make_supervisor()
    sup.review_thesis(active_trade=make_trade("SELL"), current_price=19500.0, zone_price=19500.0)
    # Second review without trade arg
    review = sup.review_thesis(current_price=19530.0, zone_price=19500.0)
    assert review is not None


def test_30_edge_zero_price_no_crash():
    """Zero prices don't crash the supervisor."""
    sup = make_supervisor()
    review = sup.review_thesis(
        active_trade=make_trade(),
        current_price=0.0,
        zone_price=0.0,
    )
    assert review is not None


def test_31_edge_reversal_zone_threshold():
    """REVERSAL has 0.8% zone tolerance."""
    sup = make_supervisor()
    # 19500 + 0.79% = 19654.05 → within 0.8%
    assert sup._check_zone_validity("BUY", 19500.0, 19654.0, TradeClass.REVERSAL) is True
    # 19500 + 0.81% = 19657.95 → beyond 0.8%
    assert sup._check_zone_validity("BUY", 19500.0, 19658.0, TradeClass.REVERSAL) is False
