"""Floor 5 — Replay Validation Integration Tests (Step 5.23).

Validates deterministic decision-making on replay:

1. Same Floor 4 data → identical decisions
2. Same data → identical conviction scores
3. Same data → identical armed plans
4. Decision snapshots identical on replay
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import pytest

from junior_aladdin.floor_5_captain.captain_engine import CaptainEngine, HeavyCycleOutput
from junior_aladdin.floor_5_captain.captain_types import (
    CaptainInput,
    ConvictionBand,
    SessionPhase,
)
from junior_aladdin.shared.testing import (
    generate_mock_floor_summary,
    generate_mock_head_report,
)
from junior_aladdin.shared.types import BiasType, HeadState

# Golden morning timestamp (9:45 IST = 4:15 UTC on Jan 1)
_GOLDEN_MORNING_UTC = datetime(2025, 1, 1, 4, 15, 0)
_HEAD_NAMES = ["SMC Head", "ICT Head", "Technical Head", "Options Head", "Macro Head", "Psychology Head"]


# =============================================================================
# Test Fixture: Deterministic Input Data
# =============================================================================


def build_deterministic_input() -> CaptainInput:
    """Build a CaptainInput with fully deterministic (seeded) data.

    All head reports use fixed biases, confidences, and states so replay
    produces identical outputs.
    """
    heads = {}
    for name in _HEAD_NAMES:
        short = name.split()[0]
        if name == "Psychology Head":
            psych = generate_mock_head_report("Psychology", bias=BiasType.NEUTRAL, confidence=0.90, state=HeadState.READY)
            psych.trade_allowed = True
            psych.caution_level = 0.1
            heads[name] = psych
        else:
            heads[name] = generate_mock_head_report(
                head_name=short, bias=BiasType.BULLISH, confidence=0.85,
                state=HeadState.READY,
            )

    # Set SMC/ICT context quality scores
    heads["SMC Head"].context_quality_score = 0.9
    heads["ICT Head"].context_quality_score = 0.85

    fs = generate_mock_floor_summary()
    if hasattr(fs, "data_health_signal"):
        from junior_aladdin.shared.types import DataHealth
        fs.data_health_signal = DataHealth.GOOD

    return CaptainInput(
        floor_summary=fs,
        head_reports=heads,
        system_context={"replay_test": True},
    )


def run_replay_cycle(
    engine: CaptainEngine,
    inp: CaptainInput,
    candle_index: int,
    **kwargs: Any,
) -> HeavyCycleOutput:
    """Run a heavy cycle with standardized parameters for replay testing."""
    return engine.heavy_cycle(
        captain_input=inp,
        timestamp=_GOLDEN_MORNING_UTC,
        capital_available=50000.0,
        candle_index=candle_index,
        current_price=19550.0,
        zone_info={"label": "FVG_REPLAY", "price": 19500.0, "type": "FVG"},
        **kwargs,
    )


# =============================================================================
# Test: Identical Decisions on Replay
# =============================================================================


class TestIdenticalDecisions:
    """Same Floor 4 data → identical Captain decisions."""

    def test_identical_input_identical_decision_type(self):
        """Two heavy cycles with identical input produce the same decision type."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=1)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=1)

        assert output1.decision is not None
        assert output2.decision is not None
        assert output1.decision.decision == output2.decision.decision

    def test_identical_input_identical_conviction_band(self):
        """Two heavy cycles with identical input produce the same conviction band."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=2)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=2)

        if output1.conviction_score and output2.conviction_score:
            assert output1.conviction_score.conviction_band == output2.conviction_score.conviction_band

    def test_identical_input_identical_confluence(self):
        """Two heavy cycles with identical input produce the same confluence result."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=3)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=3)

        if output1.confluence_result and output2.confluence_result:
            assert output1.confluence_result.dominant_direction == output2.confluence_result.dominant_direction
            assert abs(output1.confluence_result.confluence_quality - output2.confluence_result.confluence_quality) < 0.001

    def test_three_identical_runs_same_result(self):
        """Three runs with identical input produce the same result each time."""
        inp = build_deterministic_input()

        outputs = []
        for _ in range(3):
            engine = CaptainEngine()
            outputs.append(run_replay_cycle(engine, copy.deepcopy(inp), candle_index=5))

        for i in range(1, len(outputs)):
            assert outputs[i].decision.decision == outputs[0].decision.decision
            if outputs[i].conviction_score and outputs[0].conviction_score:
                assert outputs[i].conviction_score.conviction_band == outputs[0].conviction_score.conviction_band


# =============================================================================
# Test: Identical Conviction Scores on Replay
# =============================================================================


class TestIdenticalConvictionScores:
    """Same data → identical conviction scores on replay."""

    def test_identical_permission_score(self):
        """Permission scores are identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=10)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=10)

        if output1.conviction_score and output2.conviction_score:
            assert abs(output1.conviction_score.permission_score - output2.conviction_score.permission_score) < 0.1

    def test_identical_conviction_score_value(self):
        """Conviction scores are identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=11)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=11)

        if output1.conviction_score and output2.conviction_score:
            assert abs(output1.conviction_score.conviction_score - output2.conviction_score.conviction_score) < 0.1

    def test_identical_no_trade_score(self):
        """No-trade scores are identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=12)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=12)

        if output1.conviction_score and output2.conviction_score:
            assert abs(output1.conviction_score.no_trade_score - output2.conviction_score.no_trade_score) < 0.1

    def test_identical_scores_with_psych_blocked(self):
        """Psychology-blocked runs produce identical results on replay."""
        inp = build_deterministic_input()
        inp.head_reports["Psychology Head"].trade_allowed = False

        engine1 = CaptainEngine()
        output1 = run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=15)

        engine2 = CaptainEngine()
        output2 = run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=15)

        assert output1.is_blocked == output2.is_blocked
        if output1.permission_result and output2.permission_result:
            assert output1.permission_result.block_reason == output2.permission_result.block_reason


# =============================================================================
# Test: Identical Armed Plans on Replay
# =============================================================================


class TestIdenticalArmedPlans:
    """Same data → identical armed plans on replay."""

    def test_identical_plan_count_on_replay(self):
        """Number of armed plans is identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=20)
        plans1 = engine1.armed_plan_engine.get_active_plans()

        engine2 = CaptainEngine()
        run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=20)
        plans2 = engine2.armed_plan_engine.get_active_plans()

        assert len(plans1) == len(plans2)

    def test_identical_plan_directions(self):
        """Armed plan directions are identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=21)
        plans1 = engine1.armed_plan_engine.get_active_plans()

        engine2 = CaptainEngine()
        run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=21)
        plans2 = engine2.armed_plan_engine.get_active_plans()

        for p1, p2 in zip(plans1, plans2):
            assert p1.direction == p2.direction

    def test_identical_plan_trigger_conditions(self):
        """Armed plan trigger conditions are identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=22)
        plans1 = engine1.armed_plan_engine.get_active_plans()

        engine2 = CaptainEngine()
        run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=22)
        plans2 = engine2.armed_plan_engine.get_active_plans()

        for p1, p2 in zip(plans1, plans2):
            assert p1.trigger_condition == p2.trigger_condition


# =============================================================================
# Test: Identical Decision Snapshots on Replay
# =============================================================================


class TestIdenticalSnapshots:
    """Decision snapshots are identical on replay."""

    def test_identical_snapshot_count(self):
        """Number of snapshots is identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=30)
        count1 = engine1.snapshot_writer.get_snapshot_count()

        engine2 = CaptainEngine()
        run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=30)
        count2 = engine2.snapshot_writer.get_snapshot_count()

        assert count1 == count2

    def test_identical_snapshot_conviction(self):
        """Snapshot conviction score is identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=31)
        snap1 = engine1.snapshot_writer.get_latest_snapshot()

        engine2 = CaptainEngine()
        run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=31)
        snap2 = engine2.snapshot_writer.get_latest_snapshot()

        if snap1 and snap2:
            assert abs(snap1.conviction_score - snap2.conviction_score) < 0.001

    def test_identical_snapshot_session_context(self):
        """Snapshot session context is identical on replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=32)
        snap1 = engine1.snapshot_writer.get_latest_snapshot()

        engine2 = CaptainEngine()
        run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=32)
        snap2 = engine2.snapshot_writer.get_latest_snapshot()

        if snap1 and snap2:
            for key in snap1.session_context:
                if key in snap2.session_context:
                    assert snap1.session_context[key] == snap2.session_context[key], (
                        f"Mismatch in session_context.{key}"
                    )

    def test_multiple_cycle_snapshot_consistency(self):
        """Multiple heavy cycles produce consistent snapshots across replay."""
        inp = build_deterministic_input()

        engine1 = CaptainEngine()
        for ci in range(40, 45):
            run_replay_cycle(engine1, copy.deepcopy(inp), candle_index=ci)

        engine2 = CaptainEngine()
        for ci in range(40, 45):
            run_replay_cycle(engine2, copy.deepcopy(inp), candle_index=ci)

        snap1 = engine1.snapshot_writer.get_session_snapshots()
        snap2 = engine2.snapshot_writer.get_session_snapshots()
        assert len(snap1) == len(snap2)

        for s1, s2 in zip(snap1, snap2):
            assert abs(s1.conviction_score - s2.conviction_score) < 0.001


# =============================================================================
# Test: Time-Sensitive Determinism
# =============================================================================


class TestTimeSensitiveDeterminism:
    """Time-sensitive logic (session_phase) produces identical results with
    injected timestamps."""

    def test_same_timestamp_same_result(self):
        """Same injected timestamp → same session phase → same result."""
        inp = build_deterministic_input()
        fixed_time = datetime(2025, 1, 1, 4, 15, 0)

        engine1 = CaptainEngine()
        output1 = engine1.heavy_cycle(
            captain_input=copy.deepcopy(inp),
            timestamp=fixed_time,
            capital_available=50000.0,
            candle_index=50,
        )

        engine2 = CaptainEngine()
        output2 = engine2.heavy_cycle(
            captain_input=copy.deepcopy(inp),
            timestamp=fixed_time,
            capital_available=50000.0,
            candle_index=50,
        )

        assert output1.decision.decision == output2.decision.decision

    def test_different_timestamp_different_permission(self):
        """Different timestamps → different session phases → different permission results."""
        inp = build_deterministic_input()
        golden_morning = datetime(2025, 1, 1, 4, 15, 0)
        closing = datetime(2025, 1, 1, 7, 30, 0)  # 13:00 IST = 7:30 UTC

        engine = CaptainEngine()
        gm_output = engine.heavy_cycle(
            captain_input=copy.deepcopy(inp),
            timestamp=golden_morning,
            capital_available=50000.0,
            candle_index=60,
        )

        engine2 = CaptainEngine()
        closing_output = engine2.heavy_cycle(
            captain_input=copy.deepcopy(inp),
            timestamp=closing,
            capital_available=50000.0,
            candle_index=60,
        )

        assert gm_output.is_blocked is False
        assert closing_output.is_blocked is True
