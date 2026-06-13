"""Unit tests for ``psychology_head.py`` — Floor 4 Step 4.13.

Tests:
- Signal extraction (PSYCHOLOGY domain only)
- Empty signals fallback (trade_allowed=True, no block)
- DISCIPLINE_REPORT — trade blocked with reason
- COOLDOWN_STATUS — cooldown active
- MISTAKE_REPORT — repeated mistakes detected
- TRAP_ALERT — trap pressure active
- LOSS_REPORT — loss sequence auto-blocks
- Combined state — multiple factors interact
- Invalidation is never None
- Head properties
- Freshness
- ReportValidator identifies Psychology as NO_SETUP head
- set_state helper for direct state access
- Cooldown decay over time
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta

from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
)
from junior_aladdin.floor_4_heads.psychology_head import PsychologyHead
from junior_aladdin.floor_4_heads.head_report_schema import (
    HEAD_PSYCHOLOGY,
    ReportValidator,
    _NO_SETUP_HEADS,
)
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
        signal_id=signal_id or f"psy_{indicator_type}_{datetime.utcnow().timestamp()}",
        domain=CalculationDomain.PSYCHOLOGY,
        indicator_type=indicator_type,
        value=value,
    )


def make_oc(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


SAMPLE_TIME = datetime(2026, 6, 8, 10, 30, 0)

print("=" * 60)
print("Floor 4 — Psychology Head Tests")
print("=" * 60)

# =========================================================================
# 1. Signal extraction
# =========================================================================
print("\n--- 1. Signal extraction ---")

head = PsychologyHead()
all_signals = [
    make_signal("DISCIPLINE_REPORT", {"trade_allowed": True}),
    make_signal("COOLDOWN_STATUS", {"cooldown_active": False}),
    make_signal("MISTAKE_REPORT", {"mistake_count": 0, "same_zone_failures": 0}),
]
oc = make_oc(all_signals)
extracted = head._extract_signals(oc)
check("1.1 Extracts PSYCHOLOGY domain signals", len(extracted) == 3)
check("1.2 All extracted are PSYCHOLOGY domain",
      all(s.domain == CalculationDomain.PSYCHOLOGY for s in extracted))

# Non-psychology signals filtered
oc_mixed = make_oc([
    make_signal("DISCIPLINE_REPORT", {"trade_allowed": True}),
    CalculatedSignal(signal_id="smc1", domain=CalculationDomain.SMC,
                     indicator_type="FVG", value={"fvg_type": "BULLISH_FVG"}),
])
extracted2 = head._extract_signals(oc_mixed)
check("1.3 Only 1 PSYCHOLOGY signal extracted", len(extracted2) == 1)

# =========================================================================
# 2. Empty signals
# =========================================================================
print("\n--- 2. Empty signals ---")

head2 = PsychologyHead()
oc_empty = make_oc([])
report = head2.refresh(oc_empty, SAMPLE_TIME)
check("2.1 Empty -> trade_allowed True", report.trade_allowed is True)
check("2.2 Empty -> cooldown_active False", report.cooldown_active is False)
check("2.3 Empty -> repeated_mistake_flag False", report.repeated_mistake_flag is False)
check("2.4 Empty -> trap_pressure False", report.trap_pressure is False)
check("2.5 Empty -> block_reason empty", report.block_reason == "")
check("2.6 Empty -> caution_level 0.0", report.caution_level == 0.0)
check("2.7 Empty -> NEUTRAL bias", report.bias == BiasType.NEUTRAL)
check("2.8 Empty -> has invalidation", len(report.invalidation.get("rules", [])) > 0)
check("2.9 Empty -> no primary setup", report.primary_setup is None)
check("2.10 Empty -> no backup setup", report.backup_setup is None)
check("2.11 Head name correct", report.head_name == "Psychology Head")

# =========================================================================
# 3. DISCIPLINE_REPORT — trade blocked
# =========================================================================
print("\n--- 3. DISCIPLINE_REPORT -> trade blocked ---")

head3 = PsychologyHead()
block_signals = [
    make_signal("DISCIPLINE_REPORT", {"trade_allowed": False, "block_reason": "Max daily loss hit"}),
]
report = head3.refresh(make_oc(block_signals), SAMPLE_TIME)
check("3.1 Blocked -> trade_allowed False", report.trade_allowed is False)
check("3.2 Blocked -> block_reason set", "max daily loss" in report.block_reason.lower())
check("3.3 Blocked -> BEARISH bias (restricted)", report.bias == BiasType.BEARISH)
check("3.4 Blocked -> has invalidation rules", len(report.invalidation.get("rules", [])) > 0)
check("3.5 Blocked -> witness mentions BLOCKED", "BLOCKED" in report.witness_summary)
check("3.6 Blocked -> primary_setup None", report.primary_setup is None)

# =========================================================================
# 4. COOLDOWN_STATUS — cooldown active
# =========================================================================
print("\n--- 4. COOLDOWN_STATUS -> cooldown active ---")

head4 = PsychologyHead()
cooldown_signals = [
    make_signal("COOLDOWN_STATUS", {"cooldown_active": True, "cooldown_remaining_s": 300}),
]
report = head4.refresh(make_oc(cooldown_signals), SAMPLE_TIME)
check("4.1 Cooldown -> trade_allowed False", report.trade_allowed is False)
check("4.2 Cooldown -> cooldown_active True", report.cooldown_active is True)
check("4.3 Cooldown -> caution_level > 0", report.caution_level > 0)
check("4.4 Cooldown -> witness mentions cooldown", "cooldown" in report.witness_summary.lower())
check("4.5 Cooldown -> BEARISH bias (restricted)", report.bias == BiasType.BEARISH)

# =========================================================================
# 5. MISTAKE_REPORT — repeated mistakes
# =========================================================================
print("\n--- 5. MISTAKE_REPORT -> repeated mistakes ---")

head5 = PsychologyHead()
mistake_signals = [
    make_signal("MISTAKE_REPORT", {"mistake_count": 5, "same_zone_failures": 3}),
]
report = head5.refresh(make_oc(mistake_signals), SAMPLE_TIME)
check("5.1 Mistakes -> trade_allowed True (no block)", report.trade_allowed is True)
check("5.2 Mistakes -> repeated_mistake_flag True", report.repeated_mistake_flag is True)
check("5.3 Mistakes -> caution_level > 0", report.caution_level > 0)
check("5.4 Mistakes -> witness mentions mistakes", "repeated" in report.witness_summary.lower())
check("5.5 Mistakes -> has invalidation rules", len(report.invalidation.get("rules", [])) > 0)

# =========================================================================
# 6. TRAP_ALERT — trap pressure active
# =========================================================================
print("\n--- 6. TRAP_ALERT -> trap pressure ---")

head6 = PsychologyHead()
trap_signals = [
    make_signal("TRAP_ALERT", {"trap_pressure": True, "trap_density": 0.8}),
]
report = head6.refresh(make_oc(trap_signals), SAMPLE_TIME)
check("6.1 Trap -> trap_pressure True", report.trap_pressure is True)
check("6.2 Trap -> caution_level > 0", report.caution_level > 0)
check("6.3 Trap -> witness mentions trap", "trap" in report.witness_summary.lower())
check("6.4 Trap -> trade_allowed False (high density)", report.trade_allowed is False)
check("6.5 Trap -> BEARISH bias", report.bias == BiasType.BEARISH)

# Low trap density should not block
head6b = PsychologyHead()
trap_low_signals = [
    make_signal("TRAP_ALERT", {"trap_pressure": True, "trap_density": 0.5}),
]
report = head6b.refresh(make_oc(trap_low_signals), SAMPLE_TIME)
check("6.6 Trap low density -> trade_allowed True", report.trade_allowed is True)

# =========================================================================
# 7. LOSS_REPORT — loss sequence
# =========================================================================
print("\n--- 7. LOSS_REPORT -> loss sequence detection ---")

head7 = PsychologyHead()
loss_signals = [
    make_signal("LOSS_REPORT", {"loss_count": 4, "sequence_length": 3}),
]
report = head7.refresh(make_oc(loss_signals), SAMPLE_TIME)
check("7.1 Loss seq 3 -> trade_allowed False", report.trade_allowed is False)
check("7.2 Loss seq 3 -> caution_level > 0", report.caution_level > 0)
check("7.3 Loss seq 3 -> BEARISH bias", report.bias == BiasType.BEARISH)
check("7.4 Loss seq 3 -> witness mentions loss", "loss" in report.witness_summary.lower())

# Short loss sequence should not block
head7b = PsychologyHead()
short_loss_signals = [
    make_signal("LOSS_REPORT", {"loss_count": 1, "sequence_length": 1}),
]
report = head7b.refresh(make_oc(short_loss_signals), SAMPLE_TIME)
check("7.5 Loss seq 1 -> trade_allowed True", report.trade_allowed is True)

# =========================================================================
# 8. Combined state — multiple factors
# =========================================================================
print("\n--- 8. Combined state ---")

head8 = PsychologyHead()
combined_signals = [
    make_signal("MISTAKE_REPORT", {"mistake_count": 3, "same_zone_failures": 2}),
    make_signal("TRAP_ALERT", {"trap_pressure": True, "trap_density": 0.6}),
]
report = head8.refresh(make_oc(combined_signals), SAMPLE_TIME)
check("8.1 Combined -> repeated_mistake_flag True", report.repeated_mistake_flag is True)
check("8.2 Combined -> trap_pressure True", report.trap_pressure is True)
check("8.3 Combined -> caution_level elevated", report.caution_level > 0.2)
check("8.4 Combined -> has invalidation", len(report.invalidation.get("rules", [])) > 0)

# =========================================================================
# 9. Invalidation never None
# =========================================================================
print("\n--- 9. Invalidation never None ---")

head9 = PsychologyHead()

# Empty
report_e = head9.refresh(make_oc([]), SAMPLE_TIME)
check("9.1 Empty -> invalidation has rules", len(report_e.invalidation.get("rules", [])) > 0)

# Blocked
report_b = head9.refresh(make_oc([
    make_signal("DISCIPLINE_REPORT", {"trade_allowed": False, "block_reason": "Test block"}),
]), SAMPLE_TIME)
check("9.2 Blocked -> invalidation has rules", len(report_b.invalidation.get("rules", [])) > 0)

# Cooldown
report_c = head9.refresh(make_oc([
    make_signal("COOLDOWN_STATUS", {"cooldown_active": True, "cooldown_remaining_s": 120}),
]), SAMPLE_TIME)
check("9.3 Cooldown -> invalidation has rules", len(report_c.invalidation.get("rules", [])) > 0)

# Mistakes
report_m = head9.refresh(make_oc([
    make_signal("MISTAKE_REPORT", {"mistake_count": 2, "same_zone_failures": 2}),
]), SAMPLE_TIME)
check("9.4 Mistakes -> invalidation has rules", len(report_m.invalidation.get("rules", [])) > 0)

# =========================================================================
# 10. Head properties
# =========================================================================
print("\n--- 10. Head properties ---")

head10 = PsychologyHead()
check("10.1 head_name", head10.head_name == "Psychology Head")

head10_named = PsychologyHead(name="discipline")
report = head10_named.refresh(make_oc([]), SAMPLE_TIME)
check("10.2 Custom name still produces Psychology Head", report.head_name == "Psychology Head")

# =========================================================================
# 11. Freshness
# =========================================================================
print("\n--- 11. Freshness ---")

head11 = PsychologyHead()
report = head11.refresh(make_oc([]), SAMPLE_TIME)
check("11.1 freshness_score 0.0-1.0", 0.0 <= report.freshness_score <= 1.0)
check("11.2 freshness_tag valid", report.freshness_tag is not None)
check("11.3 last_deep_update set", report.last_deep_update is not None)

# =========================================================================
# 12. ReportValidator — NO_SETUP enforcement
# =========================================================================
print("\n--- 12. ReportValidator NO_SETUP enforcement ---")

validator = ReportValidator()
check("12.1 HEAD_PSYCHOLOGY in _NO_SETUP_HEADS",
      HEAD_PSYCHOLOGY in _NO_SETUP_HEADS)

# Fresh head with empty signals should pass validation
head12 = PsychologyHead()
report = head12.refresh(make_oc([]), SAMPLE_TIME)
result = validator.validate(report)
check("12.2 Fresh empty report passes validation", result.valid is True)

# Blocked report should also pass (setups are still None)
report_b2 = head12.refresh(make_oc([
    make_signal("DISCIPLINE_REPORT", {"trade_allowed": False, "block_reason": "Risk limit"}),
]), SAMPLE_TIME)
result2 = validator.validate(report_b2)
check("12.3 Blocked report passes validation", result2.valid is True)

# =========================================================================
# 13. set_state helper
# =========================================================================
print("\n--- 13. set_state helper ---")

head13 = PsychologyHead()
head13.set_state(
    trade_allowed=False,
    block_reason="Test manual block",
    cooldown_active=True,
    repeated_mistake_flag=True,
    trap_pressure=True,
    caution_level=0.7,
)
report = head13.refresh(make_oc([]), SAMPLE_TIME)
check("13.1 set_state trade_allowed False", report.trade_allowed is False)
check("13.2 set_state block_reason set", "test manual block" in report.block_reason.lower())
check("13.3 set_state caution_level 0.7", report.caution_level > 0.4)
check("13.4 set_state cooldown_active True (blocks trade)", report.trade_allowed is False)

# =========================================================================
# 14. Cooldown decay over time
# =========================================================================
print("\n--- 14. Cooldown decay ---")

head14 = PsychologyHead()
t0 = SAMPLE_TIME

# Start cooldown
head14.refresh(make_oc([
    make_signal("COOLDOWN_STATUS", {"cooldown_active": True, "cooldown_remaining_s": 120}),
]), t0)

# After 60s — cooldown still active
t1 = t0 + timedelta(seconds=60)
report = head14.refresh(make_oc([]), t1)
check("14.1 After 60s -> cooldown still active", report.cooldown_active is True)
check("14.2 After 60s -> trade still blocked", report.trade_allowed is False)

# After 120s total — cooldown expired
t2 = t0 + timedelta(seconds=180)
report = head14.refresh(make_oc([]), t2)
check("14.3 After 180s -> cooldown expired", report.cooldown_active is False)
check("14.4 After 180s -> trade allowed again", report.trade_allowed is True)

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
