"""Unit tests for ``permission_gate.py`` — Floor 5 Step 5.4.

Tests:
- All 8 checks pass → allowed = True
- Market closed → blocked (weekend, after hours)
- Psychology block → blocked (non-overridable)
- Active trade → blocked (non-overridable)
- Data health CRITICAL → blocked
- REAL mode locked → blocked (ALERT/PAPER unaffected)
- Invalid mode → blocked
- Session policy (CLOSING, OPENING) → blocked
- Capital = 0 → blocked
- Multiple blocks → all blocked_by listed
- Psychology report None → passes
- Floor summary None → passes
- Mode None → blocked by mode validation
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone, timedelta

from junior_aladdin.floor_5_captain.permission_gate import PermissionGate
from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.floor_5_captain.loss_lock_manager import LossLockManager
from junior_aladdin.shared.types import (
    DataHealth,
    ExecutionMode,
    FloorSummary,
    HeadReport,
    HeadState,
    BiasType,
    FreshnessTag,
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


def make_psychology_report(trade_allowed: bool = True) -> HeadReport:
    """Create a Psychology Head report with the given trade_allowed flag."""
    return HeadReport(
        head_name="Psychology Head",
        state=HeadState.READY,
        freshness_score=0.9,
        freshness_tag=FreshnessTag.FRESH,
        last_deep_update=datetime.utcnow(),
        bias=BiasType.NEUTRAL,
        confidence=0.0,
        dominant_tf="1m",
        timeframe_view="Neutral",
        trade_allowed=trade_allowed,
    )


def make_floor_summary(data_health: DataHealth = DataHealth.GOOD) -> FloorSummary:
    """Create a FloorSummary with the given data health signal."""
    return FloorSummary(
        summary_timestamp=datetime.utcnow(),
        data_health_signal=data_health,
    )


def utc_to_ist_dt(ist_hour: int, ist_minute: int, weekday: int = 0) -> datetime:
    """Create a UTC datetime that corresponds to the given IST time."""
    total_ist_minutes = ist_hour * 60 + ist_minute
    total_utc_minutes = total_ist_minutes - 330  # 5*60 + 30
    total_utc_minutes = total_utc_minutes % (24 * 60)
    utc_hour, utc_minute = divmod(total_utc_minutes, 60)
    return datetime(2026, 6, 8 + weekday, utc_hour, utc_minute, tzinfo=timezone.utc)


print("=" * 60)
print("Floor 5 — Permission Gate Tests")
print("=" * 60)

# Shared instances
session_policy = SessionPolicy()
loss_lock_manager = LossLockManager()
loss_lock_manager_non_locked = LossLockManager()  # Never locked

# =========================================================================
# 1. All checks pass (normal conditions)
# =========================================================================
print("\n--- 1. All checks pass ---")

gate = PermissionGate(session_policy, loss_lock_manager_non_locked)

# Golden morning (NORMAL strictness) on a weekday
dt_golden = utc_to_ist_dt(10, 0, weekday=0)  # Mon 10:00 IST

result = gate.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.GOOD),
    psychology_report=make_psychology_report(trade_allowed=True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("1.1 All checks pass -> allowed True", result.allowed is True)
check("1.2 No block_reason", result.block_reason == "")
check("1.3 No blocked_by", len(result.blocked_by) == 0)

# REAL mode with no lock
result_real = gate.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.GOOD),
    psychology_report=make_psychology_report(trade_allowed=True),
    active_trade=False,
    current_mode=ExecutionMode.REAL,
    capital_available=50000.0,
)
check("1.4 REAL mode allowed when not locked", result_real.allowed is True)

# Large capital
result_large = gate.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.GOOD),
    psychology_report=make_psychology_report(trade_allowed=True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=999999.0,
)
check("1.5 Large capital allowed", result_large.allowed is True)

# =========================================================================
# 2. Market closed check
# =========================================================================
print("\n--- 2. Market closed check ---")

gate2 = PermissionGate(session_policy, loss_lock_manager_non_locked)

# Saturday
dt_saturday = utc_to_ist_dt(10, 0, weekday=5)  # Saturday 10:00 IST
result = gate2.check_all(
    timestamp=dt_saturday,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("2.1 Saturday -> blocked", result.allowed is False)
check("2.2 Saturday blocked_by has market_open", "market_open" in result.blocked_by)
check("2.3 Saturday block_reason mentions market closed", "closed" in result.block_reason.lower())

# Sunday
dt_sunday = utc_to_ist_dt(10, 0, weekday=6)  # Sunday 10:00 IST
result = gate2.check_all(
    timestamp=dt_sunday,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("2.4 Sunday -> blocked", result.allowed is False)
check("2.5 Sunday blocked_by has market_open", "market_open" in result.blocked_by)

# After hours (20:00 IST on Monday)
dt_after = utc_to_ist_dt(20, 0, weekday=0)
result = gate2.check_all(
    timestamp=dt_after,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("2.6 After hours -> blocked", result.allowed is False)
check("2.7 After hours blocked_by has market_open", "market_open" in result.blocked_by)

# Before market (8:00 IST on Monday)
dt_before = utc_to_ist_dt(8, 0, weekday=0)
result = gate2.check_all(
    timestamp=dt_before,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("2.8 Before market -> blocked", result.allowed is False)
check("2.9 Before market blocked_by has market_open", "market_open" in result.blocked_by)

# =========================================================================
# 3. Psychology block check (NON-OVERRIDABLE)
# =========================================================================
print("\n--- 3. Psychology block check ---")

gate3 = PermissionGate(session_policy, loss_lock_manager_non_locked)

dt_golden = utc_to_ist_dt(10, 0, weekday=0)

# Psychology blocks
result = gate3.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(trade_allowed=False),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("3.1 Psychology block -> blocked", result.allowed is False)
check("3.2 Psychology blocked_by has psychology_block", "psychology_block" in result.blocked_by)
check("3.3 Block reason mentions non-overridable", "non-overridable" in result.block_reason.lower()
      or "psychology" in result.block_reason.lower())

# Psychology report None — should pass
result = gate3.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=None,
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("3.4 No psychology report -> allowed", result.allowed is True)

# =========================================================================
# 4. Active trade check (NON-OVERRIDABLE)
# =========================================================================
print("\n--- 4. Active trade check ---")

gate4 = PermissionGate(session_policy, loss_lock_manager_non_locked)

dt_golden = utc_to_ist_dt(10, 0, weekday=0)

result = gate4.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=True,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("4.1 Active trade -> blocked", result.allowed is False)
check("4.2 Active trade blocked_by has active_trade", "active_trade" in result.blocked_by)
check("4.3 Block reason mentions one-trade", "one-trade" in result.block_reason.lower()
      or "active trade" in result.block_reason.lower())

# Active trade False — should pass
result = gate4.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("4.4 No active trade -> allowed", result.allowed is True)

# =========================================================================
# 5. Data health CRITICAL
# =========================================================================
print("\n--- 5. Data health CRITICAL ---")

gate5 = PermissionGate(session_policy, loss_lock_manager_non_locked)

dt_golden = utc_to_ist_dt(10, 0, weekday=0)

# GOOD health — passes
result = gate5.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.GOOD),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("5.1 GOOD health -> allowed", result.allowed is True)

# CAUTION — passes
result = gate5.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.CAUTION),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("5.2 CAUTION health -> allowed", result.allowed is True)

# DEGRADED — passes
result = gate5.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.DEGRADED),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("5.3 DEGRADED health -> allowed", result.allowed is True)

# CRITICAL — blocks
result = gate5.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.CRITICAL),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("5.4 CRITICAL health -> blocked", result.allowed is False)
check("5.5 CRITICAL blocked_by has data_health", "data_health" in result.blocked_by)
check("5.6 Block reason mentions CRITICAL", "critical" in result.block_reason.lower())

# No FloorSummary — passes
result = gate5.check_all(
    timestamp=dt_golden,
    floor_summary=None,
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("5.7 No floor summary -> allowed", result.allowed is True)

# =========================================================================
# 6. REAL mode lock check
# =========================================================================
print("\n--- 6. REAL mode lock check ---")

llm_locked = LossLockManager()
llm_locked.set_mode(ExecutionMode.REAL)
llm_locked.record_loss()
llm_locked.record_loss()
llm_locked.record_loss()  # Lock triggered
check("6.0 Lock manager locked", llm_locked.is_locked() is True)

gate6 = PermissionGate(session_policy, llm_locked)
dt_golden = utc_to_ist_dt(10, 0, weekday=0)

# REAL mode + locked = blocked
result = gate6.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.REAL,
    capital_available=50000.0,
)
check("6.1 REAL + locked -> blocked", result.allowed is False)
check("6.2 REAL + locked blocked_by has real_mode_lock", "real_mode_lock" in result.blocked_by)

# ALERT mode + locked = allowed
result = gate6.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.ALERT,
    capital_available=50000.0,
)
check("6.3 ALERT + locked -> allowed", result.allowed is True)

# PAPER mode + locked = allowed
result = gate6.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("6.4 PAPER + locked -> allowed", result.allowed is True)

# REAL mode + not locked = allowed (use non-locked manager)
gate6_unlocked = PermissionGate(session_policy, loss_lock_manager_non_locked)
result = gate6_unlocked.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.REAL,
    capital_available=50000.0,
)
check("6.5 REAL + not locked -> allowed", result.allowed is True)

# =========================================================================
# 7. Mode validation
# =========================================================================
print("\n--- 7. Mode validation ---")

gate7 = PermissionGate(session_policy, loss_lock_manager_non_locked)
dt_golden = utc_to_ist_dt(10, 0, weekday=0)

# None mode — blocked
result = gate7.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=None,
    capital_available=50000.0,
)
check("7.1 None mode -> blocked", result.allowed is False)
check("7.2 None mode blocked_by has mode_validation", "mode_validation" in result.blocked_by)

# ALERT mode — allowed
result = gate7.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.ALERT,
    capital_available=50000.0,
)
check("7.3 ALERT mode -> allowed", result.allowed is True)

# PAPER mode — allowed
result = gate7.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("7.4 PAPER mode -> allowed", result.allowed is True)

# REAL mode — allowed
result = gate7.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.REAL,
    capital_available=50000.0,
)
check("7.5 REAL mode -> allowed", result.allowed is True)

# =========================================================================
# 8. Session policy check
# =========================================================================
print("\n--- 8. Session policy check ---")

gate8 = PermissionGate(session_policy, loss_lock_manager_non_locked)

# CLOSING window (14:00 IST Monday) — VERY_HIGH strictness → blocked
dt_closing = utc_to_ist_dt(14, 0, weekday=0)
result = gate8.check_all(
    timestamp=dt_closing,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("8.1 CLOSING -> blocked", result.allowed is False)
check("8.2 CLOSING blocked_by has session_policy", "session_policy" in result.blocked_by)

# OPENING (9:30 IST Monday) — HIGH strictness → blocked
dt_opening = utc_to_ist_dt(9, 30, weekday=0)
result = gate8.check_all(
    timestamp=dt_opening,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("8.3 OPENING -> blocked", result.allowed is False)
check("8.4 OPENING blocked_by has session_policy", "session_policy" in result.blocked_by)

# LUNCH (12:00 IST Monday) — HIGH strictness → blocked
dt_lunch = utc_to_ist_dt(12, 0, weekday=0)
result = gate8.check_all(
    timestamp=dt_lunch,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("8.5 LUNCH -> blocked", result.allowed is False)
check("8.6 LUNCH blocked_by has session_policy", "session_policy" in result.blocked_by)

# GOLDEN MORNING (10:00 IST Monday) — NORMAL strictness → allowed
dt_golden = utc_to_ist_dt(10, 0, weekday=0)
result = gate8.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("8.7 GOLDEN_MORNING -> allowed", result.allowed is True)
check("8.8 GOLDEN_MORNING no session_policy block", "session_policy" not in result.blocked_by)

# =========================================================================
# 9. Capital availability
# =========================================================================
print("\n--- 9. Capital availability ---")

gate9 = PermissionGate(session_policy, loss_lock_manager_non_locked)
dt_golden = utc_to_ist_dt(10, 0, weekday=0)

# Capital = 0 → blocked
result = gate9.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=0.0,
)
check("9.1 Capital 0 -> blocked", result.allowed is False)
check("9.2 Capital 0 blocked_by has capital_availability", "capital_availability" in result.blocked_by)

# Negative capital → blocked
result = gate9.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=-1000.0,
)
check("9.3 Negative capital -> blocked", result.allowed is False)
check("9.4 Negative capital blocked_by has capital_availability", "capital_availability" in result.blocked_by)

# Large capital → allowed
result = gate9.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=100000.0,
)
check("9.5 Positive capital -> allowed", result.allowed is True)

# =========================================================================
# 10. Multiple blocks simultaneously
# =========================================================================
print("\n--- 10. Multiple blocks ---")

gate10 = PermissionGate(session_policy, llm_locked)

# CLOSING window + CRITICAL health + REAL locked + capital = 0
dt_closing = utc_to_ist_dt(14, 0, weekday=0)
result = gate10.check_all(
    timestamp=dt_closing,
    floor_summary=make_floor_summary(DataHealth.CRITICAL),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.REAL,
    capital_available=0.0,
)

check("10.1 Multiple blocks -> blocked", result.allowed is False)
check("10.2 All 4 blocked checks present",
      "session_policy" in result.blocked_by
      and "data_health" in result.blocked_by
      and "real_mode_lock" in result.blocked_by
      and "capital_availability" in result.blocked_by)
check("10.3 Exactly 4 blocked checks", len(result.blocked_by) == 4)

# Maximum simultaneous blocks: Saturday 14:00 IST (CLOSING phase) + all checks fail
# 7 out of 8 checks can block simultaneously because:
# - mode=None → mode_validation blocks, but real_mode_lock passes
# - mode=REAL+locked → real_mode_lock blocks, but mode_validation passes
# They are mutually exclusive by design
# Saturday 14:00 IST → CLOSING phase (VERY_HIGH strictness) → session_policy blocks
# Saturday 14:00 IST → weekend → market_open blocks
dt_saturday_14 = utc_to_ist_dt(14, 0, weekday=5)
result = gate10.check_all(
    timestamp=dt_saturday_14,
    floor_summary=make_floor_summary(DataHealth.CRITICAL),
    psychology_report=make_psychology_report(False),
    active_trade=True,
    current_mode=ExecutionMode.REAL,
    capital_available=0.0,
)
check("10.4 7 blocks (REAL mode, Sat 14:00)", len(result.blocked_by) == 7)
check("10.5 Has market_open (Saturday)", "market_open" in result.blocked_by)
check("10.6 Has psychology_block", "psychology_block" in result.blocked_by)
check("10.7 Has active_trade", "active_trade" in result.blocked_by)
check("10.8 Has data_health", "data_health" in result.blocked_by)
check("10.9 Has real_mode_lock", "real_mode_lock" in result.blocked_by)
check("10.10 Has session_policy (CLOSING on Sat 14:00)", "session_policy" in result.blocked_by)
check("10.11 Has capital_availability", "capital_availability" in result.blocked_by)
check("10.12 mode_validation NOT blocked (REAL is valid)", "mode_validation" not in result.blocked_by)

# With mode=None, mode_validation blocks but real_mode_lock passes
result2 = gate10.check_all(
    timestamp=dt_saturday_14,
    floor_summary=make_floor_summary(DataHealth.CRITICAL),
    psychology_report=make_psychology_report(False),
    active_trade=True,
    current_mode=None,
    capital_available=0.0,
)
check("10.13 7 blocks (mode=None, Sat 14:00)", len(result2.blocked_by) == 7)
check("10.14 mode_validation blocked", "mode_validation" in result2.blocked_by)
check("10.15 real_mode_lock NOT blocked (mode=None)", "real_mode_lock" not in result2.blocked_by)

# =========================================================================
# 11. Edge: PermissionResult structure
# =========================================================================
print("\n--- 11. PermissionResult structure ---")

gate11 = PermissionGate(session_policy, loss_lock_manager_non_locked)
dt_golden = utc_to_ist_dt(10, 0, weekday=0)

# Allowed result
result = gate11.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("11.1 Allowed has timestamp", result.timestamp is not None)
check("11.2 Allowed block_reason empty", result.block_reason == "")
check("11.3 Allowed blocked_by empty", len(result.blocked_by) == 0)

# Permissions disabled today (all checks pass but data health CRITICAL)
result = gate11.check_all(
    timestamp=dt_golden,
    floor_summary=make_floor_summary(DataHealth.CRITICAL),
    psychology_report=make_psychology_report(True),
    active_trade=False,
    current_mode=ExecutionMode.PAPER,
    capital_available=50000.0,
)
check("11.4 CRITICAL health has timestamp", result.timestamp is not None)
check("11.5 CRITICAL health block_reason not empty", result.block_reason != "")
check("11.6 CRITICAL health has 1 blocked_by", len(result.blocked_by) == 1)

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
