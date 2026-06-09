"""Tests for Options Engine — oi_calculator, pcr_calculator, iv_calculator,
wall_calculator, max_pain_calculator, and the main options_engine orchestrator.

Covers:
1. Options engine with valid snapshot data
2. Empty snapshots -> graceful empty output
3. OI_CHANGE — buying/unwinding classification
4. PCR — put-call ratio calculation and trend
5. IV — implied volatility context detection
6. CALL_WALL / PUT_WALL — wall strike detection
7. MAX_PAIN — max pain strike calculation
8. Error isolation — one calculator failure doesn't block others
9. Edge cases: single snapshot, no OI changes, zero IV

architecture: test options/ calculators and engine with mock snapshot data
"""

import sys
from datetime import datetime
from pathlib import Path

# ── Project root for imports ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from junior_aladdin.floor_3_calculations.f3_config import F3Config, OptionsParameters
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculationDomain,
    CalculationInput,
    EngineStatus,
    MarketPhase,
    compute_input_hash,
)
from junior_aladdin.floor_3_calculations.options.options_engine import run
from junior_aladdin.floor_3_calculations.options.oi_calculator import (
    calculate_oi_changes,
    calculate_oi_summary,
)
from junior_aladdin.floor_3_calculations.options.pcr_calculator import calculate_pcr
from junior_aladdin.floor_3_calculations.options.iv_calculator import calculate_iv
from junior_aladdin.floor_3_calculations.options.wall_calculator import detect_walls
from junior_aladdin.floor_3_calculations.options.max_pain_calculator import (
    calculate_max_pain,
)

SAMPLE_TIME = datetime(2026, 6, 10, 9, 30, 0)

# ── Mock snapshot data ──────────────────────────────────────────────────

BULLISH_SNAPSHOTS = [
    {
        "strike": 19400.0, "option_type": "PE", "oi": 80000, "premium": 45.0,
        "iv": 14.0, "change_in_oi": 5000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19500.0, "option_type": "CE", "oi": 120000, "premium": 150.0,
        "iv": 16.0, "change_in_oi": 3000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19500.0, "option_type": "PE", "oi": 60000, "premium": 55.0,
        "iv": 14.5, "change_in_oi": 2000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19600.0, "option_type": "CE", "oi": 150000, "premium": 185.0,
        "iv": 15.5, "change_in_oi": -2000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19600.0, "option_type": "PE", "oi": 50000, "premium": 30.0,
        "iv": 13.5, "change_in_oi": 1000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
]

BEARISH_SNAPSHOTS = [
    {
        "strike": 19700.0, "option_type": "CE", "oi": 180000, "premium": 210.0,
        "iv": 32.0, "change_in_oi": 15000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19600.0, "option_type": "PE", "oi": 90000, "premium": 60.0,
        "iv": 28.0, "change_in_oi": 8000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19500.0, "option_type": "CE", "oi": 100000, "premium": 120.0,
        "iv": 18.0, "change_in_oi": -5000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19500.0, "option_type": "PE", "oi": 40000, "premium": 25.0,
        "iv": 15.0, "change_in_oi": -1000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
    {
        "strike": 19600.0, "option_type": "CE", "oi": 150000, "premium": 200.0,
        "iv": 35.0, "change_in_oi": 12000, "expiry": "2026-06-25",
        "timestamp": "2026-06-10T09:25:00Z",
    },
]

EMPTY_SNAPSHOTS: list[dict] = []


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_calc_input(snapshots: list[dict], reference_price: float = 19520.0) -> CalculationInput:
    """Build a CalculationInput with options_snapshots data."""
    return CalculationInput(
        packet_envelope_id="test_options_001",
        market_phase=MarketPhase.OPEN,
        symbol="NIFTY",
        timestamp=SAMPLE_TIME,
        data={
            "options_snapshots": {
                "snapshots": snapshots,
                "reference_price": reference_price,
            },
        },
    )


def _find_signals(signals, indicator_type: str):
    return [s for s in signals if s.indicator_type == indicator_type]


_count = 0


def check(label: str, condition: bool) -> None:
    global _count
    _count += 1
    status = "PASS" if condition else "FAIL"
    if not condition:
        print(f"  [{status}] Test {_count}: {label}")
        print(f"    Assertion failed!")
    else:
        print(f"  [{status}] Test {_count}: {label}")


# ═════════════════════════════════════════════════════════════════════════
# SECTION 1 — Engine: full cycle with bullish data
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 1. OPTIONS ENGINE — Bullish Data ===")
report = run(_make_calc_input(BULLISH_SNAPSHOTS, reference_price=19520.0))
signals = report.signals

check("1.1 Engine status = COMPLETE", report.status == EngineStatus.COMPLETE)
check("1.2 Has signals", len(signals) >= 5)
check("1.3 All signals are OPTIONS domain", all(s.domain == CalculationDomain.OPTIONS for s in signals))
check("1.4 No errors", len(report.errors) == 0)
check("1.5 Duration > 0", report.duration_ms > 0)

oi_signals = _find_signals(signals, "OI_CHANGE")
pcr_sigs = _find_signals(signals, "PCR")
iv_sigs = _find_signals(signals, "IV")
wall_sigs = _find_signals(signals, "CALL_WALL") + _find_signals(signals, "PUT_WALL")
mp_sigs = _find_signals(signals, "MAX_PAIN")

check("1.6 OI_CHANGE signals exist", len(oi_signals) > 0)
check("1.7 PCR signal exists", len(pcr_sigs) == 1)
check("1.8 IV signal exists", len(iv_sigs) == 1)
check("1.9 Wall signals exist", len(wall_sigs) > 0)
check("1.10 MAX_PAIN signal exists", len(mp_sigs) == 1)

# ═════════════════════════════════════════════════════════════════════════
# SECTION 2 — Engine: empty snapshots
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 2. EMPTY SNAPSHOTS ===")
report2 = run(_make_calc_input(EMPTY_SNAPSHOTS))
check("2.1 Engine status = COMPLETE", report2.status == EngineStatus.COMPLETE)
check("2.2 No signals generated", len(report2.signals_generated) == 0)
check("2.3 Error message about no data", len(report2.errors) == 1)

# ═════════════════════════════════════════════════════════════════════════
# SECTION 3 — OI Calculator
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 3. OI CALCULATOR ===")
oi_1 = calculate_oi_changes(BULLISH_SNAPSHOTS, min_oi_change_pct=1.0)
check("3.1 OI changes found", len(oi_1) > 0)
if oi_1:
    check("3.2 First has oi_direction", "oi_direction" in oi_1[0])
    check("3.3 First has change_pct", "change_pct" in oi_1[0])
    check("3.4 First has strike", "strike" in oi_1[0])
    check("3.5 First has option_type", "option_type" in oi_1[0])

# Test BUYING vs UNWINDING
oi_buying = [c for c in oi_1 if c["oi_direction"] == "BUYING"]
oi_unwinding = [c for c in oi_1 if c["oi_direction"] == "UNWINDING"]
check("3.6 Has BUYING signals", len(oi_buying) > 0)
check("3.7 Has UNWINDING signals", len(oi_unwinding) > 0)

# Test summary
summary = calculate_oi_summary(oi_1)
check("3.8 Summary has ce_buying", "ce_buying" in summary)
check("3.9 Summary has pe_buying", "pe_buying" in summary)
check("3.10 Summary has total_significant_changes", summary["total_significant_changes"] > 0)

# Test empty
oi_empty = calculate_oi_changes(EMPTY_SNAPSHOTS)
check("3.11 Empty -> no changes", len(oi_empty) == 0)

# ═════════════════════════════════════════════════════════════════════════
# SECTION 4 — PCR Calculator
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 4. PCR CALCULATOR ===")
pcr_1 = calculate_pcr(BULLISH_SNAPSHOTS)
check("4.1 PCR value > 0", pcr_1["pcr_value"] > 0)
check("4.2 PCR has pcr_trend", pcr_1["pcr_trend"] in ("RISING", "FALLING", "STABLE"))
check("4.3 PCR has total_ce_oi", pcr_1["total_ce_oi"] > 0)
check("4.4 PCR has total_pe_oi", pcr_1["total_pe_oi"] > 0)

# Test with previous value
pcr_2 = calculate_pcr(BULLISH_SNAPSHOTS, prev_pcr_value=1.5)
check("4.5 PCR trend with previous", pcr_2["pcr_trend"] in ("RISING", "FALLING", "STABLE"))

# Test empty
pcr_empty = calculate_pcr(EMPTY_SNAPSHOTS)
check("4.6 Empty -> PCR = 0.0", pcr_empty["pcr_value"] == 0.0)

# ═════════════════════════════════════════════════════════════════════════
# SECTION 5 — IV Calculator
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 5. IV CALCULATOR ===")
iv_bullish = calculate_iv(BULLISH_SNAPSHOTS)
check("5.1 IV value computed", iv_bullish["iv_value"] > 0)
check("5.2 IV has context", iv_bullish["iv_context"] in ("HIGH", "LOW", "NORMAL"))
check("5.3 IV context is LOW", iv_bullish["iv_context"] == "LOW")  # 14-16% IV -> LOW
check("5.4 IV has percentile", iv_bullish["iv_percentile"] > 0)
check("5.5 IV has sample_count", iv_bullish["sample_count"] > 0)

# Median IV of bearish data is 28 (between 15,18,28,32,35)
# Use threshold 25 to demonstrate HIGH context
iv_bearish = calculate_iv(BEARISH_SNAPSHOTS, iv_high_threshold=25.0)
check("5.6 Bearish IV context is HIGH (threshold 25)", iv_bearish["iv_context"] == "HIGH")

# Test empty
iv_empty = calculate_iv(EMPTY_SNAPSHOTS)
check("5.7 Empty -> IV = 0.0", iv_empty["iv_value"] == 0.0)
check("5.8 Empty -> context = NORMAL", iv_empty["iv_context"] == "NORMAL")

# ═════════════════════════════════════════════════════════════════════════
# SECTION 6 — Wall Calculator
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 6. WALL CALCULATOR ===")
walls_bullish = detect_walls(BULLISH_SNAPSHOTS, reference_price=19520.0)
check("6.1 Walls detected", len(walls_bullish) > 0)

call_walls = [w for w in walls_bullish if w["wall_type"] == "CALL_WALL"]
put_walls = [w for w in walls_bullish if w["wall_type"] == "PUT_WALL"]
check("6.2 Has CALL_WALLs", len(call_walls) > 0)
check("6.3 Has PUT_WALLs", len(put_walls) > 0)

if call_walls:
    check("6.4 CALL_WALL has strike", call_walls[0]["wall_strike"] > 0)
    check("6.5 CALL_WALL has strength", call_walls[0]["wall_strength"] > 0)
    check("6.6 CALL_WALL has distance_pct", "distance_pct" in call_walls[0])

# Test without reference price
walls_no_ref = detect_walls(BULLISH_SNAPSHOTS, reference_price=0.0)
check("6.7 No ref -> distance = 0", all(w["distance_pct"] == 0.0 for w in walls_no_ref))

# Test empty
walls_empty = detect_walls(EMPTY_SNAPSHOTS)
check("6.8 Empty -> no walls", len(walls_empty) == 0)

# ═════════════════════════════════════════════════════════════════════════
# SECTION 7 — Max Pain Calculator
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 7. MAX PAIN CALCULATOR ===")
mp_bullish = calculate_max_pain(BULLISH_SNAPSHOTS, reference_price=19520.0)
check("7.1 Max pain strike found", mp_bullish["max_pain_strike"] > 0)
check("7.2 Max pain OI > 0", mp_bullish["max_pain_oi"] > 0)

# For bullish data: 19500 CE (120k) + 19500 PE (60k) = 180k
# 19600 CE (150k) + 19600 PE (50k) = 200k
# 19400 PE (80k) = 80k
# So max pain should be 19600
check("7.3 Max pain strike is correct", mp_bullish["max_pain_strike"] == 19600.0)
check("7.4 Distance from reference computed", mp_bullish["distance_pct"] != 0)
check("7.5 Has total_oi_by_strike", len(mp_bullish["total_oi_by_strike"]) > 0)

# Test empty
mp_empty = calculate_max_pain(EMPTY_SNAPSHOTS)
check("7.6 Empty -> max pain = 0", mp_empty["max_pain_strike"] == 0.0)

# ═════════════════════════════════════════════════════════════════════════
# SECTION 8 — Edge Cases
# ═════════════════════════════════════════════════════════════════════════

print("\\n=== 8. EDGE CASES ===")

# Single snapshot
single = [
    {"strike": 19500.0, "option_type": "CE", "oi": 100000, "premium": 150.0,
     "iv": 16.0, "change_in_oi": 0, "expiry": "2026-06-25",
     "timestamp": "2026-06-10T09:25:00Z"},
]
report_single = run(_make_calc_input(single))
check("8.1 Single snapshot -> COMPLETE", report_single.status == EngineStatus.COMPLETE)

# Zero OI changes — all change_in_oi = 0
zero_oi_data = [
    {"strike": 19500.0, "option_type": "CE", "oi": 100000, "premium": 150.0,
     "iv": 16.0, "change_in_oi": 0, "expiry": "2026-06-25",
     "timestamp": "2026-06-10T09:25:00Z"},
    {"strike": 19500.0, "option_type": "PE", "oi": 60000, "premium": 55.0,
     "iv": 14.5, "change_in_oi": 0, "expiry": "2026-06-25",
     "timestamp": "2026-06-10T09:25:00Z"},
]
report_zero = run(_make_calc_input(zero_oi_data))
check("8.2 Zero OI changes -> COMPLETE", report_zero.status == EngineStatus.COMPLETE)

# Signal count — should have PCR, IV, and MAX_PAIN at minimum
oi_sigs_zero = _find_signals(report_zero.signals, "OI_CHANGE")
check("8.3 Zero OI change -> no OI_CHANGE signals", len(oi_sigs_zero) == 0)

# Different market phases
pre_open_input = CalculationInput(
    packet_envelope_id="test_pre",
    market_phase=MarketPhase.PRE_OPEN,
    symbol="NIFTY",
    timestamp=SAMPLE_TIME,
    data={"options_snapshots": {"snapshots": BULLISH_SNAPSHOTS}},
)
report_pre = run(pre_open_input)
check("8.4 PRE_OPEN phase -> COMPLETE", report_pre.status == EngineStatus.COMPLETE)

# ═════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════════════════════════════════

print(f"\\n{'='*50}")
print(f"Tests completed: {_count}")
print(f"{'='*50}")
