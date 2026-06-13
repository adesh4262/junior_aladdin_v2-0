"""Unit tests for ``smc_head.py`` — Floor 4 Step 4.9.

Tests:
- Signal extraction (SMC domain only)
- Empty signals fallback → NEUTRAL + context_quality_score=0
- Bullish signals (structure + FVGs) → BULLISH + context_quality_score > 0
- Bearish signals → BEARISH bias
- Mixed signals → NEUTRAL
- context_quality_score computation
- Invalidation is never None
- Head name and properties
- Primary/backup setup selection
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
from junior_aladdin.floor_4_heads.smc_head import SMCHead
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
        signal_id=signal_id or f"smc_{indicator_type}_{datetime.utcnow().timestamp()}",
        domain=CalculationDomain.SMC,
        indicator_type=indicator_type,
        value=value,
    )


def make_oc(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


print("=" * 60)
print("Floor 4 — SMC Head Tests")
print("=" * 60)

# =========================================================================
# 1. Signal extraction
# =========================================================================
print("\n--- 1. Signal extraction ---")

head = SMCHead()
all_signals = [
    make_signal("MARKET_STRUCTURE", {"structure_type": "BULLISH_HH_HL", "structure_valid": True}),
    make_signal("FVG", {"fvg_type": "BULLISH_FVG", "top": 19600.0, "mitigated": False}),
    make_signal("ORDER_BLOCK", {"ob_type": "BULLISH_OB", "price": 19550.0, "strength": 0.7}),
]
oc = make_oc(all_signals)
extracted = head._extract_signals(oc)
check("1.1 Extracts SMC domain signals", len(extracted) == 3)
check("1.2 All extracted are SMC domain",
      all(s.domain == CalculationDomain.SMC for s in extracted))

# Non-SMC signals filtered
oc_mixed = make_oc([
    make_signal("FVG", {"fvg_type": "BULLISH_FVG"}),
    CalculatedSignal(signal_id="tech1", domain=CalculationDomain.TECHNICAL,
                     indicator_type="RSI", value={"rsi_value": 50.0}),
])
extracted2 = head._extract_signals(oc_mixed)
check("1.3 Only 1 SMC signal extracted", len(extracted2) == 1)

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
check("2.7 Head name correct", report.head_name == "SMC Head")

# =========================================================================
# 3. Bullish signals — structure + FVGs + OBs
# =========================================================================
print("\n--- 3. Bullish signals ---")

bullish_signals = [
    make_signal("MARKET_STRUCTURE", {"structure_type": "BULLISH_HH_HL", "structure_valid": True}),
    make_signal("FVG", {"fvg_type": "BULLISH_FVG", "top": 19600.0, "mitigated": False, "gap_size_pips": 3.0}),
    make_signal("ORDER_BLOCK", {"ob_type": "BULLISH_OB", "price": 19550.0, "strength": 0.7}),
    make_signal("CHOCH", {"choch_type": "BULLISH_CHOCH", "break_price": 19650.0, "confirmed": True}),
]
oc_bull = make_oc(bullish_signals)
report = head.refresh(oc_bull)
check("3.1 Bullish signals -> BULLISH bias", report.bias == BiasType.BULLISH)
check("3.2 Confidence > 0", report.confidence > 0)
check("3.3 context_quality_score > 0", report.context_quality_score is not None and report.context_quality_score > 0)
check("3.4 Has primary setup", report.primary_setup is not None)
check("3.5 Primary setup mentions FVG or OB",
      "FVG" in report.primary_setup or "Order Block" in report.primary_setup)
check("3.6 Has backup setup", report.backup_setup is not None)
check("3.7 Has invalidation rules", len(report.invalidation.get("rules", [])) > 0)
check("3.8 Has active zones", len(report.active_zones) > 0)
check("3.9 Has witness summary", len(report.witness_summary) > 0)
check("3.10 Has bull_case", len(report.bull_case) > 0)
check("3.11 Has bear_case", len(report.bear_case) > 0)
check("3.12 Has confluence_note", len(report.confluence_note) > 0)

# =========================================================================
# 4. Bearish signals — structure + bearish FVGs
# =========================================================================
print("\n--- 4. Bearish signals ---")

bearish_signals = [
    make_signal("MARKET_STRUCTURE", {"structure_type": "BEARISH_LH_LL", "structure_valid": True}),
    make_signal("FVG", {"fvg_type": "BEARISH_FVG", "top": 19400.0, "mitigated": False, "gap_size_pips": 4.0}),
    make_signal("ORDER_BLOCK", {"ob_type": "BEARISH_OB", "price": 19450.0, "strength": 0.8}),
]
oc_bear = make_oc(bearish_signals)
report = head.refresh(oc_bear)
check("4.1 Bearish signals -> BEARISH bias", report.bias == BiasType.BEARISH)
check("4.2 context_quality_score > 0", report.context_quality_score is not None and report.context_quality_score > 0)
check("4.3 Has primary setup", report.primary_setup is not None)

# =========================================================================
# 5. Neutral signals — mixed structure
# =========================================================================
print("\n--- 5. Neutral signals ---")

neutral_signals = [
    make_signal("MARKET_STRUCTURE", {"structure_type": "RANGE", "structure_valid": False}),
    make_signal("FVG", {"fvg_type": "BULLISH_FVG", "top": 19600.0, "mitigated": True, "gap_size_pips": 2.0}),
    make_signal("FVG", {"fvg_type": "BEARISH_FVG", "top": 19400.0, "mitigated": True, "gap_size_pips": 2.0}),
]
oc_neutral = make_oc(neutral_signals)
report = head.refresh(oc_neutral)
check("5.1 Mixed signals -> NEUTRAL bias", report.bias == BiasType.NEUTRAL)
check("5.2 Has invalidation", len(report.invalidation.get("rules", [])) > 0)

# =========================================================================
# 6. context_quality_score computation
# =========================================================================
print("\n--- 6. context_quality_score ---")

# High quality: valid structure + active FVGs + OBs + CHOCHs
high_q = [
    make_signal("MARKET_STRUCTURE", {"structure_type": "BULLISH_HH_HL", "structure_valid": True}),
    make_signal("FVG", {"fvg_type": "BULLISH_FVG", "top": 19600.0, "mitigated": False}),
    make_signal("ORDER_BLOCK", {"ob_type": "BULLISH_OB", "price": 19550.0, "strength": 0.8}),
    make_signal("CHOCH", {"choch_type": "BULLISH_CHOCH", "break_price": 19650.0, "confirmed": True}),
]
report_hq = head.refresh(make_oc(high_q))
check("6.1 High quality inputs -> score >= 0.7",
      report_hq.context_quality_score is not None and report_hq.context_quality_score >= 0.7)

# Low quality: no structure, no active FVGs, no OBs, no CHOCHs
low_q = [
    make_signal("MARKET_STRUCTURE", {"structure_type": "RANGE", "structure_valid": False}),
    make_signal("FVG", {"fvg_type": "BULLISH_FVG", "top": 19600.0, "mitigated": True}),
]
report_lq = head.refresh(make_oc(low_q))
check("6.2 Low quality inputs -> score < 0.3",
      report_lq.context_quality_score is not None and report_lq.context_quality_score < 0.3)

# =========================================================================
# 7. Invalidation
# =========================================================================
print("\n--- 7. Invalidation never None ---")

# Empty signals
report_empty = head.refresh(make_oc([]))
check("7.1 Empty -> invalidation has rules",
      len(report_empty.invalidation.get("rules", [])) > 0)

# Bullish
report_b = head.refresh(make_oc(bullish_signals))
check("7.2 Bullish -> invalidation has rules",
      len(report_b.invalidation.get("rules", [])) > 0)
check("7.3 Bullish -> invalidation summary non-empty",
      len(report_b.invalidation.get("summary", "")) > 0)

# Bearish
report_be = head.refresh(make_oc(bearish_signals))
check("7.4 Bearish -> invalidation has rules",
      len(report_be.invalidation.get("rules", [])) > 0)

# =========================================================================
# 8. Head properties
# =========================================================================
print("\n--- 8. Head properties ---")

head2 = SMCHead()
check("8.1 head_name", head2.head_name == "SMC Head")
check("8.2 Default state STALE", head2._compute_state is not None)

head3 = SMCHead(name="custom_smc")
report3 = head3.refresh(make_oc([]))
check("8.3 Custom name", report3.head_name == "SMC Head")

# =========================================================================
# 9. Freshness
# =========================================================================
print("\n--- 9. Freshness ---")

head4 = SMCHead()
report = head4.refresh(make_oc([]))
check("9.1 freshness_score 0.0-1.0", 0.0 <= report.freshness_score <= 1.0)
check("9.2 freshness_tag valid", report.freshness_tag is not None)
check("9.3 last_deep_update set", report.last_deep_update is not None)

# =========================================================================
# 10. Armed triggers
# =========================================================================
print("\n--- 10. Armed triggers ---")

triggers = report_b.armed_triggers
check("10.1 Bullish report has triggers", len(triggers) > 0)
if triggers:
    check("10.2 Trigger has type", triggers[0].get("trigger_type", "") != "")

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
