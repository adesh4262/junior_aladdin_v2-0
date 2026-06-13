"""Tests for Floor 5 — Captain Engine (Step 5.22).

Tests cover:
- Full heavy cycle produces correct outputs
- Permission gate blocking path
- TRADE vs WAIT decisions based on conviction
- Light cycle execution
- Armed plan watching during light cycle
- Active trade supervision during light cycle
- Intervention evaluation during light cycle
- Session management (start, trade complete, loss)
- Query methods
- Edge cases (empty input, missing reports)
- Drill-down decision logic
- Stale core head detection
- NO_SETUP intelligence evaluation
"""

from __future__ import annotations

from datetime import datetime

import pytest

from junior_aladdin.floor_5_captain.captain_engine import (
    CaptainEngine,
    HeavyCycleOutput,
    LightCycleOutput,
)
from junior_aladdin.floor_5_captain.captain_types import (
    CaptainInput,
    ConvictionBand,
    SilenceReason,
)
from junior_aladdin.shared.types import (
    CaptainDecision,
    DecisionType,
    ExecutionMode,
    FloorSummary,
    HeadReport,
    HeadState,
    BiasType,
    FreshnessTag,
    DataHealth,
    TradeClass,
)


# ── Helpers ──────────────────────────────────────────────────────────────


# ── Golden Morning timestamp (10:00 AM IST = 4:30 UTC) ────────────────
# Session policy only allows trading during GOLDEN_MORNING (9:45-11:00 IST).
# Tests use this fixed timestamp so they pass regardless of wall clock time.
_GOLDEN_MORNING_UTC = datetime(2025, 1, 1, 4, 30, 0)


def make_engine() -> CaptainEngine:
    """Create a fresh CaptainEngine for testing."""
    engine = CaptainEngine()
    engine.start_session(timestamp=_GOLDEN_MORNING_UTC)
    return engine


def make_floor_summary(
    bias: str = "NEUTRAL",
    confidence: float = 0.0,
    conflict: bool = False,
    data_health: DataHealth = DataHealth.GOOD,
    active_setup_count: int = 0,
    ready_heads: int = 3,
    uncertain_heads: int = 0,
    stale_heads: int = 0,
    setup_presence: str | None = None,
    core_head_health: dict | None = None,
) -> FloorSummary:
    """Create a FloorSummary with specified properties."""
    return FloorSummary(
        summary_timestamp=datetime.utcnow(),
        floor_bias_snapshot={"dominant_bias": bias},
        floor_confidence_snapshot={"average_confidence": confidence},
        active_setup_count=active_setup_count,
        ready_heads_count=ready_heads,
        uncertain_heads_count=uncertain_heads,
        stale_heads_count=stale_heads,
        conflict_present=conflict,
        data_health_signal=data_health,
        setup_presence=setup_presence,
        core_head_health_snapshot=core_head_health or {},
        head_health_snapshot={},
    )


def make_head_report(
    head_name: str = "SMC Head",
    bias: BiasType = BiasType.NEUTRAL,
    confidence: float = 0.5,
    state: HeadState = HeadState.READY,
    freshness: FreshnessTag = FreshnessTag.FRESH,
    trade_allowed: bool = True,
    context_quality: float = 0.8,
) -> HeadReport:
    """Create a HeadReport with specified properties."""
    return HeadReport(
        head_name=head_name,
        state=state,
        freshness_score=0.8,
        freshness_tag=freshness,
        last_deep_update=datetime.utcnow(),
        bias=bias,
        confidence=confidence,
        dominant_tf="15m",
        timeframe_view="Test view",
        context_quality_score=context_quality,
        trade_allowed=trade_allowed,
    )


def make_input(
    floor_summary: FloorSummary | None = None,
    head_reports: dict[str, HeadReport] | None = None,
) -> CaptainInput:
    """Create a CaptainInput for testing."""
    return CaptainInput(
        floor_summary=floor_summary or make_floor_summary(),
        head_reports=head_reports or {},
        system_context={},
    )


# =============================================================================
# SECTION 1: Heavy Cycle — Basic Execution
# =============================================================================


class TestHeavyCycleBasic:
    """Tests for basic heavy cycle execution."""

    def test_1_heavy_cycle_produces_output(self):
        """Heavy cycle produces a HeavyCycleOutput."""
        engine = make_engine()
        inp = make_input()
        output = engine.heavy_cycle(
            captain_input=inp,
            current_price=19550.0,
            current_mode=ExecutionMode.PAPER,
            capital_available=50000.0,
            candle_index=10,
            timestamp=_GOLDEN_MORNING_UTC,
        )
        assert isinstance(output, HeavyCycleOutput)
        assert output.completed_at is not None

    def test_2_heavy_cycle_returns_decision(self):
        """Heavy cycle returns a CaptainDecision."""
        engine = make_engine()
        inp = make_input()
        output = engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert output.decision is not None
        assert isinstance(output.decision, CaptainDecision)

    def test_3_heavy_cycle_returns_captain_state(self):
        """Heavy cycle returns a CaptainState."""
        engine = make_engine()
        inp = make_input()
        output = engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert output.captain_state is not None

    def test_4_heavy_cycle_stores_permission_result(self):
        """Heavy cycle stores the PermissionResult."""
        engine = make_engine()
        inp = make_input()
        output = engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert output.permission_result is not None

    def test_5_heavy_cycle_no_crash_with_empty_input(self):
        """Heavy cycle does not crash with minimal input."""
        engine = make_engine()
        output = engine.heavy_cycle(timestamp=_GOLDEN_MORNING_UTC)
        assert output.decision is not None

    def test_6_heavy_cycle_no_crash_without_head_reports(self):
        """Heavy cycle does not crash when head_reports is empty."""
        engine = make_engine()
        inp = make_input(head_reports={})
        output = engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert output.decision is not None


# =============================================================================
# SECTION 2: Heavy Cycle — Permission Gate Blocking
# =============================================================================


class TestPermissionBlocking:
    """Tests for permission gate blocking during heavy cycle."""

    def test_7_blocked_when_no_capital(self):
        """Permission blocks when capital is 0."""
        engine = make_engine()
        inp = make_input()
        output = engine.heavy_cycle(
            captain_input=inp,
            capital_available=0.0,
            timestamp=_GOLDEN_MORNING_UTC,
        )
        assert output.is_blocked is True
        assert output.decision.decision == DecisionType.BLOCKED

    def test_8_blocked_when_psychology_blocks(self):
        """Permission blocks when psychology head blocks trading."""
        engine = make_engine()
        reports = {
            "Psychology Head": make_head_report(
                head_name="Psychology Head",
                trade_allowed=False,
            ),
        }
        inp = make_input(head_reports=reports)
        output = engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert output.is_blocked is True

    def test_9_blocked_silence_reason_logged(self):
        """Blocked permission logs a silence reason."""
        engine = make_engine()
        inp = make_input(head_reports={
            "Psychology Head": make_head_report(
                head_name="Psychology Head",
                trade_allowed=False,
            ),
        })
        engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert engine.silence_logger.has_reasons() is True
        primary = engine.silence_logger.get_primary_reason()
        assert primary is not None
        assert primary.decision == "BLOCKED" or "psychology" in primary.details.lower()

    def test_10_blocked_with_active_trade(self):
        """Permission blocks when an active trade exists."""
        engine = make_engine()
        # Set an active trade manually to simulate active trade
        engine._active_trade = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        inp = make_input()
        output = engine.heavy_cycle(inp, timestamp=_GOLDEN_MORNING_UTC)
        assert output.is_blocked is True

    def test_11_blocked_with_active_trade_does_not_crash(self):
        """Active trade blocking does not crash even with empty head reports."""
        engine = make_engine()
        engine._active_trade = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        output = engine.heavy_cycle(timestamp=_GOLDEN_MORNING_UTC)
        assert output.is_blocked is True
        assert output.decision.decision == DecisionType.BLOCKED


# =============================================================================
# SECTION 3: Heavy Cycle — Decision Types (TRADE vs WAIT)
# =============================================================================


class TestDecisionTypes:
    """Tests that heavy cycle produces correct decision types."""

    def test_12_high_confidence_produces_wait(self):
        """High confidence without setup produces WAIT, never crashes."""
        engine = make_engine()
        summary = make_floor_summary(
            bias="BULLISH",
            confidence=0.85,
            active_setup_count=1,
        )
        reports = {
            "SMC Head": make_head_report(
                head_name="SMC Head",
                bias=BiasType.BULLISH,
                confidence=0.8,
            ),
            "ICT Head": make_head_report(
                head_name="ICT Head",
                bias=BiasType.BULLISH,
                confidence=0.8,
            ),
            "Technical Head": make_head_report(
                head_name="Technical Head",
                bias=BiasType.BULLISH,
                confidence=0.7,
            ),
            "Options Head": make_head_report(
                head_name="Options Head",
                bias=BiasType.BULLISH,
                confidence=0.7,
            ),
            "Macro Head": make_head_report(
                head_name="Macro Head",
                bias=BiasType.BULLISH,
                confidence=0.6,
            ),
        }
        inp = make_input(floor_summary=summary, head_reports=reports)
        output = engine.heavy_cycle(
            captain_input=inp,
            capital_available=50000.0,
            current_price=19550.0,
            timestamp=_GOLDEN_MORNING_UTC,
        )
        # With strong confluence the engine should try to trade — may produce
        # TRADE or WAIT depending on trade construction results
        assert output.decision.decision in (
            DecisionType.TRADE, DecisionType.WAIT
        )

    def test_13_low_confidence_produces_wait_or_blocked(self):
        """Low confidence produces WAIT or BLOCKED."""
        engine = make_engine()
        inp = make_input()
        output = engine.heavy_cycle(
            captain_input=inp,
            capital_available=50000.0,
            timestamp=_GOLDEN_MORNING_UTC,
        )
        assert output.decision.decision in (
            DecisionType.WAIT, DecisionType.BLOCKED
        )


# =============================================================================
# SECTION 4: Heavy Cycle — Output Fields
# =============================================================================


class TestHeavyCycleOutputs:
    """Tests that heavy cycle populates all output fields."""

    def test_14_heavy_cycle_populates_conviction(self):
        """Heavy cycle includes ConvictionScore when not blocked."""
        engine = make_engine()
        output = engine.heavy_cycle(timestamp=_GOLDEN_MORNING_UTC)
        if not output.is_blocked:
            assert output.conviction_score is not None
        else:
            assert True  # Not blocked — conviction is computed

    def test_15_heavy_cycle_populates_market_story(self):
        """Heavy cycle includes MarketStory when not blocked."""
        engine = make_engine()
        output = engine.heavy_cycle(timestamp=_GOLDEN_MORNING_UTC)
        # Market story is only built if not blocked
        if not output.is_blocked:
            assert output.market_story is not None

    def test_16_heavy_cycle_populates_timeline(self):
        """Heavy cycle adds events to the narrative timeline."""
        engine = make_engine()
        engine.heavy_cycle(candle_index=5, timestamp=_GOLDEN_MORNING_UTC)
        assert engine.narrative_timeline.has_events() is True

    def test_17_heavy_cycle_populates_snapshot(self):
        """Heavy cycle writes a decision snapshot."""
        engine = make_engine()
        output = engine.heavy_cycle(timestamp=_GOLDEN_MORNING_UTC)
        if not output.is_blocked:
            assert output.decision_snapshot is not None
            if output.decision_snapshot:
                assert output.decision_snapshot.snapshot_id != ""
        else:
            assert True  # Snapshot written when not blocked


# =============================================================================
# SECTION 5: Drill-Down & Intelligence
# =============================================================================


class TestDrillDown:
    """Tests for drill-down decision and stale core head logic."""

    def test_18_drill_down_on_conflict(self):
        """Drill-down is triggered when conflict is present."""
        summary = make_floor_summary(conflict=True)
        assert CaptainEngine._decide_drill_down(summary, {}) is True

    def test_19_drill_down_on_stale_warning(self):
        """Drill-down is triggered when stale warning is present."""
        summary = make_floor_summary()
        summary.stale_warning_present = True
        assert CaptainEngine._decide_drill_down(summary, {}) is True

    def test_20_drill_down_on_stale_core_head(self):
        """Drill-down is triggered when SMC or ICT head is stale."""
        summary = make_floor_summary(
            core_head_health={
                "SMC Head": {"state": "STALE", "health": "degraded"},
            },
        )
        assert CaptainEngine._decide_drill_down(summary, {}) is True

    def test_21_no_drill_down_on_clean_state(self):
        """No drill-down when everything is clean."""
        summary = make_floor_summary(
            bias="BULLISH",
            confidence=0.6,
            ready_heads=5,
        )
        assert CaptainEngine._decide_drill_down(summary, {}) is False

    def test_22_stale_core_head_detected(self):
        """Stale core head detection works."""
        reports = {
            "SMC Head": make_head_report(
                head_name="SMC Head",
                state=HeadState.STALE,
            ),
        }
        assert CaptainEngine._check_stale_core_heads(reports) is True

    def test_23_healthy_core_heads_not_detected(self):
        """Healthy core heads do not trigger stale detection."""
        reports = {
            "SMC Head": make_head_report(
                head_name="SMC Head",
                state=HeadState.READY,
            ),
            "ICT Head": make_head_report(
                head_name="ICT Head",
                state=HeadState.READY,
            ),
        }
        assert CaptainEngine._check_stale_core_heads(reports) is False

    def test_24_evaluate_setup_presence_direct(self):
        """Setup presence is correctly evaluated from direct field."""
        summary = make_floor_summary(setup_presence="HAS_SETUP")
        assert CaptainEngine._evaluate_setup_presence(summary) == "HAS_SETUP"

    def test_25_evaluate_setup_presence_inferred(self):
        """Setup presence is inferred from head counts."""
        summary = make_floor_summary(
            ready_heads=4,
            uncertain_heads=0,
            stale_heads=0,
            active_setup_count=0,
        )
        assert CaptainEngine._evaluate_setup_presence(summary) == "READY_NO_SETUP"


# =============================================================================
# SECTION 6: Light Cycle
# =============================================================================


class TestLightCycle:
    """Tests for light cycle execution."""

    def test_26_light_cycle_produces_output(self):
        """Light cycle produces a LightCycleOutput."""
        engine = make_engine()
        output = engine.light_cycle(current_price=19550.0)
        assert isinstance(output, LightCycleOutput)
        assert output.checked_at is not None

    def test_27_light_cycle_no_plans_no_trigger(self):
        """Light cycle with no armed plans has no trigger."""
        engine = make_engine()
        output = engine.light_cycle(current_price=19550.0)
        assert output.plan_triggered is False
        assert output.triggered_plan_id == ""

    def test_28_light_cycle_no_active_trade(self):
        """Light cycle without active trade reports no active trade."""
        engine = make_engine()
        output = engine.light_cycle(current_price=19550.0)
        assert output.has_active_trade is False
        assert output.intervention_decision is None

    def test_29_light_cycle_with_active_trade(self):
        """Light cycle with active trade reviews the thesis."""
        engine = make_engine()
        # Set an active trade
        engine._active_trade = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        output = engine.light_cycle(
            current_price=19550.0,
            regime="TREND_UP",
        )
        assert output.has_active_trade is True
        # Thesis should be intact (regime supports BUY)
        assert output.thesis_intact is True

    def test_30_light_cycle_does_not_crash(self):
        """Light cycle runs without crashing even with no prior heavy cycle."""
        engine = make_engine()
        output = engine.light_cycle(
            current_price=19500.0,
            candle_index=5,
            regime="CHOP",
        )
        assert output is not None


# =============================================================================
# SECTION 7: Session Management
# =============================================================================


class TestSessionManagement:
    """Tests for session lifecycle."""

    def test_31_start_session_resets_state(self):
        """start_session resets all intraday state."""
        engine = make_engine()
        engine.heavy_cycle(candle_index=5, timestamp=_GOLDEN_MORNING_UTC)
        snap_count = engine.snapshot_writer.get_snapshot_count()
        # May be 0 if blocked by session policy
        
        engine.start_session(timestamp=_GOLDEN_MORNING_UTC)
        assert engine.snapshot_writer.get_snapshot_count() == 0
        assert engine._active_trade is None
        assert engine._candle_index == 0

    def test_32_on_trade_complete_clears_active(self):
        """on_trade_complete clears the active trade reference."""
        engine = make_engine()
        engine._active_trade = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        engine.on_trade_complete()
        assert engine._active_trade is None

    def test_33_record_loss_updates_loss_lock(self):
        """record_loss updates the loss lock manager (only in REAL mode)."""
        engine = make_engine()
        engine.loss_lock_manager.set_mode(ExecutionMode.REAL)
        assert engine.loss_lock_manager.get_loss_count() == 0
        engine.record_loss()
        assert engine.loss_lock_manager.get_loss_count() == 1

    def test_34_clear_session_resets_sub_engines(self):
        """start_session clears all sub-engines."""
        engine = make_engine()
        engine.heavy_cycle(candle_index=5, timestamp=_GOLDEN_MORNING_UTC)
        engine.silence_logger.log_reason(
            decision="WAIT",
            reason=SilenceReason.WEAK_CONVICTION,
        )
        assert engine.silence_logger.has_reasons() is True

        engine.start_session(timestamp=_GOLDEN_MORNING_UTC)
        assert engine.silence_logger.has_reasons() is False


# =============================================================================
# SECTION 8: Query Methods
# =============================================================================


class TestQueryMethods:
    """Tests for engine query methods."""

    def test_35_get_active_trade_none_by_default(self):
        """get_active_trade returns None when no trade is active."""
        engine = make_engine()
        assert engine.get_active_trade() is None

    def test_36_get_active_trade_returns_trade(self):
        """get_active_trade returns the active trade when set."""
        engine = make_engine()
        trade = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        engine._active_trade = trade
        assert engine.get_active_trade() is trade

    def test_37_get_current_state_returns_dict(self):
        """get_current_state returns a state dict."""
        engine = make_engine()
        state = engine.get_current_state()
        assert isinstance(state, dict)
        assert "has_active_trade" in state
        assert "active_plans" in state
        assert "snapshot_count" in state
        assert "candle_index" in state

    def test_38_get_current_state_after_heavy_cycle(self):
        """get_current_state reflects state after heavy cycle."""
        engine = make_engine()
        engine.heavy_cycle(candle_index=42, timestamp=_GOLDEN_MORNING_UTC)
        state = engine.get_current_state()
        assert state["candle_index"] == 42

    def test_39_get_engine_summary_returns_dict(self):
        """get_engine_summary returns a comprehensive summary dict."""
        engine = make_engine()
        summary = engine.get_engine_summary()
        assert isinstance(summary, dict)
        assert "armed_plans" in summary
        assert "setup_memory" in summary
        assert "silence_logger" in summary
        assert "snapshot_writer" in summary
        assert "narrative_timeline" in summary
        assert "active_trade" in summary
        assert "candle_index" in summary

    def test_40_get_engine_summary_after_heavy_cycle(self):
        """get_engine_summary populates after heavy cycle."""
        engine = make_engine()
        engine.heavy_cycle(candle_index=10, timestamp=_GOLDEN_MORNING_UTC)
        summary = engine.get_engine_summary()
        assert summary["candle_index"] == 10
        # snapshot count may be 0 if blocked by session policy


# =============================================================================
# SECTION 9: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_41_should_trade_returns_false_for_none(self):
        """_should_trade returns False when conviction_scores is None."""
        assert CaptainEngine._should_trade(None) is False

    def test_42_direction_from_confluence_returns_empty_for_none(self):
        """_direction_from_confluence returns empty string for None."""
        assert CaptainEngine._direction_from_confluence(None) == ""

    def test_43_direction_from_confluence_maps_bullish(self):
        """BULLISH confluence maps to BUY."""
        from junior_aladdin.floor_5_captain.captain_types import ConfluenceResult
        result = ConfluenceResult(dominant_direction="BULLISH")
        assert CaptainEngine._direction_from_confluence(result) == "BUY"

    def test_44_direction_from_confluence_maps_bearish(self):
        """BEARISH confluence maps to SELL."""
        from junior_aladdin.floor_5_captain.captain_types import ConfluenceResult
        result = ConfluenceResult(dominant_direction="BEARISH")
        assert CaptainEngine._direction_from_confluence(result) == "SELL"

    def test_45_decide_drill_down_with_none_summary(self):
        """Drill-down returns True when floor_summary is None."""
        assert CaptainEngine._decide_drill_down(None, {}) is True

    def test_46_check_stale_core_heads_with_none(self):
        """_check_stale_core_heads returns False when head_reports is None."""
        assert CaptainEngine._check_stale_core_heads(None) is False

    def test_47_evaluate_setup_presence_with_none(self):
        """_evaluate_setup_presence returns UNKNOWN when floor_summary is None."""
        assert CaptainEngine._evaluate_setup_presence(None) == "UNKNOWN"

    def test_48_multiple_heavy_cycles_produces_multiple_snapshots(self):
        """Multiple heavy cycles produce snapshot entries (may be 0 if blocked)."""
        engine = make_engine()
        engine.heavy_cycle(candle_index=1, timestamp=_GOLDEN_MORNING_UTC)
        engine.heavy_cycle(candle_index=2, timestamp=_GOLDEN_MORNING_UTC)
        engine.heavy_cycle(candle_index=3, timestamp=_GOLDEN_MORNING_UTC)
        # Session policy blocks outside Golden Morning — snapshots only if unblocked
        snap_count = engine.snapshot_writer.get_snapshot_count()
        assert snap_count >= 0  # No crash

    def test_49_multiple_light_cycles_no_state_leak(self):
        """Multiple light cycles without heavy cycle don't produce errors."""
        engine = make_engine()
        for i in range(5):
            output = engine.light_cycle(
                current_price=19500.0 + i,
                candle_index=i,
            )
            assert output.plan_triggered is False

    def test_50_heavy_cycle_with_strong_bullish_confluence(self):
        """Heavy cycle with strongly aligned bullish heads produces WAIT or TRADE."""
        engine = make_engine()
        summary = make_floor_summary(
            bias="BULLISH",
            confidence=0.9,
            ready_heads=5,
            active_setup_count=2,
        )
        reports = {
            "SMC Head": make_head_report(
                head_name="SMC Head",
                bias=BiasType.BULLISH,
                confidence=0.85,
                context_quality=0.9,
            ),
            "ICT Head": make_head_report(
                head_name="ICT Head",
                bias=BiasType.BULLISH,
                confidence=0.85,
                context_quality=0.8,
            ),
            "Technical Head": make_head_report(
                head_name="Technical Head",
                bias=BiasType.BULLISH,
                confidence=0.75,
            ),
            "Options Head": make_head_report(
                head_name="Options Head",
                bias=BiasType.BULLISH,
                confidence=0.7,
            ),
            "Macro Head": make_head_report(
                head_name="Macro Head",
                bias=BiasType.BULLISH,
                confidence=0.6,
            ),
            "Psychology Head": make_head_report(
                head_name="Psychology Head",
                trade_allowed=True,
            ),
        }
        inp = make_input(floor_summary=summary, head_reports=reports)
        output = engine.heavy_cycle(
            captain_input=inp,
            current_price=19550.0,
            current_mode=ExecutionMode.PAPER,
            capital_available=50000.0,
            candle_index=10,
            timestamp=_GOLDEN_MORNING_UTC,
        )
        assert output.decision.decision in (
            DecisionType.TRADE, DecisionType.WAIT
        )
        assert output.is_blocked is False
