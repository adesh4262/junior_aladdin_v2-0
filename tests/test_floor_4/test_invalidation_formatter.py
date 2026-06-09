"""Unit tests for ``invalidation_formatter.py`` — Floor 4 Step 4.7.

Tests:
- ``create_invalidation()`` — with/without rules, auto-summary
- ``check_invalidation()`` — price break, structure break, zone mitigation
- ``merge_invalidations()`` — dedup, combine triggered state
- ``InvalidationManager`` — lifecycle, check, reset, add_rule, mark_triggered
- ``InvalidationCheckResult`` dataclass
- Edge cases: empty rules, no price level, severity levels
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from junior_aladdin.floor_4_heads.invalidation_formatter import (
    InvalidationCheckResult,
    InvalidationManager,
    InvalidationSeverity,
    check_invalidation,
    create_invalidation,
    merge_invalidations,
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


print("=" * 60)
print("Floor 4 — Invalidation Formatter Tests")
print("=" * 60)

# Sample rules
RULE_BREAK_BELOW = {
    "condition": "Structure breaks below 19500",
    "price_level": 19500.0,
    "reason": "Bullish structure invalidated",
}
RULE_BREAK_ABOVE = {
    "condition": "Price breaks above 19700 resistance",
    "price_level": 19700.0,
    "reason": "Bearish structure invalidated",
}
RULE_FVG_MITIGATED = {
    "condition": "FVG at 19600 fully mitigated",
    "price_level": 19600.0,
    "reason": "Setup gap closed",
}
RULE_STRUCTURE_FLIP = {
    "condition": "Market structure flips against current bias",
    "price_level": 0.0,
    "reason": "General structural invalidation",
}

# =========================================================================
# 1. create_invalidation
# =========================================================================
print("\n--- 1. create_invalidation ---")

# 1.1 With rules
inv = create_invalidation(rules=[RULE_BREAK_BELOW, RULE_FVG_MITIGATED])
check("1.1 Has 'rules' key", "rules" in inv)
check("1.2 Has 2 rules", len(inv["rules"]) == 2)
check("1.3 Has 'summary' key", "summary" in inv)
check("1.4 Summary contains reasons", "Bullish" in inv["summary"] or "gap" in inv["summary"])
check("1.5 Has 'severity' key", "severity" in inv)
check("1.6 Default severity HARD", inv["severity"] == "HARD")
check("1.7 Has 'created_at'", "created_at" in inv)
check("1.8 triggered=False initially", not inv["triggered"])
check("1.9 First rule condition preserved", inv["rules"][0]["condition"] == RULE_BREAK_BELOW["condition"])
check("1.10 First rule price_level preserved", inv["rules"][0]["price_level"] == 19500.0)

# 1.2 Empty rules
inv_empty = create_invalidation()
check("1.11 Empty rules list", len(inv_empty["rules"]) == 0)
check("1.12 Empty rules has default summary", inv_empty["summary"] == "No invalidation rules defined")

# 1.3 Custom summary and severity
inv_custom = create_invalidation(rules=[RULE_BREAK_BELOW], summary="Custom summary", severity="SOFT")
check("1.13 Custom summary", inv_custom["summary"] == "Custom summary")
check("1.14 Custom severity", inv_custom["severity"] == "SOFT")

# 1.5 Rule with missing fields
inv_partial = create_invalidation(rules=[{"condition": "Test"}])
check("1.15 Partially specified rule gets defaults",
      inv_partial["rules"][0]["reason"] == "No reason specified")
check("1.16 Missing price_level defaults to 0",
      inv_partial["rules"][0]["price_level"] == 0.0)

# =========================================================================
# 2. check_invalidation — price break below
# =========================================================================
print("\n--- 2. check_invalidation: price break below ---")

inv = create_invalidation(rules=[RULE_BREAK_BELOW])

# 2.1 Price above level -> not triggered
r = check_invalidation(inv, {"price": 19600.0})
check("2.1 Price above level -> not triggered", not r.triggered)
check("2.2 0 rules triggered", len(r.triggered_rules) == 0)
check("2.3 1 rule pending", len(r.pending_rules) == 1)

# 2.2 Price at level -> triggered
r = check_invalidation(inv, {"price": 19500.0})
check("2.4 Price at level -> triggered", r.triggered)
check("2.5 1 rule triggered", len(r.triggered_rules) == 1)

# 2.3 Price below level -> triggered
r = check_invalidation(inv, {"price": 19400.0})
check("2.6 Price below level -> triggered", r.triggered)
check("2.7 Trigger reason contains reason", any("Bullish" in reason for reason in r.trigger_reasons))

# 2.4 Low price crossed level even if current price is above
r = check_invalidation(inv, {"price": 19600.0, "low": 19400.0})
check("2.8 Low crossed level -> triggered", r.triggered)

# =========================================================================
# 3. check_invalidation — price break above
# =========================================================================
print("\n--- 3. check_invalidation: price break above ---")

inv = create_invalidation(rules=[RULE_BREAK_ABOVE])

r = check_invalidation(inv, {"price": 19600.0})
check("3.1 Price below level -> not triggered", not r.triggered)

r = check_invalidation(inv, {"price": 19700.0})
check("3.2 Price at level -> triggered", r.triggered)

r = check_invalidation(inv, {"price": 19800.0})
check("3.3 Price above level -> triggered", r.triggered)

r = check_invalidation(inv, {"price": 19600.0, "high": 19750.0})
check("3.4 High crossed level -> triggered", r.triggered)

# =========================================================================
# 4. check_invalidation — structure break
# =========================================================================
print("\n--- 4. check_invalidation: structure break ---")

inv = create_invalidation(rules=[RULE_STRUCTURE_FLIP])

r = check_invalidation(inv, {"price": 19400.0, "structure_broken": False})
check("4.1 Structure not broken -> not triggered", not r.triggered)

r = check_invalidation(inv, {"price": 19400.0, "structure_broken": True})
check("4.2 Structure broken -> triggered", r.triggered)

# =========================================================================
# 5. check_invalidation — zone mitigated
# =========================================================================
print("\n--- 5. check_invalidation: zone mitigated ---")

inv = create_invalidation(rules=[RULE_FVG_MITIGATED])

r = check_invalidation(inv, {"price": 19500.0})
check("5.1 Price below FVG -> not triggered", not r.triggered)

r = check_invalidation(inv, {"price": 19600.0})
check("5.2 Price at FVG level -> triggered", r.triggered)

r = check_invalidation(inv, {"price": 19700.0})
check("5.3 Price above FVG -> triggered (mitigated)", r.triggered)

# =========================================================================
# 6. check_invalidation — multiple rules, partial trigger
# =========================================================================
print("\n--- 6. Multiple rules ---")

inv = create_invalidation(rules=[RULE_BREAK_BELOW, RULE_BREAK_ABOVE])

# Only first triggered
r = check_invalidation(inv, {"price": 19400.0})
check("6.1 Below both levels -> triggered (break_below triggered)", r.triggered)
check("6.2 1 rule triggered (break_below, NOT break_above)",
      len(r.triggered_rules) == 1)

r = check_invalidation(inv, {"price": 19600.0})
check("6.3 Neither triggered", not r.triggered)
check("6.4 0 triggered, 2 pending",
      len(r.triggered_rules) == 0 and len(r.pending_rules) == 2)

# =========================================================================
# 7. Empty rules check
# =========================================================================
print("\n--- 7. Empty rules check ---")

inv_empty = create_invalidation()
r = check_invalidation(inv_empty, {"price": 19400.0})
check("7.1 Empty rules -> not triggered", not r.triggered)
check("7.2 total_rules=0", r.total_rules == 0)

# =========================================================================
# 8. merge_invalidations
# =========================================================================
print("\n--- 8. merge_invalidations ---")

inv1 = create_invalidation(rules=[RULE_BREAK_BELOW], summary="Inv1")
inv2 = create_invalidation(rules=[RULE_FVG_MITIGATED], summary="Inv2")

merged = merge_invalidations([inv1, inv2])
check("8.1 Merged has 2 unique rules", len(merged["rules"]) == 2)
check("8.2 Merged has 'summary'", "summary" in merged)
check("8.3 Merged has 'merged_from'", merged["merged_from"] == 2)
check("8.4 Merged not triggered (neither was)", not merged["triggered"])

# Merge with triggered
inv2["triggered"] = True
merged2 = merge_invalidations([inv1, inv2])
check("8.5 Merged triggered if any source triggered", merged2["triggered"])

# Merge with duplicate rules
merged3 = merge_invalidations([inv1, inv1])
check("8.6 Duplicate rules deduplicated", len(merged3["rules"]) == 1)

# Merge empty list
merged_empty = merge_invalidations([])
check("8.7 Empty merge has fallback rule", len(merged_empty["rules"]) == 1)
check("8.8 Empty merge summary", "No invalidation" in merged_empty["summary"])

# =========================================================================
# 9. InvalidationCheckResult
# =========================================================================
print("\n--- 9. InvalidationCheckResult ---")

r = InvalidationCheckResult(triggered=True, trigger_reasons=["Test"],
                             triggered_rules=[RULE_BREAK_BELOW])
check("9.1 CheckResult stores triggered", r.triggered)
check("9.2 CheckResult stores reasons", "Test" in r.trigger_reasons)
check("9.3 CheckResult has triggered_at", r.triggered_at is not None)

r2 = InvalidationCheckResult()
check("9.4 Default not triggered", not r2.triggered)
check("9.5 Default empty reasons", len(r2.trigger_reasons) == 0)

# =========================================================================
# 10. InvalidationManager
# =========================================================================
print("\n--- 10. InvalidationManager ---")

manager = InvalidationManager(
    head_name="smc",
    rules=[RULE_BREAK_BELOW, RULE_FVG_MITIGATED],
)

check("10.1 Initially not triggered", not manager.triggered)
check("10.2 triggered_at None initially", manager.triggered_at is None)
check("10.3 Empty trigger_reasons", len(manager.trigger_reasons) == 0)

# Get invalidation dict
inv_from_mgr = manager.get_invalidation()
check("10.4 get_invalidation returns dict", "rules" in inv_from_mgr)
check("10.5 Has 2 rules", len(inv_from_mgr["rules"]) == 2)
check("10.6 Not triggered in dict", not inv_from_mgr["triggered"])

# Check against market data — not triggered (price between break_below=19500
# and fvg_mitigated=19600, so neither rule fires)
r = manager.check({"price": 19550.0})
check("10.7 Check with mid-range price -> not triggered", not r.triggered)
check("10.8 Manager still not triggered", not manager.triggered)

# Check — triggered
r = manager.check({"price": 19400.0})
check("10.9 Check with low price -> triggered", r.triggered)
check("10.10 Manager now triggered", manager.triggered)
check("10.11 triggered_at is set", manager.triggered_at is not None)
check("10.12 trigger_reasons populated", len(manager.trigger_reasons) > 0)

# =========================================================================
# 11. InvalidationManager — reset
# =========================================================================
print("\n--- 11. InvalidationManager: reset ---")

manager.reset()
check("11.1 After reset: not triggered", not manager.triggered)
check("11.2 After reset: triggered_at None", manager.triggered_at is None)
check("11.3 After reset: empty reasons", len(manager.trigger_reasons) == 0)

r = manager.check({"price": 19400.0})
check("11.4 Can be re-triggered after reset", manager.triggered)

# =========================================================================
# 12. InvalidationManager — mark_triggered
# =========================================================================
print("\n--- 12. InvalidationManager: mark_triggered ---")

manager2 = InvalidationManager(head_name="test", rules=[RULE_BREAK_BELOW])
manager2.mark_triggered(reasons=["Manually triggered"])
check("12.1 mark_triggered sets triggered", manager2.triggered)
check("12.2 mark_triggered stores reasons", any("Manually" in r for r in manager2.trigger_reasons))
check("12.3 triggered_at set", manager2.triggered_at is not None)

# mark_triggered without reasons
manager3 = InvalidationManager(head_name="test", rules=[RULE_BREAK_BELOW])
manager3.mark_triggered()
check("12.4 mark_triggered works without reasons", manager3.triggered)

# =========================================================================
# 13. InvalidationManager — add_rule
# =========================================================================
print("\n--- 13. InvalidationManager: add_rule ---")

manager4 = InvalidationManager(head_name="test", rules=[RULE_BREAK_BELOW])
check("13.1 Initially 1 rule", len(manager4.get_invalidation()["rules"]) == 1)

manager4.add_rule(RULE_BREAK_ABOVE)
check("13.2 After add_rule: 2 rules", len(manager4.get_invalidation()["rules"]) == 2)
check("13.3 New rule appears", manager4.get_invalidation()["rules"][1]["condition"] == "Price breaks above 19700 resistance")

# =========================================================================
# 14. InvalidationManager — to_dict
# =========================================================================
print("\n--- 14. InvalidationManager: to_dict ---")

manager5 = InvalidationManager(head_name="smc", rules=[RULE_BREAK_BELOW])
d = manager5.to_dict()
check("14.1 to_dict has head_name", d["head_name"] == "smc")
check("14.2 to_dict has triggered", "triggered" in d)
check("14.3 to_dict has invalidation", "invalidation" in d)
check("14.4 to_dict has trigger_reasons", "trigger_reasons" in d)

# After trigger
manager5.check({"price": 19400.0})
d2 = manager5.to_dict()
check("14.5 After trigger: triggered=True", d2["triggered"])
check("14.6 After trigger: triggered_at set", d2["triggered_at"] is not None)

# =========================================================================
# 15. Severity levels
# =========================================================================
print("\n--- 15. Severity levels ---")

check("15.1 HARD severity constant", InvalidationSeverity.HARD == "HARD")
check("15.2 SOFT severity constant", InvalidationSeverity.SOFT == "SOFT")
check("15.3 WARNING severity constant", InvalidationSeverity.WARNING == "WARNING")

# Soft severity rule
inv_soft = create_invalidation(rules=[RULE_BREAK_BELOW], severity="SOFT")
check("15.4 Soft severity preserved", inv_soft["severity"] == "SOFT")
check("15.5 Rule inherits severity", inv_soft["rules"][0]["severity"] == "SOFT")

# Per-rule severity override
inv_mixed = create_invalidation(rules=[
    {"condition": "Hard break", "price_level": 19500.0, "reason": "Hard", "severity": "HARD"},
    {"condition": "Soft warning", "price_level": 19600.0, "reason": "Soft", "severity": "SOFT"},
])
check("15.6 Per-rule HARD severity", inv_mixed["rules"][0]["severity"] == "HARD")
check("15.7 Per-rule SOFT severity", inv_mixed["rules"][1]["severity"] == "SOFT")


# =========================================================================
# Summary
# =========================================================================
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if failed > 0:
    sys.exit(1)
else:
    sys.exit(0)
