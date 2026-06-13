"""Unit tests for ``session_policy.py`` — Floor 5 Step 5.2.

Tests:
- get_session_phase() with various IST timestamps
- get_permission_strictness() for all 4 phases
- get_aggression_modifier() for all 4 phases
- get_preferred_trade_classes() for all 4 phases
- is_opening_window() — boundary conditions
- is_closing_window() — boundary conditions
- is_market_open() — market hours + weekday check
- is_market_closed()
- get_session_summary() — all fields present
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone

from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.floor_5_captain.captain_types import (
    SessionPhase,
    TradeClass,
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


def utc_to_ist_dt(ist_hour: int, ist_minute: int, weekday: int = 0) -> datetime:
    """Create a UTC datetime that corresponds to the given IST time.

    IST = UTC + 5:30.  So UTC hour = IST hour - 5:30 (with wrap).

    Args:
        ist_hour: Hour in IST (0-23).
        ist_minute: Minute in IST (0-59).
        weekday: Day of week (0=Monday, 6=Sunday).

    Returns:
        UTC datetime representing the given IST time.
    """
    # Convert IST to UTC by subtracting 5:30
    total_ist_minutes = ist_hour * 60 + ist_minute
    total_utc_minutes = total_ist_minutes - 330  # 5*60 + 30
    total_utc_minutes = total_utc_minutes % (24 * 60)
    utc_hour, utc_minute = divmod(total_utc_minutes, 60)
    return datetime(2026, 6, 8 + weekday, utc_hour, utc_minute, tzinfo=timezone.utc)


print("=" * 60)
print("Floor 5 — Session Policy Tests")
print("=" * 60)

policy = SessionPolicy()

# =========================================================================
# 1. get_session_phase()
# =========================================================================
print("\n--- 1. get_session_phase() ---")

# Pre-market (8:00 IST)
dt = utc_to_ist_dt(8, 0)
check("1.1 8:00 IST -> OPENING (pre-market)", policy.get_session_phase(dt) == SessionPhase.OPENING)

# Opening window
dt = utc_to_ist_dt(9, 15)
check("1.2 9:15 IST -> OPENING", policy.get_session_phase(dt) == SessionPhase.OPENING)
dt = utc_to_ist_dt(9, 30)
check("1.3 9:30 IST -> OPENING", policy.get_session_phase(dt) == SessionPhase.OPENING)
dt = utc_to_ist_dt(9, 44)
check("1.4 9:44 IST -> OPENING", policy.get_session_phase(dt) == SessionPhase.OPENING)

# Golden morning
dt = utc_to_ist_dt(9, 45)
check("1.5 9:45 IST -> GOLDEN_MORNING", policy.get_session_phase(dt) == SessionPhase.GOLDEN_MORNING)
dt = utc_to_ist_dt(10, 0)
check("1.6 10:00 IST -> GOLDEN_MORNING", policy.get_session_phase(dt) == SessionPhase.GOLDEN_MORNING)
dt = utc_to_ist_dt(10, 59)
check("1.7 10:59 IST -> GOLDEN_MORNING", policy.get_session_phase(dt) == SessionPhase.GOLDEN_MORNING)

# Lunch
dt = utc_to_ist_dt(11, 0)
check("1.8 11:00 IST -> LUNCH", policy.get_session_phase(dt) == SessionPhase.LUNCH)
dt = utc_to_ist_dt(12, 0)
check("1.9 12:00 IST -> LUNCH", policy.get_session_phase(dt) == SessionPhase.LUNCH)
dt = utc_to_ist_dt(12, 59)
check("1.10 12:59 IST -> LUNCH", policy.get_session_phase(dt) == SessionPhase.LUNCH)

# Closing
dt = utc_to_ist_dt(13, 0)
check("1.11 13:00 IST -> CLOSING", policy.get_session_phase(dt) == SessionPhase.CLOSING)
dt = utc_to_ist_dt(14, 0)
check("1.12 14:00 IST -> CLOSING", policy.get_session_phase(dt) == SessionPhase.CLOSING)
dt = utc_to_ist_dt(15, 0)
check("1.13 15:00 IST -> CLOSING", policy.get_session_phase(dt) == SessionPhase.CLOSING)
dt = utc_to_ist_dt(15, 29)
check("1.14 15:29 IST -> CLOSING", policy.get_session_phase(dt) == SessionPhase.CLOSING)

# 15:30 is market close — should still be CLOSING (13:00-15:30 inclusive)
dt = utc_to_ist_dt(15, 30)
check("1.15 15:30 IST -> CLOSING", policy.get_session_phase(dt) == SessionPhase.CLOSING)

# Post-market
dt = utc_to_ist_dt(16, 0)
check("1.16 16:00 IST -> OPENING (post-market)", policy.get_session_phase(dt) == SessionPhase.OPENING)
dt = utc_to_ist_dt(20, 0)
check("1.17 20:00 IST -> OPENING (post-market)", policy.get_session_phase(dt) == SessionPhase.OPENING)

# Default (no argument)
phase_default = policy.get_session_phase()
check("1.18 Default call returns a SessionPhase", isinstance(phase_default, SessionPhase))

# =========================================================================
# 2. get_permission_strictness()
# =========================================================================
print("\n--- 2. get_permission_strictness() ---")

check("2.1 OPENING -> HIGH", policy.get_permission_strictness(SessionPhase.OPENING) == "HIGH")
check("2.2 GOLDEN_MORNING -> NORMAL", policy.get_permission_strictness(SessionPhase.GOLDEN_MORNING) == "NORMAL")
check("2.3 LUNCH -> HIGH", policy.get_permission_strictness(SessionPhase.LUNCH) == "HIGH")
check("2.4 CLOSING -> VERY_HIGH", policy.get_permission_strictness(SessionPhase.CLOSING) == "VERY_HIGH")

# =========================================================================
# 3. get_aggression_modifier()
# =========================================================================
print("\n--- 3. get_aggression_modifier() ---")

check("3.1 OPENING -> -0.2", policy.get_aggression_modifier(SessionPhase.OPENING) == -0.2)
check("3.2 GOLDEN_MORNING -> +0.1", policy.get_aggression_modifier(SessionPhase.GOLDEN_MORNING) == 0.1)
check("3.3 LUNCH -> -0.1", policy.get_aggression_modifier(SessionPhase.LUNCH) == -0.1)
check("3.4 CLOSING -> -0.2", policy.get_aggression_modifier(SessionPhase.CLOSING) == -0.2)

# =========================================================================
# 4. get_preferred_trade_classes()
# =========================================================================
print("\n--- 4. get_preferred_trade_classes() ---")

opening_classes = policy.get_preferred_trade_classes(SessionPhase.OPENING)
check("4.1 OPENING has LIQUIDITY_RECLAIM", "LIQUIDITY_RECLAIM" in opening_classes)
check("4.2 OPENING has 1 class", len(opening_classes) == 1)

golden_classes = policy.get_preferred_trade_classes(SessionPhase.GOLDEN_MORNING)
check("4.3 GOLDEN_MORNING has CONTINUATION", "CONTINUATION" in golden_classes)
check("4.4 GOLDEN_MORNING has SCALP", "SCALP" in golden_classes)
check("4.5 GOLDEN_MORNING has LIQUIDITY_RECLAIM", "LIQUIDITY_RECLAIM" in golden_classes)
check("4.6 GOLDEN_MORNING has OPTIONS_PRESSURE", "OPTIONS_PRESSURE" in golden_classes)
check("4.7 GOLDEN_MORNING has 4 classes", len(golden_classes) == 4)

lunch_classes = policy.get_preferred_trade_classes(SessionPhase.LUNCH)
check("4.8 LUNCH has REVERSAL", "REVERSAL" in lunch_classes)
check("4.9 LUNCH has OPTIONS_PRESSURE", "OPTIONS_PRESSURE" in lunch_classes)
check("4.10 LUNCH has 2 classes", len(lunch_classes) == 2)

closing_classes = policy.get_preferred_trade_classes(SessionPhase.CLOSING)
check("4.11 CLOSING has SCALP", "SCALP" in closing_classes)
check("4.12 CLOSING has OPTIONS_PRESSURE", "OPTIONS_PRESSURE" in closing_classes)
check("4.13 CLOSING has 2 classes", len(closing_classes) == 2)

# =========================================================================
# 5. is_opening_window()
# =========================================================================
print("\n--- 5. is_opening_window() ---")

# Before opening
dt = utc_to_ist_dt(9, 14)
check("5.1 9:14 IST -> not opening", policy.is_opening_window(dt) is False)

# Opening
dt = utc_to_ist_dt(9, 15)
check("5.2 9:15 IST -> is opening", policy.is_opening_window(dt) is True)
dt = utc_to_ist_dt(9, 30)
check("5.3 9:30 IST -> is opening", policy.is_opening_window(dt) is True)
dt = utc_to_ist_dt(9, 44)
check("5.4 9:44 IST -> is opening", policy.is_opening_window(dt) is True)

# After opening
dt = utc_to_ist_dt(9, 45)
check("5.5 9:45 IST -> not opening", policy.is_opening_window(dt) is False)
dt = utc_to_ist_dt(10, 0)
check("5.6 10:00 IST -> not opening", policy.is_opening_window(dt) is False)

# =========================================================================
# 6. is_closing_window()
# =========================================================================
print("\n--- 6. is_closing_window() ---")

# Before closing
dt = utc_to_ist_dt(12, 59)
check("6.1 12:59 IST -> not closing", policy.is_closing_window(dt) is False)

# Closing
dt = utc_to_ist_dt(13, 0)
check("6.2 13:00 IST -> is closing", policy.is_closing_window(dt) is True)
dt = utc_to_ist_dt(14, 0)
check("6.3 14:00 IST -> is closing", policy.is_closing_window(dt) is True)
dt = utc_to_ist_dt(15, 0)
check("6.4 15:00 IST -> is closing", policy.is_closing_window(dt) is True)
dt = utc_to_ist_dt(15, 29)
check("6.5 15:29 IST -> is closing", policy.is_closing_window(dt) is True)

# After close
dt = utc_to_ist_dt(15, 30)
check("6.6 15:30 IST -> not closing (market closed)", policy.is_closing_window(dt) is False)
dt = utc_to_ist_dt(16, 0)
check("6.7 16:00 IST -> not closing", policy.is_closing_window(dt) is False)

# =========================================================================
# 7. is_market_open()
# =========================================================================
print("\n--- 7. is_market_open() ---")

# Weekday tests (Monday = weekday 0)
# Before market
dt = utc_to_ist_dt(9, 14, weekday=0)
check("7.1 Mon 9:14 IST -> market closed", policy.is_market_open(dt) is False)

# Market open
dt = utc_to_ist_dt(9, 15, weekday=0)
check("7.2 Mon 9:15 IST -> market open", policy.is_market_open(dt) is True)
dt = utc_to_ist_dt(12, 0, weekday=0)
check("7.3 Mon 12:00 IST -> market open", policy.is_market_open(dt) is True)
dt = utc_to_ist_dt(15, 29, weekday=0)
check("7.4 Mon 15:29 IST -> market open", policy.is_market_open(dt) is True)

# After market
dt = utc_to_ist_dt(15, 30, weekday=0)
check("7.5 Mon 15:30 IST -> market closed", policy.is_market_open(dt) is False)
dt = utc_to_ist_dt(20, 0, weekday=0)
check("7.6 Mon 20:00 IST -> market closed", policy.is_market_open(dt) is False)

# Weekend
dt = utc_to_ist_dt(10, 0, weekday=5)  # Saturday
check("7.7 Saturday 10:00 IST -> market closed", policy.is_market_open(dt) is False)
dt = utc_to_ist_dt(10, 0, weekday=6)  # Sunday
check("7.8 Sunday 10:00 IST -> market closed", policy.is_market_open(dt) is False)

# =========================================================================
# 8. is_market_closed()
# =========================================================================
print("\n--- 8. is_market_closed() ---")

dt = utc_to_ist_dt(10, 0, weekday=0)
check("8.1 Mon 10:00 IST -> market not closed", policy.is_market_closed(dt) is False)
dt = utc_to_ist_dt(20, 0, weekday=0)
check("8.2 Mon 20:00 IST -> market closed", policy.is_market_closed(dt) is True)
dt = utc_to_ist_dt(10, 0, weekday=5)
check("8.3 Saturday -> market closed", policy.is_market_closed(dt) is True)

# =========================================================================
# 9. get_session_summary()
# =========================================================================
print("\n--- 9. get_session_summary() ---")

dt = utc_to_ist_dt(10, 0, weekday=0)  # Golden morning
summary = policy.get_session_summary(dt)
check("9.1 Summary has phase", summary.get("phase") == "GOLDEN_MORNING")
check("9.2 Summary has permission_strictness", summary.get("permission_strictness") == "NORMAL")
check("9.3 Summary has aggression_modifier", summary.get("aggression_modifier") == 0.1)
check("9.4 Summary has preferred_trade_classes", len(summary.get("preferred_trade_classes", [])) > 0)
check("9.5 Summary has is_market_open", summary.get("is_market_open") is True)
check("9.6 Summary has is_opening_window", summary.get("is_opening_window") is False)
check("9.7 Summary has is_closing_window", summary.get("is_closing_window") is False)
check("9.8 Summary has timestamp", summary.get("timestamp") is not None)
check("9.9 Summary has 8 fields", len(summary) == 8)

# Post-market summary
dt = utc_to_ist_dt(20, 0, weekday=0)
summary2 = policy.get_session_summary(dt)
check("9.10 Post-market -> is_market_open False", summary2.get("is_market_open") is False)

# Default call
summary3 = policy.get_session_summary()
check("9.11 Default call returns valid summary", len(summary3) == 8)


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
