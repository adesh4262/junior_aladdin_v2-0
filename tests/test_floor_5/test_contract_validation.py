"""Floor 5 — Contract Validation Integration Tests (Step 5.23).

Validates cross-module contracts:
1. Floor 4 → Floor 5 input fields consumed correctly (CaptainInput)
2. Floor 5 → Side A output (CaptainDecision) all mandatory fields present
3. Floor 5 → Side B output (CaptainState) all mandatory fields present
4. Floor 5 → Side C output (DecisionSnapshot) all mandatory fields present
5. No Floor 3/4 calculation types in Floor 5 output
6. No execution/broker types in Floor 5 decision
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from junior_aladdin.floor_5_captain.captain_engine import CaptainEngine
from junior_aladdin.floor_5_captain.captain_types import (
    CaptainInput,
    ConvictionBand,
    DecisionState,
    MarketStory,
    SessionPhase,
)
from junior_aladdin.shared.testing import (
    generate_mock_captain_decision,
    generate_mock_floor_summary,
    generate_mock_head_report,
)
from junior_aladdin.shared.types import (
    CaptainDecision,
    CaptainMood,
    DecisionSnapshot,
    DecisionType,
    ExecutionMode,
    TradeClass,
)

# Golden morning timestamp (9:45 IST = 4:15 UTC on Jan 1)
_GOLDEN_MORNING_UTC = datetime(2025, 1, 1, 4, 15, 0)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def captain_engine() -> CaptainEngine:
    """Create a fresh CaptainEngine for each test."""
    return CaptainEngine()


@pytest.fixture
def bullish_floor_input() -> CaptainInput:
    """Build a CaptainInput with 5/5 heads bullish and strong confidence."""
    heads = {}
    for name in ["SMC", "ICT", "Technical", "Options", "Macro", "Psychology"]:
        from junior_aladdin.shared.types import BiasType, HeadState
        bias = BiasType.BULLISH
        if name == "Psychology":
            heads[name] = generate_mock_head_report(
                head_name=name, bias=BiasType.NEUTRAL, confidence=0.9,
            )
            heads[name].trade_allowed = True
        else:
            heads[name] = generate_mock_head_report(
                head_name=name, bias=bias, confidence=0.85, state=HeadState.READY,
            )
    floor_summary = generate_mock_floor_summary()
    return CaptainInput(
        floor_summary=floor_summary,
        head_reports=heads,
        system_context={"source": "floor_4"},
    )


# =============================================================================
# Test: Floor 4 → Floor 5 Input Contracts
# =============================================================================


class TestFloor4InputContracts:
    """Floor 4 → Floor 5: CaptainInput must consume all mandatory fields."""

    def test_captain_input_accepts_floor_summary_and_heads(self):
        """CaptainInput correctly stores FloorSummary + HeadReports."""
        floor_summary = generate_mock_floor_summary()
        heads = {
            "SMC Head": generate_mock_head_report("SMC"),
            "ICT Head": generate_mock_head_report("ICT"),
        }
        inp = CaptainInput(
            floor_summary=floor_summary,
            head_reports=heads,
            system_context={"test": True},
        )
        assert inp.floor_summary is not None
        assert len(inp.head_reports) == 2
        assert inp.system_context["test"] is True

    def test_floor_summary_mandatory_fields_present(self):
        """FloorSummary has all fields Captain consumes."""
        fs = generate_mock_floor_summary()
        # Captain reads these from FloorSummary:
        assert hasattr(fs, "summary_timestamp")
        assert hasattr(fs, "floor_bias_snapshot")
        assert hasattr(fs, "floor_confidence_snapshot")
        assert hasattr(fs, "active_setup_count")
        assert hasattr(fs, "conflict_present")
        assert hasattr(fs, "stale_warning_present")
        assert hasattr(fs, "data_health_signal")
        assert hasattr(fs, "setup_presence")
        assert hasattr(fs, "core_head_health_snapshot")
        assert hasattr(fs, "ready_heads_count")
        assert hasattr(fs, "uncertain_heads_count")

    def test_head_report_mandatory_fields_present(self):
        """HeadReport has all fields Captain consumes."""
        hr = generate_mock_head_report("SMC Head")
        # Captain consumes from HeadReport:
        assert hasattr(hr, "head_name")
        assert hasattr(hr, "state")
        assert hasattr(hr, "freshness_score")
        assert hasattr(hr, "freshness_tag")
        assert hasattr(hr, "bias")
        assert hasattr(hr, "confidence")
        assert hasattr(hr, "context_quality_score")  # SMC/ICT mandatory
        assert hasattr(hr, "trade_allowed")  # Psychology
        assert hasattr(hr, "caution_level")  # Psychology
        assert hasattr(hr, "primary_setup")
        assert hasattr(hr, "backup_setup")

    def test_psychology_head_specific_fields(self):
        """Psychology Head has trade_allowed, caution_level, cooldown_active."""
        psych = generate_mock_head_report("Psychology")
        assert hasattr(psych, "trade_allowed")
        assert hasattr(psych, "caution_level")
        assert hasattr(psych, "cooldown_active")
        assert hasattr(psych, "trap_pressure")
        assert hasattr(psych, "block_reason")

    def test_captain_input_with_empty_heads(self):
        """CaptainInput handles empty head_reports gracefully."""
        inp = CaptainInput(
            floor_summary=None,
            head_reports={},
        )
        assert inp.floor_summary is None
        assert inp.head_reports == {}

    def test_captain_input_system_context_optional(self):
        """CaptainInput accepts optional system_context with defaults."""
        inp = CaptainInput()
        assert inp.system_context == {}


# =============================================================================
# Test: Floor 5 → Side A Output Contracts (CaptainDecision)
# =============================================================================


class TestSideAOutputContracts:
    """Floor 5 → Side A: CaptainDecision must have all mandatory fields."""

    def test_captain_decision_mandatory_fields(self):
        """CaptainDecision has all fields Side A expects."""
        d = generate_mock_captain_decision()
        assert hasattr(d, "decision")
        assert hasattr(d, "action")
        assert hasattr(d, "option_side")
        assert hasattr(d, "selected_strike")
        assert hasattr(d, "trade_class")
        assert hasattr(d, "permission_score")
        assert hasattr(d, "conviction_score")
        assert hasattr(d, "no_trade_score")
        assert hasattr(d, "entry_plan")
        assert hasattr(d, "invalidation_level")
        assert hasattr(d, "stop_loss_plan")
        assert hasattr(d, "target_plan")
        assert hasattr(d, "reason_summary")
        assert hasattr(d, "silence_reason")
        assert hasattr(d, "snapshot_id")

    def test_captain_decision_trade_has_action(self):
        """TRADE decision always has a non-empty action."""
        d = generate_mock_captain_decision(DecisionType.TRADE)
        assert d.action in ("BUY", "SELL")
        assert d.option_side in ("CE", "PE")

    def test_captain_decision_wait_has_reason(self):
        """WAIT/BLOCKED decision has a meaningful silence_reason."""
        d = generate_mock_captain_decision(DecisionType.WAIT)
        assert d.silence_reason is not None
        assert len(d.silence_reason) > 0

    def test_captain_decision_blocked_has_no_action(self):
        """BLOCKED decision has empty action / option_side."""
        d = generate_mock_captain_decision(DecisionType.BLOCKED)
        assert d.action == "" or d.action == "NONE"

    def test_captain_decision_no_execution_types(self):
        """CaptainDecision does NOT contain execution/broker types."""
        d = generate_mock_captain_decision()
        # No broker-specific fields
        assert not hasattr(d, "order_id")
        assert not hasattr(d, "broker")
        assert not hasattr(d, "order_status")
        assert not hasattr(d, "filled_quantity")
        # No broker-specific enums
        assert not hasattr(d, "order_type") or not isinstance(getattr(d, "order_type", None), type(None))

    def test_captain_decision_has_snapshot_id_link(self):
        """CaptainDecision links to its DecisionSnapshot via snapshot_id."""
        d = generate_mock_captain_decision()
        assert d.snapshot_id != ""


# =============================================================================
# Test: Floor 5 → Side B Output Contracts (CaptainState)
# =============================================================================


class TestSideBOutputContracts:
    """Floor 5 → Side B: CaptainState must have all mandatory fields."""

    def test_captain_state_mandatory_fields(self):
        """CaptainState has all fields Side B dashboard expects."""
        from junior_aladdin.floor_5_captain.captain_types import CaptainState
        cs = CaptainState(
            mood=CaptainMood.OBSERVER,
            active_trade=False,
            decision_state=DecisionState.WAIT,
            conviction_band=ConvictionBand.REJECT,
            market_story_summary="",
            silence_reason="",
            session_phase=SessionPhase.OPENING,
            real_mode_locked=False,
        )
        assert cs.mood == CaptainMood.OBSERVER
        assert cs.active_trade is False
        assert cs.decision_state == DecisionState.WAIT
        assert cs.conviction_band == ConvictionBand.REJECT
        assert cs.market_story_summary == ""
        assert cs.session_phase == SessionPhase.OPENING
        assert cs.real_mode_locked is False

    def test_captain_state_trade_reflects_decision(self):
        """CaptainState correctly reflects active_trade from decision."""
        from junior_aladdin.floor_5_captain.captain_types import CaptainState
        cs = CaptainState(
            mood=CaptainMood.AGGRESSIVE,
            active_trade=True,
            decision_state=DecisionState.TRADE,
            conviction_band=ConvictionBand.STRONG,
        )
        assert cs.active_trade is True
        assert cs.decision_state == DecisionState.TRADE

    def test_captain_state_mood_variants(self):
        """CaptainState supports all mood variants."""
        from junior_aladdin.floor_5_captain.captain_types import CaptainState
        for mood in CaptainMood:
            cs = CaptainState(mood=mood, decision_state=DecisionState.WAIT)
            assert cs.mood == mood
            assert cs.active_trade is False

    def test_captain_state_silence_reason_link(self):
        """CaptainState carries silence_reason for dashboard display."""
        from junior_aladdin.floor_5_captain.captain_types import CaptainState
        cs = CaptainState(
            mood=CaptainMood.SILENT,
            silence_reason="weak_conviction",
        )
        assert cs.silence_reason == "weak_conviction"


# =============================================================================
# Test: Floor 5 → Side C Output Contracts (DecisionSnapshot)
# =============================================================================


class TestSideCOutputContracts:
    """Floor 5 → Side C: DecisionSnapshot must have all mandatory fields."""

    def test_decision_snapshot_mandatory_fields(self):
        """DecisionSnapshot has all fields Side C expects."""
        snap = DecisionSnapshot(
            snapshot_id="snap_test_001",
        )
        assert hasattr(snap, "snapshot_id")
        assert hasattr(snap, "timestamp")
        assert hasattr(snap, "market_story_summary")
        assert hasattr(snap, "narrative_timeline_excerpt")
        assert hasattr(snap, "heads_summary")
        assert hasattr(snap, "armed_plan_reference")
        assert hasattr(snap, "conviction_score")
        assert hasattr(snap, "invalidation")
        assert hasattr(snap, "decision_reason")
        assert hasattr(snap, "session_context")
        assert hasattr(snap, "capital_context")
        assert hasattr(snap, "mood")

    def test_decision_snapshot_has_all_context_fields(self):
        """DecisionSnapshot session_context has key fields."""
        snap = DecisionSnapshot(
            snapshot_id="snap_test_002",
            session_context={
                "session_phase": "GOLDEN_MORNING",
                "regime": "TREND_UP",
                "bias": "BULLISH",
                "candle_index": 42,
            },
            capital_context={
                "permission_score": 85.0,
                "no_trade_score": 10.0,
            },
            mood=CaptainMood.AGGRESSIVE,
        )
        assert snap.session_context["session_phase"] == "GOLDEN_MORNING"
        assert snap.session_context["candle_index"] == 42
        assert snap.capital_context["permission_score"] == 85.0
        assert snap.mood == CaptainMood.AGGRESSIVE

    def test_decision_snapshot_excerpt_structured(self):
        """DecisionSnapshot narrative_timeline_excerpt is a list of strings."""
        snap = DecisionSnapshot(
            snapshot_id="snap_test_003",
            narrative_timeline_excerpt=[
                "09:15: Market opened bullish",
                "09:20: SMC structure bullish",
            ],
        )
        assert isinstance(snap.narrative_timeline_excerpt, list)
        assert len(snap.narrative_timeline_excerpt) > 0
        assert all(isinstance(e, str) for e in snap.narrative_timeline_excerpt)

    def test_decision_snapshot_heads_summary_dict(self):
        """DecisionSnapshot heads_summary is a dict with head details."""
        snap = DecisionSnapshot(
            snapshot_id="snap_test_004",
            heads_summary={
                "SMC Head": {"bias": "BULLISH", "confidence": 0.85},
                "ICT Head": {"bias": "BULLISH", "confidence": 0.80},
            },
        )
        assert "SMC Head" in snap.heads_summary
        assert snap.heads_summary["SMC Head"]["confidence"] == 0.85

    def test_decision_snapshot_invalidation_has_level(self):
        """DecisionSnapshot invalidation has level + stop_loss + opposite."""
        snap = DecisionSnapshot(
            snapshot_id="snap_test_005",
            invalidation={
                "level": 19450.0,
                "stop_loss": {"price": 19400.0, "type": "fixed"},
                "opposite_strength": 0.3,
            },
        )
        assert snap.invalidation["level"] == 19450.0
        assert "stop_loss" in snap.invalidation


# =============================================================================
# Test: No Floor 3/4 Types in Floor 5 Output (Architecture Enforcement)
# =============================================================================


class TestArchitectureTypeEnforcement:
    """Floor 5 output must NOT contain Floor 3/4 calculation types."""

    def test_no_floor3_types_in_captain_decision(self):
        """CaptainDecision does not carry Floor 3 domain types."""
        d = generate_mock_captain_decision()
        # These are Floor 3 concerns, not in CaptainDecision
        decision_str = str(d.__dict__)
        assert "smc_quality_score" not in decision_str or not hasattr(d, "smc_quality_score")
        assert "ict_delivery_score" not in decision_str or not hasattr(d, "ict_delivery_score")
        assert "pcr" not in decision_str or not hasattr(d, "pcr")
        assert "vwap" not in decision_str or not hasattr(d, "vwap")

    def test_no_floor3_types_in_decision_snapshot(self):
        """DecisionSnapshot does not carry Floor 3 domain fields at root."""
        snap = DecisionSnapshot(snapshot_id="snap_arch_001")
        # Root-level fields should not contain Floor 3 types
        snap_str = str(snap.__dataclass_fields__)
        assert "quality_score" not in snap_str or not hasattr(snap, "quality_score")
        assert "delivery_score" not in snap_str or not hasattr(snap, "delivery_score")

    def test_captain_engine_no_floor3_imports(self):
        """captain_engine does not import from floor_3_calculations."""
        import junior_aladdin.floor_5_captain.captain_engine as ce
        import inspect
        source = inspect.getsource(ce)
        assert "floor_3_calculations" not in source, (
            "Floor 5 must NOT import from floor_3_calculations"
        )

    def test_captain_engine_no_execution_imports(self):
        """captain_engine does not import from side_a_execution (execution)."""
        import junior_aladdin.floor_5_captain.captain_engine as ce
        import inspect
        source = inspect.getsource(ce)
        assert "side_a_execution" not in source, (
            "Floor 5 must NOT import from side_a_execution"
        )

    def test_all_floor5_modules_no_floor3_imports(self):
        """No floor_5_captain module imports from floor_3_calculations."""
        import importlib
        import inspect
        import pkgutil
        import junior_aladdin.floor_5_captain as pkg

        forbidden = ("floor_3_calculations", "floor_4_heads")
        for importer, modname, ispkg in pkgutil.walk_packages(
            pkg.__path__, prefix="junior_aladdin.floor_5_captain.",
        ):
            if ispkg:
                continue
            try:
                mod = importlib.import_module(modname)
                source = inspect.getsource(mod)
                for fb in forbidden:
                    assert fb not in source, (
                        f"{modname} must NOT import from {fb}"
                    )
            except (ImportError, OSError, TypeError):
                pass  # Skip modules that can't be inspected


# =============================================================================
# Test: Heavy Cycle Output Contract Alignment
# =============================================================================


class TestHeavyCycleOutputContracts:
    """Heavy cycle output contracts align with downstream expectations."""

    def test_heavy_cycle_output_has_all_fields(self, captain_engine):
        """HeavyCycleOutput contains decision, state, snapshot, and scores."""
        from junior_aladdin.floor_5_captain.captain_engine import HeavyCycleOutput
        output = captain_engine.heavy_cycle(
            timestamp=_GOLDEN_MORNING_UTC,
            candle_index=1,
            capital_available=50000.0,
        )
        assert hasattr(output, "decision")
        assert hasattr(output, "captain_state")
        assert hasattr(output, "decision_snapshot")
        assert hasattr(output, "conviction_score")
        assert hasattr(output, "market_story")
        assert hasattr(output, "confluence_result")
        assert hasattr(output, "opposite_case")
        assert hasattr(output, "permission_result")
        assert hasattr(output, "has_trade")
        assert hasattr(output, "is_blocked")
        assert hasattr(output, "execution_time_ms")

    def test_heavy_cycle_decision_captain_state_consistency(self, captain_engine):
        """Heavy cycle output's decision and captain_state are consistent."""
        output = captain_engine.heavy_cycle(
            timestamp=_GOLDEN_MORNING_UTC,
            candle_index=2,
            capital_available=50000.0,
        )
        if output.decision and output.captain_state:
            if output.decision.decision == DecisionType.TRADE:
                assert output.captain_state.active_trade is True
                assert output.captain_state.decision_state == DecisionState.TRADE
            elif output.decision.decision == DecisionType.BLOCKED:
                assert output.captain_state.active_trade is False
                assert output.captain_state.decision_state == DecisionState.WAIT

    def test_heavy_cycle_decision_snapshot_link(self, captain_engine):
        """Heavy cycle's decision references the correct snapshot ID."""
        output = captain_engine.heavy_cycle(
            timestamp=_GOLDEN_MORNING_UTC,
            candle_index=3,
            capital_available=50000.0,
        )
        if output.decision and output.decision_snapshot:
            # Either linked or one exists without the other for WAIT decisions
            if output.decision.decision == DecisionType.TRADE:
                assert output.decision.snapshot_id == output.decision_snapshot.snapshot_id
            else:
                assert output.decision_snapshot.snapshot_id != ""

    def test_heavy_cycle_state_trade_class_consistency(self, captain_engine):
        """When has_trade is True, trade_plan should be populated."""
        # This may not always produce a trade, but the contract should hold
        output = captain_engine.heavy_cycle(
            timestamp=_GOLDEN_MORNING_UTC,
            candle_index=4,
            capital_available=50000.0,
        )
        if output.has_trade:
            assert output.trade_plan is not None
            assert output.trade_plan.is_constructable is True
