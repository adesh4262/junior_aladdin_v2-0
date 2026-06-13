"""Tests for Floor 5 — Intervention Engine (Step 5.20).

Tests cover:
- All 5 intervention scenarios (thesis_break, regime_flip, strong_opposite,
  options_collapse, risk_emergency)
- Severity determination (NORMAL / CAUTION / EMERGENCY_OVERRIDE)
- Action selection by trigger + severity
- Non-intervention when concerns are below threshold
- Integration with ActiveTradeSupervisor
- Session management (history, count, clear)
- Portfolio risk summary
- Edge cases (no trade, empty regime, weak opposite case)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from junior_aladdin.floor_5_captain.active_trade_supervisor import (
    ActiveTradeSupervisor,
    ThesisReview,
)
from junior_aladdin.floor_5_captain.captain_types import InterventionSeverity
from junior_aladdin.floor_5_captain.intervention_engine import (
    InterventionDecision,
    InterventionEngine,
)
from junior_aladdin.shared.types import (
    CaptainDecision,
    DecisionType,
    TradeClass,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def make_supervisor() -> ActiveTradeSupervisor:
    """Create a fresh ActiveTradeSupervisor instance for testing."""
    return ActiveTradeSupervisor()


def make_trade(
    action: str = "BUY",
    trade_class: TradeClass = TradeClass.SCALP,
) -> CaptainDecision:
    """Create a simplified CaptainDecision for test use."""
    return CaptainDecision(
        decision=DecisionType.TRADE,
        action=action,
        option_side="CE",
        selected_strike="19500",
        trade_class=trade_class,
        permission_score=80.0,
        conviction_score=75.0,
        no_trade_score=10.0,
    )


def make_review(
    thesis_intact: bool = True,
    concerns: list[str] | None = None,
    zone_valid: bool = True,
    options_alive: bool = True,
    macro_shift: bool = False,
    story_supports: bool = True,
    opposite_stronger: bool = False,
    recommendation: str = "THESIS_INTACT",
) -> ThesisReview:
    """Create a ThesisReview with specified properties."""
    return ThesisReview(
        thesis_intact=thesis_intact,
        concerns=concerns or [],
        zone_valid=zone_valid,
        options_support_alive=options_alive,
        macro_shift_detected=macro_shift,
        market_story_supports=story_supports,
        opposite_case_strengthened=opposite_stronger,
        recommendation=recommendation,
        recommendation_label=_rec_label(recommendation),
        reviewed_at=datetime.utcnow(),
    )


def _rec_label(rec: str) -> str:
    labels = {
        "THESIS_INTACT": "Thesis intact",
        "MONITOR_CLOSELY": "Monitor closely",
        "PREPARE_EXIT": "Prepare exit",
        "INTERVENTION_REQUIRED": "Intervention required",
    }
    return labels.get(rec, "Unknown")


def inject_review(supervisor: ActiveTradeSupervisor, review: ThesisReview) -> None:
    """Inject a ThesisReview into the supervisor's review list."""
    supervisor._reviews.append(review)


# =============================================================================
# SECTION 1: No-Intervention (Clean) Cases
# =============================================================================


class TestNoIntervention:
    """Tests where intervention is NOT warranted."""

    def test_1_no_intervention_clean_thesis(self):
        """No intervention when thesis is fully intact."""
        engine = InterventionEngine()
        sup = make_supervisor()
        decision = engine.evaluate_intervention(sup)

        assert decision.intervene is False
        assert decision.severity == InterventionSeverity.NORMAL
        assert decision.reason != ""
        assert decision.trigger == ""
        assert engine.get_intervention_count() == 0

    def test_2_no_intervention_few_concerns(self):
        """No intervention when concerns exist but below structural break threshold."""
        engine = InterventionEngine()
        sup = make_supervisor()

        # Inject a review with 2 concerns but zone still valid
        review = make_review(
            thesis_intact=False,
            concerns=["Zone validity concern", "Minor macro shift"],
            zone_valid=True,
            macro_shift=False,
            opposite_stronger=False,
            recommendation="MONITOR_CLOSELY",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(sup)
        assert decision.intervene is False
        assert engine.get_intervention_count() == 0

    def test_3_no_intervention_no_supervisor_reviews(self):
        """No intervention when supervisor has no reviews."""
        engine = InterventionEngine()
        sup = make_supervisor()
        decision = engine.evaluate_intervention(sup)

        assert decision.intervene is False
        assert decision.trigger == ""

    def test_4_no_intervention_weak_opposite_case(self):
        """No intervention when opposite strength is below threshold."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            opposite_stronger=False,
            recommendation="THESIS_INTACT",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            opposite_case_strength=0.3,
        )
        assert decision.intervene is False


# =============================================================================
# SECTION 2: Thesis Break Scenario
# =============================================================================


class TestThesisBreak:
    """Tests for thesis break intervention scenario."""

    def test_5_thesis_break_triggers(self):
        """Thesis break triggers when zone invalid + opposite stronger + macro shift."""
        engine = InterventionEngine()
        sup = make_supervisor()

        # Structural break: all 3 critical failures
        review = make_review(
            thesis_intact=False,
            concerns=[
                "Zone not valid",
                "Macro context shifted",
                "Opposite case strengthened",
            ],
            zone_valid=False,
            opposite_stronger=True,
            macro_shift=True,
            recommendation="INTERVENTION_REQUIRED",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(sup)
        assert decision.intervene is True, "Thesis break should trigger"
        assert decision.trigger == "thesis_break"
        assert decision.severity in (
            InterventionSeverity.CAUTION,
            InterventionSeverity.EMERGENCY_OVERRIDE,
        )

    def test_6_thesis_break_emergency_on_three_failures(self):
        """Three critical failures = EMERGENCY_OVERRIDE severity."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            thesis_intact=False,
            concerns=["Zone bad", "Macro shifted", "Opposite stronger"],
            zone_valid=False,
            opposite_stronger=True,
            macro_shift=True,
            recommendation="INTERVENTION_REQUIRED",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(sup)
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.EMERGENCY_OVERRIDE

    def test_7_thesis_break_caution_on_two_failures(self):
        """Two critical failures + 3 concerns = CAUTION."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            thesis_intact=False,
            concerns=["Zone bad", "Macro shifted", "Minor concern"],
            zone_valid=False,
            opposite_stronger=False,
            macro_shift=True,
            recommendation="PREPARE_EXIT",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(sup)
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.CAUTION


# =============================================================================
# SECTION 3: Regime Flip Scenario
# =============================================================================


class TestRegimeFlip:
    """Tests for regime flip intervention scenario."""

    def test_8_regime_flip_chop_triggers(self):
        """Regime flip to CHOP triggers CAUTION."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            regime="CHOP",
        )
        assert decision.intervene is True
        assert decision.trigger == "regime_flip"
        assert decision.severity == InterventionSeverity.CAUTION

    def test_9_regime_flip_unclear_triggers(self):
        """Regime flip to UNCLEAR triggers CAUTION."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            regime="UNCLEAR",
        )
        assert decision.intervene is True
        assert decision.trigger == "regime_flip"

    def test_10_regime_no_flip_on_supportive_regime(self):
        """No intervention when regime is supportive."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            regime="TREND_UP",
        )
        assert decision.intervene is False
        assert decision.trigger == ""

    def test_11_regime_empty_does_not_trigger(self):
        """Empty regime string does not trigger intervention."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            regime="",
        )
        assert decision.intervene is False


# =============================================================================
# SECTION 4: Strong Opposite Confluence Scenario
# =============================================================================


class TestStrongOppositeConfluence:
    """Tests for strong opposite confluence intervention scenario."""

    def test_12_opposite_confluence_direction_flip_triggers(self):
        """Direction flip triggers intervention."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            opposite_stronger=True,
            recommendation="INTERVENTION_REQUIRED",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            opposite_case_strength=0.8,
        )
        assert decision.intervene is True
        assert decision.trigger == "strong_opposite_confluence"

    def test_13_opposite_confluence_emergency_on_high_strength(self):
        """Direction flip + strength >= 0.7 = EMERGENCY_OVERRIDE."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            opposite_stronger=True,
            recommendation="INTERVENTION_REQUIRED",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            opposite_case_strength=0.9,
        )
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.EMERGENCY_OVERRIDE

    def test_14_opposite_confluence_caution_on_low_strength(self):
        """Direction flip + low strength = CAUTION."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            opposite_stronger=True,
            recommendation="PREPARE_EXIT",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            opposite_case_strength=0.4,
        )
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.CAUTION

    def test_15_opposite_confluence_high_strength_alone_triggers(self):
        """High opposite strength alone can trigger even without direction flip."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            opposite_stronger=False,
            recommendation="THESIS_INTACT",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            opposite_case_strength=0.8,
        )
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.CAUTION


# =============================================================================
# SECTION 5: Options Collapse Scenario
# =============================================================================


class TestOptionsCollapse:
    """Tests for options support collapse intervention scenario."""

    def test_16_options_collapse_triggers_for_options_pressure(self):
        """Options collapse triggers for OPTIONS_PRESSURE trade."""
        engine = InterventionEngine()
        sup = make_supervisor()
        trade = make_trade(trade_class=TradeClass.OPTIONS_PRESSURE)

        decision = engine.evaluate_intervention(
            sup,
            active_trade=trade,
            options_oi_healthy=False,
        )
        assert decision.intervene is True
        assert decision.trigger == "options_collapse"
        assert decision.severity == InterventionSeverity.CAUTION

    def test_17_options_collapse_ignores_for_other_trades(self):
        """Options collapse does NOT trigger for non-OPTIONS trades."""
        engine = InterventionEngine()
        sup = make_supervisor()
        trade = make_trade(trade_class=TradeClass.CONTINUATION)

        decision = engine.evaluate_intervention(
            sup,
            active_trade=trade,
            options_oi_healthy=False,
        )
        assert decision.intervene is False
        assert decision.trigger == ""

    def test_18_options_collapse_healthy_oi_no_trigger(self):
        """Healthy OI does not trigger options collapse."""
        engine = InterventionEngine()
        sup = make_supervisor()
        trade = make_trade(trade_class=TradeClass.OPTIONS_PRESSURE)

        decision = engine.evaluate_intervention(
            sup,
            active_trade=trade,
            options_oi_healthy=True,
        )
        assert decision.intervene is False


# =============================================================================
# SECTION 6: Risk Emergency Scenario
# =============================================================================


class TestRiskEmergency:
    """Tests for risk emergency intervention scenario."""

    def test_19_risk_emergency_data_health_critical(self):
        """CRITICAL data health triggers EMERGENCY_OVERRIDE."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            data_health_critical=True,
        )
        assert decision.intervene is True
        assert decision.trigger == "risk_emergency"
        assert decision.severity == InterventionSeverity.EMERGENCY_OVERRIDE
        assert decision.action == "IMMEDIATE_EXIT"

    def test_20_risk_emergency_risk_event_detected(self):
        """External risk event triggers EMERGENCY_OVERRIDE."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            risk_event_detected=True,
        )
        assert decision.intervene is True
        assert decision.trigger == "risk_emergency"
        assert decision.severity == InterventionSeverity.EMERGENCY_OVERRIDE


# =============================================================================
# SECTION 7: Multiple Scenarios & Severity Resolution
# =============================================================================


class TestMultipleScenarios:
    """Tests for multiple concurrent intervention scenarios."""

    def test_21_multiple_scenarios_highest_severity_wins(self):
        """When multiple scenarios trigger, highest severity dominates."""
        engine = InterventionEngine()
        sup = make_supervisor()

        # Regime flip (CAUTION) + risk emergency (EMERGENCY_OVERRIDE)
        decision = engine.evaluate_intervention(
            sup,
            regime="CHOP",
            data_health_critical=True,
        )
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.EMERGENCY_OVERRIDE
        assert decision.trigger == "regime_flip"  # First in order

    def test_22_multiple_scenarios_combined_reason(self):
        """Combined reason includes all triggered scenarios."""
        engine = InterventionEngine()
        sup = make_supervisor()

        # Inject a review with opposite_stronger=True so both scenarios trigger
        review = make_review(
            opposite_stronger=True,
            recommendation="MONITOR_CLOSELY",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            regime="CHOP",
            opposite_case_strength=0.8,
        )
        assert decision.intervene is True
        assert "regime_flip" in decision.reason
        assert "strong_opposite_confluence" in decision.reason


# =============================================================================
# SECTION 8: Action Selection
# =============================================================================


class TestActionSelection:
    """Tests for intervention action selection."""

    def test_23_action_thesis_break_emergency(self):
        """Thesis break + EMERGENCY_OVERRIDE = CLOSE_POSITION."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            thesis_intact=False,
            concerns=["A", "B", "C"],
            zone_valid=False,
            opposite_stronger=True,
            macro_shift=True,
            recommendation="INTERVENTION_REQUIRED",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(sup)
        assert decision.action == "CLOSE_POSITION"

    def test_24_action_regime_flip_caution(self):
        """Regime flip + CAUTION = EXIT_HALF_POSITION."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            regime="CHOP",
        )
        assert decision.action == "EXIT_HALF_POSITION"

    def test_25_action_risk_emergency_immediate_exit(self):
        """Risk emergency always maps to IMMEDIATE_EXIT."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            data_health_critical=True,
        )
        assert decision.action == "IMMEDIATE_EXIT"


# =============================================================================
# SECTION 9: Session Management & Query Methods
# =============================================================================


class TestSessionManagement:
    """Tests for session lifecycle and query methods."""

    def test_26_intervention_history(self):
        """get_intervention_history returns all evaluations in order."""
        engine = InterventionEngine()
        sup_clean = make_supervisor()
        sup_critical = make_supervisor()

        # First evaluation: clean
        engine.evaluate_intervention(sup_clean)
        # Second evaluation: regime flip
        engine.evaluate_intervention(sup_critical, regime="CHOP")

        history = engine.get_intervention_history()
        assert len(history) == 2
        assert history[0].intervene is False
        assert history[1].intervene is True

    def test_27_intervention_count(self):
        """get_intervention_count counts only actual interventions."""
        engine = InterventionEngine()
        sup = make_supervisor()

        assert engine.get_intervention_count() == 0

        engine.evaluate_intervention(sup)  # no intervention
        assert engine.get_intervention_count() == 0

        engine.evaluate_intervention(
            make_supervisor(),
            regime="CHOP",
        )
        assert engine.get_intervention_count() == 1

    def test_28_total_evaluations(self):
        """get_total_evaluations counts all evaluations."""
        engine = InterventionEngine()
        sup = make_supervisor()

        assert engine.get_total_evaluations() == 0
        engine.evaluate_intervention(sup)
        assert engine.get_total_evaluations() == 1
        engine.evaluate_intervention(make_supervisor())
        assert engine.get_total_evaluations() == 2

    def test_29_latest_decision(self):
        """get_latest_decision returns most recent evaluation."""
        engine = InterventionEngine()
        sup = make_supervisor()

        assert engine.get_latest_decision() is None

        engine.evaluate_intervention(sup)
        first = engine.get_latest_decision()
        assert first is not None
        assert first.intervene is False

        engine.evaluate_intervention(make_supervisor(), regime="CHOP")
        second = engine.get_latest_decision()
        assert second is not None
        assert second.intervene is True

    def test_30_clear_session(self):
        """clear_session resets all state."""
        engine = InterventionEngine()
        sup = make_supervisor()

        engine.evaluate_intervention(sup, regime="CHOP")
        assert engine.get_total_evaluations() == 1
        assert engine.get_intervention_count() == 1

        engine.clear_session()
        assert engine.get_total_evaluations() == 0
        assert engine.get_intervention_count() == 0
        assert engine.get_latest_decision() is None

    def test_31_portfolio_risk_summary(self):
        """get_portfolio_risk_summary returns correct fields."""
        engine = InterventionEngine()
        sup = make_supervisor()

        summary = engine.get_portfolio_risk_summary()
        assert "total_evaluations" in summary
        assert "intervention_count" in summary
        assert "non_intervention_count" in summary
        assert "latest_intervention" in summary
        assert "latest_severity" in summary
        assert "latest_action" in summary
        assert "latest_trigger" in summary
        assert summary["total_evaluations"] == 0
        assert summary["intervention_count"] == 0

        engine.evaluate_intervention(sup, regime="CHOP")
        summary = engine.get_portfolio_risk_summary()
        assert summary["total_evaluations"] == 1
        assert summary["intervention_count"] == 1
        assert summary["latest_intervention"] is True

    def test_32_get_recent_interventions(self):
        """get_recent_interventions returns N most recent."""
        engine = InterventionEngine()
        sup = make_supervisor()

        for _ in range(5):
            engine.evaluate_intervention(sup)

        recent = engine.get_recent_interventions(count=3)
        assert len(recent) == 3


# =============================================================================
# SECTION 10: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_33_no_active_trade(self):
        """No active trade does not crash the engine."""
        engine = InterventionEngine()
        sup = make_supervisor()

        decision = engine.evaluate_intervention(
            sup,
            active_trade=None,
            regime="CHOP",
        )
        assert decision.intervene is True  # Regime flip still triggers

    def test_34_options_collapse_with_no_trade(self):
        """Options collapse check handles missing trade gracefully."""
        result = InterventionEngine._check_options_collapse(None, False)
        assert result[0] is False  # No trigger

    def test_35_trade_without_trade_class(self):
        """_determine_action falls back to ALERT_OPERATOR for unknown trigger."""
        action = InterventionEngine._determine_action("unknown_trigger", "EMERGENCY_OVERRIDE")
        assert action == "ALERT_OPERATOR"

    def test_36_empty_concerns_no_intervention(self):
        """Empty concerns + clean review = no intervention."""
        engine = InterventionEngine()
        sup = make_supervisor()

        review = make_review(
            thesis_intact=True,
            concerns=[],
            zone_valid=True,
            opposite_stronger=False,
            macro_shift=False,
            recommendation="THESIS_INTACT",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(sup)
        assert decision.intervene is False

    def test_37_all_5_scenarios_simultaneously(self):
        """All 5 scenarios triggering at once resolves to highest severity."""
        engine = InterventionEngine()
        sup = make_supervisor()
        trade = make_trade(trade_class=TradeClass.OPTIONS_PRESSURE)

        review = make_review(
            thesis_intact=False,
            concerns=["A", "B", "C"],
            zone_valid=False,
            opposite_stronger=True,
            macro_shift=True,
            recommendation="INTERVENTION_REQUIRED",
        )
        inject_review(sup, review)

        decision = engine.evaluate_intervention(
            sup,
            active_trade=trade,
            regime="CHOP",
            opposite_case_strength=0.9,
            options_oi_healthy=False,
            data_health_critical=False,
        )
        assert decision.intervene is True
        # Highest severity from thesis_break (3 critical failures) = EMERGENCY
        assert decision.severity == InterventionSeverity.EMERGENCY_OVERRIDE

    def test_38_reason_builds_correctly_for_no_intervention(self):
        """_build_no_intervention_reason produces reasonable messages."""
        reason_empty = InterventionEngine._build_no_intervention_reason([], "TREND_UP")
        assert "intact" in reason_empty

        reason_few = InterventionEngine._build_no_intervention_reason(
            ["Minor concern"], "CHOP"
        )
        assert "below structural break threshold" in reason_few

        reason_no_regime = InterventionEngine._build_no_intervention_reason(
            ["Concern 1"], ""
        )
        assert "concern" in reason_no_regime.lower()

    def test_39_intervention_decision_dataclass(self):
        """InterventionDecision dataclass fields work correctly."""
        decision = InterventionDecision(
            intervene=True,
            severity=InterventionSeverity.CAUTION,
            action="HEDGE_POSITION",
            reason="Test reason",
            trigger="regime_flip",
            details={"regime": "CHOP"},
        )
        assert decision.intervene is True
        assert decision.severity == InterventionSeverity.CAUTION
        assert decision.action == "HEDGE_POSITION"
        assert decision.trigger == "regime_flip"
        assert decision.details["regime"] == "CHOP"
        assert isinstance(decision.timestamp, datetime)

    def test_40_default_intervention_decision_is_no_intervention(self):
        """Default InterventionDecision has intervene=False."""
        decision = InterventionDecision()
        assert decision.intervene is False
        assert decision.severity == InterventionSeverity.NORMAL
        assert decision.action == ""
        assert decision.trigger == ""
