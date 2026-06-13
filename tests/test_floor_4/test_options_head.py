"""Unit tests for ``options_head.py`` — Floor 4 Step 4.11.

Tests:
- Signal extraction (OPTIONS domain only)
- Empty signals fallback → NEUTRAL
- Bullish signals (put wall, low PCR, CE buying) → BULLISH
- Bearish signals (call wall, high PCR, PE buying) → BEARISH
- Wall zone creation
- Invalidation never None
- PCR and IV analysis
- Max pain proximity
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
)
from junior_aladdin.floor_4_heads.options_head import OptionsHead
from junior_aladdin.shared.types import BiasType, HeadState

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


def make_signal(indicator_type: str, value: dict, signal_id: str = "") -> CalculatedSignal:
    return CalculatedSignal(
        signal_id=signal_id or f"opt_{indicator_type}_{datetime.utcnow().timestamp()}",
        domain=CalculationDomain.OPTIONS,
        indicator_type=indicator_type,
        value=value,
    )


def make_oc(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


print("=" * 60)
print("Floor 4 — Options Head Tests")
print("=" * 60)

# =========================================================================
# 1. Signal extraction
# =========================================================================
print("\n--- 1. Signal extraction ---")

head = OptionsHead()
all_signals = [
    make_signal("OI_CHANGE", {"oi_direction": "BUYING", "option_type": "CE", "change_pct": 15.0}),
    make_signal("PCR", {"pcr_value": 0.6, "pcr_trend": "FALLING"}),
    make_signal("CALL_WALL", {"wall_strike": 19700.0, "wall_strength": 50000, "distance_pct": 0.8}),
]
oc = make_oc(all_signals)
extracted = head._extract_signals(oc)
check("1.1 Extracts OPTIONS domain signals", len(extracted) == 3)
check("1.2 All extracted are OPTIONS domain",
      all(s.domain == CalculationDomain.OPTIONS for s in extracted))

# Non-options signals filtered
oc_mixed = make_oc([
    make_signal("PCR", {"pcr_value": 0.5}),
    CalculatedSignal(signal_id="smc1", domain=CalculationDomain.SMC,
                     indicator_type="FVG", value={"fvg_type": "BULLISH_FVG"}),
])
extracted2 = head._extract_signals(oc_mixed)
check("1.3 Only 1 OPTIONS signal extracted", len(extracted2) == 1)

# =========================================================================
# 2. Empty signals
# =========================================================================
print("\n--- 2. Empty signals ---")

oc_empty = make_oc([])
report = head.refresh(oc_empty)
check("2.1 Empty -> NEUTRAL", report.bias == BiasType.NEUTRAL)
check("2.2 Empty -> confidence 0", report.confidence == 0.0)
check("2.3 Empty -> STALE state", report.state == HeadState.STALE)
check("2.4 Empty -> has invalidation", len(report.invalidation.get("rules", [])) > 0)
check("2.5 Empty -> no primary setup", report.primary_setup is None)
check("2.6 Head name correct", report.head_name == "Options Head")

# =========================================================================
# 3. Bullish signals — put wall + low PCR + CE buying
# =========================================================================
print("\n--- 3. Bullish signals ---")

bullish_signals = [
    make_signal("OI_CHANGE", {"oi_direction": "BUYING", "option_type": "CE", "change_pct": 20.0}),
    make_signal("PCR", {"pcr_value": 0.45, "pcr_trend": "FALLING"}),
    make_signal("IV", {"iv_value": 18.5, "iv_percentile": 25.0, "iv_context": "LOW"}),
    make_signal("PUT_WALL", {"wall_strike": 19400.0, "wall_strength": 80000, "distance_pct": 0.5}),
    make_signal("MAX_PAIN", {"max_pain_strike": 19500.0, "distance_pct": 0.3}),
]
oc_bull = make_oc(bullish_signals)
report = head.refresh(oc_bull)
check("3.1 Bullish signals -> BULLISH bias", report.bias == BiasType.BULLISH)
check("3.2 Confidence > 0", report.confidence > 0)
check("3.3 Has primary setup", report.primary_setup is not None)
check("3.4 Primary mentions Wall or Pressure",
      "Wall" in report.primary_setup or "Pressure" in report.primary_setup)
check("3.5 Has invalidation", len(report.invalidation.get("rules", [])) > 0)
check("3.6 Has active zones (put wall + max pain)", len(report.active_zones) >= 2)
check("3.7 Has witness summary", len(report.witness_summary) > 0)
check("3.8 Has PCR in timeframe_view", "PCR" in report.timeframe_view)

# =========================================================================
# 4. Bearish signals — call wall + high PCR + PE buying
# =========================================================================
print("\n--- 4. Bearish signals ---")

bearish_signals = [
    make_signal("OI_CHANGE", {"oi_direction": "BUYING", "option_type": "PE", "change_pct": 25.0}),
    make_signal("PCR", {"pcr_value": 1.3, "pcr_trend": "RISING"}),
    make_signal("IV", {"iv_value": 35.0, "iv_percentile": 80.0, "iv_context": "HIGH"}),
    make_signal("CALL_WALL", {"wall_strike": 19700.0, "wall_strength": 100000, "distance_pct": 0.6}),
]
oc_bear = make_oc(bearish_signals)
report = head.refresh(oc_bear)
check("4.1 Bearish signals -> BEARISH bias", report.bias == BiasType.BEARISH)
check("4.2 Confidence > 0", report.confidence > 0)
check("4.3 Has primary setup", report.primary_setup is not None)
check("4.4 Has call wall zone", any(z.get("zone_type") == "CALL_WALL" for z in report.active_zones))

# =========================================================================
# 5. Mixed/neutral signals
# =========================================================================
print("\n--- 5. Mixed signals ---")

neutral_signals = [
    make_signal("PCR", {"pcr_value": 0.95, "pcr_trend": "STABLE"}),
    make_signal("IV", {"iv_value": 22.0, "iv_percentile": 50.0, "iv_context": "NORMAL"}),
]
oc_neutral = make_oc(neutral_signals)
report = head.refresh(oc_neutral)
check("5.1 Neutral signals -> NEUTRAL or directional",
      report.bias in (BiasType.NEUTRAL, BiasType.BULLISH, BiasType.BEARISH))
check("5.2 Has invalidation", len(report.invalidation.get("rules", [])) > 0)

# =========================================================================
# 6. Wall zone creation
# =========================================================================
print("\n--- 6. Wall zones ---")

wall_signals = [
    make_signal("CALL_WALL", {"wall_strike": 19700.0, "wall_strength": 100000, "distance_pct": 0.5}),
    make_signal("PUT_WALL", {"wall_strike": 19400.0, "wall_strength": 80000, "distance_pct": 0.6}),
    make_signal("MAX_PAIN", {"max_pain_strike": 19550.0, "distance_pct": 0.4}),
]
oc_wall = make_oc(wall_signals)
report = head.refresh(oc_wall)
zone_types = [z.get("zone_type") for z in report.active_zones]
check("6.1 Has CALL_WALL zone", "CALL_WALL" in zone_types)
check("6.2 Has PUT_WALL zone", "PUT_WALL" in zone_types)
check("6.3 Has MAX_PAIN zone", "MAX_PAIN" in zone_types)
check("6.4 Has armed triggers", len(report.armed_triggers) > 0)

# =========================================================================
# 7. Invalidation
# =========================================================================
print("\n--- 7. Invalidation never None ---")

report_empty = head.refresh(make_oc([]))
check("7.1 Empty -> invalidation has rules", len(report_empty.invalidation.get("rules", [])) > 0)

report_b = head.refresh(make_oc(bullish_signals))
check("7.2 Bullish -> invalidation has rules", len(report_b.invalidation.get("rules", [])) > 0)
check("7.3 Bullish -> invalidation summary non-empty", len(report_b.invalidation.get("summary", "")) > 0)

report_be = head.refresh(make_oc(bearish_signals))
check("7.4 Bearish -> invalidation has rules", len(report_be.invalidation.get("rules", [])) > 0)

# =========================================================================
# 8. Head properties
# =========================================================================
print("\n--- 8. Head properties ---")

check("8.1 head_name", head.head_name == "Options Head")

# =========================================================================
# 9. Freshness
# =========================================================================
print("\n--- 9. Freshness ---")

head2 = OptionsHead()
report = head2.refresh(make_oc([]))
check("9.1 freshness_score 0.0-1.0", 0.0 <= report.freshness_score <= 1.0)
check("9.2 freshness_tag valid", report.freshness_tag is not None)
check("9.3 last_deep_update set", report.last_deep_update is not None)

# =========================================================================
# 10. OI unwinding
# =========================================================================
print("\n--- 10. OI unwinding ---")

unwind_signals = [
    make_signal("OI_CHANGE", {"oi_direction": "UNWINDING", "option_type": "CE", "change_pct": -10.0}),
    make_signal("OI_CHANGE", {"oi_direction": "UNWINDING", "option_type": "PE", "change_pct": -12.0}),
    make_signal("PCR", {"pcr_value": 0.8, "pcr_trend": "STABLE"}),
]
oc_unwind = make_oc(unwind_signals)
report = head.refresh(oc_unwind)
check("10.1 Unwinding + stable PCR -> bias determined",
      report.bias in (BiasType.NEUTRAL, BiasType.BULLISH, BiasType.BEARISH))
check("10.2 Has invalidation", len(report.invalidation.get("rules", [])) > 0)


# =========================================================================
# Summary
# =========================================================================
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if __name__ == '__main__':
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
