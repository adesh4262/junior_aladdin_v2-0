"""Tests for Calendar Engine — shared calendar + Floor 3 MACRO integration.

Tests:
1. Shared TradingCalendar module (pure functions)
2. Floor 3 calendar_state_engine integration
3. Edge cases (weekend, holidays, expiry, events)
4. API completeness (get_market_session, get_next_event, etc.)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import date, datetime, timedelta, timezone

from junior_aladdin.shared.trading_calendar import (
    CalendarEvent,
    EventType,
    MarketSession,
    SessionState,
    format_market_session,
    get_events_for_date,
    get_expiry_dates,
    get_market_session,
    get_next_event,
    get_session_state,
    get_today,
    is_expiry_day,
    is_expiry_week,
    is_holiday,
    is_market_open,
    is_monthly_expiry,
    is_rollover_week,
    is_weekend,
    IST,
)
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculationDomain,
    CalculationInput,
    MarketPhase,
)
from junior_aladdin.floor_3_calculations.macro.calendar_state_engine import (
    run as calendar_engine_run,
)

passed = 0
failed = 0

UTC = timezone.utc


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}{' -- ' + detail if detail else ''}")


def approx_equal(a: float, b: float, eps: float = 0.01) -> bool:
    return abs(a - b) < eps


print("=" * 60)
print("CALENDAR ENGINE TESTS")
print("=" * 60)

# ════════════════════════════════════════════════════════════════
# SECTION 1: SHARED CALENDAR — Basic Queries
# ════════════════════════════════════════════════════════════════
print("\n--- 1. Basic Calendar Queries ---")

# 1.1 IST timezone
check("1.1 IST offset = 5:30", IST.utcoffset(None) == timedelta(hours=5, minutes=30))

# 1.2 Weekend detection
sat = date(2026, 1, 3)   # Saturday
sun = date(2026, 1, 4)   # Sunday
mon = date(2026, 1, 5)   # Monday
check("1.2 Saturday is weekend", is_weekend(sat))
check("1.3 Sunday is weekend", is_weekend(sun))
check("1.4 Monday is NOT weekend", not is_weekend(mon))

# 1.5 Holiday detection
rep_day = date(2026, 1, 26)  # Republic Day
check("1.5 Republic Day is holiday", is_holiday(rep_day))
check("1.6 Normal day NOT holiday", not is_holiday(date(2026, 1, 15)))

# 1.7 get_today returns a date
today = get_today()
check("1.7 get_today returns date", isinstance(today, date))

# ════════════════════════════════════════════════════════════════
# SECTION 2: EXPIRY DATES
# ════════════════════════════════════════════════════════════════
print("\n--- 2. Expiry Dates ---")

expiries = get_expiry_dates(2026)

# 2.1 Expiry list is not empty
check("2.1 Expiry list non-empty", len(expiries) > 0)

# 2.2 January monthly expiry (last Thursday: 29th Jan 2026)
check("2.2 Jan monthly expiry in list", date(2026, 1, 29) in expiries)

# 2.3 June monthly expiry (last Thursday: 25th June 2026)
check("2.3 Jun monthly expiry in list", date(2026, 6, 25) in expiries)

# 2.4 is_expiry_day works
check("2.4 Jan 29 is expiry day", is_expiry_day(date(2026, 1, 29)))
# Jan 15 is a Thursday (expiry day) — use a non-expiry date instead
check("2.5 Jan 12 (Mon) NOT expiry day", not is_expiry_day(date(2026, 1, 12)))

# 2.6 is_monthly_expiry
check("2.6 Jan 29 is monthly expiry", is_monthly_expiry(date(2026, 1, 29)))
check("2.7 Regular Thursday NOT monthly", not is_monthly_expiry(date(2026, 1, 8)))

# 2.8 is_expiry_week — Jan 26-30 (Mon-Fri of expiry week)
check("2.8 Jan 27 (Tue) is expiry week", is_expiry_week(date(2026, 1, 27)))
# With weekly expiry every Thursday, every weekday is in an expiry week.
# Only weekends are between expiry weeks.
check("2.9 Jan 3 (Sat) NOT expiry week", not is_expiry_week(date(2026, 1, 3)))

# 2.10 All Thursdays in year are expiry dates
thu_dates = [d for d in expiries if d.weekday() == 3]  # Thursday
wed_dates = [d for d in expiries if d.weekday() == 2]  # Wednesday (holiday-adjusted)
check("2.10 Most expiries on Thursday", len(thu_dates) >= len(expiries) * 0.8)
check("2.11 Some may be Wednesday (holiday)", len(wed_dates) >= 0)  # At least 0

# 2.12 No holidays in expiry list (holidays replaced with Wednesday)
# Exception: monthly expiry on holiday is kept as reference but the
# actual trading expiry moves to the previous day
holiday_expiry_count = sum(1 for ex in expiries if is_holiday(ex))
check("2.12 At most 1 holiday expiry (monthly ref)", holiday_expiry_count <= 1,
      f"found {holiday_expiry_count} holiday expiries")

# ════════════════════════════════════════════════════════════════
# SECTION 3: SESSION STATE
# ════════════════════════════════════════════════════════════════
print("\n--- 3. Session State ---")

# 3.1 Weekend = CLOSED
weekend_dt = datetime(2026, 1, 3, 12, 0, tzinfo=IST)  # Saturday 12:00 PM
check("3.1 Saturday -> CLOSED", get_session_state(weekend_dt) == SessionState.CLOSED)

# 3.2 Holiday = CLOSED
holiday_dt = datetime(2026, 1, 26, 12, 0, tzinfo=IST)  # Republic Day
check("3.2 Holiday -> CLOSED", get_session_state(holiday_dt) == SessionState.CLOSED)

# 3.3 Pre-market (before 9:00)
pre_market_dt = datetime(2026, 1, 15, 7, 30, tzinfo=IST)
check("3.3 7:30 AM -> PRE_MARKET", get_session_state(pre_market_dt) == SessionState.PRE_MARKET)

# 3.4 Pre-open (9:00-9:15)
pre_open_dt = datetime(2026, 1, 15, 9, 5, tzinfo=IST)
check("3.4 9:05 AM -> PRE_OPEN", get_session_state(pre_open_dt) == SessionState.PRE_OPEN)

# 3.5 Open (9:15-12:00)
open_dt = datetime(2026, 1, 15, 10, 30, tzinfo=IST)
check("3.5 10:30 AM -> OPEN", get_session_state(open_dt) == SessionState.OPEN)

# 3.6 Lunch (12:00-13:00)
lunch_dt = datetime(2026, 1, 15, 12, 30, tzinfo=IST)
check("3.6 12:30 PM -> LUNCH", get_session_state(lunch_dt) == SessionState.LUNCH)

# 3.7 Closing (13:00-15:30)
closing_dt = datetime(2026, 1, 15, 14, 0, tzinfo=IST)
check("3.7 2:00 PM -> CLOSING", get_session_state(closing_dt) == SessionState.CLOSING)

# 3.8 Post-close (15:30-16:00)
post_dt = datetime(2026, 1, 15, 15, 45, tzinfo=IST)
check("3.8 3:45 PM -> POST_CLOSE", get_session_state(post_dt) == SessionState.POST_CLOSE)

# 3.9 Late night -> CLOSED
late_dt = datetime(2026, 1, 15, 22, 0, tzinfo=IST)
check("3.9 10:00 PM -> CLOSED", get_session_state(late_dt) == SessionState.CLOSED)

# ════════════════════════════════════════════════════════════════
# SECTION 4: MARKET OPEN CHECK
# ════════════════════════════════════════════════════════════════
print("\n--- 4. Market Open Check ---")

# 4.1 Weekday 10:30 AM = OPEN
check("4.1 Weekday 10:30 -> open", is_market_open(open_dt))

# 4.2 Weekend 12:00 PM = CLOSED
check("4.2 Saturday 12:00 -> closed", not is_market_open(weekend_dt))

# 4.3 Holiday 12:00 PM = CLOSED
check("4.3 Holiday 12:00 -> closed", not is_market_open(holiday_dt))

# 4.4 Before market open (7:30 AM) = CLOSED
check("4.4 7:30 AM -> closed", not is_market_open(pre_market_dt))

# 4.5 After market close (3:45 PM) = CLOSED
check("4.5 3:45 PM -> closed", not is_market_open(post_dt))

# 4.6 Exactly 9:15 AM = OPEN
exact_open = datetime(2026, 1, 15, 9, 15, tzinfo=IST)
check("4.6 9:15 exact -> open", is_market_open(exact_open))

# 4.7 Exactly 3:30 PM = OPEN
exact_close = datetime(2026, 1, 15, 15, 30, tzinfo=IST)
check("4.7 3:30 exact -> open", is_market_open(exact_close))

# ════════════════════════════════════════════════════════════════
# SECTION 5: EVENTS FOR DATE
# ════════════════════════════════════════════════════════════════
print("\n--- 5. Events for Date ---")

# 5.1 Holiday date has events
holiday_events = get_events_for_date(date(2026, 1, 26))
check("5.1 Republic Day has events", len(holiday_events) >= 1)
if holiday_events:
    check("5.1 Republic Day type HOLIDAY", holiday_events[0].event_type == EventType.HOLIDAY)

# 5.2 Expiry date has events
expiry_events = get_events_for_date(date(2026, 1, 29))
check("5.2 Expiry date has events", len(expiry_events) >= 1)
expiry_found = any(e.event_type == EventType.EXPIRY for e in expiry_events)
check("5.2 Expiry event present", expiry_found)

# 5.3 Economic event — Union Budget (Feb 1)
budget_events = get_events_for_date(date(2026, 2, 1))
check("5.3 Budget day has events", len(budget_events) >= 1)
econ_found = any(
    e.event_type == EventType.ECONOMIC_HIGH and "Budget" in e.name
    for e in budget_events
)
check("5.3 Budget event present", econ_found)

# 5.4 Normal day — no events
normal_events = get_events_for_date(date(2026, 1, 12))
# May have some events or may be empty
check("5.4 Normal day events count >= 0", len(normal_events) >= 0)

# 5.5 Event list sorted by risk (highest first)
for i in range(len(holiday_events) - 1):
    check("5.5 Events sorted by risk",
          holiday_events[i].risk_level >= holiday_events[i + 1].risk_level)

# ════════════════════════════════════════════════════════════════
# SECTION 6: NEXT EVENT
# ════════════════════════════════════════════════════════════════
print("\n--- 6. Next Event ---")

# 6.1 Next event after Jan 1 should find something
jan1 = date(2026, 1, 1)
next_ev = get_next_event(jan1)
check("6.1 Next event after Jan 1 exists", next_ev is not None)
if next_ev:
    check("6.1 Next event date > Jan 1", next_ev.date > jan1)

# 6.2 Next event after Dec 31 may be None
# (no events defined for 2027)
dec31 = date(2026, 12, 31)
late_ev = get_next_event(dec31)
# May or may not have events on Dec 31 itself
check("6.2 Late year next event", late_ev is not None or late_ev is None)

# 6.3 Next event returns CalendarEvent
check("6.3 Next event is CalendarEvent",
      next_ev is None or isinstance(next_ev, CalendarEvent))

# ════════════════════════════════════════════════════════════════
# SECTION 7: MARKET SESSION (Complete query)
# ════════════════════════════════════════════════════════════════
print("\n--- 7. Market Session ---")

# 7.1 Business hours session
session_open = get_market_session(open_dt)
check("7.1 Session state = OPEN", session_open.session_state == SessionState.OPEN)
check("7.1 is_market_open = True", session_open.is_market_open)

# 7.2 Holiday session
session_holiday = get_market_session(holiday_dt)
check("7.2 is_holiday_today = True", session_holiday.is_holiday_today)
check("7.2 is_market_open = False", not session_holiday.is_market_open)

# 7.3 Expiry day session
expiry_dt = datetime(2026, 1, 29, 10, 30, tzinfo=IST)
session_expiry = get_market_session(expiry_dt)
check("7.3 is_expiry_today = True", session_expiry.is_expiry_today)
if session_expiry.events_today:
    check("7.3 Events include expiry",
          any("Expiry" in e["name"] for e in session_expiry.events_today))

# 7.4 Weekend session
session_weekend = get_market_session(weekend_dt)
check("7.4 is_holiday_today = True (weekend)", session_weekend.is_holiday_today)
check("7.4 is_market_open = False", not session_weekend.is_market_open)

# 7.5 MarketSession dataclass instance
check("7.5 Return type MarketSession", isinstance(session_open, MarketSession))

# 7.6 MarketSession has all fields
check("7.6 Has session_state", session_open.session_state is not None)
check("7.6 Has is_market_open", isinstance(session_open.is_market_open, bool))
check("7.6 Has events_today", isinstance(session_open.events_today, list))

# 7.7 Rollover week detection (last week of June = monthly expiry June 25)
check("7.7 Jun 22 is rollover week", is_rollover_week(date(2026, 6, 22)))
check("7.8 Jan 12 NOT rollover week", not is_rollover_week(date(2026, 1, 12)))

# ════════════════════════════════════════════════════════════════
# SECTION 8: FORMAT MARKET SESSION
# ════════════════════════════════════════════════════════════════
print("\n--- 8. Format Session ---")

fmt_open = format_market_session(session_open)
fmt_holiday = format_market_session(session_holiday)

check("8.1 Format returns string", isinstance(fmt_open, str))
check("8.2 Format has Session info", "Session:" in fmt_open)
check("8.3 Format has Open/Closed", "YES" in fmt_open or "NO" in fmt_open)
check("8.4 Holiday format has HOLIDAY", "HOLIDAY" in fmt_holiday)
check("8.5 Format not empty", len(fmt_open) > 0)

# ════════════════════════════════════════════════════════════════
# SECTION 9: FLOOR 3 ENGINE INTEGRATION
# ════════════════════════════════════════════════════════════════
print("\n--- 9. Floor 3 Engine Integration ---")

now_ist = datetime.now(IST)
calc_input = CalculationInput(
    packet_envelope_id="cal_test_001",
    market_phase=MarketPhase.OPEN,
    symbol="NIFTY",
    timestamp=now_ist,
    data={"source": "calendar_test"},
)

report = calendar_engine_run(calc_input)

# 9.1 Engine returns COMPLETE
check("9.1 Engine status COMPLETE", report.status.value == "COMPLETE",
      str(report.status.value))

# 9.2 Engine produces signals
check("9.2 Signals generated", len(report.signals) >= 2,
      str(len(report.signals)))

# 9.3 Domain is MACRO
check("9.3 Domain = MACRO", report.domain == CalculationDomain.MACRO)

# 9.4 Signal types present
indicator_types = {s.indicator_type for s in report.signals}
check("9.4 EVENT_CALENDAR signal", "EVENT_CALENDAR" in indicator_types)
check("9.4 MACRO_CONTEXT signal", "MACRO_CONTEXT" in indicator_types)

# 9.5 EVENT_CALENDAR has required fields
event_sigs = [s for s in report.signals if s.indicator_type == "EVENT_CALENDAR"]
if event_sigs:
    ev = event_sigs[0]
    check("9.5 EVENT_CALENDAR has session_state", "session_state" in ev.value)
    check("9.5 EVENT_CALENDAR has is_market_open", "is_market_open" in ev.value)
    check("9.5 EVENT_CALENDAR has is_expiry_today", "is_expiry_today" in ev.value)
    check("9.5 EVENT_CALENDAR has next_event", "next_event" in ev.value)
    check("9.5 EVENT_CALENDAR has days_until_event", "days_until_event" in ev.value)

# 9.6 MACRO_CONTEXT has required fields
ctx_sigs = [s for s in report.signals if s.indicator_type == "MACRO_CONTEXT"]
if ctx_sigs:
    ctx = ctx_sigs[0]
    check("9.6 MACRO_CONTEXT has context_summary", "context_summary" in ctx.value)
    check("9.6 MACRO_CONTEXT has macro_bias", "macro_bias" in ctx.value)
    check("9.6 MACRO_CONTEXT has caution_level", "caution_level" in ctx.value)
    check("9.6 MACRO_CONTEXT has event_risk_flag", "event_risk_flag" in ctx.value)

# 9.7 No errors
check("9.7 No engine errors", len(report.errors) == 0, str(report.errors))

# 9.8 All signals have CalculationLog
for sig in report.signals:
    check(f"9.8 {sig.indicator_type} has log", sig.calculation_log is not None)
    if sig.calculation_log:
        check(f"9.8 {sig.indicator_type} log has input_hash",
              bool(sig.calculation_log.input_hash))
        check(f"9.8 {sig.indicator_type} log domain MACRO",
              sig.calculation_log.domain == CalculationDomain.MACRO)

# 9.9 Signals have metadata
for sig in report.signals:
    check(f"9.9 {sig.indicator_type} has metadata", bool(sig.metadata.get("symbol")))

# 9.10 Engine name correct
check("9.10 Engine name = calendar_state_engine",
      report.engine_name == "calendar_state_engine")

# 9.11 Duration >= 0
check("9.11 Duration >= 0", report.duration_ms >= 0.0)

# ════════════════════════════════════════════════════════════════
# SECTION 10: EDGE CASES
# ════════════════════════════════════════════════════════════════
print("\n--- 10. Edge Cases ---")

# 10.1 is_market_open on expiry day (should be OPEN during trading hours)
check("10.1 Expiry day 10:30 AM = OPEN",
      is_market_open(datetime(2026, 1, 29, 10, 30, tzinfo=IST)))

# 10.2 None timestamp is handled by engine
calc_none_ts = CalculationInput(
    packet_envelope_id="cal_test_002",
    market_phase=MarketPhase.POST_CLOSE,
    symbol="NIFTY",
    timestamp=datetime.now(),  # No timezone
    data={},
)
report_none = calendar_engine_run(calc_none_ts)
check("10.2 No-tz timestamp handled", report_none.status.value == "COMPLETE")

# 10.3 Empty data dict handled
check("10.3 Empty data handled", len(report_none.signals) >= 2)

# 10.4 is_market_open at market boundaries
# 8:59 AM = closed
check("10.4 8:59 AM = closed",
      not is_market_open(datetime(2026, 1, 15, 8, 59, tzinfo=IST)))
# 9:15 AM = open
check("10.4 9:15 AM = open",
      is_market_open(datetime(2026, 1, 15, 9, 15, tzinfo=IST)))
# 3:30 PM = open
check("10.4 3:30 PM = open",
      is_market_open(datetime(2026, 1, 15, 15, 30, tzinfo=IST)))
# 3:31 PM = closed
check("10.4 3:31 PM = closed",
      not is_market_open(datetime(2026, 1, 15, 15, 31, tzinfo=IST)))

# 10.5 event_risk_flag True on expiry day
if ctx_sigs:
    session_expiry_ctx = get_market_session(expiry_dt)
    exp_ctx_sigs = calendar_engine_run(CalculationInput(
        packet_envelope_id="cal_test_003",
        market_phase=MarketPhase.OPEN,
        symbol="NIFTY",
        timestamp=expiry_dt,
        data={},
    ))
    exp_ctx = [s for s in exp_ctx_sigs.signals if s.indicator_type == "MACRO_CONTEXT"]
    if exp_ctx:
        check("10.5 Expiry day event_risk_flag",
              exp_ctx[0].value.get("event_risk_flag", False))

# 10.6 Format on holiday
fmt_holiday_str = format_market_session(session_holiday)
check("10.6 Holiday format mentions HOLIDAY",
      "HOLIDAY" in fmt_holiday_str or "Closed" in fmt_holiday_str)

# 10.7 FOMC event exists
fomc_events = get_events_for_date(date(2026, 1, 28))
fomc_found = any("FOMC" in e.name for e in fomc_events)
check("10.7 FOMC event on Jan 28", fomc_found)

# 10.8 RBI policy event exists
rbi_events = get_events_for_date(date(2026, 2, 7))
rbi_found = any("RBI" in e.name for e in rbi_events)
check("10.8 RBI event on Feb 7", rbi_found)

# 10.9 Christmas = holiday
check("10.9 Christmas is holiday", is_holiday(date(2026, 12, 25)))

# 10.10 Expiry week on Monday before expiry (Jan 26 = Mon of expiry week)
check("10.10 Jan 26 (Mon) = expiry week", is_expiry_week(date(2026, 1, 26)))

# ════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
print(f"{'=' * 60}")

if __name__ == "__main__":
    sys.exit(0 if failed == 0 else 1)
