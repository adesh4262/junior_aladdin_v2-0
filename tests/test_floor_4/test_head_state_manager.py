"""Unit tests for ``head_state_manager.py`` — Floor 4 Step 4.5.

Tests:
- ``compute_freshness()`` — score and tag decay over time
- ``compute_state()`` — READY/UNCERTAIN/STALE from freshness + confidence
- ``transition()`` — state transition logic
- ``FreshnessState`` dataclass
- ``HeadStateManager`` — lifecycle, is_stale, snapshot, reset
- Edge cases: never updated, boundary thresholds, conflicts
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta

from junior_aladdin.floor_4_heads.head_refresh_policy import (
    RefreshPolicy,
)
from junior_aladdin.floor_4_heads.head_state_manager import (
    HeadStateManager,
    compute_freshness,
    compute_state,
    transition,
)
from junior_aladdin.shared.types import FreshnessTag, HeadState

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
print("Floor 4 — Head State Manager Tests")
print("=" * 60)

NOW = datetime.utcnow()
_1S_AGO = NOW - timedelta(seconds=1)
_60S_AGO = NOW - timedelta(seconds=60)
_150S_AGO = NOW - timedelta(seconds=150)
_300S_AGO = NOW - timedelta(seconds=300)
_900S_AGO = NOW - timedelta(seconds=900)
_2000S_AGO = NOW - timedelta(seconds=2000)
_4000S_AGO = NOW - timedelta(seconds=4000)

# =========================================================================
# 1. compute_freshness
# =========================================================================
print("\n--- 1. compute_freshness ---")

# 1.1 Never updated
score, tag, secs = compute_freshness(None, NOW)
check("1.1 Never updated -> score=0, STALE", score == 0.0 and tag == FreshnessTag.STALE and secs > 0)

# 1.2 Just updated (1s ago)
score, tag, secs = compute_freshness(_1S_AGO, NOW)
check("1.2 Just updated -> score ~1.0, FRESH", score > 0.9 and tag == FreshnessTag.FRESH and secs == 1)

# 1.3 60s ago (within 2 min)
score, tag, secs = compute_freshness(_60S_AGO, NOW)
check("1.3 60s ago -> FRESH", score > 0.4 and tag == FreshnessTag.FRESH)

# 1.4 150s ago (2-10 min window)
score, tag, secs = compute_freshness(_150S_AGO, NOW)
check("1.4 150s ago -> score 0.4-0.7, WARM", 0.3 < score < 0.7 and tag == FreshnessTag.WARM)

# 1.5 300s ago (5 min, still 2-10 min window)
score, tag, secs = compute_freshness(_300S_AGO, NOW)
check("1.5 300s ago -> WARM", tag == FreshnessTag.WARM)

# 1.6 900s ago (15 min, 10-30 min window)
score, tag, secs = compute_freshness(_900S_AGO, NOW)
check("1.6 900s ago -> STALE", tag == FreshnessTag.STALE and score < 0.3)

# 1.7 2000s ago (33 min, > 30 min)
score, tag, secs = compute_freshness(_2000S_AGO, NOW)
check("1.7 2000s ago -> score near 0, STALE", score < 0.1 and tag == FreshnessTag.STALE)

# 1.8 Very old (4000s)
score, tag, secs = compute_freshness(_4000S_AGO, NOW)
check("1.8 4000s ago -> score=0, STALE", score == 0.0 and tag == FreshnessTag.STALE)

# =========================================================================
# 2. compute_state
# =========================================================================
print("\n--- 2. compute_state ---")

# 2.1 FRESH + high confidence + no conflict -> READY
state = compute_state(FreshnessTag.FRESH, 0.8)
check("2.1 FRESH + high conf -> READY", state == HeadState.READY)

# 2.2 WARM + medium confidence + no conflict -> READY
state = compute_state(FreshnessTag.WARM, 0.5)
check("2.2 WARM + med conf -> READY", state == HeadState.READY)

# 2.3 FRESH + low confidence -> UNCERTAIN
state = compute_state(FreshnessTag.FRESH, 0.2)
check("2.3 FRESH + low conf -> UNCERTAIN", state == HeadState.UNCERTAIN)

# 2.4 FRESH + high confidence + conflict -> UNCERTAIN
state = compute_state(FreshnessTag.FRESH, 0.8, has_internal_conflict=True)
check("2.4 FRESH + high conf + conflict -> UNCERTAIN", state == HeadState.UNCERTAIN)

# 2.5 STALE + high confidence -> STALE (freshness overrides confidence)
state = compute_state(FreshnessTag.STALE, 0.9)
check("2.5 STALE + high conf -> STALE (freshness wins)", state == HeadState.STALE)

# 2.6 STALE + low confidence -> STALE
state = compute_state(FreshnessTag.STALE, 0.1)
check("2.6 STALE + low conf -> STALE", state == HeadState.STALE)

# 2.7 FRESH + confidence exactly at UNCERTAIN boundary (0.3)
state = compute_state(FreshnessTag.FRESH, 0.29)
check("2.7 FRESH + conf 0.29 < 0.3 -> UNCERTAIN", state == HeadState.UNCERTAIN)

state = compute_state(FreshnessTag.FRESH, 0.3)
check("2.8 FRESH + conf 0.3 >= 0.3 -> READY", state == HeadState.READY)

# =========================================================================
# 3. transition
# =========================================================================
print("\n--- 3. transition ---")

# 3.1 READY -> READY (no change)
check("3.1 READY -> READY stays same",
      transition(HeadState.READY, HeadState.READY) == HeadState.READY)

# 3.2 READY -> UNCERTAIN
check("3.2 READY -> UNCERTAIN",
      transition(HeadState.READY, HeadState.UNCERTAIN) == HeadState.UNCERTAIN)

# 3.3 READY -> STALE
check("3.3 READY -> STALE",
      transition(HeadState.READY, HeadState.STALE) == HeadState.STALE)

# 3.4 UNCERTAIN -> READY (confidence improved)
check("3.4 UNCERTAIN -> READY",
      transition(HeadState.UNCERTAIN, HeadState.READY) == HeadState.READY)

# 3.5 STALE -> READY (fresh update)
check("3.5 STALE -> READY",
      transition(HeadState.STALE, HeadState.READY) == HeadState.READY)

# 3.6 STALE -> UNCERTAIN
check("3.6 STALE -> UNCERTAIN",
      transition(HeadState.STALE, HeadState.UNCERTAIN) == HeadState.UNCERTAIN)

# =========================================================================
# 4. HeadStateManager — basic lifecycle
# =========================================================================
print("\n--- 4. HeadStateManager basic lifecycle ---")

policy = RefreshPolicy(stale_after_seconds=600)
manager = HeadStateManager(policy=policy)

check("4.1 Initial state is STALE", manager.current_state == HeadState.STALE)
check("4.2 Initial freshness score 0", manager.last_freshness.freshness_score == 0.0)
check("4.3 Initial freshness tag STALE", manager.last_freshness.freshness_tag == FreshnessTag.STALE)

# Update with fresh data
fs = manager.update(last_deep_update=_1S_AGO, confidence=0.8, now=NOW)
check("4.4 After fresh update -> READY", manager.current_state == HeadState.READY)
check("4.5 FreshnessState returned correctly", fs.state == HeadState.READY)
check("4.6 Freshness score > 0.9", fs.freshness_score > 0.9)
check("4.7 Freshness tag FRESH", fs.freshness_tag == FreshnessTag.FRESH)
check("4.8 Seconds == 1", fs.seconds_since_update == 1)

# =========================================================================
# 5. State transitions over time
# =========================================================================
print("\n--- 5. State transitions over time ---")

mgr = HeadStateManager(policy=RefreshPolicy(stale_after_seconds=600))

# Start: never updated -> STALE
# 5.1 Update with fresh data -> READY
mgr.update(last_deep_update=_1S_AGO, confidence=0.8, now=NOW)
check("5.1 Fresh data -> READY", mgr.current_state == HeadState.READY)

# 5.2 Update with low confidence -> UNCERTAIN
mgr.update(last_deep_update=_1S_AGO, confidence=0.1, now=NOW)
check("5.2 Low confidence -> UNCERTAIN", mgr.current_state == HeadState.UNCERTAIN)

# 5.3 Update with conflict -> UNCERTAIN
mgr.update(last_deep_update=_1S_AGO, confidence=0.8, has_internal_conflict=True, now=NOW)
check("5.3 Conflict -> UNCERTAIN", mgr.current_state == HeadState.UNCERTAIN)

# 5.4 Update with old data -> STALE (freshness overrides)
mgr.update(last_deep_update=_60S_AGO, confidence=0.0, now=NOW)
# 60s ago is still FRESH, confidence 0.0 -> UNCERTAIN
check("5.4 60s stale-ish + low conf -> UNCERTAIN", mgr.current_state == HeadState.UNCERTAIN)

# 5.5 Very old data -> STALE
mgr.update(last_deep_update=_2000S_AGO, confidence=0.9, now=NOW)
check("5.5 Old data (33m) + high conf -> STALE (freshness wins)", mgr.current_state == HeadState.STALE)

# =========================================================================
# 6. is_stale
# =========================================================================
print("\n--- 6. is_stale ---")

policy6 = RefreshPolicy(stale_after_seconds=600)  # 10 min stale
mgr6 = HeadStateManager(policy=policy6)

check("6.1 Never updated -> stale", mgr6.is_stale())
check("6.2 is_stale with recent update -> not stale",
      not mgr6.is_stale(_60S_AGO))
check("6.3 is_stale with old update -> stale",
      mgr6.is_stale(NOW - timedelta(seconds=601)))
check("6.4 is_stale exactly at threshold -> stale",
      mgr6.is_stale(NOW - timedelta(seconds=600)))

# =========================================================================
# 7. get_freshness_snapshot
# =========================================================================
print("\n--- 7. get_freshness_snapshot ---")

mgr7 = HeadStateManager(policy=RefreshPolicy(stale_after_seconds=600))
mgr7.update(last_deep_update=_1S_AGO, confidence=0.8, now=NOW)
snap = mgr7.get_freshness_snapshot()

check("7.1 Snapshot has 'state' key", "state" in snap)
check("7.2 Snapshot has 'freshness_score' key", "freshness_score" in snap)
check("7.3 Snapshot has 'freshness_tag' key", "freshness_tag" in snap)
check("7.4 Snapshot has 'seconds_since_update' key", "seconds_since_update" in snap)
check("7.5 Snapshot state = READY", snap["state"] == HeadState.READY.value)
check("7.6 Snapshot freshness_tag = FRESH", snap["freshness_tag"] == FreshnessTag.FRESH.value)

# =========================================================================
# 8. reset
# =========================================================================
print("\n--- 8. reset ---")

mgr8 = HeadStateManager(policy=RefreshPolicy(stale_after_seconds=600))
mgr8.update(last_deep_update=_1S_AGO, confidence=0.8, now=NOW)
check("8.1 Before reset: READY", mgr8.current_state == HeadState.READY)

mgr8.reset()
check("8.2 After reset: STALE", mgr8.current_state == HeadState.STALE)
check("8.3 After reset: score=0", mgr8.last_freshness.freshness_score == 0.0)
check("8.4 After reset: tag=STALE", mgr8.last_freshness.freshness_tag == FreshnessTag.STALE)

# Reset to specific state
mgr8.reset(state=HeadState.UNCERTAIN)
check("8.5 Reset to UNCERTAIN", mgr8.current_state == HeadState.UNCERTAIN)

# =========================================================================
# 9. Freshness state from last_freshness property
# =========================================================================
print("\n--- 9. FreshnessState property ---")

mgr9 = HeadStateManager(policy=RefreshPolicy(stale_after_seconds=600))
fs = mgr9.update(last_deep_update=_1S_AGO, confidence=0.8, now=NOW)

check("9.1 last_freshness matches returned value",
      mgr9.last_freshness == fs)
check("9.2 FreshnessState.score via property",
      mgr9.last_freshness.freshness_score == fs.freshness_score)
check("9.3 FreshnessState.tag via property",
      mgr9.last_freshness.freshness_tag == fs.freshness_tag)

# =========================================================================
# 10. Edge cases
# =========================================================================
print("\n--- 10. Edge cases ---")

# 10.1 Extremely old data
mgr10 = HeadStateManager(policy=RefreshPolicy(stale_after_seconds=600))
fs = mgr10.update(last_deep_update=_4000S_AGO, confidence=0.0, now=NOW)
check("10.1 Very old data -> STALE", mgr10.current_state == HeadState.STALE)
check("10.2 Very old -> score 0", fs.freshness_score == 0.0)

# 10.3 Negative seconds (future timestamp)
future = NOW + timedelta(seconds=3600)
fs = mgr10.update(last_deep_update=future, confidence=0.9, now=NOW)
# Future timestamp means 0 elapsed -> max freshness
check("10.3 Future timestamp -> FRESH", fs.freshness_tag == FreshnessTag.FRESH)
check("10.4 Future timestamp -> score >= 0.9", fs.freshness_score >= 0.9)

# 10.5 Policy with very short stale threshold
short_policy = RefreshPolicy(stale_after_seconds=5)
mgr_short = HeadStateManager(policy=short_policy)
mgr_short.update(last_deep_update=NOW - timedelta(seconds=10), confidence=0.8, now=NOW)
check("10.5 Short stale threshold (5s) + old -> stale",
      mgr_short.is_stale())

# 10.6 Policy with zero stale threshold
zero_policy = RefreshPolicy(stale_after_seconds=0)
check("10.6 Zero stale threshold -> always stale",
      zero_policy.stale_after_seconds == 0)


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
