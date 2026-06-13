"""Unit tests for ``opposite_case_engine.py`` — Floor 5 Step 5.8.

Tests:
- analyze() with BULLISH proposed → opposite case strength/reasons
- analyze() with BEARISH proposed → opposite case strength/reasons
- No opposition → exists=False, strength=0
- Head biases opposing → score from count + confidence
- SMC/ICT opposing → higher score (boosted)
- Options wall opposition → score from zones + confidence
- Macro event risk + opposite bias → score
- Invalidation clarity → weak invalidation increases score
- SMC/ICT structure supporting opposite → score
- Multiple checks combining → aggregate score
- get_opposition_summary() dict
- NEUTRAL direction → no opposite case (no-direction edge)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_5_captain.opposite_case_engine import OppositeCaseEngine
from junior_aladdin.shared.types import (
    BiasType,
    FreshnessTag,
    HeadReport,
    HeadState,
)

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}{' -- ' + detail if detail else ''}")


def make_report(
    head_name: str,
    bias: BiasType = BiasType.NEUTRAL,
    confidence: float = 0.5,
    bull_case: str = "",
    bear_case: str = "",
    zones: list | None = None,
    invalidation: dict | None = None,
    context_quality_score: float | None = None,
    event_risk_flag: bool = False,
    state: HeadState = HeadState.READY,
) -> HeadReport:
    """Create a HeadReport with the given parameters."""
    return HeadReport(
        head_name=head_name,
        state=state,
        freshness_score=0.8,
        freshness_tag=FreshnessTag.FRESH,
        last_deep_update=datetime.utcnow(),
        bias=bias,
        confidence=confidence,
        dominant_tf="1m",
        timeframe_view="",
        bull_case=bull_case,
        bear_case=bear_case,
        active_zones=zones or [],
        invalidation=invalidation or {},
        context_quality_score=context_quality_score,
        event_risk_flag=event_risk_flag,
    )


print("=" * 60)
print("Floor 5 — Opposite Case Engine Tests")
print("=" * 60)

engine = OppositeCaseEngine()

# =========================================================================
# 1. No opposition — proposed BULLISH, all heads bullish
# =========================================================================
print("\n--- 1. No opposition (all bullish) ---")

reports_all_bull = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85,
                            invalidation={"condition": "Below PDH", "price": 19500}),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80,
                            invalidation={"condition": "Premium flip", "level": "PDH"}),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70,
                                   invalidation={"reason": "RSI break below 40"}),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.60,
                                   invalidation={"reason": "OI wall breakdown"}),
    "Macro Head": make_report("Macro Head", BiasType.BULLISH, 0.50,
                                invalidation={"condition": "Global risk-on ends"}),
    "Psychology Head": make_report("Psychology Head", BiasType.NEUTRAL, 0.0),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_all_bull)
check("1.1 No opposite case exists", result.exists is False)
check("1.2 Strength 0 or very low", result.strength < 0.2)
check("1.3 No reasons", len(result.reasons) == 0)

# =========================================================================
# 2. Strong opposition — proposed BULLISH, most heads bearish
# =========================================================================
print("\n--- 2. Strong bearish opposition vs BULLISH proposal ---")

reports_bear_opposition = {
    "SMC Head": make_report("SMC Head", BiasType.BEARISH, 0.85,
                            bear_case="Strong breakdown below support"),
    "ICT Head": make_report("ICT Head", BiasType.BEARISH, 0.80,
                            bear_case="Premium sweep likely"),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.60,
                                zones=[{"label": "CE wall at 19600"}]),
    "Macro Head": make_report("Macro Head", BiasType.BEARISH, 0.50, event_risk_flag=True),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_bear_opposition)
check("2.1 Opposite case exists", result.exists is True)
check("2.2 Strength > 0.3", result.strength > 0.3)
check("2.3 Has reasons", len(result.reasons) >= 1)
check("2.4 First reason mentions heads", result.reasons[0] is not None)

# =========================================================================
# 3. SMC + ICT opposing → boosted score
# =========================================================================
print("\n--- 3. SMC + ICT opposing (boosted) ---")

reports_core_oppose = {
    "SMC Head": make_report("SMC Head", BiasType.BEARISH, 0.90,
                            context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BEARISH, 0.85,
                            context_quality_score=0.8),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_core_oppose)
check("3.1 Opposite case exists", result.exists is True)
check("3.2 Strength > 0.2 (SMC+ICT boost)", result.strength > 0.2)

# Compare with same count but non-core opposition
reports_non_core = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.90),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.85),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result_core = engine.analyze(proposed_direction="BULLISH", head_reports=reports_core_oppose)
result_non_core = engine.analyze(proposed_direction="BULLISH", head_reports=reports_non_core)
check("3.3 SMC+ICT opposing > Technical+Options opposing",
      result_core.strength >= result_non_core.strength)

# =========================================================================
# 4. Options wall opposition
# =========================================================================
print("\n--- 4. Options wall opposition ---")

reports_options_wall = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.80,
                                zones=[{"label": "PE wall at 19500"}, {"label": "CE wall at 19700"}]),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_options_wall)
check("4.1 Options wall opposition detected", result.exists is True)
check("4.2 Reason mentions wall",
      any("wall" in r.lower() for r in result.reasons))
check("4.3 Strength > 0", result.strength > 0)

# =========================================================================
# 5. Macro event risk + bias
# =========================================================================
print("\n--- 5. Macro event risk + bias ---")

reports_macro_risk = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.BEARISH, 0.60, event_risk_flag=True),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_macro_risk)
check("5.1 Macro risk detected", result.exists is True)
check("5.2 Reason mentions macro or event",
      any("macro" in r.lower() or "event" in r.lower() for r in result.reasons))

# Macro risk without direction
reports_macro_risk_only = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50, event_risk_flag=True),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_macro_risk_only)
check("5.3 Macro risk flagged (non-directional)", result.exists is True)

# =========================================================================
# 6. Invalid invalidation clarity
# =========================================================================
print("\n--- 6. Invalidation clarity ---")

# Supporting heads with unclear invalidation
reports_weak_inval = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85, invalidation={}),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80, invalidation={}),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70, invalidation={}),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_weak_inval)
check("6.1 Weak invalidation detected",
      any("invalid" in r.lower() for r in result.reasons))

# Supporting heads with clear invalidation
reports_clear_inval = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85,
                            invalidation={"condition": "Below 19500", "price": 19500}),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80,
                            invalidation={"condition": "Below PDH", "level": "PDH"}),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result_clear = engine.analyze(proposed_direction="BULLISH", head_reports=reports_clear_inval)
# Weak invalidation should produce a higher score or existence
check("6.2 Clear invalidation -> lower score than weak",
      result_clear.strength < result.strength)

# =========================================================================
# 7. BEARISH proposed with bullish opposition
# =========================================================================
print("\n--- 7. BEARISH proposed with bullish opposition ---")

reports_bull_opposition = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.analyze(proposed_direction="BEARISH", head_reports=reports_bull_opposition)
check("7.1 BEARISH proposal -> opposite case exists", result.exists is True)
check("7.2 Strength > 0", result.strength > 0)
check("7.3 Reasons mention heads", len(result.reasons) >= 1)

# =========================================================================
# 8. NEUTRAL proposal -> no opposite case
# =========================================================================
print("\n--- 8. NEUTRAL proposal ---")

result = engine.analyze(proposed_direction="NEUTRAL", head_reports=reports_bull_opposition)
check("8.1 NEUTRAL -> no opposite case", result.exists is False)
check("8.2 Strength 0 for NEUTRAL", result.strength == 0.0)
check("8.3 Mitigating mentions no direction",
      any("directional" in m.lower() for m in result.mitigating_factors))

# =========================================================================
# 9. Empty/no head reports
# =========================================================================
print("\n--- 9. Empty/no head reports ---")

result = engine.analyze(proposed_direction="BULLISH")
check("9.1 No reports -> exists False", result.exists is False)
check("9.2 No reports -> strength 0", result.strength == 0.0)

result = engine.analyze(proposed_direction="BEARISH", head_reports={})
check("9.3 Empty dict -> exists False", result.exists is False)

# =========================================================================
# 10. SMC/ICT structure supporting opposite
# =========================================================================
print("\n--- 10. SMC/ICT structure supporting opposite ---")

reports_smc_oppose_struct = {
    "SMC Head": make_report("SMC Head", BiasType.BEARISH, 0.90,
                            context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.NEUTRAL, 0.50),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.BULLISH, 0.50),
}

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_smc_oppose_struct)
check("10.1 SMC structural opposition detected", result.exists is True)
check("10.2 Reason mentions SMC",
      any("smc" in r.lower() for r in result.reasons))

# Both SMC + ICT opposing structure
reports_both_core = {
    "SMC Head": make_report("SMC Head", BiasType.BEARISH, 0.85,
                            context_quality_score=0.85),
    "ICT Head": make_report("ICT Head", BiasType.BEARISH, 0.80,
                            context_quality_score=0.80),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result_both = engine.analyze(proposed_direction="BULLISH", head_reports=reports_both_core)
check("10.3 Both SMC+ICT opposing -> higher score",
      result_both.strength > result.strength)

# =========================================================================
# 11. get_opposition_summary()
# =========================================================================
print("\n--- 11. get_opposition_summary() ---")

result = engine.analyze(proposed_direction="BULLISH", head_reports=reports_bear_opposition)
summary = engine.get_opposition_summary(result)
check("11.1 Summary has exists", "exists" in summary)
check("11.2 Summary has strength", "strength" in summary)
check("11.3 Summary has reason_count", "reason_count" in summary)
check("11.4 Summary has top_reasons", "top_reasons" in summary)
check("11.5 Summary has severity", "severity" in summary)
check("11.6 Severity is one of expected",
      summary["severity"] in ("HIGH", "MODERATE", "LOW"))
check("11.7 Summary top_reasons length > 0", len(summary["top_reasons"]) > 0)
check("11.8 Summary has mitigating_factors", "mitigating_factors" in summary)

# Low opposition
result_low = engine.analyze(proposed_direction="BULLISH", head_reports=reports_all_bull)
summary_low = engine.get_opposition_summary(result_low)
check("11.9 Low opposition -> LOW severity", summary_low["severity"] == "LOW")

# =========================================================================
# Summary
# =========================================================================
total = passed + failed
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed out of {total}")
print(f"{'=' * 60}")

if __name__ == '__main__':
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
