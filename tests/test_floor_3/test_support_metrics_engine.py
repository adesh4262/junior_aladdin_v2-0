"""Floor 3 — Support Metrics (Psychology) Engine Test Suite.

Covers Support Metrics domain: trap detection, loss reporting,
cooldown status, overtrade detection.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculationDomain,
    CalculationInput,
    EngineRunReport,
    EngineStatus,
    MarketPhase,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.support_metrics.trap_metrics_engine import (
    detect_trap_pressure,
)
from junior_aladdin.floor_3_calculations.support_metrics.loss_metrics_engine import (
    compute_loss_report,
)
from junior_aladdin.floor_3_calculations.support_metrics.cooldown_metrics_engine import (
    compute_cooldown_status,
)
from junior_aladdin.floor_3_calculations.support_metrics.overtrade_metrics_engine import (
    detect_overtrade,
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


def make_calc_input(**overrides) -> CalculationInput:
    data = {
        "mistake_history": [],
        "recent_trades": [],
        "loss_count": 0,
        "sequence_length": 0,
        "same_zone_failures": 0,
        "cooldown_remaining_s": 0.0,
        "trade_count_today": 0,
    }
    data.update(overrides)
    return CalculationInput(
        packet_envelope_id="test_support",
        market_phase=MarketPhase.OPEN,
        symbol="NIFTY",
        timestamp=datetime.now(UTC),
        data=data,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: TRAP METRICS
# ═══════════════════════════════════════════════════════════════════════════


def test_trap_metrics() -> None:
    print("\n--- Section 1: Trap Metrics ---")

    # 1.1: No mistakes -> no trap
    result = detect_trap_pressure(mistake_history=None, same_zone_failures=0, total_mistakes=0)
    check("TRAP: no mistakes -> no pressure", not result["trap_pressure"])
    check("TRAP: no mistakes -> density 0", result["trap_density"] == 0.0)

    # 1.2: Same-zone failures -> trap pressure
    result2 = detect_trap_pressure(mistake_history=None, same_zone_failures=5, total_mistakes=6)
    check("TRAP: high same-zone -> pressure", result2["trap_pressure"],
          f"density={result2['trap_density']}")
    check("TRAP: trap_count matches", result2["trap_count"] == 5)

    # 1.3: Low same-zone -> no trap
    result3 = detect_trap_pressure(mistake_history=None, same_zone_failures=1, total_mistakes=10)
    check("TRAP: low same-zone -> no pressure", not result3["trap_pressure"])

    # 1.4: Mistake history analysis
    mistakes = [
        {"zone_id": "z1", "is_same_zone": True, "timestamp": "10:00"},
        {"zone_id": "z1", "is_same_zone": True, "timestamp": "10:05"},
        {"zone_id": "z2", "is_same_zone": False, "timestamp": "10:10"},
        {"zone_id": "z1", "is_same_zone": True, "timestamp": "10:15"},
        {"zone_id": "z1", "is_same_zone": True, "timestamp": "10:20"},
    ]
    result4 = detect_trap_pressure(mistake_history=mistakes)
    check("TRAP: history analysis", result4["trap_pressure"])

    # 1.5: Return dict has all keys
    for key in ("trap_pressure", "trap_density", "trap_count", "same_zone_failures"):
        check(f"TRAP: has {key}", key in result)

    # 1.6: Edge case — zero total mistakes
    result6 = detect_trap_pressure(mistake_history=[], same_zone_failures=0, total_mistakes=0)
    check("TRAP: zero total -> density 0", result6["trap_density"] == 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: LOSS METRICS
# ═══════════════════════════════════════════════════════════════════════════


def test_loss_metrics() -> None:
    print("\n--- Section 2: Loss Metrics ---")

    # 2.1: No losses
    result = compute_loss_report(recent_trades=None, loss_count=0, sequence_length=0)
    check("LOSS: no losses -> count 0", result["loss_count"] == 0)
    check("LOSS: no losses -> no streak", not result["has_loss_streak"])

    # 2.2: Loss streak detected
    result2 = compute_loss_report(recent_trades=None, loss_count=5, sequence_length=3)
    check("LOSS: streak detected", result2["has_loss_streak"])
    check("LOSS: sequence=3", result2["sequence_length"] == 3)

    # 2.3: Short streak -> no alert
    result3 = compute_loss_report(recent_trades=None, loss_count=2, sequence_length=1)
    check("LOSS: short streak -> no alert", not result3["has_loss_streak"])

    # 2.4: Trade history analysis
    trades = [
        {"outcome": "WIN", "timestamp": "10:00"},
        {"outcome": "LOSS", "timestamp": "10:05"},
        {"outcome": "LOSS", "timestamp": "10:10"},
        {"outcome": "LOSS", "timestamp": "10:15"},
        {"outcome": "LOSS", "timestamp": "10:20"},
    ]
    result4 = compute_loss_report(recent_trades=trades)
    check("LOSS: history analysis", result4["has_loss_streak"])
    check("LOSS: history sequence=4", result4["sequence_length"] == 4,
          str(result4["sequence_length"]))

    # 2.5: Mixed wins/losses
    mixed_trades = [
        {"outcome": "WIN", "timestamp": "10:00"},
        {"outcome": "LOSS", "timestamp": "10:05"},
        {"outcome": "WIN", "timestamp": "10:10"},
        {"outcome": "LOSS", "timestamp": "10:15"},
    ]
    result5 = compute_loss_report(recent_trades=mixed_trades)
    check("LOSS: mixed -> sequence=1", result5["sequence_length"] == 1)
    check("LOSS: mixed -> loss_count=2", result5["loss_count"] == 2)

    # 2.6: Return dict has all keys
    for key in ("loss_count", "sequence_length", "has_loss_streak", "max_sequence_length"):
        check(f"LOSS: has {key}", key in result)

    # 2.7: max_sequence_length tracks longest
    result7 = compute_loss_report(recent_trades=trades)
    check("LOSS: max_sequence >= sequence",
          result7["max_sequence_length"] >= result7["sequence_length"])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: COOLDOWN METRICS
# ═══════════════════════════════════════════════════════════════════════════


def test_cooldown_metrics() -> None:
    print("\n--- Section 3: Cooldown Metrics ---")

    # 3.1: No losses -> no cooldown
    result = compute_cooldown_status(remaining_seconds=0.0, sequence_length=0)
    check("COOL: no losses -> not active", not result["cooldown_active"])
    check("COOL: no losses -> remaining 0", result["cooldown_remaining_s"] == 0.0)

    # 3.2: 1 loss -> 120s cooldown
    result2 = compute_cooldown_status(remaining_seconds=0.0, sequence_length=1)
    check("COOL: 1 loss -> active", result2["cooldown_active"])
    check("COOL: 1 loss -> 120s", result2["cooldown_total_s"] == 120.0)

    # 3.3: 2 losses -> 300s cooldown
    result3 = compute_cooldown_status(remaining_seconds=0.0, sequence_length=2)
    check("COOL: 2 losses -> 300s", result3["cooldown_total_s"] == 300.0)

    # 3.4: 3+ losses -> 600s cooldown
    result4 = compute_cooldown_status(remaining_seconds=0.0, sequence_length=3)
    check("COOL: 3 losses -> 600s", result4["cooldown_total_s"] == 600.0)

    result5 = compute_cooldown_status(remaining_seconds=0.0, sequence_length=5)
    check("COOL: 5 losses -> 600s", result5["cooldown_total_s"] == 600.0)

    # 3.5: Remaining seconds passed through
    result6 = compute_cooldown_status(remaining_seconds=45.0, sequence_length=1)
    check("COOL: remaining preserved", result6["cooldown_remaining_s"] == 45.0)

    # 3.6: Time-based decay
    from datetime import timedelta
    past_time = datetime.now(UTC) - timedelta(seconds=60)
    result7 = compute_cooldown_status(
        remaining_seconds=0.0, sequence_length=1,
        last_loss_time=past_time, current_time=datetime.now(UTC),
    )
    check("COOL: decayed remaining", result7["cooldown_remaining_s"] <= 120.0)
    check("COOL: still active after 60s", result7["cooldown_active"])

    # 3.7: Very old loss -> cooldown expired
    old_time = datetime.now(UTC) - timedelta(seconds=500)
    result8 = compute_cooldown_status(
        remaining_seconds=0.0, sequence_length=1,
        last_loss_time=old_time, current_time=datetime.now(UTC),
    )
    check("COOL: old loss -> not active", not result8["cooldown_active"])

    # 3.8: Return dict has all keys
    for key in ("cooldown_active", "cooldown_remaining_s", "cooldown_total_s"):
        check(f"COOL: has {key}", key in result)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: OVERTRADE METRICS
# ═══════════════════════════════════════════════════════════════════════════


def test_overtrade_metrics() -> None:
    print("\n--- Section 4: Overtrade Metrics ---")

    # 4.1: No trades -> no overtrade
    result = detect_overtrade(recent_trades=None, trade_count_today=0)
    check("OVER: no trades -> not overtrading", not result["overtrade_flag"])
    check("OVER: no trades -> trades=0", result["trades_in_window"] == 0)

    # 4.2: Below threshold -> no overtrade
    result2 = detect_overtrade(recent_trades=None, trade_count_today=2)
    check("OVER: 2 trades -> not overtrading", not result2["overtrade_flag"])

    # 4.3: Above threshold -> overtrade
    result3 = detect_overtrade(recent_trades=None, trade_count_today=5)
    check("OVER: 5 trades -> overtrading", result3["overtrade_flag"])

    # 4.4: Trade history with recent timestamps
    now = datetime.now(UTC)
    recent_trades = [
        {"timestamp": now, "outcome": "WIN"},
        {"timestamp": now, "outcome": "LOSS"},
        {"timestamp": now, "outcome": "WIN"},
        {"timestamp": now, "outcome": "LOSS"},
    ]
    result4 = detect_overtrade(recent_trades=recent_trades, trade_count_today=0)
    check("OVER: history -> flag", result4["overtrade_flag"])
    check("OVER: history -> trades=4", result4["trades_in_window"] == 4)

    # 4.5: Old trades outside window
    old_time = now.replace(year=2020)
    old_trades = [
        {"timestamp": old_time, "outcome": "WIN"},
        {"timestamp": old_time, "outcome": "LOSS"},
    ]
    result5 = detect_overtrade(recent_trades=old_trades, trade_count_today=0)
    check("OVER: old trades -> 0 in window", result5["trades_in_window"] == 0)

    # 4.6: Return dict has all keys
    for key in ("overtrade_flag", "trade_frequency", "trades_in_window", "max_trades_allowed"):
        check(f"OVER: has {key}", key in result)

    # 4.7: Max trades allowed constant
    check("OVER: max_trades_allowed=3", result["max_trades_allowed"] == 3)

    # 4.8: Trade frequency computed
    check("OVER: frequency >= 0", result4["trade_frequency"] >= 0)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: SUPPORT METRICS ENGINE (Full Run)
# ═══════════════════════════════════════════════════════════════════════════


def test_support_metrics_engine() -> None:
    print("\n--- Section 5: Support Metrics (Full Engine) ---")

    from junior_aladdin.floor_3_calculations.support_metrics.support_metrics_engine import (
        run as support_run,
    )

    # 5.1: Empty data -> COMPLETE, signals generated (no errors)
    input_ = make_calc_input()
    report = support_run(input_)
    check("SM: empty data -> COMPLETE", report.status == EngineStatus.COMPLETE,
          str(report.status.value))
    check("SM: signals generated", len(report.signals) >= 4,
          str(len(report.signals)))

    # 5.2: TRAP_ALERT signal present
    trap_sigs = [s for s in report.signals if s.indicator_type == "TRAP_ALERT"]
    check("SM: TRAP_ALERT signal", len(trap_sigs) >= 1, str(len(trap_sigs)))
    if trap_sigs:
        check("SM: TRAP_ALERT has trap_pressure",
              "trap_pressure" in trap_sigs[0].value)
        check("SM: TRAP_ALERT has trap_density",
              "trap_density" in trap_sigs[0].value)

    # 5.3: LOSS_REPORT signal present
    loss_sigs = [s for s in report.signals if s.indicator_type == "LOSS_REPORT"]
    check("SM: LOSS_REPORT signal", len(loss_sigs) >= 1)
    if loss_sigs:
        check("SM: LOSS_REPORT has loss_count",
              "loss_count" in loss_sigs[0].value)

    # 5.4: COOLDOWN_STATUS signal present
    cool_sigs = [s for s in report.signals if s.indicator_type == "COOLDOWN_STATUS"]
    check("SM: COOLDOWN_STATUS signal", len(cool_sigs) >= 1)
    if cool_sigs:
        check("SM: COOLDOWN_STATUS has cooldown_active",
              "cooldown_active" in cool_sigs[0].value)

    # 5.5: DISCIPLINE_REPORT signal present
    disc_sigs = [s for s in report.signals if s.indicator_type == "DISCIPLINE_REPORT"]
    check("SM: DISCIPLINE_REPORT signal", len(disc_sigs) >= 1)
    if disc_sigs:
        check("SM: DISCIPLINE_REPORT has trade_allowed",
              "trade_allowed" in disc_sigs[0].value)

    # 5.6: All signals have proper metadata
    for sig in report.signals:
        check(f"SM: {sig.indicator_type} domain=PSYCHOLOGY",
              sig.domain == CalculationDomain.PSYCHOLOGY,
              f"got {sig.domain.value}")
        check(f"SM: {sig.indicator_type} has log",
              sig.calculation_log is not None)
        check(f"SM: {sig.indicator_type} has metadata.symbol",
              sig.metadata.get("symbol") == "NIFTY")
        if sig.calculation_log:
            check(f"SM: {sig.indicator_type} has input_hash",
                  bool(sig.calculation_log.input_hash))

    # 5.7: Signal IDs unique
    ids = [s.signal_id for s in report.signals]
    check("SM: unique signal IDs", len(ids) == len(set(ids)))

    # 5.8: With trap data
    trap_data = make_calc_input(
        mistake_history=[{"zone_id": "z1", "is_same_zone": True, "timestamp": "10:00"}],
        same_zone_failures=3,
    )
    report2 = support_run(trap_data)
    check("SM: trap data -> COMPLETE", report2.status == EngineStatus.COMPLETE)
    check("SM: trap data -> signals", len(report2.signals) >= 4)

    # 5.9: With loss streak data
    loss_data = make_calc_input(
        recent_trades=[
            {"outcome": "LOSS", "timestamp": "10:00"},
            {"outcome": "LOSS", "timestamp": "10:05"},
            {"outcome": "LOSS", "timestamp": "10:10"},
        ],
        loss_count=3,
        sequence_length=3,
    )
    report3 = support_run(loss_data)
    check("SM: loss data -> COMPLETE", report3.status == EngineStatus.COMPLETE)

    # 5.10: With cooldown + overtrade data
    stress_data = make_calc_input(
        sequence_length=3,
        cooldown_remaining_s=300.0,
        trade_count_today=5,
    )
    report4 = support_run(stress_data)
    check("SM: stress data -> COMPLETE", report4.status == EngineStatus.COMPLETE)
    check("SM: stress data -> signals", len(report4.signals) >= 4)

    # 5.11: Engine report properties
    check("SM: engine_name=support_metrics_engine",
          report.engine_name == "support_metrics_engine")
    check("SM: duration >= 0", report.duration_ms >= 0)
    check("SM: domain = PSYCHOLOGY",
          report.domain == CalculationDomain.PSYCHOLOGY)

    # 5.12: With custom config
    cfg = F3Config()
    cfg.support_metrics.trap_density_threshold = 0.2
    report5 = support_run(input_, config=cfg)
    check("SM: custom config works", report5.status == EngineStatus.COMPLETE)

    # 5.13: All signal IDs are 32 hex chars
    for sig in report.signals:
        check(f"SM: {sig.indicator_type} signal_id=32",
              len(sig.signal_id) == 32)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    global passed, failed

    print("=" * 60)
    print("FLOOR 3 — SUPPORT METRICS TEST SUITE")
    print("=" * 60)

    test_trap_metrics()
    test_loss_metrics()
    test_cooldown_metrics()
    test_overtrade_metrics()
    test_support_metrics_engine()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    if failed == 0:
        print("ALL SUPPORT METRICS TESTS PASSED!")
    else:
        print("SOME TESTS FAILED — check logs above")
    print(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
