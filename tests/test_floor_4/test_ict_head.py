"""Unit tests for ``ict_head.py`` — Floor 4 Step 4.10.

Tests:
- Signal extraction (ICT domain only)
- Empty signals fallback → NEUTRAL + context_quality_score=0
- Premium zone signals → BEARISH bias
- Discount zone signals → BULLISH bias
- Mixed signals → NEUTRAL
- context_quality_score computation (mandatory for ICT)
- Invalidation is never None
- Kill zone triggers
- Liquidity zone analysis
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
from junior_aladdin.floor_4_heads.ict_head import ICTHead
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
        signal_id=signal_id or f"ict_{indicator_type}_{datetime.utcnow().timestamp()}",
        domain=CalculationDomain.ICT,
        indicator_type=indicator_type,
        value=value,
    )


def make_oc(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


print("=" * 60)
print("Floor 4 — ICT Head Tests")
print("=" * 60)

# =========================================================================
# 1. Signal extraction
# =========================================================================
print("\n--- 1. Signal extraction ---")

head = ICTHead()
all_signals = [
    make_signal("PD_ARRAY", {"zone_type": "PREMIUM", "price_level": 19700.0, "active": True}),
    make_signal("KILL_ZONE", {"zone_type": "LONDON_OPEN", "active": True}),
    make_signal("LIQUIDITY", {"liquidity_type": "BUY", "price_level": 19800.0, "strength": 0.7}),
]
oc = make_oc(all_signals)
extracted = head._extract_signals(oc)
check("1.1 Extracts ICT domain signals", len(extracted) == 3)
check("1.2 All extracted are ICT domain",
      all(s.domain == CalculationDomain.ICT for s in extracted))

# Non-ICT signals filtered
oc_mixed = make_oc([
    make_signal("PD_ARRAY", {"zone_type": "DISCOUNT"}),
    CalculatedSignal(signal_id="smc1", domain=CalculationDomain.SMC,
                     indicator_type="FVG", value={"fvg_type": "BULLISH_FVG"}),
])
extracted2 = head._extract_signals(oc_mixed)
check("1.3 Only 1 ICT signal extracted", len(extracted2) == 1)

# =========================================================================
# 2. Empty signals
# =========================================================================
print("\n--- 2. Empty signals ---")

oc_empty = make_oc([])
report = head.refresh(oc_empty)
check("2.1 Empty -> NEUTRAL", report.bias == BiasType.NEUTRAL)
check("2.2 Empty -> confidence 0", report.confidence == 0.0)
check("2.3 Empty -> context_quality_score 0", report.context_quality_score == 0.0)
check("2.4 Empty -> STALE state", report.state == HeadState.STALE)
check("2.5 Empty -> has invalidation", len(report.invalidation.get("rules", [])) > 0)
check("2.6 Empty -> no primary setup", report.primary_setup is None)
check("2.7 Head name correct", report.head_name == "ICT Head")

# =========================================================================
# 3. Premium zone (bearish)
# =========================================================================
print("\n--- 3. Premium zone signals -> BEARISH ---")

premium_signals = [
    make_signal("PD_ARRAY", {"zone_type": "PREMIUM", "price_level": 19700.0, "active": True, "strength": 0.8}),
    make_signal("LIQUIDITY", {"liquidity_type": "SELL", "price_level": 19600.0, "strength": 0.6}),
    make_signal("LIQUIDITY_CONTEXT", {"context_summary": "Sell pressure building", "bias": "bearish"}),
]
oc_premium = make_oc(premium_signals)
report = head.refresh(oc_premium)
check("3.1 Premium zone -> BEARISH bias", report.bias == BiasType.BEARISH)
check("3.2 context_quality_score > 0", report.context_quality_score is not None and report.context_quality_score > 0)
check("3.3 Has primary setup", report.primary_setup is not None)
check("3.4 Has invalidation rules", len(report.invalidation.get("rules", [])) > 0)
check("3.5 Has active zones (premium + liquidity)", len(report.active_zones) >= 2)
check("3.6 Has witness summary", len(report.witness_summary) > 0)

# =========================================================================
# 4. Discount zone (bullish)
# =========================================================================
print("\n--- 4. Discount zone signals -> BULLISH ---")

discount_signals = [
    make_signal("PD_ARRAY", {"zone_type": "DISCOUNT", "price_level": 19400.0, "active": True, "strength": 0.8}),
    make_signal("KILL_ZONE", {"zone_type": "NY_OPEN", "active": True}),
    make_signal("LIQUIDITY", {"liquidity_type": "BUY", "price_level": 19550.0, "strength": 0.7}),
]
oc_discount = make_oc(discount_signals)
report = head.refresh(oc_discount)
check("4.1 Discount zone -> BULLISH bias", report.bias == BiasType.BULLISH)
check("4.2 context_quality_score > 0", report.context_quality_score is not None and report.context_quality_score > 0)
check("4.3 Has primary setup", report.primary_setup is not None)
check("4.4 Has armed triggers (kill zone)", len(report.armed_triggers) > 0)

# =========================================================================
# 5. Mixed signals
# =========================================================================
print("\n--- 5. Mixed signals -> NEUTRAL ---")

mixed_signals = [
    make_signal("PD_ARRAY", {"zone_type": "PREMIUM", "price_level": 19700.0, "active": False, "strength": 0.5}),
    make_signal("PD_ARRAY", {"zone_type": "DISCOUNT", "price_level": 19400.0, "active": False, "strength": 0.5}),
]
oc_mixed = make_oc(mixed_signals)
report = head.refresh(oc_mixed)
check("5.1 Mixed signals -> NEUTRAL", report.bias == BiasType.NEUTRAL)
check("5.2 Has invalidation", len(report.invalidation.get("rules", [])) > 0)

# =========================================================================
# 6. context_quality_score
# =========================================================================
print("\n--- 6. context_quality_score ---")

# High quality: PD + kill zone + liquidity + context
high_ict = [
    make_signal("PD_ARRAY", {"zone_type": "PREMIUM", "price_level": 19700.0, "active": True, "strength": 0.8}),
    make_signal("PD_ARRAY", {"zone_type": "DISCOUNT", "price_level": 19400.0, "active": True, "strength": 0.8}),
    make_signal("KILL_ZONE", {"zone_type": "LONDON_OPEN", "active": True}),
    make_signal("LIQUIDITY", {"liquidity_type": "BUY", "price_level": 19800.0, "strength": 0.7}),
    make_signal("LIQUIDITY_CONTEXT", {"context_summary": "Balanced", "bias": "neutral"}),
]
report_hq = head.refresh(make_oc(high_ict))
check("6.1 High quality -> score > 0.7", report_hq.context_quality_score is not None and report_hq.context_quality_score >= 0.7)

# Low quality: minimal signals
low_ict = [
    make_signal("PD_ARRAY", {"zone_type": "DISCOUNT", "price_level": 19400.0, "active": False, "strength": 0.3}),
]
report_lq = head.refresh(make_oc(low_ict))
check("6.2 Low quality -> score < 0.4", report_lq.context_quality_score is not None and report_lq.context_quality_score < 0.4)

# =========================================================================
# 7. Invalidation
# =========================================================================
print("\n--- 7. Invalidation never None ---")

# Empty
report_empty = head.refresh(make_oc([]))
check("7.1 Empty -> invalidation has rules", len(report_empty.invalidation.get("rules", [])) > 0)

# Premium
report_p = head.refresh(make_oc(premium_signals))
check("7.2 Premium -> invalidation has rules", len(report_p.invalidation.get("rules", [])) > 0)

# Discount
report_d = head.refresh(make_oc(discount_signals))
check("7.3 Discount -> invalidation has rules", len(report_d.invalidation.get("rules", [])) > 0)

# =========================================================================
# 8. Head properties
# =========================================================================
print("\n--- 8. Head properties ---")

head2 = ICTHead()
check("8.1 head_name", head2.head_name == "ICT Head")

# =========================================================================
# 9. Freshness
# =========================================================================
print("\n--- 9. Freshness ---")

head3 = ICTHead()
report = head3.refresh(make_oc([]))
check("9.1 freshness_score 0.0-1.0", 0.0 <= report.freshness_score <= 1.0)
check("9.2 freshness_tag valid", report.freshness_tag is not None)
check("9.3 last_deep_update set", report.last_deep_update is not None)

# =========================================================================
# 10. Kill zone triggers
# =========================================================================
print("\n--- 10. Kill zone triggers ---")

kz_signals = [
    make_signal("KILL_ZONE", {"zone_type": "LONDON_OPEN", "active": True}),
    make_signal("KILL_ZONE", {"zone_type": "NY_OPEN", "active": True}),
    make_signal("LIQUIDITY", {"liquidity_type": "BUY", "price_level": 19500.0, "strength": 0.6}),
]
report_kz = head.refresh(make_oc(kz_signals))
trigger_types = [t.get("trigger_type", "") for t in report_kz.armed_triggers]
check("10.1 Has kill_zone_active triggers", "kill_zone_active" in trigger_types)

# =========================================================================
# 11. NEXT_KILL_ZONE signals
# =========================================================================
print("\n--- 11. NEXT_KILL_ZONE signals ---")

# Upcoming kill zone within 5 min -> trigger and witness line
nkz_signals = [
    make_signal("PD_ARRAY", {"zone_type": "DISCOUNT", "price_level": 19400.0, "active": True, "strength": 0.6}),
    make_signal("NEXT_KILL_ZONE", {"zone_type": "NY_OPEN", "time_remaining": 120, "active": False}),
    make_signal("KILL_ZONE", {"zone_type": "LONDON_OPEN", "active": True}),
]
report_nkz = head.refresh(make_oc(nkz_signals))
trigger_types = [t.get("trigger_type", "") for t in report_nkz.armed_triggers]
check("11.1 Upcoming KZ within 5min -> upcoming_kill_zone trigger",
      "upcoming_kill_zone" in trigger_types)
check("11.2 Witness summary mentions upcoming kill zone",
      "upcoming kill zone" in report_nkz.witness_summary.lower() or "imminent" in report_nkz.witness_summary.lower())
check("11.3 Has BULLISH bias from discount + active KZ + upcoming KZ",
      report_nkz.bias == BiasType.BULLISH)
check("11.4 context_quality_score includes upcoming KZ bonus",
      report_nkz.context_quality_score is not None and report_nkz.context_quality_score > 0)

# Upcoming kill zone far away -> no trigger (but still in witness)
nkz_distant = [
    make_signal("PD_ARRAY", {"zone_type": "PREMIUM", "price_level": 19700.0, "active": True, "strength": 0.6}),
    make_signal("NEXT_KILL_ZONE", {"zone_type": "NY_OPEN", "time_remaining": 900, "active": False}),  # 15 min away
]
report_distant = head.refresh(make_oc(nkz_distant))
trigger_types_distant = [t.get("trigger_type", "") for t in report_distant.armed_triggers]
check("11.5 Distant upcoming KZ (900s) -> no upcoming_kill_zone trigger",
      "upcoming_kill_zone" not in trigger_types_distant)

# Only NEXT_KILL_ZONE signals, no other ICT data
nkz_only = [
    make_signal("NEXT_KILL_ZONE", {"zone_type": "LONDON_OPEN", "time_remaining": 180, "active": False}),
]
report_nkz_only = head.refresh(make_oc(nkz_only))
check("11.6 Only upcoming KZ -> NEUTRAL bias",
      report_nkz_only.bias == BiasType.NEUTRAL)
check("11.7 Only upcoming KZ -> witness has imminent",
      "imminent" in report_nkz_only.witness_summary.lower())
check("11.8 Only upcoming KZ -> upcoming_kill_zone trigger",
      "upcoming_kill_zone" in [t.get("trigger_type", "") for t in report_nkz_only.armed_triggers])

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
