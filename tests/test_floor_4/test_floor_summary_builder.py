"""Unit tests for ``floor_summary_builder.py`` — Floor 4 Step 4.14.

Tests:
- Build with all 6 heads — complete summary
- State counting (ready/uncertain/stale)
- Bias snapshot and dominant floor bias
- Confidence snapshot (average, highest/lowest heads)
- Primary/backup setup extraction
- Conflict detection (bullish vs bearish heads)
- Stale warning detection
- Strongest domain signal identification
- Strongest context signal (macro/psychology)
- Strongest risk warning
- Data health computation
- Head health snapshots (all + core)
- Setup presence/absence context
- Witness line generation
- Partial report handling (some heads missing)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from junior_aladdin.floor_4_heads.floor_summary_builder import FloorSummaryBuilder
from junior_aladdin.shared.types import (
    BiasType,
    DataHealth,
    FreshnessTag,
    HeadReport,
    HeadState,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_report(
    head_name: str,
    state: HeadState = HeadState.READY,
    bias: BiasType = BiasType.NEUTRAL,
    confidence: float = 0.5,
    primary_setup: str | None = None,
    backup_setup: str | None = None,
    freshness_tag: FreshnessTag = FreshnessTag.FRESH,
    context_quality_score: float | None = None,
    trade_allowed: bool = True,
    caution_level: float = 0.0,
    cooldown_active: bool = False,
    repeated_mistake_flag: bool = False,
    trap_pressure: bool = False,
    block_reason: str = "",
    event_risk_flag: bool = False,
) -> HeadReport:
    """Create a HeadReport with specified parameters for testing."""
    return HeadReport(
        head_name=head_name,
        state=state,
        freshness_score=0.9 if state != HeadState.STALE else 0.1,
        freshness_tag=freshness_tag if state != HeadState.STALE else FreshnessTag.STALE,
        last_deep_update=datetime(2026, 6, 8, 10, 30, 0, tzinfo=timezone.utc),
        bias=bias,
        confidence=confidence,
        dominant_tf="1m",
        timeframe_view=f"{head_name} view",
        primary_setup=primary_setup,
        backup_setup=backup_setup,
        invalidation={"rules": [{"condition": "Test invalidation", "price_level": 0.0, "reason": "Test"}], "summary": "Test"},
        bull_case=f"{head_name} bull case" if bias == BiasType.BULLISH else "",
        bear_case=f"{head_name} bear case" if bias == BiasType.BEARISH else "",
        witness_summary=f"{head_name} witness",
        context_quality_score=context_quality_score,
        trade_allowed=trade_allowed,
        caution_level=caution_level,
        cooldown_active=cooldown_active,
        repeated_mistake_flag=repeated_mistake_flag,
        trap_pressure=trap_pressure,
        block_reason=block_reason,
        event_risk_flag=event_risk_flag,
    )


_SAMPLE_TIME = datetime(2026, 6, 8, 11, 0, 0, tzinfo=timezone.utc)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def all_neutral_reports() -> dict[str, HeadReport]:
    """All 6 heads in NEUTRAL/READY state with no setups."""
    return {
        "SMC Head": _make_report("SMC Head", context_quality_score=0.6),
        "ICT Head": _make_report("ICT Head", context_quality_score=0.5),
        "Technical Head": _make_report("Technical Head"),
        "Options Head": _make_report("Options Head"),
        "Macro Head": _make_report("Macro Head", caution_level=0.2),
        "Psychology Head": _make_report("Psychology Head"),
    }


@pytest.fixture
def bullish_reports() -> dict[str, HeadReport]:
    """All 4 directional heads BULLISH, macro supportive, psychology clear."""
    return {
        "SMC Head": _make_report(
            "SMC Head", bias=BiasType.BULLISH, confidence=0.7,
            primary_setup="FVG Retest", backup_setup="Order Block Bounce",
            context_quality_score=0.7,
        ),
        "ICT Head": _make_report(
            "ICT Head", bias=BiasType.BULLISH, confidence=0.65,
            primary_setup="Premium/Discount Reaction",
            context_quality_score=0.6,
        ),
        "Technical Head": _make_report(
            "Technical Head", bias=BiasType.BULLISH, confidence=0.6,
            primary_setup="VWAP Pullback Continuation",
        ),
        "Options Head": _make_report(
            "Options Head", bias=BiasType.BULLISH, confidence=0.55,
            primary_setup="OI Wall Bounce",
        ),
        "Macro Head": _make_report(
            "Macro Head", bias=BiasType.BULLISH, confidence=0.6,
            caution_level=0.15,
        ),
        "Psychology Head": _make_report("Psychology Head"),
    }


@pytest.fixture
def conflicted_reports() -> dict[str, HeadReport]:
    """SMC/Technical BULLISH, ICT/Options BEARISH → conflict."""
    return {
        "SMC Head": _make_report(
            "SMC Head", bias=BiasType.BULLISH, confidence=0.6,
            primary_setup="FVG Retest", context_quality_score=0.6,
        ),
        "ICT Head": _make_report(
            "ICT Head", bias=BiasType.BEARISH, confidence=0.6,
            primary_setup="Premium/Discount Reaction",
            context_quality_score=0.5,
        ),
        "Technical Head": _make_report(
            "Technical Head", bias=BiasType.BULLISH, confidence=0.5,
        ),
        "Options Head": _make_report(
            "Options Head", bias=BiasType.BEARISH, confidence=0.5,
            primary_setup="Pressure Collapse",
        ),
        "Macro Head": _make_report("Macro Head"),
        "Psychology Head": _make_report("Psychology Head"),
    }


@pytest.fixture
def stale_reports() -> dict[str, HeadReport]:
    """SMC and ICT are STALE."""
    return {
        "SMC Head": _make_report(
            "SMC Head", state=HeadState.STALE,
            context_quality_score=0.2,
        ),
        "ICT Head": _make_report(
            "ICT Head", state=HeadState.STALE,
            context_quality_score=0.15,
        ),
        "Technical Head": _make_report("Technical Head"),
        "Options Head": _make_report("Options Head"),
        "Macro Head": _make_report("Macro Head", caution_level=0.3),
        "Psychology Head": _make_report("Psychology Head"),
    }


@pytest.fixture
def blocked_psychology_reports() -> dict[str, HeadReport]:
    """Psychology blocks trading, macro caution high."""
    return {
        "SMC Head": _make_report(
            "SMC Head", bias=BiasType.BULLISH, confidence=0.5,
            primary_setup="FVG Retest", context_quality_score=0.5,
        ),
        "ICT Head": _make_report(
            "ICT Head", bias=BiasType.BULLISH, confidence=0.4,
            context_quality_score=0.4,
        ),
        "Technical Head": _make_report(
            "Technical Head", bias=BiasType.NEUTRAL, confidence=0.3,
        ),
        "Options Head": _make_report(
            "Options Head", bias=BiasType.NEUTRAL, confidence=0.3,
        ),
        "Macro Head": _make_report(
            "Macro Head", caution_level=0.75, event_risk_flag=True,
        ),
        "Psychology Head": _make_report(
            "Psychology Head", trade_allowed=False, block_reason="Max daily loss hit",
        ),
    }


# =============================================================================
# Test Class
# =============================================================================


class TestFloorSummaryBuilder:
    """FloorSummaryBuilder tests."""

    def test_1_build_with_all_heads(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert summary.summary_timestamp == _SAMPLE_TIME
        assert summary.ready_heads_count == 6
        assert summary.uncertain_heads_count == 0
        assert summary.stale_heads_count == 0

    def test_2_state_counting(self) -> None:
        builder = FloorSummaryBuilder()
        reports = {
            "SMC Head": _make_report("SMC Head", state=HeadState.READY, context_quality_score=0.5),
            "ICT Head": _make_report("ICT Head", state=HeadState.UNCERTAIN, confidence=0.2, context_quality_score=0.3),
            "Technical Head": _make_report("Technical Head", state=HeadState.STALE),
            "Options Head": _make_report("Options Head", state=HeadState.READY),
            "Macro Head": _make_report("Macro Head", state=HeadState.READY),
            "Psychology Head": _make_report("Psychology Head", state=HeadState.STALE),
        }
        summary = builder.build(reports, _SAMPLE_TIME)
        assert summary.ready_heads_count == 3
        assert summary.uncertain_heads_count == 1
        assert summary.stale_heads_count == 2

    def test_3_bias_snapshot_all_neutral(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert summary.floor_bias_snapshot["dominant_floor_bias"] == "NEUTRAL"
        assert summary.floor_bias_snapshot["bullish_count"] == 0
        assert summary.floor_bias_snapshot["bearish_count"] == 0
        assert summary.floor_bias_snapshot["neutral_count"] == 6

    def test_4_bias_snapshot_bullish(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        assert summary.floor_bias_snapshot["dominant_floor_bias"] == "BULLISH"
        assert summary.floor_bias_snapshot["bullish_count"] >= 4

    def test_5_bias_snapshot_conflict(self, conflicted_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(conflicted_reports, _SAMPLE_TIME)
        # Should be NEUTRAL because 2B vs 2S
        assert summary.floor_bias_snapshot["bullish_count"] >= 2
        assert summary.floor_bias_snapshot["bearish_count"] >= 2
        assert summary.conflict_present is True

    def test_6_active_setup_count(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        # SMC + ICT + Technical + Options = 4 setups
        assert summary.active_setup_count == 4

    def test_7_primary_setups_by_head(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        assert summary.primary_setups_by_head["SMC Head"] == "FVG Retest"
        assert summary.primary_setups_by_head["ICT Head"] == "Premium/Discount Reaction"
        assert summary.primary_setups_by_head["Technical Head"] == "VWAP Pullback Continuation"
        assert summary.primary_setups_by_head["Options Head"] == "OI Wall Bounce"
        assert summary.primary_setups_by_head["Macro Head"] is None
        assert summary.primary_setups_by_head["Psychology Head"] is None

    def test_8_backup_setups_by_head(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        assert summary.backup_setups_by_head["SMC Head"] == "Order Block Bounce"
        assert summary.backup_setups_by_head["Macro Head"] is None

    def test_9_confidence_snapshot(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        conf = summary.floor_confidence_snapshot
        assert "head_confidences" in conf
        assert "average_confidence" in conf
        assert conf["average_confidence"] > 0
        assert conf["highest_confidence_head"] == "SMC Head"
        assert conf["lowest_confidence_head"] == "Psychology Head"

    def test_10_conflict_detection(self, conflicted_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(conflicted_reports, _SAMPLE_TIME)
        assert summary.conflict_present is True

    def test_11_no_conflict_when_aligned(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        assert summary.conflict_present is False

    def test_12_stale_warning(self, stale_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(stale_reports, _SAMPLE_TIME)
        assert summary.stale_warning_present is True
        assert summary.stale_heads_count == 2

    def test_13_no_stale_warning(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert summary.stale_warning_present is False

    def test_14_strongest_domain_signal(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        # SMC has highest confidence (0.7) + setup bonus → strongest
        assert "SMC Head" in summary.strongest_domain_signal
        assert "FVG Retest" in summary.strongest_domain_signal

    def test_15_strongest_context_signal_calm(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert "No significant context" not in summary.strongest_context_signal

    def test_16_strongest_context_signal_blocked(self, blocked_psychology_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(blocked_psychology_reports, _SAMPLE_TIME)
        assert "psychology block" in summary.strongest_context_signal.lower() or "trading blocked" in summary.strongest_context_signal.lower()

    def test_17_strongest_risk_warning_blocked(self, blocked_psychology_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(blocked_psychology_reports, _SAMPLE_TIME)
        assert summary.strongest_risk_warning != "No significant warnings"
        assert "trading blocked" in summary.strongest_risk_warning.lower() or "block" in summary.strongest_risk_warning.lower()

    def test_18_strongest_risk_warning_stale(self, stale_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(stale_reports, _SAMPLE_TIME)
        assert "STALE" in summary.strongest_risk_warning

    def test_19_data_health_good(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert summary.data_health_signal == DataHealth.GOOD

    def test_20_data_health_caution(self, stale_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(stale_reports, _SAMPLE_TIME)
        assert summary.data_health_signal in (DataHealth.CAUTION, DataHealth.DEGRADED)

    def test_21_head_health_snapshot(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert "SMC Head" in summary.head_health_snapshot
        assert "ICT Head" in summary.head_health_snapshot
        assert "Psychology Head" in summary.head_health_snapshot
        assert summary.head_health_snapshot["SMC Head"]["state"] == "READY"

    def test_22_core_head_health_snapshot(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        # Core heads: SMC, ICT, Technical, Macro, Psychology (NOT Options)
        assert "SMC Head" in summary.core_head_health_snapshot
        assert "Options Head" not in summary.core_head_health_snapshot

    def test_23_setup_presence_has_setup(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        assert summary.setup_presence == "HAS_SETUP"
        assert summary.setup_absence_context is None

    def test_24_setup_presence_no_setup(self, all_neutral_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(all_neutral_reports, _SAMPLE_TIME)
        assert summary.setup_presence == "NO_SETUP"
        assert summary.setup_absence_context == "READY_NO_SETUP"

    def test_25_setup_absence_uncertain(self) -> None:
        builder = FloorSummaryBuilder()
        reports = {
            "SMC Head": _make_report("SMC Head", state=HeadState.UNCERTAIN, confidence=0.2, context_quality_score=0.2),
            "ICT Head": _make_report("ICT Head", state=HeadState.READY, context_quality_score=0.3),
            "Technical Head": _make_report("Technical Head"),
            "Options Head": _make_report("Options Head"),
            "Macro Head": _make_report("Macro Head"),
            "Psychology Head": _make_report("Psychology Head"),
        }
        summary = builder.build(reports, _SAMPLE_TIME)
        assert summary.setup_presence == "NO_SETUP"
        assert summary.setup_absence_context == "UNCERTAIN_NO_SETUP"

    def test_26_witness_lines_present(self, bullish_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(bullish_reports, _SAMPLE_TIME)
        assert len(summary.summary_witness_lines) > 0
        witness_text = " ".join(summary.summary_witness_lines)
        assert "Floor state" in witness_text
        assert "Floor bias" in witness_text
        assert "active setup" in witness_text

    def test_27_witness_lines_blocked(self, blocked_psychology_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(blocked_psychology_reports, _SAMPLE_TIME)
        witness_text = " ".join(summary.summary_witness_lines)
        assert "block" in witness_text.lower()

    def test_28_witness_lines_conflict(self, conflicted_reports) -> None:
        builder = FloorSummaryBuilder()
        summary = builder.build(conflicted_reports, _SAMPLE_TIME)
        witness_text = " ".join(summary.summary_witness_lines)
        assert "conflict" in witness_text.lower()

    def test_29_partial_reports(self) -> None:
        """Builder should handle missing heads gracefully."""
        builder = FloorSummaryBuilder()
        partial = {
            "SMC Head": _make_report("SMC Head", context_quality_score=0.5),
            "ICT Head": _make_report("ICT Head", context_quality_score=0.4),
        }
        summary = builder.build(partial, _SAMPLE_TIME)
        assert summary.ready_heads_count == 2
        assert summary.uncertain_heads_count == 0
        assert summary.stale_heads_count == 0

    def test_30_empty_reports(self) -> None:
        """Builder should handle empty dict."""
        builder = FloorSummaryBuilder()
        summary = builder.build({}, _SAMPLE_TIME)
        assert summary.ready_heads_count == 0
        assert summary.data_health_signal == DataHealth.CRITICAL
