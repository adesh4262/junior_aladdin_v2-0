"""Unit tests for ``loss_lock_manager.py`` — Floor 5 Step 5.3.

Tests:
- LossLockManager initial state
- record_loss() in REAL mode: 0→1, 1→2, 2→3 (lock), 3+ (stays locked)
- Losses in ALERT/PAPER mode do NOT count
- is_locked() after various loss states
- get_loss_count() returns correct count
- get_remaining_losses_before_lock() correct
- reset_counter() clears lock and count
- set_mode/get_mode correct
- get_loss_history() returns recorded losses
- get_lock_summary() returns all fields
- check_and_reset_if_new_day() resets on new day
- check_and_reset_if_new_day() does NOT reset on same day
- Configurable MAX_LOSSES (e.g., 5)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import date, timedelta

from junior_aladdin.floor_5_captain.loss_lock_manager import LossLockManager
from junior_aladdin.shared.types import ExecutionMode

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


print("=" * 60)
print("Floor 5 — Loss Lock Manager Tests")
print("=" * 60)

# =========================================================================
# 1. Initial state
# =========================================================================
print("\n--- 1. Initial state ---")

llm = LossLockManager()
check("1.1 Initial loss count 0", llm.get_loss_count() == 0)
check("1.2 Initial not locked", llm.is_locked() is False)
check("1.3 Initial remaining = MAX", llm.get_remaining_losses_before_lock() == llm.MAX_LOSSES)
check("1.4 Default MAX_LOSSES = 3", llm.MAX_LOSSES == 3)
check("1.5 Loss history empty", len(llm.get_loss_history()) == 0)
check("1.6 Default mode ALERT", llm.get_mode() == ExecutionMode.ALERT)

summary = llm.get_lock_summary()
check("1.7 Summary has loss_count", summary.get("loss_count") == 0)
check("1.8 Summary has is_locked False", summary.get("is_locked") is False)
check("1.9 Summary has max_losses", summary.get("max_losses") == 3)
check("1.10 Summary has current_mode", summary.get("current_mode") == "ALERT")

# =========================================================================
# 2. ALERT mode losses do NOT count
# =========================================================================
print("\n--- 2. ALERT mode losses do NOT count ---")

llm_alert = LossLockManager()
llm_alert.set_mode(ExecutionMode.ALERT)

result = llm_alert.record_loss({"symbol": "NIFTY", "pnl": -500})
check("2.1 ALERT loss does not trigger lock", result is False)
check("2.2 ALERT loss count still 0", llm_alert.get_loss_count() == 0)
check("2.3 ALERT not locked", llm_alert.is_locked() is False)

# =========================================================================
# 3. PAPER mode losses do NOT count
# =========================================================================
print("\n--- 3. PAPER mode losses do NOT count ---")

llm_paper = LossLockManager()
llm_paper.set_mode(ExecutionMode.PAPER)

for i in range(5):
    llm_paper.record_loss({"pnl": -200 * (i + 1)})

check("3.1 5 PAPER losses count still 0", llm_paper.get_loss_count() == 0)
check("3.2 PAPER not locked even after 5 losses", llm_paper.is_locked() is False)
check("3.3 PAPER remaining = MAX", llm_paper.get_remaining_losses_before_lock() == 3)

# =========================================================================
# 4. REAL mode: 3 losses → lock
# =========================================================================
print("\n--- 4. REAL mode: 3 losses -> lock ---")

llm_real = LossLockManager()
llm_real.set_mode(ExecutionMode.REAL)

# Loss 1
result1 = llm_real.record_loss({"symbol": "NIFTY", "pnl": -1000})
check("4.1 Loss 1 does not lock", result1 is False)
check("4.2 Loss 1 count = 1", llm_real.get_loss_count() == 1)
check("4.3 Loss 1 not locked", llm_real.is_locked() is False)
check("4.4 Loss 1 remaining = 2", llm_real.get_remaining_losses_before_lock() == 2)

# Loss 2
result2 = llm_real.record_loss({"symbol": "BANKNIFTY", "pnl": -2000})
check("4.5 Loss 2 does not lock", result2 is False)
check("4.6 Loss 2 count = 2", llm_real.get_loss_count() == 2)
check("4.7 Loss 2 remaining = 1", llm_real.get_remaining_losses_before_lock() == 1)

# Loss 3 — should lock
result3 = llm_real.record_loss({"symbol": "NIFTY", "pnl": -1500})
check("4.8 Loss 3 -> lock", result3 is True)
check("4.9 Loss 3 count = 3", llm_real.get_loss_count() == 3)
check("4.10 Loss 3 locked", llm_real.is_locked() is True)
check("4.11 Loss 3 remaining = 0", llm_real.get_remaining_losses_before_lock() == 0)

# Additional loss stays locked
result4 = llm_real.record_loss({"symbol": "FINNIFTY", "pnl": -3000})
check("4.12 Extra loss stays locked (locked was already True)", result4 is True)
check("4.13 Extra loss count = 4", llm_real.get_loss_count() == 4)
check("4.14 Extra loss still locked", llm_real.is_locked() is True)
check("4.15 Extra loss remaining = 0", llm_real.get_remaining_losses_before_lock() == 0)

# =========================================================================
# 5. Loss history
# =========================================================================
print("\n--- 5. Loss history ---")

llm_hist = LossLockManager()
llm_hist.set_mode(ExecutionMode.REAL)
llm_hist.record_loss({"symbol": "NIFTY", "pnl": -500})
llm_hist.record_loss({"symbol": "BANKNIFTY", "pnl": -1000})
llm_hist.record_loss({"symbol": "NIFTY", "pnl": -800})

history = llm_hist.get_loss_history()
check("5.1 History has 3 records", len(history) == 3)
check("5.2 First loss has symbol", history[0].get("symbol") == "NIFTY")
check("5.3 First loss has mode REAL", history[0].get("mode") == "REAL")
check("5.4 Second loss has BANKNIFTY", history[1].get("symbol") == "BANKNIFTY")
check("5.5 Third loss has NIFTY", history[2].get("symbol") == "NIFTY")
check("5.6 All records have timestamp", all("timestamp" in r for r in history))
check("5.7 Second loss count = 2", history[1].get("loss_count_at_time") == 2)

# =========================================================================
# 6. reset_counter() clears lock and count
# =========================================================================
print("\n--- 6. reset_counter() ---")

llm_reset = LossLockManager()
llm_reset.set_mode(ExecutionMode.REAL)
llm_reset.record_loss()
llm_reset.record_loss()
llm_reset.record_loss()
check("6.1 Locked before reset", llm_reset.is_locked() is True)
check("6.2 Count 3 before reset", llm_reset.get_loss_count() == 3)

llm_reset.reset_counter()
check("6.3 Count 0 after reset", llm_reset.get_loss_count() == 0)
check("6.4 Not locked after reset", llm_reset.is_locked() is False)
check("6.5 Remaining = MAX after reset", llm_reset.get_remaining_losses_before_lock() == 3)
check("6.6 History empty after reset", len(llm_reset.get_loss_history()) == 0)

# =========================================================================
# 7. set_mode() / get_mode()
# =========================================================================
print("\n--- 7. set_mode() / get_mode() ---")

llm_mode = LossLockManager()
check("7.1 Default ALERT", llm_mode.get_mode() == ExecutionMode.ALERT)

llm_mode.set_mode(ExecutionMode.PAPER)
check("7.2 Set PAPER", llm_mode.get_mode() == ExecutionMode.PAPER)

llm_mode.set_mode(ExecutionMode.REAL)
check("7.3 Set REAL", llm_mode.get_mode() == ExecutionMode.REAL)

llm_mode.set_mode(ExecutionMode.ALERT)
check("7.4 Set back to ALERT", llm_mode.get_mode() == ExecutionMode.ALERT)

# =========================================================================
# 8. check_and_reset_if_new_day()
# =========================================================================
print("\n--- 8. check_and_reset_if_new_day() ---")

llm_day = LossLockManager()
llm_day.set_mode(ExecutionMode.REAL)
llm_day.record_loss()
llm_day.record_loss()
llm_day.record_loss()
check("8.1 Locked", llm_day.is_locked() is True)

# Same day — no reset
today = date.today()
check("8.2 Same day no reset", llm_day.check_and_reset_if_new_day(today) is False)
check("8.3 Still locked same day", llm_day.is_locked() is True)

# Next day — should reset
tomorrow = today + timedelta(days=1)
check("8.4 New day resets", llm_day.check_and_reset_if_new_day(tomorrow) is True)
check("8.5 Not locked after new day", llm_day.is_locked() is False)
check("8.6 Count 0 after new day", llm_day.get_loss_count() == 0)

# After reset, another same-day check does nothing
check("8.7 Same day after reset no reset", llm_day.check_and_reset_if_new_day(tomorrow) is False)

# =========================================================================
# 9. Configurable MAX_LOSSES
# =========================================================================
print("\n--- 9. Configurable MAX_LOSSES ---")

llm_config = LossLockManager(max_losses=5)
check("9.1 Custom MAX_LOSSES = 5", llm_config.MAX_LOSSES == 5)
check("9.2 Custom remaining = 5", llm_config.get_remaining_losses_before_lock() == 5)

llm_config.set_mode(ExecutionMode.REAL)
for i in range(4):
    llm_config.record_loss()
check("9.3 4 losses, not locked yet", llm_config.is_locked() is False)
check("9.4 4 losses, remaining = 1", llm_config.get_remaining_losses_before_lock() == 1)

llm_config.record_loss()
check("9.5 5 losses, locked", llm_config.is_locked() is True)
check("9.6 5 losses, remaining = 0", llm_config.get_remaining_losses_before_lock() == 0)

# =========================================================================
# 10. REAL mode: 0 losses
# =========================================================================
print("\n--- 10. 0 losses edge case ---")

llm_zero = LossLockManager()
llm_zero.set_mode(ExecutionMode.REAL)
check("10.1 Count 0", llm_zero.get_loss_count() == 0)
check("10.2 Not locked", llm_zero.is_locked() is False)
check("10.3 Remaining = MAX", llm_zero.get_remaining_losses_before_lock() == 3)
check("10.4 History empty", len(llm_zero.get_loss_history()) == 0)

# =========================================================================
# 11. REAL mode: exactly at boundary (2 losses, not locked)
# =========================================================================
print("\n--- 11. Boundary: 2 losses ---")

llm_boundary = LossLockManager()
llm_boundary.set_mode(ExecutionMode.REAL)
llm_boundary.record_loss()
llm_boundary.record_loss()
check("11.1 2 losses count = 2", llm_boundary.get_loss_count() == 2)
check("11.2 2 losses not locked", llm_boundary.is_locked() is False)
check("11.3 2 losses remaining = 1", llm_boundary.get_remaining_losses_before_lock() == 1)

# =========================================================================
# 12. get_lock_summary() after lock
# =========================================================================
print("\n--- 12. get_lock_summary() after lock ---")

llm_summary = LossLockManager()
llm_summary.set_mode(ExecutionMode.REAL)
llm_summary.record_loss()
llm_summary.record_loss()
llm_summary.record_loss()

lock_summ = llm_summary.get_lock_summary()
check("12.1 Summary loss_count = 3", lock_summ.get("loss_count") == 3)
check("12.2 Summary is_locked True", lock_summ.get("is_locked") is True)
check("12.3 Summary remaining = 0", lock_summ.get("remaining_before_lock") == 0)
check("12.4 Summary current_mode = REAL", lock_summ.get("current_mode") == "REAL")
check("12.5 Summary has locked_date", lock_summ.get("locked_date") is not None)
check("12.6 Summary max_losses = 3", lock_summ.get("max_losses") == 3)

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
