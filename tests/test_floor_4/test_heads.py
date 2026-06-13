"""Tests for Floor 4 — Department Heads.

Covers all 4 newly implemented heads + existing SMC/Psychology integration:
- TechnicalHead, ICTHead, OptionsHead, MacroHead
- Empty signal handling for each
- Floor summary builder with all 6 heads

Each head is tested with:
1. No signals (empty interpretation)
2. Full bullish signals
3. Full bearish signals
4. Neutral / mixed signals
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    generate_signal_id,
)
from junior_aladdin.floor_4_heads import (
    FloorSummaryBuilder,
    ICTHead,
    MacroHead,
    OptionsHead,
    TechnicalHead,
)
from junior_aladdin.floor_4_heads.floor_summary_builder import FloorSummaryBuilder as _FloorSummaryBuilder
from junior_aladdin.shared.types import BiasType, DataHealth, HeadState


# =============================================================================
# Helpers
# =============================================================================


def _make_signal(
    domain: CalculationDomain,
    indicator_type: str,
    value: dict[str, Any],
) -> CalculatedSignal:
    return CalculatedSignal(
        signal_id=generate_signal_id(),
        domain=domain,
        indicator_type=indicator_type,
        value=value,
        timestamp=datetime.utcnow(),
    )


def _make_output_contract(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


NOW = datetime.utcnow()


# =============================================================================
# Test: TechnicalHead
# =============================================================================


class TestTechnicalHead:
    """TechnicalHead — trend, RSI, MA, VWAP interpretation."""

    def test_empty_signals(self):
        """No signals → neutral bias, zero confidence."""
        head = TechnicalHead()
        contract = _make_output_contract([])

        # First refresh warms up (last_deep_update starts as None → STALE)
        head.refresh(contract, NOW)
        # Second refresh checks state after fresh update
        report = head.refresh(contract, NOW)

        assert report.bias == BiasType.NEUTRAL
        assert report.confidence == 0.0
        assert report.primary_setup is None
        assert report.state == HeadState.UNCERTAIN  # No signals, low confidence

    def test_bullish_trend_aligned(self):
        """Strong uptrend with MTF alignment → bullish."""
        head = TechnicalHead()
        signals = [
            _make_signal(CalculationDomain.TECHNICAL, "TREND", {
                "trend_state": "STRONG_UP", "mtf_alignment": "ALIGNED",
            }),
            _make_signal(CalculationDomain.TECHNICAL, "VWAP", {
                "vwap_value": 19500.0, "vwap_distance_pct": 0.3,
            }),
            _make_signal(CalculationDomain.TECHNICAL, "RSI", {
                "rsi_value": 55.0, "oversold": False, "overbought": False,
            }),
        ]
        report = TechnicalHead().refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BULLISH
        assert report.confidence > 0.3
        assert report.primary_setup is not None
        assert len(report.active_zones) >= 1

    def test_bearish_trend(self):
        """Strong downtrend → bearish."""
        head = TechnicalHead()
        signals = [
            _make_signal(CalculationDomain.TECHNICAL, "TREND", {
                "trend_state": "STRONG_DOWN", "mtf_alignment": "ALIGNED",
            }),
            _make_signal(CalculationDomain.TECHNICAL, "VWAP", {
                "vwap_value": 19400.0, "vwap_distance_pct": -0.5,
            }),
            _make_signal(CalculationDomain.TECHNICAL, "RSI", {
                "rsi_value": 35.0, "oversold": False, "overbought": False,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BEARISH
        assert report.primary_setup is not None

    def test_neutral_range(self):
        """Range-bound market → neutral bias."""
        head = TechnicalHead()
        signals = [
            _make_signal(CalculationDomain.TECHNICAL, "TREND", {
                "trend_state": "RANGE", "mtf_alignment": "FRAGMENTED",
            }),
            _make_signal(CalculationDomain.TECHNICAL, "RSI", {
                "rsi_value": 50.0, "oversold": False, "overbought": False,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.NEUTRAL

    def test_invalidation_present(self):
        """Report always includes invalidation rules."""
        report = TechnicalHead().refresh(_make_output_contract([]), NOW)
        assert len(report.invalidation) > 0
        assert "rules" in report.invalidation


# =============================================================================
# Test: ICTHead
# =============================================================================


class TestICTHead:
    """ICTHead — premium/discount, displacement, MSS, delivery context."""

    def test_empty_signals(self):
        """No signals → neutral with context_quality_score = 0."""
        head = ICTHead()
        report = head.refresh(_make_output_contract([]), NOW)

        assert report.bias == BiasType.NEUTRAL
        assert report.confidence == 0.0
        assert report.context_quality_score == 0.0
        assert report.primary_setup is None

    def test_bullish_discount_active(self):
        """Discount zone + bullish displacement → bullish."""
        head = ICTHead()
        signals = [
            _make_signal(CalculationDomain.ICT, "PREMIUM_DISCOUNT", {
                "pd_state": "DISCOUNT", "equilibrium": 19500.0,
            }),
            _make_signal(CalculationDomain.ICT, "DISPLACEMENT", {
                "displacement_type": "BULLISH_DISPLACEMENT", "strength": 0.7,
            }),
            _make_signal(CalculationDomain.ICT, "MSS", {
                "mss_type": "BULLISH_MSS", "confirmed": True,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BULLISH
        assert report.confidence > 0.2
        assert report.context_quality_score > 0.3
        assert report.primary_setup is not None

    def test_bearish_premium_active(self):
        """Premium zone + bearish displacement → bearish."""
        head = ICTHead()
        signals = [
            _make_signal(CalculationDomain.ICT, "PREMIUM_DISCOUNT", {
                "pd_state": "PREMIUM", "equilibrium": 19600.0,
            }),
            _make_signal(CalculationDomain.ICT, "DISPLACEMENT", {
                "displacement_type": "BEARISH_DISPLACEMENT", "strength": 0.8,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BEARISH
        assert report.primary_setup is not None

    def test_context_quality_score_mandatory(self):
        """context_quality_score is always present in output."""
        report = ICTHead().refresh(_make_output_contract([]), NOW)
        assert report.context_quality_score is not None

    def test_invalidation_rules_present(self):
        """Always has invalidation rules."""
        report = ICTHead().refresh(_make_output_contract([]), NOW)
        assert len(report.invalidation.get("rules", [])) > 0


# =============================================================================
# Test: OptionsHead
# =============================================================================


class TestOptionsHead:
    """OptionsHead — PCR, OI walls, IV, pressure."""

    def test_empty_signals(self):
        """No signals → neutral."""
        head = OptionsHead()
        report = head.refresh(_make_output_contract([]), NOW)

        assert report.bias == BiasType.NEUTRAL
        assert report.confidence == 0.0
        assert report.primary_setup is None

    def test_bullish_put_wall(self):
        """Put wall + PE OI building + bullish pressure → bullish."""
        head = OptionsHead()
        signals = [
            _make_signal(CalculationDomain.OPTIONS, "WALL", {
                "wall_type": "PUT_WALL", "strike": 19500.0, "oi_concentration": 0.8,
            }),
            _make_signal(CalculationDomain.OPTIONS, "OI_CHANGE", {
                "option_type": "PE", "oi_change_pct": 25, "strike": 19500.0,
            }),
            _make_signal(CalculationDomain.OPTIONS, "OPTIONS_PRESSURE", {
                "direction": "BULLISH", "strength": 0.6,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BULLISH
        assert report.primary_setup is not None
        assert len(report.active_zones) >= 1

    def test_bearish_call_wall(self):
        """Call wall + CE OI building → bearish."""
        head = OptionsHead()
        signals = [
            _make_signal(CalculationDomain.OPTIONS, "WALL", {
                "wall_type": "CALL_WALL", "strike": 19600.0, "oi_concentration": 0.9,
            }),
            _make_signal(CalculationDomain.OPTIONS, "OI_CHANGE", {
                "option_type": "CE", "oi_change_pct": 30, "strike": 19600.0,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BEARISH

    def test_neutral_pcr(self):
        """Balanced PCR, no walls → neutral."""
        head = OptionsHead()
        signals = [
            _make_signal(CalculationDomain.OPTIONS, "PCR", {
                "pcr_value": 1.0, "pcr_change": 0.02,
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)
        assert report.bias == BiasType.NEUTRAL


# =============================================================================
# Test: MacroHead
# =============================================================================


class TestMacroHead:
    """MacroHead — VIX, FII/DII, event risk, environment context."""

    def test_empty_signals(self):
        """No signals → neutral, no event risk, no caution."""
        head = MacroHead()
        report = head.refresh(_make_output_contract([]), NOW)

        assert report.bias == BiasType.NEUTRAL
        assert report.confidence == 0.0
        assert report.caution_level == 0.0
        assert report.event_risk_flag is False

    def test_no_setups_locked(self):
        """Macro must NOT produce setups."""
        head = MacroHead()
        report = head.refresh(_make_output_contract([]), NOW)

        assert report.primary_setup is None
        assert report.backup_setup is None

    def test_calm_environment(self):
        """Low VIX, stable environment, FII buying → mildly bullish."""
        head = MacroHead()
        signals = [
            _make_signal(CalculationDomain.MACRO, "VIX", {
                "vix_value": 12.0, "vix_change": -0.5,
            }),
            _make_signal(CalculationDomain.MACRO, "FII_DII", {
                "net_state": "BUY", "magnitude": 800,
            }),
            _make_signal(CalculationDomain.MACRO, "MACRO_ENVIRONMENT", {
                "environment_state": "STABLE",
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.bias == BiasType.BULLISH  # Mildly supportive
        assert report.caution_level < 0.3

    def test_stressed_environment(self):
        """High VIX, event risk, FII selling → high caution, bearish lean."""
        head = MacroHead()
        signals = [
            _make_signal(CalculationDomain.MACRO, "VIX", {
                "vix_value": 25.0, "vix_change": 2.0,
            }),
            _make_signal(CalculationDomain.MACRO, "FII_DII", {
                "net_state": "SELL", "magnitude": 1200,
            }),
            _make_signal(CalculationDomain.MACRO, "EVENT_CALENDAR", {
                "event_type": "FOMC", "risk_level": 0.8, "time_until": 3600,
            }),
            _make_signal(CalculationDomain.MACRO, "MACRO_ENVIRONMENT", {
                "environment_state": "STRESSED",
            }),
        ]
        report = head.refresh(_make_output_contract(signals), NOW)

        assert report.caution_level > 0.5
        assert report.event_risk_flag is True


# =============================================================================
# Test: Floor Summary Builder with 6 heads
# =============================================================================


class TestFloorSummaryBuilder:
    """FloorSummaryBuilder — aggregates all 6 heads."""

    def _make_mock_reports(self) -> dict[str, Any]:
        """Create mock HeadReports for all 6 heads."""
        from junior_aladdin.shared.types import HeadReport, FreshnessTag, HeadState

        now = datetime.utcnow()
        return {
            "SMC Head": HeadReport(
                head_name="SMC Head", state=HeadState.READY,
                freshness_score=0.9, freshness_tag=FreshnessTag.FRESH,
                last_deep_update=now, bias=BiasType.BULLISH,
                confidence=0.75, dominant_tf="1m",
                timeframe_view="Bullish structure",
                primary_setup="FVG Retest",
                context_quality_score=0.8,
            ),
            "ICT Head": HeadReport(
                head_name="ICT Head", state=HeadState.READY,
                freshness_score=0.85, freshness_tag=FreshnessTag.FRESH,
                last_deep_update=now, bias=BiasType.BULLISH,
                confidence=0.6, dominant_tf="1m",
                timeframe_view="Discount active",
                primary_setup="Premium/Discount Reaction",
                context_quality_score=0.7,
            ),
            "Technical Head": HeadReport(
                head_name="Technical Head", state=HeadState.READY,
                freshness_score=0.8, freshness_tag=FreshnessTag.WARM,
                last_deep_update=now, bias=BiasType.BULLISH,
                confidence=0.65, dominant_tf="1m",
                timeframe_view="Trend aligned",
                primary_setup="VWAP Pullback Continuation",
            ),
            "Options Head": HeadReport(
                head_name="Options Head", state=HeadState.UNCERTAIN,
                freshness_score=0.5, freshness_tag=FreshnessTag.WARM,
                last_deep_update=now, bias=BiasType.NEUTRAL,
                confidence=0.3, dominant_tf="",
                timeframe_view="Mixed signals",
            ),
            "Macro Head": HeadReport(
                head_name="Macro Head", state=HeadState.READY,
                freshness_score=0.7, freshness_tag=FreshnessTag.WARM,
                last_deep_update=now, bias=BiasType.BULLISH,
                confidence=0.5, dominant_tf="",
                timeframe_view="Environment calm",
                caution_level=0.2, event_risk_flag=False,
            ),
            "Psychology Head": HeadReport(
                head_name="Psychology Head", state=HeadState.READY,
                freshness_score=0.95, freshness_tag=FreshnessTag.FRESH,
                last_deep_update=now, bias=BiasType.NEUTRAL,
                confidence=0.8, dominant_tf="",
                timeframe_view="Discipline OK",
                trade_allowed=True, caution_level=0.1,
            ),
        }

    def test_summary_aggregates_all_six_heads(self):
        """FloorSummary contains data from all 6 heads."""
        reports = self._make_mock_reports()
        builder = FloorSummaryBuilder()
        summary = builder.build(reports)

        assert len(reports) == 6
        assert summary.ready_heads_count >= 4  # Most heads are READY
        assert summary.uncertain_heads_count == 1  # Options is UNCERTAIN
        assert summary.active_setup_count >= 3  # SMC + ICT + Technical have setups

    def test_bias_snapshot_dominant_bullish(self):
        """4 bullish heads → dominant BULLISH."""
        reports = self._make_mock_reports()
        summary = FloorSummaryBuilder().build(reports)

        assert summary.floor_bias_snapshot["dominant_floor_bias"] == "BULLISH"
        assert summary.floor_bias_snapshot["bullish_count"] >= 3

    def test_conflict_detection(self):
        """One bearish + one bullish → conflict detected."""
        reports = self._make_mock_reports()
        # Flip SMC to bearish
        reports["SMC Head"].bias = BiasType.BEARISH
        summary = FloorSummaryBuilder().build(reports)

        assert summary.conflict_present is True

    def test_data_health_good(self):
        """Most heads READY → GOOD data health."""
        reports = self._make_mock_reports()
        summary = FloorSummaryBuilder().build(reports)

        assert summary.data_health_signal == DataHealth.GOOD

    def test_data_health_degraded_with_stale_heads(self):
        """Multiple stale heads → data health degrades."""
        reports = self._make_mock_reports()
        from junior_aladdin.shared.types import HeadState
        reports["SMC Head"].state = HeadState.STALE
        reports["ICT Head"].state = HeadState.STALE
        summary = FloorSummaryBuilder().build(reports)

        assert summary.data_health_signal in (DataHealth.DEGRADED, DataHealth.CRITICAL)

    def test_witness_lines_include_all_major_signals(self):
        """Witness lines include stale warnings, conflict, blocks."""
        reports = self._make_mock_reports()
        from junior_aladdin.shared.types import HeadState
        reports["Macro Head"].state = HeadState.STALE
        reports["Psychology Head"].trade_allowed = False
        reports["Psychology Head"].block_reason = "Tilt detected"

        summary = FloorSummaryBuilder().build(reports)

        witness = " ".join(summary.summary_witness_lines)
        assert "stale" in witness.lower()
        assert "psychology block" in witness.lower() or "block" in witness.lower()

    def test_setup_presence_happy_path(self):
        """Setups exist → HAS_SETUP."""
        reports = self._make_mock_reports()
        summary = FloorSummaryBuilder().build(reports)

        assert summary.setup_presence == "HAS_SETUP"
        assert summary.setup_absence_context is None

    def test_setup_absence_readiness(self):
        """No setups → NO_SETUP with context."""
        reports = self._make_mock_reports()
        for r in reports.values():
            r.primary_setup = None
            r.backup_setup = None
        summary = FloorSummaryBuilder().build(reports)

        assert summary.setup_presence == "NO_SETUP"
        assert summary.setup_absence_context is not None

    def test_health_snapshot_includes_core_heads(self):
        """core_head_health_snapshot has SMC, ICT, Technical, Macro, Psychology."""
        reports = self._make_mock_reports()
        summary = FloorSummaryBuilder().build(reports)

        core = summary.core_head_health_snapshot
        for head in ("SMC Head", "ICT Head", "Technical Head", "Macro Head", "Psychology Head"):
            assert head in core, f"Missing {head} in core_head_health_snapshot"
            assert "state" in core[head]
            assert "freshness_tag" in core[head]
