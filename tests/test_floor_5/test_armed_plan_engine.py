"""Unit tests for ``armed_plan_engine.py`` — Floor 5 Step 5.13.

Tests:
- MarketDataSnapshot, TriggerCheckResult, WatchResult dataclasses
- create_plan() creates WATCHING plan with UUID
- get_plan(), get_active_plans(), get_all_plans(), get_plan_count()
- cancel_plan() transitions to CANCELLED
- watch_plans() with price trigger (above/below/between/touch/reclaim)
- watch_plans() with candle-based expiry
- watch_plans() with time-based expiry
- watch_plans() with invalidation check (BUY/SELL directions)
- watch_plans() with invalidation level 0 (no invalidation)
- watch_plans() with no active plans -> empty result
- clear_session() resets all plans
- has_active_plans()
- get_engine_summary() dict
- Trigger condition helpers (_check_price_trigger, _check_expiry_condition)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta

from junior_aladdin.floor_5_captain.armed_plan_engine import (
    ArmedPlanEngine,
    MarketDataSnapshot,
    TriggerCheckResult,
    WatchResult,
    _check_price_trigger,
    _check_expiry_condition,
)
from junior_aladdin.floor_5_captain.captain_types import ArmedPlanState
from junior_aladdin.floor_5_captain.setup_memory_store import SetupMemoryStore
from junior_aladdin.shared.types import ArmedPlan

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


def make_data(price: float = 19500.0) -> MarketDataSnapshot:
    return MarketDataSnapshot(price=price)


print("=" * 60)
print("Floor 5 -- Armed Plan Engine Tests")
print("=" * 60)

# =========================================================================
# 1. Dataclass instantiation
# =========================================================================
print("\n--- 1. Dataclass creation ---")

data = MarketDataSnapshot(price=19500.0, volume=1000)
check("1.1 MarketDataSnapshot has price", data.price == 19500.0)

result = TriggerCheckResult(plan_id="P1", triggered=True)
check("1.2 TriggerCheckResult has plan_id", result.plan_id == "P1")

watch = WatchResult()
check("1.3 WatchResult default has_trigger False", watch.has_trigger is False)
check("1.4 WatchResult default triggered empty", len(watch.triggered_plans) == 0)
check("1.5 WatchResult default active_plan_count 0", watch.active_plan_count == 0)

# =========================================================================
# 2. create_plan creates WATCHING plan
# =========================================================================
print("\n--- 2. create_plan ---")

engine = ArmedPlanEngine()

plan = engine.create_plan(
    direction="BUY",
    setup_class="CONTINUATION",
    trigger_condition={"type": "above", "level": 19500},
    expiry_condition={"type": "candles", "count": 4},
    invalidation_level=19300.0,
    originating_heads=["SMC Head", "ICT Head"],
    zone_label="OB_19450",
)

check("2.1 Plan has UUID", len(plan.plan_id) > 10)
check("2.2 Direction is BUY", plan.direction == "BUY")
check("2.3 Setup class set", plan.setup_class == "CONTINUATION")
check("2.4 Readiness is WATCHING",
      plan.readiness == ArmedPlanState.WATCHING.value)
check("2.5 Trigger condition stored", plan.trigger_condition.get("type") == "above")
check("2.6 Expiry condition stored", plan.expiry_condition.get("type") == "candles")
check("2.7 Invalidation level set", plan.invalidation_level == 19300.0)
check("2.8 Originating heads stored", "SMC Head" in plan.originating_heads)
check("2.9 created_at set", plan.created_at is not None)

# =========================================================================
# 3. get_plan and plan queries
# =========================================================================
print("\n--- 3. Plan queries ---")

p2 = engine.create_plan(direction="SELL", setup_class="SCALP")
p3 = engine.create_plan(direction="BUY", setup_class="REVERSAL")

check("3.1 get_plan returns existing", engine.get_plan(plan.plan_id) is not None)
check("3.2 get_plan unknown returns None", engine.get_plan("UNKNOWN") is None)

active = engine.get_active_plans()
check("3.3 Has 3 active plans", len(active) == 3)

all_plans = engine.get_all_plans()
check("3.4 Has 3 total plans", len(all_plans) == 3)

check("3.5 get_plan_count is 3", engine.get_plan_count() == 3)

# =========================================================================
# 4. cancel_plan
# =========================================================================
print("\n--- 4. cancel_plan ---")

cancelled = engine.cancel_plan(p3.plan_id)
check("4.1 Cancelled plan exists", cancelled is not None)
check("4.2 Status is CANCELLED",
      cancelled.readiness == ArmedPlanState.CANCELLED.value if cancelled else False)

check("4.3 Unknown plan returns None",
      engine.cancel_plan("UNKNOWN") is None)

# Only 2 active now (p3 was cancelled)
check("4.4 2 active after cancel", len(engine.get_active_plans()) == 2)

# =========================================================================
# 5. watch_plans - price trigger (above)
# =========================================================================
print("\n--- 5. Price trigger: above ---")

engine2 = ArmedPlanEngine()
p_above = engine2.create_plan(
    direction="BUY",
    setup_class="CONTINUATION",
    trigger_condition={"type": "above", "level": 19500},
)

# Price below trigger
result = engine2.watch_plans(make_data(price=19490))
check("5.1 No trigger below level",
      result.has_trigger is False and len(result.triggered_plans) == 0)
check("5.2 1 active still", result.active_plan_count == 1)

# Price at trigger
result = engine2.watch_plans(make_data(price=19510))
check("5.3 Triggered above level",
      result.has_trigger is True and len(result.triggered_plans) == 1)
check("5.4 Trigger reason includes 'above'",
      "above" in result.triggered_plans[0].reason.lower())
check("5.5 Plan readiness is TRIGGERED",
      engine2.get_plan(p_above.plan_id).readiness == ArmedPlanState.TRIGGERED.value)

# =========================================================================
# 6. Price trigger (below)
# =========================================================================
print("\n--- 6. Price trigger: below ---")

engine3 = ArmedPlanEngine()
p_below = engine3.create_plan(
    direction="SELL",
    setup_class="SCALP",
    trigger_condition={"type": "below", "level": 19400},
)

# Price above trigger
engine3.watch_plans(make_data(price=19450))
check("6.1 No trigger when price above", engine3.get_triggered_plan() is None)

# Price at trigger
engine3.watch_plans(make_data(price=19380))
check("6.2 Triggered below level", engine3.get_triggered_plan() is not None)

# =========================================================================
# 7. Price trigger (touch and between)
# =========================================================================
print("\n--- 7. Price trigger: touch and between ---")

# Touch
met, reason = _check_price_trigger({"type": "touch", "level": 19500}, 19501.0)
check("7.1 Touch within tolerance", met is True)

met, reason = _check_price_trigger({"type": "touch", "level": 19500}, 19600.0)
check("7.2 Touch outside tolerance", met is False)

# Between
met, reason = _check_price_trigger(
    {"type": "between", "low": 19400, "high": 19500}, 19450.0)
check("7.3 Price between range", met is True)

met, reason = _check_price_trigger(
    {"type": "between", "low": 19400, "high": 19500}, 19350.0)
check("7.4 Price outside range", met is False)

# Reclaim
met, reason = _check_price_trigger({"type": "reclaim", "level": 19450}, 19460.0)
check("7.5 Reclaim above level", met is True)

met, reason = _check_price_trigger({"type": "reclaim", "level": 19450}, 19440.0)
check("7.6 Reclaim below level", met is False)

# Unknown type
met, reason = _check_price_trigger({"type": "unknown"}, 19500)
check("7.7 Unknown type returns False", met is False)

# None condition
met, reason = _check_price_trigger(None, 19500)
check("7.8 None condition returns False", met is False)

# =========================================================================
# 8. watch_plans - candle-based expiry
# =========================================================================
print("\n--- 8. Candle-based expiry ---")

engine4 = ArmedPlanEngine()
p_expire = engine4.create_plan(
    direction="BUY",
    setup_class="SCALP",
    trigger_condition={"type": "above", "level": 20000},  # Won't trigger
    expiry_condition={"type": "candles", "count": 5, "elapsed": 3},  # Not yet
)

# Before expiry
result = engine4.watch_plans(make_data(price=19500), candle_index=1)
# manually update elapsed
engine4.get_plan(p_expire.plan_id).expiry_condition["elapsed"] = 6  # Past expiry
result = engine4.watch_plans(make_data(price=19500))
check("8.1 Plan expired after candle count",
      len(result.expired_plans) == 1)
check("8.2 Expired reason mentions expired",
      "expired" in result.expired_plans[0].reason.lower())

# =========================================================================
# 9. watch_plans with invalidation
# =========================================================================
print("\n--- 9. Invalidation ---")

engine5 = ArmedPlanEngine()

# BUY plan: invalidated if price < invalidation_level
p_buy = engine5.create_plan(
    direction="BUY",
    setup_class="CONTINUATION",
    trigger_condition={"type": "above", "level": 19500},
    invalidation_level=19300.0,
)

# Price below invalidation
result = engine5.watch_plans(make_data(price=19250))
check("9.1 BUY plan invalidated below level",
      len(result.invalidated_plans) == 1)
check("9.2 Plan readiness is INVALIDATED",
      engine5.get_plan(p_buy.plan_id).readiness == ArmedPlanState.INVALIDATED.value)

# SELL plan: invalidated if price > invalidation_level
p_sell = engine5.create_plan(
    direction="SELL",
    setup_class="SCALP",
    invalidation_level=19600.0,
)
result = engine5.watch_plans(make_data(price=19700))
check("9.3 SELL plan invalidated above level",
      len(result.invalidated_plans) >= 1)

# Zero invalidation level = no invalidation
p_zero = engine5.create_plan(
    direction="BUY", setup_class="SCALP",
    invalidation_level=0.0,
)
result = engine5.watch_plans(make_data(price=1.0))  # Very low price
# p_zero should not be invalidated because invalidation_level=0
check("9.4 Zero invalidation level prevents invalidation",
      engine5.get_plan(p_zero.plan_id).readiness == ArmedPlanState.WATCHING.value)

# =========================================================================
# 10. watch_plans with no active plans
# =========================================================================
print("\n--- 10. No active plans ---")

engine_empty = ArmedPlanEngine()
result = engine_empty.watch_plans(make_data(price=19500))
check("10.1 No trigger", result.has_trigger is False)
check("10.2 No triggered", len(result.triggered_plans) == 0)
check("10.3 No expired", len(result.expired_plans) == 0)
check("10.4 No invalidated", len(result.invalidated_plans) == 0)
check("10.5 active_plan_count 0", result.active_plan_count == 0)

# =========================================================================
# 11. clear_session
# =========================================================================
print("\n--- 11. clear_session ---")

engine6 = ArmedPlanEngine()
engine6.create_plan(direction="BUY", setup_class="SCALP")
engine6.create_plan(direction="SELL", setup_class="REVERSAL")
check("11.1 Has plans before clear", engine6.get_plan_count() == 2)
check("11.2 Has active before clear", engine6.has_active_plans() is True)

engine6.clear_session()
check("11.3 No plans after clear", engine6.get_plan_count() == 0)
check("11.4 No active after clear", engine6.has_active_plans() is False)

# =========================================================================
# 12. has_active_plans
# =========================================================================
print("\n--- 12. has_active_plans ---")

engine7 = ArmedPlanEngine()
check("12.1 No active initially", engine7.has_active_plans() is False)

p = engine7.create_plan(
    direction="BUY",
    setup_class="SCALP",
    trigger_condition={"type": "above", "level": 1},  # Very low trigger
)
check("12.2 Active after create", engine7.has_active_plans() is True)

engine7.watch_plans(make_data(price=999999))  # Trigger
check("12.3 No active after all triggered",
      engine7.has_active_plans() is False)

# =========================================================================
# 13. get_engine_summary
# =========================================================================
print("\n--- 13. get_engine_summary ---")

engine8 = ArmedPlanEngine()
engine8.create_plan(
    direction="BUY", setup_class="CONTINUATION", zone_label="Z1",
    trigger_condition={"type": "above", "level": 1},
)
engine8.create_plan(direction="SELL", setup_class="SCALP")

# Trigger the first plan
engine8.watch_plans(make_data(price=999999))

summary = engine8.get_engine_summary()
check("13.1 Summary has total_plans", summary.get("total_plans") == 2)
check("13.2 Summary has active_plans", summary.get("active_plans") >= 0)
check("13.3 Summary has triggered_plans", summary.get("triggered_plans") >= 1)
check("13.4 Summary has has_active", "has_active" in summary)
check("13.5 Summary has setup_store", "setup_store" in summary)
check("13.6 Setup store has total_setups",
      summary["setup_store"].get("total_setups") >= 1)

# =========================================================================
# 14. Expiry condition helpers
# =========================================================================
print("\n--- 14. Expiry condition helpers ---")

now = datetime.utcnow()

# Candle-based expiry
met, reason = _check_expiry_condition(
    {"type": "candles", "count": 5, "elapsed": 3},
    now, 19500,
)
check("14.1 3/5 candles not expired", met is False)

met, reason = _check_expiry_condition(
    {"type": "candles", "count": 5, "elapsed": 5},
    now, 19500,
)
check("14.2 5/5 candles expired", met is True)

# Time-based expiry (plan created 2 min ago, expiry is 1 min)
past = now - timedelta(minutes=2)
met, reason = _check_expiry_condition(
    {"type": "time", "minutes": 1},
    past, 19500,
)
check("14.3 Time-based expired (2 min elapsed, 1 min limit)", met is True)

# Not expired yet (plan created 30 sec ago, expiry is 5 min)
recent = now - timedelta(seconds=30)
met, reason = _check_expiry_condition(
    {"type": "time", "minutes": 5},
    recent, 19500,
)
check("14.4 Time-based not expired (30s elapsed, 5 min limit)", met is False)

# Price beyond expiry
met, reason = _check_expiry_condition(
    {"type": "price_beyond", "level": 19600, "direction": "above"},
    now, 19700,
)
check("14.5 Price beyond level (above)", met is True)

met, reason = _check_expiry_condition(
    {"type": "price_beyond", "level": 19600, "direction": "above"},
    now, 19500,
)
check("14.6 Price not beyond level", met is False)

# None condition
met, reason = _check_expiry_condition(None, now, 19500)
check("14.7 None expiry condition returns False", met is False)

# Unknown type
met, reason = _check_expiry_condition({"type": "unknown"}, now, 19500)
check("14.8 Unknown expiry type returns False", met is False)

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
