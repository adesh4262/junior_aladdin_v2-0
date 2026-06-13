"""Floor 3 — Macro (Calendar State) Engine Test Suite.

Covers Macro domain: calendar state engine with EVENT_CALENDAR
and MACRO_CONTEXT signals.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    CalculationInput,
    EngineRunReport,
    EngineStatus,
    MarketPhase,
)
from junior_aladdin.shared.trading_calendar import (
    get_market_session,
    MarketSession,
    SessionState,
    IST,
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


def make_calc_input(dt: datetime | None = None) -> CalculationInput:
    return CalculationInput(
        packet_envelope_id="test_macro",
        market_phase=MarketPhase.OPEN,
        symbol="NIFTY",
        timestamp=dt or datetime.now(IST),
        data={},
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: CALENDAR STATE ENGINE
# ═══════════════════════════════════════════════════════════════════════════


def test_calendar_engine() -> None:
    print("\n--- Section 1: Calendar Engine ---")

    from junior_aladdin.floor_3_calculations.macro.calendar_state_engine import (
        run as calendar_run,
    )

    # 1.1: Normal input -> COMPLETE, 2 signals
    input_ = make_calc_input()
    report = calendar_run(input_)
    check("MACRO: normal -> COMPLETE", report.status == EngineStatus.COMPLETE,
          str(report.status.value))
    check("MACRO: 2 signals generated", len(report.signals) == 2,
          str(len(report.signals)))

    # 1.2: EVENT_CALENDAR signal
    ec_sigs = [s for s in report.signals if s.indicator_type == "EVENT_CALENDAR"]
    check("MACRO: EVENT_CALENDAR present", len(ec_sigs) == 1)
    if ec_sigs:
        ec = ec_sigs[0]
        check("MACRO: EC has session_state",
              "session_state" in ec.value)
        check("MACRO: EC has is_market_open",
              "is_market_open" in ec.value)
        check("MACRO: EC has is_expiry_today",
              "is_expiry_today" in ec.value)
        check("MACRO: EC has events_today",
              "events_today" in ec.value)
        check("MACRO: EC has next_event",
              "next_event" in ec.value)
        check("MACRO: EC has days_until_event",
              "days_until_event" in ec.value)

    # 1.3: MACRO_CONTEXT signal
    ctx_sigs = [s for s in report.signals if s.indicator_type == "MACRO_CONTEXT"]
    check("MACRO: MACRO_CONTEXT present", len(ctx_sigs) == 1)
    if ctx_sigs:
        ctx = ctx_sigs[0]
        check("MACRO: CTX has context_summary",
              "context_summary" in ctx.value)
        check("MACRO: CTX has macro_bias",
              ctx.value["macro_bias"] in ("neutral", "bullish", "bearish"))
        check("MACRO: CTX has caution_level",
              0.0 <= ctx.value["caution_level"] <= 1.0)
        check("MACRO: CTX has event_risk_flag",
              isinstance(ctx.value["event_risk_flag"], bool))

    # 1.4: Domain = MACRO
    for sig in report.signals:
        check(f"MACRO: {sig.indicator_type} domain=MACRO",
              sig.domain == CalculationDomain.MACRO,
              f"got {sig.domain.value}")

    # 1.5: Signal IDs unique
    ids = [s.signal_id for s in report.signals]
    check("MACRO: unique signal IDs", len(ids) == len(set(ids)))

    # 1.6: Signal IDs are 32 hex chars
    for sig in report.signals:
        check(f"MACRO: {sig.indicator_type} signal_id=32",
              len(sig.signal_id) == 32)

    # 1.7: Metadata present
    for sig in report.signals:
        check(f"MACRO: {sig.indicator_type} has log",
              sig.calculation_log is not None)
        check(f"MACRO: {sig.indicator_type} has input_hash",
              bool(sig.calculation_log.input_hash) if sig.calculation_log else False)
        check(f"MACRO: {sig.indicator_type} has metadata.symbol",
              sig.metadata.get("symbol") == "NIFTY")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: CALENDAR STATE VARIATIONS
# ═══════════════════════════════════════════════════════════════════════════


def test_calendar_variations() -> None:
    print("\n--- Section 2: Calendar Variations ---")

    from junior_aladdin.floor_3_calculations.macro.calendar_state_engine import (
        run as calendar_run,
    )

    # 2.1: Market hours (OPEN session)
    open_dt = datetime(2026, 6, 9, 10, 0, tzinfo=IST)  # Tuesday 10:00 IST
    open_input = make_calc_input(dt=open_dt)
    open_report = calendar_run(open_input)
    open_ec = [s for s in open_report.signals if s.indicator_type == "EVENT_CALENDAR"]
    if open_ec:
        check("MACRO: open hours -> market_open",
              open_ec[0].value.get("is_market_open", False) or
              open_ec[0].value.get("session_state") in ("PRE_OPEN", "OPEN"),
              f"state={open_ec[0].value.get('session_state')}")

    # 2.2: Engine report properties
    check("MACRO: engine_name=calendar_state_engine",
          open_report.engine_name == "calendar_state_engine")
    check("MACRO: domain=MACRO",
          open_report.domain == CalculationDomain.MACRO)
    check("MACRO: duration >= 0", open_report.duration_ms >= 0)

    # 2.3: No errors
    check("MACRO: no errors", len(open_report.errors) == 0)

    # 2.4: MACRO_CONTEXT caution_level for non-event day
    ctx_sigs = [s for s in open_report.signals if s.indicator_type == "MACRO_CONTEXT"]
    if ctx_sigs:
        check("MACRO: normal day -> caution <= 0.25",
              ctx_sigs[0].value["caution_level"] <= 0.25)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: MARKET SESSION UTILITIES
# ═══════════════════════════════════════════════════════════════════════════


def test_market_session() -> None:
    print("\n--- Section 3: Market Session ---")

    # 3.1: get_market_session returns MarketSession
    dt = datetime.now(IST)
    session = get_market_session(dt)
    check("SESSION: returns MarketSession", isinstance(session, MarketSession))
    check("SESSION: has session_state",
          hasattr(session, "session_state"))
    check("SESSION: has is_market_open",
          hasattr(session, "is_market_open"))
    check("SESSION: has is_holiday_today",
          hasattr(session, "is_holiday_today"))
    check("SESSION: has is_expiry_today",
          hasattr(session, "is_expiry_today"))
    check("SESSION: has events_today",
          hasattr(session, "events_today"))
    check("SESSION: has next_event",
          hasattr(session, "next_event"))

    # 3.2: Session state is valid
    check("SESSION: valid state",
          isinstance(session.session_state, SessionState))

    # 3.3: IST timezone offset
    check("IST offset", str(IST) in ("UTC+05:30", "+05:30", "IST", "UTC+5:30") or
          IST.utcoffset(datetime.now()).total_seconds() == 19800)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    global passed, failed

    print("=" * 60)
    print("FLOOR 3 — MACRO ENGINE TEST SUITE")
    print("=" * 60)

    test_calendar_engine()
    test_calendar_variations()
    test_market_session()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    if failed == 0:
        print("ALL MACRO TESTS PASSED!")
    else:
        print("SOME TESTS FAILED — check logs above")
    print(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
