"""Unit tests for ``head_types.py`` — Floor 4 type definitions and helpers.

Tests:
- HeadDecision enum (4 members)
- SetupGrade enum (3 members)
- TriggerStatus enum (5 members)
- ZoneStatus enum (6 members)
- ZoneInfo dataclass fields and defaults
- TriggerInfo dataclass fields and defaults
- InvalidationRule dataclass fields and defaults
- compute_freshness() — None, FRESH, WARM, STALE, boundary transitions
- compute_bias_from_signals() — bullish, bearish, neutral, edge cases
- compute_confidence() — weight blending, bounds clamping
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta
from dataclasses import fields

from junior_aladdin.floor_4_heads.head_types import (
    HeadDecision,
    SetupGrade,
    TriggerStatus,
    ZoneStatus,
    ZoneInfo,
    TriggerInfo,
    InvalidationRule,
    compute_freshness,
    compute_bias_from_signals,
    compute_confidence,
)
from junior_aladdin.shared.types import FreshnessTag, BiasType

from junior_aladdin.floor_4_heads.head_types import (
    _FRESH_MAX_SECONDS,
    _WARM_MAX_SECONDS,
    _STALE_MAX_SECONDS,
    _CRITICAL_STALE_SECONDS,
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
print("Floor 4 — Head Types Tests")
print("=" * 60)

# =========================================================================
# 1. HeadDecision enum
# =========================================================================
print("\n--- 1. HeadDecision enum ---")

check("1.1 Has SETUP_ACTIVE", HeadDecision.SETUP_ACTIVE.value == "SETUP_ACTIVE")
check("1.2 Has WATCHING", HeadDecision.WATCHING.value == "WATCHING")
check("1.3 Has NO_SETUP", HeadDecision.NO_SETUP.value == "NO_SETUP")
check("1.4 Has BLOCKING", HeadDecision.BLOCKING.value == "BLOCKING")
check("1.5 Total 4 members", len(list(HeadDecision)) == 4)

# =========================================================================
# 2. SetupGrade enum
# =========================================================================
print("\n--- 2. SetupGrade enum ---")

check("2.1 Has grade A", SetupGrade.A.value == "A")
check("2.2 Has grade B", SetupGrade.B.value == "B")
check("2.3 Has grade C", SetupGrade.C.value == "C")
check("2.4 Total 3 members", len(list(SetupGrade)) == 3)

# =========================================================================
# 3. TriggerStatus enum
# =========================================================================
print("\n--- 3. TriggerStatus enum ---")

check("3.1 Has PENDING", TriggerStatus.PENDING.value == "PENDING")
check("3.2 Has ACTIVE", TriggerStatus.ACTIVE.value == "ACTIVE")
check("3.3 Has TRIGGERED", TriggerStatus.TRIGGERED.value == "TRIGGERED")
check("3.4 Has EXPIRED", TriggerStatus.EXPIRED.value == "EXPIRED")
check("3.5 Has INVALIDATED", TriggerStatus.INVALIDATED.value == "INVALIDATED")
check("3.6 Total 5 members", len(list(TriggerStatus)) == 5)

# =========================================================================
# 4. ZoneStatus enum
# =========================================================================
print("\n--- 4. ZoneStatus enum ---")

check("4.1 Has ACTIVE", ZoneStatus.ACTIVE.value == "ACTIVE")
check("4.2 Has APPROACHING", ZoneStatus.APPROACHING.value == "APPROACHING")
check("4.3 Has TOUCHED", ZoneStatus.TOUCHED.value == "TOUCHED")
check("4.4 Has MITIGATED", ZoneStatus.MITIGATED.value == "MITIGATED")
check("4.5 Has BROKEN", ZoneStatus.BROKEN.value == "BROKEN")
check("4.6 Has INVALID", ZoneStatus.INVALID.value == "INVALID")
check("4.7 Total 6 members", len(list(ZoneStatus)) == 6)

# =========================================================================
# 5. ZoneInfo dataclass
# =========================================================================
print("\n--- 5. ZoneInfo dataclass ---")

z_default = ZoneInfo()
check("5.1 Default zone_type empty", z_default.zone_type == "")
check("5.2 Default price_level 0.0", z_default.price_level == 0.0)
check("5.3 Default direction empty", z_default.direction == "")
check("5.4 Default status ACTIVE", z_default.status == ZoneStatus.ACTIVE)
check("5.5 Default strength 0.5", z_default.strength == 0.5)
check("5.6 Default signal_ref empty", z_default.signal_ref == "")

z_custom = ZoneInfo(
    zone_type="FVG",
    price_level=19550.0,
    direction="bullish",
    status=ZoneStatus.APPROACHING,
    strength=0.85,
    signal_ref="smc_fvg_123",
)
check("5.7 Custom zone_type", z_custom.zone_type == "FVG")
check("5.8 Custom price_level", z_custom.price_level == 19550.0)
check("5.9 Custom direction", z_custom.direction == "bullish")
check("5.10 Custom status", z_custom.status == ZoneStatus.APPROACHING)
check("5.11 Custom strength", z_custom.strength == 0.85)
check("5.12 Custom signal_ref", z_custom.signal_ref == "smc_fvg_123")
check("5.13 Total 6 fields", len(fields(ZoneInfo)) == 6)

# =========================================================================
# 6. TriggerInfo dataclass
# =========================================================================
print("\n--- 6. TriggerInfo dataclass ---")

t_default = TriggerInfo()
check("6.1 Default trigger_type empty", t_default.trigger_type == "")
check("6.2 Default condition empty", t_default.condition == "")
check("6.3 Default zone_ref empty", t_default.zone_ref == "")
check("6.4 Default status PENDING", t_default.status == TriggerStatus.PENDING)
check("6.5 Default price_level 0.0", t_default.price_level == 0.0)

t_custom = TriggerInfo(
    trigger_type="zone_touch",
    condition="Price touches 19600",
    zone_ref="zone_01",
    status=TriggerStatus.ACTIVE,
    price_level=19600.0,
)
check("6.6 Custom trigger_type", t_custom.trigger_type == "zone_touch")
check("6.7 Custom condition", t_custom.condition == "Price touches 19600")
check("6.8 Custom zone_ref", t_custom.zone_ref == "zone_01")
check("6.9 Custom status", t_custom.status == TriggerStatus.ACTIVE)
check("6.10 Custom price_level", t_custom.price_level == 19600.0)
check("6.11 Total 5 fields", len(fields(TriggerInfo)) == 5)

# =========================================================================
# 7. InvalidationRule dataclass
# =========================================================================
print("\n--- 7. InvalidationRule dataclass ---")

ir_default = InvalidationRule()
check("7.1 Default condition empty", ir_default.condition == "")
check("7.2 Default price_level 0.0", ir_default.price_level == 0.0)
check("7.3 Default reason empty", ir_default.reason == "")

ir_custom = InvalidationRule(
    condition="Price breaks below 19400",
    price_level=19400.0,
    reason="Market structure invalidated",
)
check("7.4 Custom condition", ir_custom.condition == "Price breaks below 19400")
check("7.5 Custom price_level", ir_custom.price_level == 19400.0)
check("7.6 Custom reason", ir_custom.reason == "Market structure invalidated")
check("7.7 Total 3 fields", len(fields(InvalidationRule)) == 3)

# =========================================================================
# 8. compute_freshness()
# =========================================================================
print("\n--- 8. compute_freshness() ---")

# 8a. None last_update
score, tag, secs = compute_freshness(None)
check("8.1 None update -> score 0.0", score == 0.0)
check("8.2 None update -> tag STALE", tag == FreshnessTag.STALE)
check("8.3 None update -> secs == CRITICAL", secs == _CRITICAL_STALE_SECONDS)

# 8b. FRESH — just updated
now = datetime.utcnow()
recent = now - timedelta(seconds=30)
score, tag, secs = compute_freshness(recent, now)
check("8.4 30s ago -> score > 0.5", score > 0.5)
check("8.5 30s ago -> tag FRESH", tag == FreshnessTag.FRESH)
check("8.6 30s ago -> secs == 30", secs == 30)

# 8c. FRESH boundary — just before 120s (119s is still FRESH)
boundary_fresh = now - timedelta(seconds=_FRESH_MAX_SECONDS - 1)
score, tag, secs = compute_freshness(boundary_fresh, now)
check("8.7 119s ago -> score > 0.0 (still FRESH)", score > 0.0)
check("8.8 119s ago -> tag FRESH", tag == FreshnessTag.FRESH)
check("8.9 119s ago -> secs == 119", secs == 119)

# 8d. WARM — 5 minutes
warm_time = now - timedelta(seconds=300)
score, tag, secs = compute_freshness(warm_time, now)
check("8.10 300s ago -> score between 0.0-0.5", 0.0 < score < 0.5)
check("8.11 300s ago -> tag WARM", tag == FreshnessTag.WARM)
check("8.12 300s ago -> secs == 300", secs == 300)

# 8e. WARM boundary — just before 600s (599s is still WARM)
boundary_warm = now - timedelta(seconds=_WARM_MAX_SECONDS - 1)
score, tag, secs = compute_freshness(boundary_warm, now)
check("8.13 599s ago -> score > 0.0 (still WARM)", score > 0.0)
check("8.14 599s ago -> tag WARM", tag == FreshnessTag.WARM)
check("8.15 599s ago -> secs == 599", secs == 599)

# 8f. STALE — 15 minutes
stale_time = now - timedelta(seconds=900)
score, tag, secs = compute_freshness(stale_time, now)
check("8.16 900s ago -> tag STALE", tag == FreshnessTag.STALE)
check("8.17 900s ago -> secs == 900", secs == 900)

# 8g. Deeply stale — 1 hour
deep_stale = now - timedelta(seconds=3600)
score, tag, secs = compute_freshness(deep_stale, now)
check("8.18 3600s ago -> score 0.0", score == 0.0)
check("8.19 3600s ago -> tag STALE", tag == FreshnessTag.STALE)
check("8.20 3600s ago -> secs == 3600", secs == 3600)

# 8h. Very old — 2 hours
old = now - timedelta(hours=2)
score, tag, secs = compute_freshness(old, now)
check("8.21 2hrs ago -> score 0.0", score == 0.0)
check("8.22 2hrs ago -> tag STALE", tag == FreshnessTag.STALE)

# 8i. Just updated — 1 second
super_fresh = now - timedelta(seconds=1)
score, tag, _ = compute_freshness(super_fresh, now)
check("8.23 1s ago -> score near 1.0", score > 0.99)

# =========================================================================
# 9. compute_bias_from_signals()
# =========================================================================
print("\n--- 9. compute_bias_from_signals() ---")

# 9a. Bullish majority
bias = compute_bias_from_signals(bullish_count=5, bearish_count=1)
check("9.1 5 bullish vs 1 bearish -> BULLISH", bias == BiasType.BULLISH)

# 9b. Bearish majority
bias = compute_bias_from_signals(bullish_count=1, bearish_count=5)
check("9.2 1 bullish vs 5 bearish -> BEARISH", bias == BiasType.BEARISH)

# 9c. Zero signals
bias = compute_bias_from_signals(bullish_count=0, bearish_count=0)
check("9.3 0 vs 0 -> NEUTRAL", bias == BiasType.NEUTRAL)

# 9d. Equal counts
bias = compute_bias_from_signals(bullish_count=3, bearish_count=3)
check("9.4 3 vs 3 -> NEUTRAL (ratio 1.0)", bias == BiasType.NEUTRAL)

# 9e. Near threshold — 4 vs 3 (ratio 0.75, default threshold 0.3)
# 3/4 = 0.75 > 0.3 -> NEUTRAL
bias = compute_bias_from_signals(bullish_count=4, bearish_count=3)
check("9.5 4 vs 3 (ratio 0.75 > 0.3) -> NEUTRAL", bias == BiasType.NEUTRAL)

# 9f. Clear majority below threshold — 10 vs 2 (ratio 0.2 < 0.3) -> BULLISH
bias = compute_bias_from_signals(bullish_count=10, bearish_count=2)
check("9.6 10 vs 2 (ratio 0.2 < 0.3) -> BULLISH", bias == BiasType.BULLISH)

# 9g. Custom neutral_threshold (strict)
bias = compute_bias_from_signals(bullish_count=5, bearish_count=3, neutral_threshold=0.1)
# 3/5 = 0.6 > 0.1 -> NEUTRAL
check("9.7 Custom threshold 0.1 -> NEUTRAL (ratio 0.6 > 0.1)", bias == BiasType.NEUTRAL)

# 9h. Strict threshold but clear majority
bias = compute_bias_from_signals(bullish_count=10, bearish_count=1, neutral_threshold=0.1)
# 1/10 = 0.1 is NOT > 0.1 -> BULLISH
check("9.8 Strict threshold 0.1, 10 vs 1 -> BULLISH", bias == BiasType.BULLISH)

# 9i. Only bullish
bias = compute_bias_from_signals(bullish_count=3, bearish_count=0)
check("9.9 3 bullish, 0 bearish -> BULLISH", bias == BiasType.BULLISH)

# 9j. Only bearish
bias = compute_bias_from_signals(bullish_count=0, bearish_count=3)
check("9.10 0 bullish, 3 bearish -> BEARISH", bias == BiasType.BEARISH)

# =========================================================================
# 10. compute_confidence()
# =========================================================================
print("\n--- 10. compute_confidence() ---")

# 10a. All max
conf = compute_confidence(base_score=1.0, freshness_score=1.0, context_quality=1.0, signal_strength=1.0)
# 1.0*0.4 + 1.0*0.2 + 1.0*0.25 + 1.0*0.15 = 1.0
check("10.1 All max -> 1.0", conf == 1.0)

# 10b. All min
conf = compute_confidence(base_score=0.0, freshness_score=0.0, context_quality=0.0, signal_strength=0.0)
check("10.2 All min -> 0.0", conf == 0.0)

# 10c. Mid values
# 0.5*0.4 + 0.5*0.2 + 0.5*0.25 + 0.5*0.15 = 0.5
conf = compute_confidence(base_score=0.5, freshness_score=0.5, context_quality=0.5, signal_strength=0.5)
check("10.3 All mid -> 0.5", conf == 0.5)

# 10d. Default context_quality and signal_strength
conf = compute_confidence(base_score=1.0, freshness_score=1.0)
# 1.0*0.4 + 1.0*0.2 + 0.5*0.25 + 0.5*0.15 = 0.4 + 0.2 + 0.125 + 0.075 = 0.8
check("10.4 Default context_quality=0.5, signal_strength=0.5", conf == 0.8)

# 10e. Only base score matters most (40% weight)
conf = compute_confidence(base_score=1.0, freshness_score=0.0, context_quality=0.0, signal_strength=0.0)
# 1.0*0.4 = 0.4
check("10.5 Base score only -> 0.4", conf == 0.4)

# 10f. Clamping — values above 1.0
conf = compute_confidence(base_score=2.0, freshness_score=2.0, context_quality=2.0, signal_strength=2.0)
check("10.6 Over max -> clamped to 1.0", conf == 1.0)

# 10g. Negative values
conf = compute_confidence(base_score=-0.5, freshness_score=-0.5, context_quality=-0.5, signal_strength=-0.5)
check("10.7 Negative -> clamped to 0.0", conf == 0.0)

# 10h. Weights sum verified: 0.4 + 0.2 + 0.25 + 0.15 = 1.0
conf = compute_confidence(base_score=0.3, freshness_score=0.4, context_quality=0.1, signal_strength=0.2)
# 0.3*0.4 + 0.4*0.2 + 0.1*0.25 + 0.2*0.15 = 0.12 + 0.08 + 0.025 + 0.03 = 0.255
check("10.8 Weighted blend correct: 0.12+0.08+0.025+0.03=0.255", conf == 0.255)


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
