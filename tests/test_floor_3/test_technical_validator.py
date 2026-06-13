"""Tests for technical_validator.py — Floor 3 domain-specific validation.

Tests Technical domain signal validation:
- RSI: rsi_value in [0,100], oversold/overbought bool, classification valid
- MA_FAST / MA_SLOW: period, latest_value, total_values
- MA_CROSS: cross type, periods, values
- ATR: period, latest_value, total_values
- VOLUME_PROFILE: poc/vah/val, value_area_volume, total_volume
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
)
from junior_aladdin.floor_3_calculations.technical.technical_validator import (
    validate_technical_signals,
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


def make_signal(indicator_type: str, value: dict, domain=CalculationDomain.TECHNICAL) -> CalculatedSignal:
    return CalculatedSignal(
        signal_id="c" * 32,
        domain=domain,
        indicator_type=indicator_type,
        value=value,
        timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
        quality=CalculationQuality.NOMINAL,
        metadata={},
        calculation_log=CalculationLog(
            signal_id="c" * 32, domain=domain, engine_version="1.0",
            input_hash="abc", parameters_used=[], calculation_steps=[], warnings=[],
        ),
    )


print("=" * 60)
print("Technical Validator Tests")
print("=" * 60)

# ─────────────────────────────────────────────────────────────────
# 1. RSI validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 1. RSI ---")

# 1.1 Valid RSI
sig = make_signal("RSI", {
    "rsi_value": 45.0,
    "oversold": False,
    "overbought": False,
    "classification": "NEUTRAL",
})
r = validate_technical_signals([sig])
check("1.1 Valid RSI (neutral) passes", r.valid and len(r.halt_errors) == 0)

# 1.2 RSI = 0 (edge)
sig2 = make_signal("RSI", {"rsi_value": 0.0, "oversold": True, "overbought": False, "classification": "OVERSOLD"})
r2 = validate_technical_signals([sig2])
check("1.2 RSI=0 passes", r2.valid and len(r2.halt_errors) == 0)

# 1.3 RSI = 100 (edge)
sig3 = make_signal("RSI", {"rsi_value": 100.0, "oversold": False, "overbought": True, "classification": "OVERBOUGHT"})
r3 = validate_technical_signals([sig3])
check("1.3 RSI=100 passes", r3.valid)

# 1.4 RSI < 0
sig4 = make_signal("RSI", {"rsi_value": -5.0, "oversold": False, "overbought": False, "classification": ""})
r4 = validate_technical_signals([sig4])
check("1.4 RSI < 0 is HALT", len(r4.halt_errors) >= 1)

# 1.5 RSI > 100
sig5 = make_signal("RSI", {"rsi_value": 150.0, "oversold": False, "overbought": False, "classification": ""})
r5 = validate_technical_signals([sig5])
check("1.5 RSI > 100 is HALT", len(r5.halt_errors) >= 1)

# 1.6 Invalid classification
sig6 = make_signal("RSI", {"rsi_value": 50.0, "oversold": False, "overbought": False, "classification": "INVALID"})
r6 = validate_technical_signals([sig6])
check("1.6 Invalid classification is FLAG", len(r6.flag_errors) >= 1 and r6.valid)

# 1.7 Non-bool oversold
sig7 = make_signal("RSI", {"rsi_value": 30.0, "oversold": "yes", "overbought": False, "classification": ""})
r7 = validate_technical_signals([sig7])
check("1.7 Non-bool oversold is FLAG", len(r7.flag_errors) >= 1 and r7.valid)

# ─────────────────────────────────────────────────────────────────
# 2. MA_FAST / MA_SLOW validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 2. MA_FAST / MA_SLOW ---")

# 2.1 Valid MA_FAST
sig = make_signal("MA_FAST", {"period": 9, "latest_value": 101.5, "total_values": 41})
r = validate_technical_signals([sig])
check("2.1 Valid MA_FAST passes", r.valid and len(r.halt_errors) == 0)

# 2.2 Valid MA_SLOW
sig2 = make_signal("MA_SLOW", {"period": 21, "latest_value": 100.2, "total_values": 29})
r2 = validate_technical_signals([sig2])
check("2.2 Valid MA_SLOW passes", r2.valid)

# 2.3 Invalid period (0)
sig3 = make_signal("MA_FAST", {"period": 0, "latest_value": 100.0, "total_values": 50})
r3 = validate_technical_signals([sig3])
check("2.3 Period=0 is HALT", len(r3.halt_errors) >= 1)

# 2.4 Negative total_values
sig4 = make_signal("MA_FAST", {"period": 9, "latest_value": 100.0, "total_values": -1})
r4 = validate_technical_signals([sig4])
check("2.4 Negative total_values is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# 2.5 Non-numeric latest_value
sig5 = make_signal("MA_SLOW", {"period": 21, "latest_value": "n/a", "total_values": 30})
r5 = validate_technical_signals([sig5])
check("2.5 Non-numeric latest_value is HALT", len(r5.halt_errors) >= 1)

# ─────────────────────────────────────────────────────────────────
# 3. MA_CROSS validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 3. MA_CROSS ---")

# 3.1 Valid bullish cross
sig = make_signal("MA_CROSS", {
    "fast_period": 9,
    "slow_period": 21,
    "cross": "BULLISH_CROSS",
    "fast_value": 102.0,
    "slow_value": 101.0,
})
r = validate_technical_signals([sig])
check("3.1 Valid BULLISH_CROSS passes", r.valid and len(r.halt_errors) == 0)

# 3.2 Bearish cross
sig2 = make_signal("MA_CROSS", {
    "fast_period": 9,
    "slow_period": 21,
    "cross": "BEARISH_CROSS",
    "fast_value": 99.0,
    "slow_value": 100.0,
})
r2 = validate_technical_signals([sig2])
check("3.2 Valid BEARISH_CROSS passes", r2.valid)

# 3.3 No cross
sig3 = make_signal("MA_CROSS", {
    "fast_period": 9,
    "slow_period": 21,
    "cross": "NO_CROSS",
    "fast_value": 100.0,
    "slow_value": 100.0,
})
r3 = validate_technical_signals([sig3])
check("3.3 NO_CROSS passes", r3.valid)

# 3.4 Invalid cross type
sig4 = make_signal("MA_CROSS", {
    "fast_period": 9,
    "slow_period": 21,
    "cross": "INVALID_CROSS",
    "fast_value": 100.0,
    "slow_value": 100.0,
})
r4 = validate_technical_signals([sig4])
check("3.4 Invalid cross is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# ─────────────────────────────────────────────────────────────────
# 4. ATR validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 4. ATR ---")

# 4.1 Valid ATR
sig = make_signal("ATR", {"period": 14, "latest_value": 2.5, "total_values": 36})
r = validate_technical_signals([sig])
check("4.1 Valid ATR passes", r.valid and len(r.halt_errors) == 0)

# 4.2 ATR with 0 latest_value
sig2 = make_signal("ATR", {"period": 14, "latest_value": 0.0, "total_values": 14})
r2 = validate_technical_signals([sig2])
check("4.2 ATR=0 passes", r2.valid)

# 4.3 Invalid period
sig3 = make_signal("ATR", {"period": 0, "latest_value": 1.0, "total_values": 10})
r3 = validate_technical_signals([sig3])
check("4.3 Period=0 is HALT", len(r3.halt_errors) >= 1)

# 4.4 Negative latest_value
sig4 = make_signal("ATR", {"period": 14, "latest_value": -1.0, "total_values": 10})
r4 = validate_technical_signals([sig4])
check("4.4 Negative ATR is HALT", len(r4.halt_errors) >= 1)

# ─────────────────────────────────────────────────────────────────
# 5. VOLUME_PROFILE validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 5. VOLUME_PROFILE ---")

# 5.1 Valid volume profile
sig = make_signal("VOLUME_PROFILE", {
    "poc": 101.0,
    "vah": 103.0,
    "val": 99.0,
    "value_area_volume": 150000,
    "total_volume": 300000,
})
r = validate_technical_signals([sig])
check("5.1 Valid VOLUME_PROFILE passes", r.valid and len(r.halt_errors) == 0)

# 5.2 VAH <= VAL (should flag)
sig2 = make_signal("VOLUME_PROFILE", {
    "poc": 100.0,
    "vah": 95.0,
    "val": 105.0,
    "value_area_volume": 100,
    "total_volume": 200,
})
r2 = validate_technical_signals([sig2])
check("5.2 VAH <= VAL is FLAG", len(r2.flag_errors) >= 1 and r2.valid)

# 5.3 Non-positive POC
sig3 = make_signal("VOLUME_PROFILE", {
    "poc": 0,
    "vah": 105.0,
    "val": 95.0,
    "value_area_volume": 100,
    "total_volume": 200,
})
r3 = validate_technical_signals([sig3])
check("5.3 POC=0 is HALT", len(r3.halt_errors) >= 1)

# 5.4 Negative volume
sig4 = make_signal("VOLUME_PROFILE", {
    "poc": 100.0,
    "vah": 105.0,
    "val": 95.0,
    "value_area_volume": -100,
    "total_volume": 200,
})
r4 = validate_technical_signals([sig4])
check("5.4 Negative value_area_volume is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# ─────────────────────────────────────────────────────────────────
# 6. Edge cases
# ─────────────────────────────────────────────────────────────────
print("\n--- 6. Edge Cases ---")

# 6.1 Empty list
r = validate_technical_signals([])
check("6.1 Empty list passes", r.valid and r.total_checks == 0)

# 6.2 Non-Technical signals filtered
non_tech = make_signal("LIQUIDITY", {"liquidity_type": "BUY_SIDE", "price": 100, "swept": False, "size": 10},
                       domain=CalculationDomain.ICT)
r2 = validate_technical_signals([non_tech])
check("6.2 Non-Technical signals filtered", r2.total_checks == 0 and r2.valid)

# 6.3 Unknown indicator
sig_bad = make_signal("UNKNOWN_TECH", {})
r3 = validate_technical_signals([sig_bad])
check("6.3 Unknown indicator is FLAG", len(r3.flag_errors) >= 1 and r3.valid)

# 6.4 quick_validate
check("6.4 quick_validate True", quick_validate([sig]) is True)
# Use a signal that triggers HALT (not just FLAG)
sig_bad_period = make_signal("ATR", {"period": 0, "latest_value": 1.0, "total_values": 10})
check("6.5 quick_validate False", quick_validate([sig_bad_period]) is False)

# 6.6 None value
sig_none = make_signal("RSI", None)  # type: ignore
r6 = validate_technical_signals([sig_none])
check("6.6 None value handled", r6.valid or len(r6.flag_errors) > 0)

# 6.7 All indicator types together
all_sigs = [
    make_signal("RSI", {"rsi_value": 50, "oversold": False, "overbought": False, "classification": "NEUTRAL"}),
    make_signal("MA_FAST", {"period": 9, "latest_value": 100, "total_values": 40}),
    make_signal("MA_SLOW", {"period": 21, "latest_value": 99, "total_values": 30}),
    make_signal("MA_CROSS", {"fast_period": 9, "slow_period": 21, "cross": "NO_CROSS", "fast_value": 100, "slow_value": 99}),
    make_signal("ATR", {"period": 14, "latest_value": 1.5, "total_values": 36}),
    make_signal("VOLUME_PROFILE", {"poc": 100, "vah": 103, "val": 97, "value_area_volume": 5000, "total_volume": 10000}),
]
r7 = validate_technical_signals(all_sigs)
check("6.7 All indicators together pass", r7.valid and len(r7.halt_errors) == 0)


print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if __name__ == "__main__":
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
