"""Tests for smc_validator.py — Floor 3 domain-specific validation.

Tests SMC domain signal validation:
- MARKET_STRUCTURE: valid/invalid types, swing counts
- FVG: fvg_type, top/bottom, gap_size, mitigated
- ORDER_BLOCK: ob_type, price, strength
- CHOCH: choch_type, break_price, prior_structure, confirmed
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
    FvgType,
    ObType,
    ChoChType,
    MarketStructureType,
)
from junior_aladdin.floor_3_calculations.smc.smc_validator import (
    validate_smc_signals,
    quick_validate,
    ValidationResult,
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


def make_signal(indicator_type: str, value: dict, domain=CalculationDomain.SMC) -> CalculatedSignal:
    return CalculatedSignal(
        signal_id="a" * 32,
        domain=domain,
        indicator_type=indicator_type,
        value=value,
        timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
        quality=CalculationQuality.NOMINAL,
        metadata={},
        calculation_log=CalculationLog(
            signal_id="a" * 32, domain=domain, engine_version="1.0",
            input_hash="abc", parameters_used=[], calculation_steps=[], warnings=[],
        ),
    )


print("=" * 60)
print("SMC Validator Tests")
print("=" * 60)

# ─────────────────────────────────────────────────────────────────
# 1. MARKET_STRUCTURE validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 1. MARKET_STRUCTURE ---")

# 1.1 Valid bullish structure
sig = make_signal("MARKET_STRUCTURE", {
    "structure_type": "BULLISH_HH_HL",
    "structure_valid": True,
    "swing_high_count": 5,
    "swing_low_count": 4,
    "description": "Uptrend",
})
r = validate_smc_signals([sig])
check("1.1 Valid bullish MS passes", r.valid and len(r.halt_errors) == 0)

# 1.2 Invalid structure_type
sig2 = make_signal("MARKET_STRUCTURE", {
    "structure_type": "INVALID_TYPE",
    "structure_valid": True,
    "swing_high_count": 3,
    "swing_low_count": 2,
})
r2 = validate_smc_signals([sig2])
check("1.2 Invalid structure_type is HALT", len(r2.halt_errors) == 1)
check("1.2 Result not valid", not r2.valid)

# 1.3 Non-boolean structure_valid
sig3 = make_signal("MARKET_STRUCTURE", {
    "structure_type": "CHOP",
    "structure_valid": "yes",
    "swing_high_count": 0,
    "swing_low_count": 0,
})
r3 = validate_smc_signals([sig3])
check("1.3 Non-bool structure_valid is FLAG", len(r3.halt_errors) == 0 and len(r3.flag_errors) >= 1)

# 1.4 Negative swing count
sig4 = make_signal("MARKET_STRUCTURE", {
    "structure_type": "CHOP",
    "structure_valid": False,
    "swing_high_count": -1,
    "swing_low_count": 0,
})
r4 = validate_smc_signals([sig4])
check("1.4 Negative swing_high_count is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# 1.5 All valid structure types
for st in MarketStructureType:
    sig5 = make_signal("MARKET_STRUCTURE", {
        "structure_type": st.value,
        "structure_valid": True,
        "swing_high_count": 3,
        "swing_low_count": 2,
    })
    r5 = validate_smc_signals([sig5])
    check(f"1.5 Structure type {st.value} passes", r5.valid and len(r5.halt_errors) == 0)

# ─────────────────────────────────────────────────────────────────
# 2. FVG validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 2. FVG ---")

# 2.1 Valid bullish FVG
sig = make_signal("FVG", {
    "fvg_type": "BULLISH_FVG",
    "top": 101.5,
    "bottom": 100.5,
    "gap_size_pips": 1.0,
    "mitigated": False,
})
r = validate_smc_signals([sig])
check("2.1 Valid bullish FVG passes", r.valid and len(r.halt_errors) == 0)

# 2.2 Invalid fvg_type
sig2 = make_signal("FVG", {
    "fvg_type": "INVALID_FVG",
    "top": 101.0,
    "bottom": 100.0,
    "gap_size_pips": 1.0,
    "mitigated": False,
})
r2 = validate_smc_signals([sig2])
check("2.2 Invalid fvg_type is HALT", len(r2.halt_errors) == 1)

# 2.3 Bearish FVG
sig3 = make_signal("FVG", {
    "fvg_type": "BEARISH_FVG",
    "top": 105.0,
    "bottom": 103.0,
    "gap_size_pips": 2.0,
    "mitigated": True,
})
r3 = validate_smc_signals([sig3])
check("2.3 Valid bearish FVG passes", r3.valid and len(r3.halt_errors) == 0)

# 2.4 top <= bottom (should flag)
sig4 = make_signal("FVG", {
    "fvg_type": "BULLISH_FVG",
    "top": 100.0,
    "bottom": 101.0,
    "gap_size_pips": -1.0,
    "mitigated": False,
})
r4 = validate_smc_signals([sig4])
check("2.4 top <= bottom is FLAG", len(r4.flag_errors) >= 1)

# 2.5 Non-bool mitigated
sig5 = make_signal("FVG", {
    "fvg_type": "BULLISH_FVG",
    "top": 101.0,
    "bottom": 100.0,
    "gap_size_pips": 1.0,
    "mitigated": "yes",
})
r5 = validate_smc_signals([sig5])
check("2.5 Non-bool mitigated is FLAG", len(r5.flag_errors) >= 1 and r5.valid)

# ─────────────────────────────────────────────────────────────────
# 3. ORDER_BLOCK validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 3. ORDER_BLOCK ---")

# 3.1 Valid bullish OB
sig = make_signal("ORDER_BLOCK", {
    "ob_type": "BULLISH_OB",
    "price": 100.5,
    "strength": 0.75,
})
r = validate_smc_signals([sig])
check("3.1 Valid bullish OB passes", r.valid and len(r.halt_errors) == 0)

# 3.2 Invalid ob_type
sig2 = make_signal("ORDER_BLOCK", {
    "ob_type": "INVALID_OB",
    "price": 100.0,
    "strength": 0.5,
})
r2 = validate_smc_signals([sig2])
check("3.2 Invalid ob_type is HALT", len(r2.halt_errors) == 1)

# 3.3 Non-positive price
sig3 = make_signal("ORDER_BLOCK", {
    "ob_type": "BEARISH_OB",
    "price": 0,
    "strength": 0.3,
})
r3 = validate_smc_signals([sig3])
check("3.3 Zero price is HALT", len(r3.halt_errors) >= 1)

# 3.4 Strength outside [0,1]
sig4 = make_signal("ORDER_BLOCK", {
    "ob_type": "BULLISH_OB",
    "price": 150.0,
    "strength": 1.5,
})
r4 = validate_smc_signals([sig4])
check("3.4 Strength > 1.0 is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# 3.5 Bearish OB
sig5 = make_signal("ORDER_BLOCK", {
    "ob_type": "BEARISH_OB",
    "price": 200.0,
    "strength": 0.9,
})
r5 = validate_smc_signals([sig5])
check("3.5 Valid bearish OB passes", r5.valid and len(r5.halt_errors) == 0)

# ─────────────────────────────────────────────────────────────────
# 4. CHOCH validation
# ─────────────────────────────────────────────────────────────────
print("\n--- 4. CHOCH ---")

# 4.1 Valid bullish CHOCH
sig = make_signal("CHOCH", {
    "choch_type": "BULLISH_CHOCH",
    "break_price": 105.0,
    "prior_structure": "BEARISH_LH_LL",
    "confirmed": True,
})
r = validate_smc_signals([sig])
check("4.1 Valid bullish CHOCH passes", r.valid and len(r.halt_errors) == 0)

# 4.2 Invalid choch_type
sig2 = make_signal("CHOCH", {
    "choch_type": "INVALID_CHOCH",
    "break_price": 100.0,
    "prior_structure": "CHOP",
    "confirmed": False,
})
r2 = validate_smc_signals([sig2])
check("4.2 Invalid choch_type is HALT", len(r2.halt_errors) == 1)

# 4.3 Non-positive break_price
sig3 = make_signal("CHOCH", {
    "choch_type": "BEARISH_CHOCH",
    "break_price": -5.0,
    "prior_structure": "BULLISH_HH_HL",
    "confirmed": True,
})
r3 = validate_smc_signals([sig3])
check("4.3 Negative break_price is HALT", len(r3.halt_errors) >= 1)

# 4.4 Non-bool confirmed
sig4 = make_signal("CHOCH", {
    "choch_type": "BULLISH_CHOCH",
    "break_price": 110.0,
    "prior_structure": "CHOP",
    "confirmed": None,
})
r4 = validate_smc_signals([sig4])
check("4.4 Non-bool confirmed is FLAG", len(r4.flag_errors) >= 1 and r4.valid)

# ─────────────────────────────────────────────────────────────────
# 5. Edge cases
# ─────────────────────────────────────────────────────────────────
print("\n--- 5. Edge Cases ---")

# 5.1 Empty signal list
r = validate_smc_signals([])
check("5.1 Empty list passes", r.valid and r.total_checks == 0)

# 5.2 Non-SMC domain signals filtered
non_smc = make_signal("RSI", {"rsi_value": 50}, domain=CalculationDomain.TECHNICAL)
r2 = validate_smc_signals([non_smc])
check("5.2 Non-SMC signals filtered out", r2.total_checks == 0 and r2.valid)

# 5.3 Unknown indicator type
sig_bad = make_signal("UNKNOWN_SMC", {})
r3 = validate_smc_signals([sig_bad])
check("5.3 Unknown indicator is FLAG", len(r3.flag_errors) >= 1 and r3.valid)

# 5.4 quick_validate returns bool
check("5.4 quick_validate returns True for valid",
      quick_validate([sig]) is True)
check("5.5 quick_validate returns False for invalid",
      quick_validate([sig2]) is False)

# 5.5 Missing value fields (non-dict value)
sig_no_val = make_signal("FVG", None)  # type: ignore
r5 = validate_smc_signals([sig_no_val])
check("5.6 None value handled gracefully", r5.valid or len(r5.flag_errors) > 0)

# ─────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if __name__ == "__main__":
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
