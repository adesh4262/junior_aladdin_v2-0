"""Tests for ict_validator.py — Floor 3 domain-specific validation.

Tests ICT domain signal validation:
- PD_ARRAY: pd_type, level, strength
- KILL_ZONE / NEXT_KILL_ZONE: kill_zone_type, active, time_remaining
- LIQUIDITY: liquidity_type, price, swept, size
- LIQUIDITY_CONTEXT: context, buy/sell counts
- Empty/mixed signal lists
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    CalculationLog,
    CalculationQuality,
    PdArrayType,
    KillZoneType,
    LiquidityType,
)
from junior_aladdin.floor_3_calculations.ict.ict_validator import (
    validate_ict_signals,
    quick_validate,
)

UTC = timezone.utc
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


def make_signal(indicator_type: str, value: dict, domain=CalculationDomain.ICT) -> CalculatedSignal:
    return CalculatedSignal(
        signal_id="b" * 32,
        domain=domain,
        indicator_type=indicator_type,
        value=value,
        timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
        quality=CalculationQuality.NOMINAL,
        metadata={},
        calculation_log=CalculationLog(
            signal_id="b" * 32, domain=domain, engine_version="1.0",
            input_hash="abc", parameters_used=[], calculation_steps=[], warnings=[],
        ),
    )


print("=" * 60)
print("ICT Validator Tests")
print("=" * 60)

# ─────────────────────────────────────────────────────────────────
# 1. PD_ARRAY validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 1. PD_ARRAY ---")

# 1.1 Valid premium level
sig = make_signal("PD_ARRAY", {
    "pd_type": "PREMIUM",
    "level": 100.5,
    "strength": 0.8,
})
r = validate_ict_signals([sig])
check("1.1 Valid PREMIUM PD_ARRAY passes", r.valid and len(r.halt_errors) == 0)

# 1.2 Invalid pd_type
sig2 = make_signal("PD_ARRAY", {
    "pd_type": "INVALID_PD",
    "level": 100.0,
    "strength": 0.5,
})
r2 = validate_ict_signals([sig2])
check("1.2 Invalid pd_type is HALT", len(r2.halt_errors) == 1 and not r2.valid)

# 1.3 Discount + OTE
sig3 = make_signal("PD_ARRAY", {"pd_type": "DISCOUNT", "level": 95.0, "strength": 0.6})
sig3b = make_signal("PD_ARRAY", {"pd_type": "OPTIMAL_TRADE_ENTRY", "level": 97.5, "strength": 0.9})
r3 = validate_ict_signals([sig3, sig3b])
check("1.3 DISCOUNT + OTE both pass", r3.valid and len(r3.halt_errors) == 0)

# 1.4 Non-positive level
sig4 = make_signal("PD_ARRAY", {"pd_type": "PREMIUM", "level": 0, "strength": 0.5})
r4 = validate_ict_signals([sig4])
check("1.4 Zero level is HALT", len(r4.halt_errors) >= 1)

# 1.5 Strength out of range
sig5 = make_signal("PD_ARRAY", {"pd_type": "DISCOUNT", "level": 200.0, "strength": 1.5})
r5 = validate_ict_signals([sig5])
check("1.5 Strength > 1.0 is FLAG", len(r5.flag_errors) >= 1 and r5.valid)

# ─────────────────────────────────────────────────────────────────
# 2. KILL_ZONE validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 2. KILL_ZONE ---")

# 2.1 Valid active kill zone
sig = make_signal("KILL_ZONE", {
    "kill_zone_type": "ASIAN",
    "active": True,
    "time_remaining_s": 120,
})
r = validate_ict_signals([sig])
check("2.1 Valid active KILL_ZONE passes", r.valid and len(r.halt_errors) == 0)

# 2.2 Valid inactive zone
sig2 = make_signal("KILL_ZONE", {
    "kill_zone_type": "LONDON_OPEN",
    "active": False,
    "time_remaining_s": 0,
})
r2 = validate_ict_signals([sig2])
check("2.2 Valid inactive KILL_ZONE passes", r2.valid)

# 2.3 Invalid kill_zone_type
sig3 = make_signal("KILL_ZONE", {
    "kill_zone_type": "INVALID_ZONE",
    "active": False,
    "time_remaining_s": 0,
})
r3 = validate_ict_signals([sig3])
check("2.3 Invalid kill_zone_type is HALT", len(r3.halt_errors) == 1)

# 2.4 Non-bool active
sig4 = make_signal("KILL_ZONE", {
    "kill_zone_type": "NY_AM_OPEN",
    "active": "yes",
    "time_remaining_s": 300,
})
r4 = validate_ict_signals([sig4])
check("2.4 Non-bool active is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# 2.5 Negative time_remaining
sig5 = make_signal("KILL_ZONE", {
    "kill_zone_type": "NY_PM_CLOSE",
    "active": True,
    "time_remaining_s": -5,
})
r5 = validate_ict_signals([sig5])
check("2.5 Negative time_remaining_s is FLAG", len(r5.flag_errors) >= 1 and r5.valid)

# ─────────────────────────────────────────────────────────────────
# 3. NEXT_KILL_ZONE validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 3. NEXT_KILL_ZONE ---")

# 3.1 Valid next zone
sig = make_signal("NEXT_KILL_ZONE", {
    "kill_zone_type": "LONDON_OPEN",
    "time_until_s": 1800,
})
r = validate_ict_signals([sig])
check("3.1 Valid NEXT_KILL_ZONE passes", r.valid and len(r.halt_errors) == 0)

# 3.2 Negative time_until
sig2 = make_signal("NEXT_KILL_ZONE", {
    "kill_zone_type": "ASIAN",
    "time_until_s": -10,
})
r2 = validate_ict_signals([sig2])
check("3.2 Negative time_until_s is FLAG", len(r2.flag_errors) >= 1 and r2.valid)

# 3.3 Invalid type
sig3 = make_signal("NEXT_KILL_ZONE", {
    "kill_zone_type": "BAD",
    "time_until_s": 300,
})
r3 = validate_ict_signals([sig3])
check("3.3 Invalid type in NEXT_KILL_ZONE is HALT", len(r3.halt_errors) >= 1)

# ─────────────────────────────────────────────────────────────────
# 4. LIQUIDITY validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 4. LIQUIDITY ---")

# 4.1 Valid buy-side liquidity
sig = make_signal("LIQUIDITY", {
    "liquidity_type": "BUY_SIDE",
    "price": 105.0,
    "swept": False,
    "size": 150,
})
r = validate_ict_signals([sig])
check("4.1 Valid BUY_SIDE liquidity passes", r.valid and len(r.halt_errors) == 0)

# 4.2 Sell-side swept
sig2 = make_signal("LIQUIDITY", {
    "liquidity_type": "SELL_SIDE",
    "price": 95.0,
    "swept": True,
    "size": 0,
})
r2 = validate_ict_signals([sig2])
check("4.2 Valid SELL_SIDE swept passes", r2.valid)

# 4.3 Double distribution
sig3 = make_signal("LIQUIDITY", {
    "liquidity_type": "DOUBLE_DISTRIBUTION",
    "price": 100.0,
    "swept": False,
    "size": 500,
})
r3 = validate_ict_signals([sig3])
check("4.3 DOUBLE_DISTRIBUTION passes", r3.valid)

# 4.4 Invalid liquidity_type
sig4 = make_signal("LIQUIDITY", {"liquidity_type": "BAD_LIQ", "price": 100.0, "swept": False, "size": 10})
r4 = validate_ict_signals([sig4])
check("4.4 Invalid liquidity_type is HALT", len(r4.halt_errors) >= 1)

# 4.5 Non-positive price
sig5 = make_signal("LIQUIDITY", {"liquidity_type": "BUY_SIDE", "price": -10, "swept": False, "size": 10})
r5 = validate_ict_signals([sig5])
check("4.5 Negative price is HALT", len(r5.halt_errors) >= 1)

# ─────────────────────────────────────────────────────────────────
# 5. LIQUIDITY_CONTEXT validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 5. LIQUIDITY_CONTEXT ---")

# 5.1 Valid context — DOUBLE_DISTRIBUTION (both sides active)
sig = make_signal("LIQUIDITY_CONTEXT", {
    "context": "DOUBLE_DISTRIBUTION",
    "buy_side_active": 3,
    "sell_side_active": 2,
    "total_levels": 5,
})
r = validate_ict_signals([sig])
check("5.1 Valid LIQUIDITY_CONTEXT passes", r.valid and len(r.halt_errors) == 0)

# 5.2 All valid context types (uses LiquidityType enum)
for ctx in LiquidityType:
    sig2 = make_signal("LIQUIDITY_CONTEXT", {
        "context": ctx.value,
        "buy_side_active": 1,
        "sell_side_active": 1,
        "total_levels": 2,
    })
    r2 = validate_ict_signals([sig2])
    check(f"5.2 Context {ctx.value} passes", r2.valid and len(r2.halt_errors) == 0)

# 5.3 Invalid context
sig3 = make_signal("LIQUIDITY_CONTEXT", {
    "context": "INVALID_CTX",
    "buy_side_active": 1,
    "sell_side_active": 1,
    "total_levels": 2,
})
r3 = validate_ict_signals([sig3])
check("5.3 Invalid context is HALT", len(r3.halt_errors) >= 1)

# ─────────────────────────────────────────────────────────────────
# 6. Edge cases
# ─────────────────────────────────────────────────────────────────
print("\n--- 6. Edge Cases ---")

# 6.1 Empty list
r = validate_ict_signals([])
check("6.1 Empty list passes", r.valid and r.total_checks == 0)

# 6.2 Non-ICT signals filtered
non_ict = make_signal("FVG", {"fvg_type": "BULLISH_FVG", "top": 101, "bottom": 100,
                                "gap_size_pips": 1, "mitigated": False},
                      domain=CalculationDomain.SMC)
r2 = validate_ict_signals([non_ict])
check("6.2 Non-ICT signals filtered", r2.total_checks == 0 and r2.valid)

# 6.3 Unknown indicator
sig_bad = make_signal("UNKNOWN_ICT", {})
r3 = validate_ict_signals([sig_bad])
check("6.3 Unknown indicator is FLAG", len(r3.flag_errors) >= 1 and r3.valid)

# 6.4 quick_validate
check("6.4 quick_validate True", quick_validate([sig]) is True)
check("6.5 quick_validate False", quick_validate([sig4]) is False)

# 6.6 None value — produces HALT errors (missing fields), but no crash
sig_none = make_signal("PD_ARRAY", None)  # type: ignore
r6 = validate_ict_signals([sig_none])
check("6.6 None value handled gracefully (no crash)",
      len(r6.halt_errors) > 0 or len(r6.flag_errors) > 0)


print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if __name__ == "__main__":
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
