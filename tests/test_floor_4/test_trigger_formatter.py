"""Unit tests for ``trigger_formatter.py`` — Floor 4 Step 4.6.

Tests:
- ``create_trigger()`` — normal single-condition trigger
- ``create_premium_trigger()`` — multi-condition trigger
- ``check_trigger()`` — all condition types (zone_touch, reclaim, volume_spike,
  structure_support, trend_aligned, price_above, price_below, unknown)
- ``TriggerCheckResult`` dataclass
- Edge cases: empty zone, no direction, unknown condition type
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from junior_aladdin.floor_4_heads.trigger_formatter import (
    TriggerCheckResult,
    TriggerConditionStatus,
    check_trigger,
    create_premium_trigger,
    create_trigger,
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
print("Floor 4 — Trigger Formatter Tests")
print("=" * 60)

ZONE_BULLISH = {"price_level": 19600.0, "direction": "bullish", "zone_type": "FVG"}
ZONE_BEARISH = {"price_level": 19500.0, "direction": "bearish", "zone_type": "FVG"}
ZONE_NEUTRAL = {"price_level": 19550.0, "direction": "", "zone_type": "LEVEL"}

# =========================================================================
# 1. create_trigger — normal triggers
# =========================================================================
print("\n--- 1. create_trigger ---")

t1 = create_trigger("FVG Retest", ZONE_BULLISH)
check("1.1 Has trigger_id", "trigger_id" in t1)
check("1.2 trigger_type = zone_touch", t1["trigger_type"] == "zone_touch")
check("1.3 price_level matches zone", t1["price_level"] == 19600.0)
check("1.4 direction = bullish", t1["direction"] == "bullish")
check("1.5 zone_ref = FVG", t1["zone_ref"] == "FVG")
check("1.6 Not premium", not t1["premium"])
check("1.7 Status PENDING", t1["status"] == "PENDING")
check("1.8 Has 1 condition", len(t1["conditions"]) == 1)
check("1.9 Condition type = zone_touch", t1["conditions"][0]["type"] == "zone_touch")

# Custom trigger type + confirmation
t2 = create_trigger("Reclaim", ZONE_BULLISH, trigger_type="reclaim",
                     confirmation_needed="price holds above after reclaim")
check("1.10 Custom trigger type", t2["trigger_type"] == "reclaim")
check("1.11 Custom confirmation in description", "above after reclaim" in t2["conditions"][0]["description"])

# Explicit price level override
t3 = create_trigger("Manual Level", ZONE_BULLISH, price_level=19700.0)
check("1.12 Price level override", t3["price_level"] == 19700.0)

# =========================================================================
# 2. create_premium_trigger
# =========================================================================
print("\n--- 2. create_premium_trigger ---")

conds = [
    {"type": "zone_touch", "level": 19600.0},
    {"type": "volume_spike", "min_volume": 50000, "description": "volume > 50K"},
    {"type": "structure_support", "direction": "bullish", "description": "bullish structure"},
]
pt = create_premium_trigger("Premium FVG Reclaim", ZONE_BULLISH, conds)
check("2.1 Has trigger_id", "trigger_id" in pt)
check("2.2 trigger_type = premium", pt["trigger_type"] == "premium")
check("2.3 price_level from zone", pt["price_level"] == 19600.0)
check("2.4 direction = bullish", pt["direction"] == "bullish")
check("2.5 Is premium", pt["premium"])
check("2.6 Has 3 conditions", len(pt["conditions"]) == 3)
check("2.7 1st condition zone_touch", pt["conditions"][0]["type"] == "zone_touch")
check("2.8 2nd condition volume_spike", pt["conditions"][1]["type"] == "volume_spike")
check("2.9 3rd condition structure_support", pt["conditions"][2]["type"] == "structure_support")
check("2.10 All conditions PENDING initially",
      all(c["status"] == "PENDING" for c in pt["conditions"]))

# =========================================================================
# 3. check_trigger — zone_touch (bullish)
# =========================================================================
print("\n--- 3. check_trigger: zone_touch ---")

trigger_touch = create_trigger("Bullish FVG Touch", ZONE_BULLISH)

# 3.1 Price well below zone -> not touched
r = check_trigger(trigger_touch, {"price": 19500.0})
check("3.1 Price below bullish zone -> not triggered", not r.triggered)
check("3.2 Status FAILED", r.condition_statuses.get("zone_touch at 19600.0") == TriggerConditionStatus.FAILED)

# 3.2 Price at zone level
r = check_trigger(trigger_touch, {"price": 19600.0})
check("3.3 Price at zone level -> triggered", r.triggered)
check("3.4 Status MET", r.condition_statuses.get("zone_touch at 19600.0") == TriggerConditionStatus.MET)

# 3.3 Price above zone (bullish)
r = check_trigger(trigger_touch, {"price": 19700.0})
check("3.5 Price above bullish zone -> triggered", r.triggered)

# 3.4 Bearish zone touch
bear_trigger = create_trigger("Bearish Touch", ZONE_BEARISH)
r = check_trigger(bear_trigger, {"price": 19600.0})
check("3.6 Price above bearish zone -> not triggered", not r.triggered)
r = check_trigger(bear_trigger, {"price": 19400.0})
check("3.7 Price below bearish zone -> triggered", r.triggered)

# 3.5 Neutral zone (no direction)
neutral_trigger = create_trigger("Neutral Touch", ZONE_NEUTRAL)
r = check_trigger(neutral_trigger, {"price": 19550.0})
check("3.8 Neutral zone at price -> triggered", r.triggered)
r = check_trigger(neutral_trigger, {"price": 19200.0})
check("3.9 Neutral zone far away -> not triggered", not r.triggered)

# =========================================================================
# 4. check_trigger — reclaim
# =========================================================================
print("\n--- 4. check_trigger: reclaim ---")

reclaim_trigger = create_trigger("Bullish Reclaim", ZONE_BULLISH, trigger_type="reclaim")

# 4.1 Price below level -> not reclaimed
r = check_trigger(reclaim_trigger, {"price": 19500.0})
check("4.1 Price below -> not reclaimed", not r.triggered)

# 4.2 Price above level -> reclaimed
r = check_trigger(reclaim_trigger, {"price": 19650.0})
check("4.2 Price above -> reclaimed", r.triggered)

# =========================================================================
# 5. check_trigger — volume_spike
# =========================================================================
print("\n--- 5. check_trigger: volume_spike ---")

vol_conds = [{"type": "volume_spike", "min_volume": 50000}]
vol_trigger = create_premium_trigger("Volume Check", ZONE_BULLISH, vol_conds)

r = check_trigger(vol_trigger, {"price": 19600.0, "volume": 30000})
check("5.1 Low volume -> not triggered", not r.triggered)

r = check_trigger(vol_trigger, {"price": 19600.0, "volume": 50000})
check("5.2 Volume exactly at min -> triggered", r.triggered)

r = check_trigger(vol_trigger, {"price": 19600.0, "volume": 100000})
check("5.3 High volume -> triggered", r.triggered)

# =========================================================================
# 6. check_trigger — structure_support
# =========================================================================
print("\n--- 6. check_trigger: structure_support ---")

struct_conds = [{"type": "structure_support", "direction": "bullish"}]
struct_trigger = create_premium_trigger("Structure Check", ZONE_BULLISH, struct_conds)

r = check_trigger(struct_trigger, {"price": 19600.0, "structure_bias": "bullish"})
check("6.1 Structure bullish -> triggered", r.triggered)

r = check_trigger(struct_trigger, {"price": 19600.0, "structure_bias": "bearish"})
check("6.2 Structure bearish -> not triggered", not r.triggered)

r = check_trigger(struct_trigger, {"price": 19600.0})
check("6.3 No structure data -> not triggered", not r.triggered)

# =========================================================================
# 7. check_trigger — trend_aligned
# =========================================================================
print("\n--- 7. check_trigger: trend_aligned ---")

trend_conds = [{"type": "trend_aligned"}]
trend_trigger = create_premium_trigger("Trend Check", ZONE_BULLISH, trend_conds)

r = check_trigger(trend_trigger, {"price": 19600.0, "trend_aligned": True})
check("7.1 Trend aligned -> triggered", r.triggered)

r = check_trigger(trend_trigger, {"price": 19600.0, "trend_aligned": False})
check("7.2 Trend not aligned -> not triggered", not r.triggered)

# =========================================================================
# 8. check_trigger — price_above / price_below
# =========================================================================
print("\n--- 8. check_trigger: price_above / price_below ---")

above_conds = [{"type": "price_above", "level": 19600.0}]
above_trigger = create_premium_trigger("Above Check", ZONE_BULLISH, above_conds)

r = check_trigger(above_trigger, {"price": 19700.0})
check("8.1 Price above 19600 -> triggered", r.triggered)
r = check_trigger(above_trigger, {"price": 19500.0})
check("8.2 Price below 19600 -> not triggered", not r.triggered)

below_conds = [{"type": "price_below", "level": 19500.0}]
below_trigger = create_premium_trigger("Below Check", ZONE_BEARISH, below_conds)

r = check_trigger(below_trigger, {"price": 19400.0})
check("8.3 Price below 19500 -> triggered", r.triggered)
r = check_trigger(below_trigger, {"price": 19600.0})
check("8.4 Price above 19500 -> not triggered", not r.triggered)

# =========================================================================
# 9. Premium trigger — all conditions must be met
# =========================================================================
print("\n--- 9. Premium: all conditions must be met ---")

multi_conds = [
    {"type": "zone_touch", "level": 19600.0},
    {"type": "volume_spike", "min_volume": 50000},
    {"type": "structure_support", "direction": "bullish"},
]
multi_trigger = create_premium_trigger("Multi-Condition", ZONE_BULLISH, multi_conds)

# 9.1 Only zone touched, no volume
r = check_trigger(multi_trigger, {"price": 19600.0, "volume": 10000, "structure_bias": "bullish"})
check("9.1 Zone + structure met, volume not -> not triggered", not r.triggered)
check("9.2 2/3 conditions met", r.met_count == 2)

# 9.2 All conditions met
r = check_trigger(multi_trigger,
                  {"price": 19600.0, "volume": 60000, "structure_bias": "bullish"})
check("9.3 All conditions met -> triggered", r.triggered)
check("9.4 3/3 conditions met", r.met_count == 3 and r.total_conditions == 3)

# 9.3 None met
r = check_trigger(multi_trigger, {"price": 19400.0, "volume": 1000, "structure_bias": ""})
check("9.5 No conditions met -> not triggered", not r.triggered)
check("9.6 0/3 conditions met", r.met_count == 0)

# =========================================================================
# 10. Unknown condition type
# =========================================================================
print("\n--- 10. Unknown condition type ---")

unknown_conds = [{"type": "nonexistent_check"}]
unknown_trigger = create_premium_trigger("Unknown", ZONE_BULLISH, unknown_conds)
r = check_trigger(unknown_trigger, {"price": 19600.0})
check("10.1 Unknown condition -> not triggered", not r.triggered)
check("10.2 Unknown -> FAILED status",
      list(r.condition_statuses.values())[0] == TriggerConditionStatus.FAILED)

# =========================================================================
# 11. TriggerCheckResult helpers
# =========================================================================
print("\n--- 11. TriggerCheckResult ---")

result = TriggerCheckResult(triggered=True, met_count=3, total_conditions=3)
check("11.1 all_met when counts match", result.all_met)
check("11.2 triggered=True", result.triggered)

result2 = TriggerCheckResult(triggered=False, met_count=2, total_conditions=3)
check("11.3 all_met False when not all met", not result2.all_met)

result3 = TriggerCheckResult(triggered=False, met_count=0, total_conditions=0)
check("11.4 all_met False with 0 conditions", not result3.all_met)

result4 = check_trigger(create_trigger("Test", ZONE_BULLISH), {"price": 19000.0})
check("11.5 Details has PENDING when not triggered", "PENDING" in result4.details)

check("11.6 has checked_at timestamp", result.checked_at is not None)

# =========================================================================
# 12. Empty zone / edge cases
# =========================================================================
print("\n--- 12. Edge cases ---")

# 12.1 Empty zone
empty_zone = {}
t_empty = create_trigger("Empty Zone", empty_zone)
check("12.1 Empty zone still creates trigger", t_empty["price_level"] == 0.0)

# 12.2 Premium trigger with empty conditions list
t_empty_conds = create_premium_trigger("No Conditions", ZONE_BULLISH, [])
check("12.2 Empty conditions list", len(t_empty_conds["conditions"]) == 0)
r = check_trigger(t_empty_conds, {"price": 19600.0})
check("12.3 Empty conditions -> not triggered", not r.triggered)

# 12.4 create_premium_trigger with price_level override
pt_override = create_premium_trigger("Level Override", ZONE_BULLISH, [
    {"type": "zone_touch", "level": 19700.0},
], price_level=19800.0)
check("12.4 Premium with price_level override", pt_override["price_level"] == 19800.0)
check("12.5 Condition level still 19700", pt_override["conditions"][0]["level"] == 19700.0)


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
