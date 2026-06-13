"""Floor 3 — Options Engine Test Suite.

Covers Options domain: OI changes, PCR, IV, Walls, Max Pain.
Follows same pattern as test_comprehensive.py.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculationDomain,
    CalculationInput,
    EngineStatus,
    MarketPhase,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
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

UTC = timezone.utc
passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)


def make_snapshot(
    strike: float = 19500.0,
    option_type: str = "CE",
    oi: int = 100000,
    change_in_oi: int = 5000,
    premium: float = 185.0,
    iv: float = 18.5,
) -> dict[str, Any]:
    return {
        "strike": strike,
        "option_type": option_type,
        "oi": oi,
        "change_in_oi": change_in_oi,
        "premium": premium,
        "iv": iv,
        "timestamp": datetime.now(UTC),
        "expiry": "2026-06-25",
    }


def make_snapshots() -> list[dict[str, Any]]:
    """Build realistic options snapshot data."""
    return [
        # CE strikes (change_in_oi must be >5% of oi to pass threshold)
        make_snapshot(19400, "CE", 150000, 30000, 250.0, 20.0),
        make_snapshot(19500, "CE", 200000, -25000, 185.0, 18.5),
        make_snapshot(19600, "CE", 120000, 18000, 140.0, 16.0),
        make_snapshot(19700, "CE", 80000, 12000, 100.0, 15.0),
        # PE strikes
        make_snapshot(19300, "PE", 180000, 45000, 210.0, 22.0),
        make_snapshot(19400, "PE", 220000, -35000, 180.0, 20.5),
        make_snapshot(19500, "PE", 160000, 30000, 160.0, 19.0),
        make_snapshot(19600, "PE", 90000, 15000, 130.0, 17.5),
    ]


def make_calc_input(snapshots: list | None = None) -> CalculationInput:
    return CalculationInput(
        packet_envelope_id="test_options",
        market_phase=MarketPhase.OPEN,
        symbol="NIFTY",
        timestamp=datetime.now(UTC),
        data={"options_snapshots": {"snapshots": snapshots if snapshots is not None else make_snapshots(), "reference_price": 19520.0}},
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: OI CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════


def test_oi_calculator() -> None:
    print("\n--- Section 1: OI Calculator ---")

    snapshots = make_snapshots()

    # 1.1: OI changes detected
    changes = calculate_oi_changes(snapshots, min_oi_change_pct=5.0)
    check("OI: changes detected", len(changes) > 0, str(len(changes)))

    # 1.2: Each change has required fields
    for c in changes:
        check(f"OI: strike={c['strike']} has oi_direction",
              c["oi_direction"] in ("BUYING", "UNWINDING"))
        check(f"OI: strike={c['strike']} has change_pct",
              isinstance(c["change_pct"], (int, float)))
        check(f"OI: strike={c['strike']} has strike",
              isinstance(c["strike"], (int, float)))
        check(f"OI: strike={c['strike']} has option_type",
              c["option_type"] in ("CE", "PE"))

    # 1.3: Negative change_in_oi = UNWINDING
    unwinding = [c for c in changes if c["oi_direction"] == "UNWINDING"]
    check("OI: UNWINDING detected", len(unwinding) > 0, str(len(unwinding)))

    # 1.4: Positive change_in_oi = BUYING
    buying = [c for c in changes if c["oi_direction"] == "BUYING"]
    check("OI: BUYING detected", len(buying) > 0, str(len(buying)))

    # 1.5: Sorted by |change_pct| descending
    if len(changes) >= 2:
        check("OI: sorted descending",
              abs(changes[0]["change_pct"]) >= abs(changes[-1]["change_pct"]))

    # 1.6: Empty snapshots -> empty list
    empty = calculate_oi_changes([])
    check("OI: empty -> []", len(empty) == 0)

    # 1.7: High threshold filters more aggressively
    filtered = calculate_oi_changes(snapshots, min_oi_change_pct=50.0)
    check("OI: high threshold filters", len(filtered) <= len(changes))

    # 1.8: OI with zero -> skipped
    zero_oi_snap = [make_snapshot(19800, "CE", 0, 0, 50.0, 15.0)]
    zero_result = calculate_oi_changes(zero_oi_snap)
    check("OI: zero OI skipped", len(zero_result) == 0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: OI SUMMARY
# ═══════════════════════════════════════════════════════════════════════════


def test_oi_summary() -> None:
    print("\n--- Section 2: OI Summary ---")

    snapshots = make_snapshots()
    changes = calculate_oi_changes(snapshots)
    summary = calculate_oi_summary(changes)

    # 2.1: Summary has all fields
    check("OI-SUM: has ce_buying", "ce_buying" in summary)
    check("OI-SUM: has ce_unwinding", "ce_unwinding" in summary)
    check("OI-SUM: has pe_buying", "pe_buying" in summary)
    check("OI-SUM: has pe_unwinding", "pe_unwinding" in summary)
    check("OI-SUM: has total", "total_significant_changes" in summary)

    # 2.2: Counts are non-negative
    for key in ("ce_buying", "ce_unwinding", "pe_buying", "pe_unwinding"):
        check(f"OI-SUM: {key} >= 0", summary[key] >= 0)

    # 2.3: Total matches sum
    check("OI-SUM: total matches",
          summary["total_significant_changes"] == (
              summary["ce_buying"] + summary["ce_unwinding"] +
              summary["pe_buying"] + summary["pe_unwinding"]
          ))

    # 2.4: Empty changes
    empty_summary = calculate_oi_summary([])
    check("OI-SUM: empty -> zeros",
          empty_summary["total_significant_changes"] == 0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: PCR CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════


def test_pcr_calculator() -> None:
    print("\n--- Section 3: PCR Calculator ---")

    snapshots = make_snapshots()

    # 3.1: PCR computed
    result = calculate_pcr(snapshots)
    check("PCR: value computed", result["pcr_value"] > 0)
    check("PCR: total_ce_oi > 0", result["total_ce_oi"] > 0)
    check("PCR: total_pe_oi > 0", result["total_pe_oi"] > 0)
    check("PCR: trend STABLE (no prev)", result["pcr_trend"] == "STABLE")

    # 3.2: PCR value = PE OI / CE OI
    expected_pcr = result["total_pe_oi"] / result["total_ce_oi"]
    check("PCR: formula correct",
          abs(result["pcr_value"] - expected_pcr) < 0.01)

    # 3.3: Rising trend
    rising_result = calculate_pcr(snapshots, prev_pcr_value=0.5)
    check("PCR: RISING trend", rising_result["pcr_trend"] == "RISING",
          rising_result["pcr_trend"])

    # 3.4: Falling trend
    falling_result = calculate_pcr(snapshots, prev_pcr_value=2.0)
    check("PCR: FALLING trend", falling_result["pcr_trend"] == "FALLING")

    # 3.5: No CE OI -> PCR = 0
    no_ce = [make_snapshot(19500, "PE", 100000, 0, 150.0, 20.0)]
    no_ce_result = calculate_pcr(no_ce)
    check("PCR: no CE -> 0", no_ce_result["pcr_value"] == 0.0)

    # 3.6: Empty snapshots
    empty_result = calculate_pcr([])
    check("PCR: empty -> 0", empty_result["pcr_value"] == 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: IV CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════


def test_iv_calculator() -> None:
    print("\n--- Section 4: IV Calculator ---")

    snapshots = make_snapshots()

    # 4.1: IV computed
    result = calculate_iv(snapshots)
    check("IV: value computed", result["iv_value"] > 0)
    check("IV: percentile computed", result["iv_percentile"] > 0)
    check("IV: context set", result["iv_context"] in ("HIGH", "LOW", "NORMAL"))
    check("IV: sample_count > 0", result["sample_count"] > 0)

    # 4.2: HIGH IV
    high_iv_snaps = [make_snapshot(19500, "CE", 100000, 0, 185.0, 35.0)]
    high_result = calculate_iv(high_iv_snaps, iv_high_threshold=30.0)
    check("IV: HIGH context", high_result["iv_context"] == "HIGH")

    # 4.3: LOW IV
    low_iv_snaps = [make_snapshot(19500, "CE", 100000, 0, 185.0, 10.0)]
    low_result = calculate_iv(low_iv_snaps, iv_low_threshold=15.0)
    check("IV: LOW context", low_result["iv_context"] == "LOW")

    # 4.4: NORMAL IV
    normal_iv_snaps = [make_snapshot(19500, "CE", 100000, 0, 185.0, 20.0)]
    normal_result = calculate_iv(normal_iv_snaps, iv_low_threshold=15.0, iv_high_threshold=30.0)
    check("IV: NORMAL context", normal_result["iv_context"] == "NORMAL")

    # 4.5: Empty IV values
    no_iv_snaps = [{"strike": 19500, "option_type": "CE", "oi": 100000, "premium": 185.0}]
    no_iv_result = calculate_iv(no_iv_snaps)
    check("IV: no iv field -> 0 samples", no_iv_result["sample_count"] == 0)
    check("IV: no iv -> NORMAL context", no_iv_result["iv_context"] == "NORMAL")

    # 4.6: Custom thresholds
    custom_result = calculate_iv(snapshots, iv_high_threshold=25.0, iv_low_threshold=10.0)
    check("IV: custom thresholds", custom_result["iv_value"] > 0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: WALL CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════


def test_wall_calculator() -> None:
    print("\n--- Section 5: Wall Calculator ---")

    snapshots = make_snapshots()

    # 5.1: Walls detected
    walls = detect_walls(snapshots, reference_price=19520.0)
    check("WALL: walls detected", len(walls) > 0, str(len(walls)))

    # 5.2: CALL_WALL and PUT_WALL present
    call_walls = [w for w in walls if w["wall_type"] == "CALL_WALL"]
    put_walls = [w for w in walls if w["wall_type"] == "PUT_WALL"]
    check("WALL: CALL_WALL found", len(call_walls) > 0)
    check("WALL: PUT_WALL found", len(put_walls) > 0)

    # 5.3: Each wall has required fields
    for w in walls:
        check(f"WALL: {w['wall_type']} has strike", "wall_strike" in w)
        check(f"WALL: {w['wall_type']} has strength", w["wall_strength"] > 0)
        check(f"WALL: {w['wall_type']} has distance_pct",
              "distance_pct" in w)

    # 5.4: Default top_n=3
    check("WALL: max 3 CE walls", len(call_walls) <= 3)
    check("WALL: max 3 PE walls", len(put_walls) <= 3)

    # 5.5: top_n parameter
    walls_top1 = detect_walls(snapshots, reference_price=19520.0, top_n=1)
    call_1 = [w for w in walls_top1 if w["wall_type"] == "CALL_WALL"]
    put_1 = [w for w in walls_top1 if w["wall_type"] == "PUT_WALL"]
    check("WALL: top_n=1 -> 1 each", len(call_1) == 1 and len(put_1) == 1)

    # 5.6: Sorted by strength descending
    if len(walls) >= 2:
        check("WALL: sorted descending",
              walls[0]["wall_strength"] >= walls[-1]["wall_strength"])

    # 5.7: Empty snapshots
    empty_walls = detect_walls([])
    check("WALL: empty -> []", len(empty_walls) == 0)

    # 5.8: No reference price -> distance_pct=0
    walls_no_ref = detect_walls(snapshots, reference_price=0.0)
    if walls_no_ref:
        check("WALL: no ref -> distance=0",
              walls_no_ref[0]["distance_pct"] == 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: MAX PAIN CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════


def test_max_pain_calculator() -> None:
    print("\n--- Section 6: Max Pain Calculator ---")

    snapshots = make_snapshots()

    # 6.1: Max pain computed
    result = calculate_max_pain(snapshots, reference_price=19520.0)
    check("MP: max_pain_strike > 0", result["max_pain_strike"] > 0)
    check("MP: max_pain_oi > 0", result["max_pain_oi"] > 0)
    check("MP: distance computed", isinstance(result["distance_pct"], float))

    # 6.2: total_oi_by_strike has all strikes
    check("MP: total_oi_by_strike present",
          len(result["total_oi_by_strike"]) > 0)

    # 6.3: Max pain is the highest OI strike
    max_strike = result["max_pain_strike"]
    max_oi = result["max_pain_oi"]
    all_oi = result["total_oi_by_strike"]
    check("MP: is highest OI",
          all(all_oi[s] <= max_oi for s in all_oi))

    # 6.4: Empty snapshots
    empty_result = calculate_max_pain([])
    check("MP: empty -> 0 strike", empty_result["max_pain_strike"] == 0.0)

    # 6.5: No reference price -> distance=0
    no_ref_result = calculate_max_pain(snapshots, reference_price=0.0)
    check("MP: no ref -> distance=0", no_ref_result["distance_pct"] == 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: OPTIONS ENGINE (Full Engine Run)
# ═══════════════════════════════════════════════════════════════════════════


def test_options_engine() -> None:
    print("\n--- Section 7: Options Engine (Full) ---")

    from junior_aladdin.floor_3_calculations.options.options_engine import (
        run as options_run,
    )

    # 7.1: Empty snapshots -> COMPLETE with error
    empty_input = make_calc_input(snapshots=[])
    report = options_run(empty_input)
    check("OPT: empty -> COMPLETE", report.status == EngineStatus.COMPLETE)
    check("OPT: empty -> error msg",
          any("No options snapshot data" in e for e in report.errors))

    # 7.2: Normal snapshots -> signals generated
    snapshots = make_snapshots()
    input_ = make_calc_input(snapshots=snapshots)
    report2 = options_run(input_)
    check("OPT: normal -> COMPLETE", report2.status == EngineStatus.COMPLETE,
          str(report2.status.value))
    check("OPT: signals generated", len(report2.signals) > 0,
          str(len(report2.signals)))

    # 7.3: OI_CHANGE signal present
    oi_sigs = [s for s in report2.signals if s.indicator_type == "OI_CHANGE"]
    check("OPT: OI_CHANGE signals", len(oi_sigs) > 0, str(len(oi_sigs)))

    # 7.4: OI_SUMMARY signal present
    sum_sigs = [s for s in report2.signals if s.indicator_type == "OI_SUMMARY"]
    check("OPT: OI_SUMMARY signal", len(sum_sigs) >= 1, str(len(sum_sigs)))

    # 7.5: PCR signal present
    pcr_sigs = [s for s in report2.signals if s.indicator_type == "PCR"]
    check("OPT: PCR signal", len(pcr_sigs) >= 1, str(len(pcr_sigs)))

    # 7.6: IV signal present
    iv_sigs = [s for s in report2.signals if s.indicator_type == "IV"]
    check("OPT: IV signal", len(iv_sigs) >= 1)

    # 7.7: Walls present
    wall_sigs = [s for s in report2.signals
                 if s.indicator_type in ("CALL_WALL", "PUT_WALL")]
    check("OPT: Wall signals", len(wall_sigs) > 0, str(len(wall_sigs)))

    # 7.8: MAX_PAIN signal present
    mp_sigs = [s for s in report2.signals if s.indicator_type == "MAX_PAIN"]
    check("OPT: MAX_PAIN signal", len(mp_sigs) >= 1)

    # 7.9: All signals have proper metadata
    for sig in report2.signals:
        check(f"OPT: {sig.indicator_type} domain=OPTIONS",
              sig.domain == CalculationDomain.OPTIONS)
        check(f"OPT: {sig.indicator_type} has log",
              sig.calculation_log is not None)
        check(f"OPT: {sig.indicator_type} has metadata.symbol",
              sig.metadata.get("symbol") == "NIFTY")
        check(f"OPT: {sig.indicator_type} has input_hash",
              bool(sig.calculation_log.input_hash) if sig.calculation_log else False)

    # 7.10: Signal IDs unique
    ids = [s.signal_id for s in report2.signals]
    check("OPT: unique signal IDs", len(ids) == len(set(ids)))

    # 7.11: All signal IDs are 32 hex chars
    for sig in report2.signals:
        check(f"OPT: {sig.indicator_type} signal_id=32",
              len(sig.signal_id) == 32)

    # 7.12: With custom config
    cfg = F3Config()
    cfg.options.min_oi_change_pct = 10.0
    report3 = options_run(input_, config=cfg)
    check("OPT: custom config works", report3.status == EngineStatus.COMPLETE)

    # 7.13: Engine report properties
    check("OPT: report has engine_name",
          report2.engine_name == "options_engine")
    check("OPT: report has duration", report2.duration_ms >= 0)
    check("OPT: report no errors", len(report2.errors) == 0)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    global passed, failed

    print("=" * 60)
    print("FLOOR 3 — OPTIONS ENGINE TEST SUITE")
    print("=" * 60)

    test_oi_calculator()
    test_oi_summary()
    test_pcr_calculator()
    test_iv_calculator()
    test_wall_calculator()
    test_max_pain_calculator()
    test_options_engine()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    if failed == 0:
        print("ALL OPTIONS TESTS PASSED!")
    else:
        print("SOME TESTS FAILED — check logs above")
    print(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
