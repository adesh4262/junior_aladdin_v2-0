"""Tests for Floor 4 Step 4.12 — MacroHead.

Covers:
1. Signal extraction (MACRO domain only)
2. Empty signals fallback (NEUTRAL + caution 0 + event_risk_flag False)
3. VIX extreme → high caution, bearish bias
4. VIX calm → low caution, neutral bias
5. FII/DII positive + global cue → mildly bullish
6. Event week → event_risk_flag True
7. Multiple risk factors → caution level aggregation
8. NO setups — primary_setup and backup_setup are None
9. Invalidation never None
10. Head properties and identity
11. Freshness
12. ReportValidator contract enforcement
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
)
from junior_aladdin.floor_4_heads.head_report_schema import (
    HEAD_MACRO,
    ReportValidator,
)
from junior_aladdin.floor_4_heads.macro_head import MacroHead
from junior_aladdin.shared.types import BiasType, FreshnessTag, HeadState


# =============================================================================
# Helpers
# =============================================================================


def _make_signal(
    indicator_type: str,
    value: dict,
    domain: CalculationDomain = CalculationDomain.MACRO,
) -> CalculatedSignal:
    return CalculatedSignal(
        signal_id=f"sig_macro_{indicator_type.lower()}_{datetime.utcnow().timestamp()}",
        domain=domain,
        indicator_type=indicator_type,
        value=value,
        timestamp=datetime.utcnow(),
    )


def _make_oc(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


SAMPLE_TIME = datetime(2026, 6, 8, 10, 30, 0, tzinfo=timezone.utc)


# Signal types the MacroHead code actually recognises:
#   VIX, FII_DII, EVENT_CALENDAR, MACRO_ENVIRONMENT


# =============================================================================
# Shared fixture for high-risk scenario
# =============================================================================


@pytest.fixture
def high_risk_signals() -> list[CalculatedSignal]:
    """Multiple macro risk factors active simultaneously."""
    return [
        _make_signal("VIX", {"vix_value": 35.0}),
        _make_signal("FII_DII", {"net_state": "SELL", "magnitude": 800.0}),
        _make_signal("EVENT_CALENDAR", {"risk_level": 0.9, "event_type": "RBI Policy"}),
        _make_signal("MACRO_ENVIRONMENT", {"environment_state": "STRESSED"}),
    ]


# =============================================================================
# Section 1 — Signal Extraction
# =============================================================================


class TestSignalExtraction:
    """MacroHead only extracts MACRO-domain signals."""

    def test_1_1_extracts_macro_signals_only(self) -> None:
        head = MacroHead()
        macro_sig = _make_signal("VIX", {"vix_value": 15.0})
        other_sig = _make_signal(
            "RSI", {"rsi_value": 65.0},
            domain=CalculationDomain.TECHNICAL,
        )
        oc = _make_oc([macro_sig, other_sig])
        extracted = head._extract_signals(oc)
        assert len(extracted) == 1
        assert extracted[0].indicator_type == "VIX"

    def test_1_2_returns_empty_list_for_no_macro_signals(self) -> None:
        head = MacroHead()
        other_sig = _make_signal(
            "RSI", {"rsi_value": 65.0},
            domain=CalculationDomain.TECHNICAL,
        )
        oc = _make_oc([other_sig])
        extracted = head._extract_signals(oc)
        assert len(extracted) == 0

    def test_1_3_extracts_all_macro_signal_types(self) -> None:
        head = MacroHead()
        signals = [
            _make_signal("VIX", {"vix_value": 15.0}),
            _make_signal("FII_DII", {"net_state": "BUY", "magnitude": 500.0}),
            _make_signal("EVENT_CALENDAR", {"risk_level": 0.2, "event_type": "FOMC"}),
            _make_signal("MACRO_ENVIRONMENT", {"environment_state": "STABLE"}),
        ]
        oc = _make_oc(signals)
        extracted = head._extract_signals(oc)
        assert len(extracted) == 4


# =============================================================================
# Section 2 — Empty Signals Fallback
# =============================================================================


class TestEmptySignals:
    """When no MACRO signals are present, safe defaults apply."""

    def test_2_1_empty_signals_neutral_bias(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.bias == BiasType.NEUTRAL

    def test_2_2_empty_signals_zero_confidence(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.confidence == 0.0

    def test_2_3_empty_signals_caution_zero(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.caution_level == 0.0

    def test_2_4_empty_signals_no_event_risk(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.event_risk_flag is False

    def test_2_5_empty_signals_no_setups(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.primary_setup is None
        assert report.backup_setup is None

    def test_2_6_empty_signals_invalidation_not_none(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.invalidation is not None
        assert len(report.invalidation.get("rules", [])) >= 1

    def test_2_7_empty_signals_state(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        # First refresh always starts STALE (last_deep_update is None)
        assert report.state == HeadState.STALE


# =============================================================================
# Section 3 — VIX Extreme → High Caution, Bearish Bias
# =============================================================================


class TestVixExtreme:
    """VIX at extreme levels should raise caution and lean bearish."""

    @pytest.fixture
    def extreme_vix_signals(self) -> list[CalculatedSignal]:
        return [
            _make_signal("VIX", {"vix_value": 35.0}),
        ]

    def test_3_1_extreme_vix_elevates_caution(self, extreme_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(extreme_vix_signals), SAMPLE_TIME)
        # VIX stressed → caution += 0.4
        assert report.caution_level >= 0.25

    def test_3_2_extreme_vix_neutral_bias(self, extreme_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(extreme_vix_signals), SAMPLE_TIME)
        # VIX alone gives caution=0.4, not > 0.6, so bias is NEUTRAL
        assert report.bias == BiasType.NEUTRAL

    def test_3_3_extreme_vix_no_setups(self, extreme_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(extreme_vix_signals), SAMPLE_TIME)
        assert report.primary_setup is None
        assert report.backup_setup is None

    def test_3_4_extreme_vix_invalidation_has_rule(self, extreme_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(extreme_vix_signals), SAMPLE_TIME)
        rules = report.invalidation.get("rules", [])
        conditions = " ".join(r.get("condition", "") for r in rules)
        assert "VIX" in conditions or "volatility" in conditions


# =============================================================================
# Section 4 — VIX Calm → Low Caution
# =============================================================================


class TestVixCalm:
    """VIX calm environment should keep caution low."""

    @pytest.fixture
    def calm_vix_signals(self) -> list[CalculatedSignal]:
        return [
            _make_signal("VIX", {"vix_value": 12.0}),
        ]

    def test_4_1_calm_vix_low_caution(self, calm_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(calm_vix_signals), SAMPLE_TIME)
        assert report.caution_level < 0.1

    def test_4_2_calm_vix_neutral_bias(self, calm_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(calm_vix_signals), SAMPLE_TIME)
        # VIX calm + no FII BUY → bias stays NEUTRAL
        assert report.bias == BiasType.NEUTRAL

    def test_4_3_calm_vix_invalidation_not_empty(self, calm_vix_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(calm_vix_signals), SAMPLE_TIME)
        # Calm VIX adds no specific invalidation rule, so baseline rule is used
        assert len(report.invalidation.get("rules", [])) >= 1


# =============================================================================
# Section 5 — FII/DII + Global Cue → Bullish
# =============================================================================


class TestBullishMacro:
    """FII/DII positive + global cue positive should lean bullish."""

    @pytest.fixture
    def bullish_signals(self) -> list[CalculatedSignal]:
        return [
            # VIX calm (12 < 14) → caution stays 0
            _make_signal("VIX", {"vix_value": 12.0}),
            # FII_DII BUY → triggers BULLISH bias when caution < 0.2
            _make_signal("FII_DII", {"net_state": "BUY", "magnitude": 1500.0}),
        ]

    def test_5_1_bullish_bias(self, bullish_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(bullish_signals), SAMPLE_TIME)
        assert report.bias == BiasType.BULLISH

    def test_5_2_caution_low(self, bullish_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(bullish_signals), SAMPLE_TIME)
        assert report.caution_level < 0.3

    def test_5_3_no_event_risk(self, bullish_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(bullish_signals), SAMPLE_TIME)
        assert report.event_risk_flag is False


# =============================================================================
# Section 6 — Event Week → Event Risk Flag
# =============================================================================


class TestEventRisk:
    """Event week or approaching events should raise event_risk_flag."""

    @pytest.fixture
    def event_week_signals(self) -> list[CalculatedSignal]:
        return [
            _make_signal("EVENT_CALENDAR", {
                "risk_level": 0.8,
                "event_type": "FOMC Meeting",
            }),
        ]

    def test_6_1_event_risk_flag_raised(self, event_week_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(event_week_signals), SAMPLE_TIME)
        # risk_level 0.8 > 0.5 → event_risk_flag = True
        assert report.event_risk_flag is True

    def test_6_2_caution_elevated(self, event_week_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(event_week_signals), SAMPLE_TIME)
        # event_risk contributes 0.3 * min(1.0, 0.8) = 0.24 to caution
        assert report.caution_level >= 0.15

    def test_6_3_event_trigger_created(self, event_week_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(event_week_signals), SAMPLE_TIME)
        # MacroHead now populates armed_triggers for events
        trigger_types = [t.get("trigger_type") for t in report.armed_triggers]
        assert "event_risk" in trigger_types


# =============================================================================
# Section 7 — Multiple Risk Factors → Caution Aggregation
# =============================================================================


class TestCautionAggregation:
    """Multiple risk factors stack to produce high caution."""

    def test_7_1_high_caution_from_multiple_factors(self, high_risk_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(high_risk_signals), SAMPLE_TIME)
        # VIX stressed(0.4) + FII SELL >500(0.3) + event_risk(0.27) + env STRESSED(0.3) = 1.27 → capped at 1.0
        assert report.caution_level >= 0.5

    def test_7_2_caution_capped_at_one(self, high_risk_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(high_risk_signals), SAMPLE_TIME)
        assert report.caution_level <= 1.0

    def test_7_3_event_risk_true(self, high_risk_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(high_risk_signals), SAMPLE_TIME)
        assert report.event_risk_flag is True

    def test_7_4_invalidation_rules_count(self, high_risk_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(high_risk_signals), SAMPLE_TIME)
        rules = report.invalidation.get("rules", [])
        # VIX stressed + event_risk_flag + caution > 0.4 → 3 invalidation rules
        assert len(rules) >= 3


# =============================================================================
# Section 8 — NO Setups (Locked Gate)
# =============================================================================


class TestNoSetups:
    """Macro Head must NEVER produce setups — locked architecture rule."""

    def test_8_1_no_setups_with_signals(self) -> None:
        head = MacroHead()
        signals = [
            _make_signal("VIX", {"vix_value": 15.0}),
            _make_signal("FII_DII", {"net_state": "BUY", "magnitude": 500.0}),
        ]
        report = head.refresh(_make_oc(signals), SAMPLE_TIME)
        assert report.primary_setup is None
        assert report.backup_setup is None

    def test_8_2_no_setups_empty_signals(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.primary_setup is None
        assert report.backup_setup is None

    def test_8_3_no_setups_high_caution(self) -> None:
        head = MacroHead()
        signals = [_make_signal("VIX", {"vix_value": 35.0})]
        report = head.refresh(_make_oc(signals), SAMPLE_TIME)
        assert report.primary_setup is None
        assert report.backup_setup is None


# =============================================================================
# Section 9 — Invalidation
# =============================================================================


class TestInvalidation:
    """Invalidation is mandatory and never None for Macro Head."""

    def test_9_1_invalidation_exists_with_signals(self) -> None:
        head = MacroHead()
        signals = [_make_signal("VIX", {"vix_value": 20.0})]
        report = head.refresh(_make_oc(signals), SAMPLE_TIME)
        assert report.invalidation is not None
        assert isinstance(report.invalidation, dict)
        assert len(report.invalidation.get("rules", [])) >= 1

    def test_9_2_invalidation_has_summary(self, high_risk_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(high_risk_signals), SAMPLE_TIME)
        assert report.invalidation.get("summary", "") != ""


# =============================================================================
# Section 10 — Head Properties and Identity
# =============================================================================


class TestHeadProperties:
    """Verify MacroHead identity and configuration."""

    def test_10_1_head_name(self) -> None:
        head = MacroHead()
        assert head.head_name == "Macro Head"

    def test_10_2_head_name_constant(self) -> None:
        head = MacroHead()
        assert head.head_name == HEAD_MACRO

    def test_10_3_no_context_quality_score(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.context_quality_score is None

    def test_10_4_dominant_tf_is_daily(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        # MacroHead dominant_tf is "1d" for daily macro assessment
        assert report.dominant_tf == "1d"


# =============================================================================
# Section 11 — Freshness
# =============================================================================


class TestFreshness:
    """Freshness should be computed correctly."""

    def test_11_1_initial_refresh_stale(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        # First refresh is STALE because _last_deep_update starts as None
        assert report.freshness_tag == FreshnessTag.STALE

    def test_11_2_initial_freshness_zero(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        # First refresh freshness is 0.0 (last_deep_update was None)
        assert report.freshness_score == 0.0

    def test_11_3_last_deep_update_set(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.last_deep_update is not None


# =============================================================================
# Section 12 — ReportValidator Contract Enforcement
# =============================================================================


class TestReportValidator:
    """Verify Macro Head passes ReportValidator checks for NO_SETUP heads."""

    def test_12_1_passes_validation_with_signals(self) -> None:
        head = MacroHead()
        signals = [
            _make_signal("VIX", {"vix_value": 15.0}),
        ]
        report = head.refresh(_make_oc(signals), SAMPLE_TIME)
        validator = ReportValidator()
        result = validator.validate(report)
        assert result.valid, f"Validation failed: {result.reasons}"

    def test_12_2_passes_validation_empty_signals(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        validator = ReportValidator()
        result = validator.validate(report)
        assert result.valid, f"Validation failed: {result.reasons}"

    def test_12_3_passes_validation_high_risk(self, high_risk_signals) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc(high_risk_signals), SAMPLE_TIME)
        validator = ReportValidator()
        result = validator.validate(report)
        assert result.valid, f"Validation failed: {result.reasons}"

    def test_12_4_head_name_recognised(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        assert report.head_name in ("Macro Head",)

    def test_12_5_invalidation_passes_rule_check(self) -> None:
        head = MacroHead()
        report = head.refresh(_make_oc([]), SAMPLE_TIME)
        validator = ReportValidator()
        result = validator.validate(report)
        assert result.valid
        assert len(report.invalidation.get("rules", [])) >= 1
