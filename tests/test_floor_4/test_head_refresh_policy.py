"""Unit tests for ``head_refresh_policy.py`` — Floor 4 Step 4.4.

Tests the three-tier refresh model:
- DEEP refresh (structural, 5m/15m intervals)
- BASE refresh (tactical, 1m interval)
- TICK_WATCH (light trigger observation, throttled)

Also tests:
- is_stale() detection
- get_refresh_tier() priority ordering
- get_policy() lookup
- All 6 pre-built per-head policies
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta

from junior_aladdin.floor_4_heads.head_refresh_policy import (
    REFRESH_POLICY_SMC,
    REFRESH_POLICY_ICT,
    REFRESH_POLICY_TECHNICAL,
    REFRESH_POLICY_OPTIONS,
    REFRESH_POLICY_MACRO,
    REFRESH_POLICY_PSYCHOLOGY,
    RefreshPolicy,
    RefreshTier,
    get_policy,
    get_refresh_tier,
    is_stale,
    should_base_refresh,
    should_deep_refresh,
    should_tick_watch,
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
print("Floor 4 — Head Refresh Policy Tests")
print("=" * 60)

# Common test time
NOW = datetime.utcnow()
ONE_MIN_AGO = NOW - timedelta(seconds=60)
THREE_MIN_AGO = NOW - timedelta(seconds=180)
SIX_MIN_AGO = NOW - timedelta(seconds=360)
TEN_MIN_AGO = NOW - timedelta(seconds=600)
TWENTY_MIN_AGO = NOW - timedelta(seconds=1200)

# For deep=300s/base=60s tests: deep_not_due = < 300s ago
_FOUR_MIN_AGO = NOW - timedelta(seconds=240)   # deep NOT due (4m < 5m)
_THREE_HALF_AGO = NOW - timedelta(seconds=210)  # deep NOT due
_90S_AGO = NOW - timedelta(seconds=90)           # base due (90s >= 60s)
_30S_AGO = NOW - timedelta(seconds=30)           # base NOT due
_15S_AGO = NOW - timedelta(seconds=15)           # very recent

# =========================================================================
# 1. RefreshPolicy dataclass
# =========================================================================
print("\n--- 1. RefreshPolicy dataclass ---")

policy = RefreshPolicy(head_name="test", base_refresh_interval_seconds=60,
                       deep_refresh_interval_seconds=300, stale_after_seconds=600)
check("1.1 head_name stored", policy.head_name == "test")
check("1.2 base interval 60s", policy.base_refresh_interval_seconds == 60)
check("1.3 deep interval 300s", policy.deep_refresh_interval_seconds == 300)
check("1.4 stale after 600s", policy.stale_after_seconds == 600)
check("1.5 tick_watch default True", policy.tick_watch_enabled)
check("1.6 min_ticks default 5", policy.min_ticks_between_refresh == 5)

# =========================================================================
# 2. should_deep_refresh
# =========================================================================
print("\n--- 2. should_deep_refresh ---")

pol = RefreshPolicy(deep_refresh_interval_seconds=300)

check("2.1 Never refreshed -> deep due",
      should_deep_refresh(pol, None, NOW))
check("2.2 Last deep 1m ago -> not due",
      not should_deep_refresh(pol, ONE_MIN_AGO, NOW))
check("2.3 Last deep 3m ago -> not due (< 5m)",
      not should_deep_refresh(pol, THREE_MIN_AGO, NOW))
check("2.4 Last deep 6m ago -> due (>= 5m)",
      should_deep_refresh(pol, SIX_MIN_AGO, NOW))
check("2.5 Last deep exactly at interval -> due",
      should_deep_refresh(pol, NOW - timedelta(seconds=300), NOW))

# =========================================================================
# 3. should_base_refresh
# =========================================================================
print("\n--- 3. should_base_refresh ---")

pol_b = RefreshPolicy(base_refresh_interval_seconds=60)

check("3.1 Never refreshed -> base due",
      should_base_refresh(pol_b, None, NOW))
check("3.2 Last update 30s ago -> not due",
      not should_base_refresh(pol_b, NOW - timedelta(seconds=30), NOW))
check("3.3 Last update 60s ago -> due",
      should_base_refresh(pol_b, NOW - timedelta(seconds=60), NOW))
check("3.4 Last update 90s ago -> due",
      should_base_refresh(pol_b, NOW - timedelta(seconds=90), NOW))

# =========================================================================
# 4. should_tick_watch
# =========================================================================
print("\n--- 4. should_tick_watch ---")

pol_t = RefreshPolicy(
    base_refresh_interval_seconds=60,
    tick_watch_enabled=True,
    min_ticks_between_refresh=5,
)

# 4.1 Tick watch disabled
pol_no_tick = RefreshPolicy(tick_watch_enabled=False)
check("4.1 Tick watch disabled -> False",
      not should_tick_watch(pol_no_tick, ONE_MIN_AGO, 10, NOW))

# 4.2 Not enough ticks
check("4.2 Not enough ticks (3 < 5) -> False",
      not should_tick_watch(pol_t, ONE_MIN_AGO, 3, NOW))

# 4.3 Enough ticks (10 >= 5), last tick 30s ago (within 60s base window) -> True
check("4.3 Enough ticks, within base window -> True",
      should_tick_watch(pol_t, _30S_AGO, 10, NOW))

# 4.4 Tick watch but base refresh due (90s >= 60s) -> False (full refresh preferred)
check("4.4 Base also due -> False",
      not should_tick_watch(pol_t, _90S_AGO, 10, NOW))

# 4.5 Never ticked before -> base refresh is due (never refreshed) -> False
check("4.5 Never ticked -> base due first -> False",
      not should_tick_watch(pol_t, None, 10, NOW))
check("4.6 Never ticked, not enough ticks -> False",
      not should_tick_watch(pol_t, None, 2, NOW))

# =========================================================================
# 5. get_refresh_tier
# =========================================================================
print("\n--- 5. get_refresh_tier ---")

pol_g = RefreshPolicy(
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=300,
    tick_watch_enabled=True,
    min_ticks_between_refresh=5,
)

# 5.1 Never refreshed -> DEEP
check("5.1 Never refreshed -> DEEP",
      get_refresh_tier(pol_g, None, None, None, 0, NOW) == RefreshTier.DEEP)

# 5.2 Deep due (6m since deep) -> DEEP
check("5.2 Deep due (6m) -> DEEP",
      get_refresh_tier(pol_g, SIX_MIN_AGO, ONE_MIN_AGO, ONE_MIN_AGO, 10, NOW) == RefreshTier.DEEP)

# 5.3 Base due (90s >= 60s), deep not due (240s < 300s) -> BASE
check("5.3 Base due, deep not due -> BASE",
      get_refresh_tier(pol_g, _FOUR_MIN_AGO, _90S_AGO, _90S_AGO, 10, NOW) == RefreshTier.BASE)

# 5.4 Neither due (deep=240s<300, last=30s<60), tick ready -> TICK_WATCH
check("5.4 Neither due, tick watch ready -> TICK_WATCH",
      get_refresh_tier(pol_g, _FOUR_MIN_AGO, _30S_AGO, _30S_AGO, 10, NOW) == RefreshTier.TICK_WATCH)

# 5.5 Not enough ticks (2 < 5) -> SKIP
check("5.5 Not enough ticks -> SKIP",
      get_refresh_tier(pol_g, _FOUR_MIN_AGO, _30S_AGO, _30S_AGO, 2, NOW) == RefreshTier.SKIP)

# 5.6 Very recent (deep=240s<300, last=15s<60, ticks=1<5) -> SKIP
check("5.6 Very recent -> SKIP",
      get_refresh_tier(pol_g, _FOUR_MIN_AGO, _15S_AGO, _15S_AGO, 1, NOW) == RefreshTier.SKIP)

# =========================================================================
# 6. is_stale
# =========================================================================
print("\n--- 6. is_stale ---")

pol_s = RefreshPolicy(stale_after_seconds=600)

check("6.1 Never updated -> stale", is_stale(pol_s, None, NOW))
check("6.2 Updated 1m ago -> not stale",
      not is_stale(pol_s, ONE_MIN_AGO, NOW))
check("6.3 Updated 5m ago -> not stale (< 10m)",
      not is_stale(pol_s, NOW - timedelta(seconds=300), NOW))
check("6.4 Updated 10m ago -> stale (>= 600s)",
      is_stale(pol_s, NOW - timedelta(seconds=600), NOW))
check("6.5 Updated 15m ago -> stale",
      is_stale(pol_s, NOW - timedelta(seconds=900), NOW))

# =========================================================================
# 7. get_policy lookup
# =========================================================================
print("\n--- 7. get_policy lookup ---")

check("7.1 get_policy('smc') returns SMC policy",
      get_policy("smc").head_name == "smc")
check("7.2 get_policy('ict') returns ICT policy",
      get_policy("ict").head_name == "ict")
check("7.3 get_policy('technical') returns Technical",
      get_policy("technical").head_name == "technical")
check("7.4 get_policy('macro') returns Macro",
      get_policy("macro").head_name == "macro")
check("7.5 get_policy('options') returns Options",
      get_policy("options").head_name == "options")
check("7.6 get_policy('psychology') returns Psychology",
      get_policy("psychology").head_name == "psychology")
check("7.7 get_policy('unknown') returns None",
      get_policy("unknown") is None)
check("7.8 get_policy('SMC') is case-insensitive",
      get_policy("SMC").head_name == "smc")

# =========================================================================
# 8. Pre-built policies — intervals
# =========================================================================
print("\n--- 8. Pre-built policy intervals ---")

check("8.1 SMC base=60, deep=300, stale=600",
      REFRESH_POLICY_SMC.base_refresh_interval_seconds == 60 and
      REFRESH_POLICY_SMC.deep_refresh_interval_seconds == 300 and
      REFRESH_POLICY_SMC.stale_after_seconds == 600)
check("8.2 ICT base=60, deep=300, stale=600",
      REFRESH_POLICY_ICT.base_refresh_interval_seconds == 60 and
      REFRESH_POLICY_ICT.deep_refresh_interval_seconds == 300 and
      REFRESH_POLICY_ICT.stale_after_seconds == 600)
check("8.3 Technical base=60, deep=300, stale=300",
      REFRESH_POLICY_TECHNICAL.base_refresh_interval_seconds == 60 and
      REFRESH_POLICY_TECHNICAL.deep_refresh_interval_seconds == 300 and
      REFRESH_POLICY_TECHNICAL.stale_after_seconds == 300)
check("8.4 Options base=60, deep=900, stale=900",
      REFRESH_POLICY_OPTIONS.base_refresh_interval_seconds == 60 and
      REFRESH_POLICY_OPTIONS.deep_refresh_interval_seconds == 900 and
      REFRESH_POLICY_OPTIONS.stale_after_seconds == 900)
check("8.5 Macro base=60, deep=900, stale=1800",
      REFRESH_POLICY_MACRO.base_refresh_interval_seconds == 60 and
      REFRESH_POLICY_MACRO.deep_refresh_interval_seconds == 900 and
      REFRESH_POLICY_MACRO.stale_after_seconds == 1800)
check("8.6 Psychology base=60, deep=300, stale=600",
      REFRESH_POLICY_PSYCHOLOGY.base_refresh_interval_seconds == 60 and
      REFRESH_POLICY_PSYCHOLOGY.deep_refresh_interval_seconds == 300 and
      REFRESH_POLICY_PSYCHOLOGY.stale_after_seconds == 600)

# =========================================================================
# 9. Pre-built policies — tick watch
# =========================================================================
print("\n--- 9. Pre-built tick watch settings ---")

check("9.1 All heads have tick_watch_enabled=True",
      all([
          REFRESH_POLICY_SMC.tick_watch_enabled,
          REFRESH_POLICY_ICT.tick_watch_enabled,
          REFRESH_POLICY_TECHNICAL.tick_watch_enabled,
          REFRESH_POLICY_OPTIONS.tick_watch_enabled,
          REFRESH_POLICY_MACRO.tick_watch_enabled,
          REFRESH_POLICY_PSYCHOLOGY.tick_watch_enabled,
      ]))
check("9.2 Options min_ticks=10 (slower data)",
      REFRESH_POLICY_OPTIONS.min_ticks_between_refresh == 10)
check("9.3 Macro min_ticks=20 (slowest)",
      REFRESH_POLICY_MACRO.min_ticks_between_refresh == 20)
check("9.4 SMC min_ticks=5",
      REFRESH_POLICY_SMC.min_ticks_between_refresh == 5)

# =========================================================================
# 10. Edge cases
# =========================================================================
print("\n--- 10. Edge cases ---")

# 10.1 Exactly at threshold
pol_e = RefreshPolicy(base_refresh_interval_seconds=60, deep_refresh_interval_seconds=300)
check("10.1 Base due exactly at interval",
      should_base_refresh(pol_e, NOW - timedelta(seconds=60), NOW))
check("10.2 Deep due exactly at interval",
      should_deep_refresh(pol_e, NOW - timedelta(seconds=300), NOW))

# 10.3 One second before threshold
check("10.3 Base NOT due 1s before interval",
      not should_base_refresh(pol_e, NOW - timedelta(seconds=59), NOW))
check("10.4 Deep NOT due 1s before interval",
      not should_deep_refresh(pol_e, NOW - timedelta(seconds=299), NOW))

# 10.5 Tick watch edge: exactly enough ticks (5), last tick within base window
pol_t5 = RefreshPolicy(base_refresh_interval_seconds=60, tick_watch_enabled=True,
                       min_ticks_between_refresh=5)
check("10.5 Exactly enough ticks (5), within base window",
      should_tick_watch(pol_t5, _30S_AGO, 5, NOW))

# 10.6 Tick watch: 0 ticks
check("10.6 Zero ticks since refresh -> False",
      not should_tick_watch(pol_t5, _30S_AGO, 0, NOW))


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
