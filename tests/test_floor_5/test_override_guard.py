"""Unit tests for ``override_guard.py`` — Floor 5 Step 5.3.

Tests:
- OverrideGuard initial state
- require_override() sets override required
- is_override_required() correct
- grant_override() grants and clears required flag
- grant_override() when not required returns False
- deny_override() denies and clears flags
- is_override_granted() correct after grant/deny
- clear_override() resets state
- log_override() records events
- get_override_history() returns records
- get_override_count() correct
- get_override_summary() returns all fields
- Full flow: require → grant → trade → clear → require again
- OverrideRecord dataclass fields all present
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from junior_aladdin.floor_5_captain.override_guard import OverrideGuard, OverrideRecord

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
print("Floor 5 — Override Guard Tests")
print("=" * 60)

# =========================================================================
# 1. Initial state
# =========================================================================
print("\n--- 1. Initial state ---")

og = OverrideGuard()
check("1.1 Override not required initially", og.is_override_required() is False)
check("1.2 Override not granted initially", og.is_override_granted() is False)
check("1.3 No current override", og.get_current_override() is None)
check("1.4 History empty", len(og.get_override_history()) == 0)
check("1.5 Override count 0", og.get_override_count() == 0)

summary = og.get_override_summary()
check("1.6 Summary override_required False", summary.get("override_required") is False)
check("1.7 Summary override_granted False", summary.get("override_granted") is False)
check("1.8 Summary total_overrides 0", summary.get("total_overrides") == 0)
check("1.9 Summary has_active_override False", summary.get("has_active_override") is False)
check("1.10 Summary has granted_count 0", summary.get("granted_count") == 0)

# =========================================================================
# 2. require_override()
# =========================================================================
print("\n--- 2. require_override() ---")

og2 = OverrideGuard()
og2.require_override("REAL mode loss lock active")
check("2.1 Override required after require()", og2.is_override_required() is True)
check("2.2 Override not granted yet", og2.is_override_granted() is False)
check("2.3 Current override exists", og2.get_current_override() is not None)
check("2.4 Current override not granted",
      og2.get_current_override() is not None and og2.get_current_override().granted is False)
check("2.5 Current override has reason", og2.get_current_override() is not None
      and "loss lock" in og2.get_current_override().reason)

# =========================================================================
# 3. grant_override()
# =========================================================================
print("\n--- 3. grant_override() ---")

og3 = OverrideGuard()
og3.require_override()

# Grant with reason
result = og3.grant_override("Market conditions exceptional, will monitor closely", {"symbol": "NIFTY"})
check("3.1 grant_override returns True", result is True)
check("3.2 Override required cleared after grant", og3.is_override_required() is False)
check("3.3 Override granted True", og3.is_override_granted() is True)
check("3.4 Override count = 1", og3.get_override_count() == 1)
check("3.5 History has 1 record", len(og3.get_override_history()) == 1)
check("3.6 Current override cleared after grant", og3.get_current_override() is None)
check("3.7 Grant recorded in history", og3.get_override_count() == 1
      and og3.get_override_history()[0].granted is True)

# Verify the record
record = og3.get_override_history()[0]
check("3.8 Record has override_id", len(record.override_id) > 0)
check("3.9 Record has timestamp", record.timestamp is not None)
check("3.10 Record has granted True", record.granted is True)
check("3.11 Record has operator reason", "exceptional" in record.reason)
check("3.12 Record has symbol in details", record.details.get("symbol") == "NIFTY")

# =========================================================================
# 4. grant_override() when not required
# =========================================================================
print("\n--- 4. grant_override() when not required ---")

og4 = OverrideGuard()
result = og4.grant_override("Testing")
check("4.1 Returns False when no override required", result is False)
check("4.2 Override not granted", og4.is_override_granted() is False)
check("4.3 Count still 0", og4.get_override_count() == 0)

# =========================================================================
# 5. deny_override()
# =========================================================================
print("\n--- 5. deny_override() ---")

og5 = OverrideGuard()
og5.require_override()
check("5.1 Override required before deny", og5.is_override_required() is True)

og5.deny_override("Too risky, markets too volatile")
check("5.2 Override not required after deny", og5.is_override_required() is False)
check("5.3 Override not granted after deny", og5.is_override_granted() is False)
check("5.4 Count = 1", og5.get_override_count() == 1)
check("5.5 History has 1 record", len(og5.get_override_history()) == 1)
check("5.6 No current override after deny", og5.get_current_override() is None)

record5 = og5.get_override_history()[0]
check("5.7 Denied record granted False", record5.granted is False)
check("5.8 Denied record has reason", "volatile" in record5.reason)

# =========================================================================
# 6. clear_override()
# =========================================================================
print("\n--- 6. clear_override() ---")

og6 = OverrideGuard()
og6.require_override()
og6.grant_override("Proceed", {"trade_id": "T001"})
check("6.1 Override granted before clear", og6.is_override_granted() is True)

og6.clear_override()
check("6.2 Override not required after clear", og6.is_override_required() is False)
check("6.3 Override not granted after clear", og6.is_override_granted() is False)
check("6.4 No current override after clear", og6.get_current_override() is None)
check("6.5 History preserved after clear", og6.get_override_count() == 1)

# =========================================================================
# 7. log_override()
# =========================================================================
print("\n--- 7. log_override() ---")

og7 = OverrideGuard()

# Log without active override
record7a = og7.log_override({"reason": "Audit checkpoint"})
check("7.1 log returns record even without active override", record7a is not None)
check("7.2 Count = 1 after log", og7.get_override_count() == 1)
check("7.3 Standalone entry not granted", record7a is not None and record7a.granted is False)

# After grant_override clears _current_override, log_override creates a standalone entry
og7.require_override()
og7.grant_override("Approved", {"trade_id": "T002"})
check("7.4 Count = 2 after grant", og7.get_override_count() == 2)

record7b = og7.log_override({"checkpoint": "post_trade"})
check("7.5 Count = 3 after explicit log (standalone2)", og7.get_override_count() == 3)
check("7.6 Third record has checkpoint", record7b is not None
      and record7b.details.get("checkpoint") == "post_trade")

# =========================================================================
# 8. Full workflow: require → grant → clear → require again
# =========================================================================
print("\n--- 8. Full workflow cycle ---")

og8 = OverrideGuard()

# Trade 1 — require, grant, clear
og8.require_override("Real mode lock, trade 1")
og8.grant_override("Dual setup confluence strong", {"trade_id": "T001"})
check("8.1 Trade 1 granted", og8.is_override_granted() is True)
og8.clear_override()
check("8.2 Trade 1 cleared", og8.is_override_granted() is False)
check("8.3 Count = 1 after trade 1", og8.get_override_count() == 1)

# Trade 2 — require again (fresh override needed)
og8.require_override("Real mode lock, trade 2")
check("8.4 Trade 2 requires fresh override", og8.is_override_required() is True)
og8.grant_override("Price at key level, good RR", {"trade_id": "T002"})
check("8.5 Trade 2 granted", og8.is_override_granted() is True)
og8.clear_override()
check("8.6 Trade 2 cleared", og8.is_override_granted() is False)
check("8.7 Count = 2 after trade 2", og8.get_override_count() == 2)

# Trade 3 — denied
og8.require_override("Real mode lock, trade 3")
og8.deny_override("Choppy market, no edge")
check("8.8 Trade 3 denied", og8.is_override_granted() is False)
check("8.9 Count = 3 after trade 3", og8.get_override_count() == 3)
check("8.10 History has 3 records", len(og8.get_override_history()) == 3)

# =========================================================================
# 9. get_override_summary()
# =========================================================================
print("\n--- 9. get_override_summary() ---")

og9 = OverrideGuard()
og9.require_override()
og9.grant_override("Test grant")
# deny_override after grant is a no-op (current override already cleared)
# so history = [granted_record]
og9.deny_override("Test deny")
check("9.0 Count still 1 after no-op deny", og9.get_override_count() == 1)

# Log an auditable entry
og9.log_override({"reason": "Routine checkpoint"})
# history = [granted_record, standalone]

summary9 = og9.get_override_summary()
check("9.1 Summary total = 2", summary9.get("total_overrides") == 2)
check("9.2 Summary granted_count = 1", summary9.get("granted_count") == 1)
check("9.3 Summary denied_count = 1", summary9.get("denied_count") == 1)
check("9.4 Summary override_required False", summary9.get("override_required") is False)
check("9.5 Summary override_granted False", summary9.get("override_granted") is False)
check("9.6 Summary has_active_override False", summary9.get("has_active_override") is False)

# =========================================================================
# 10. OverrideRecord dataclass
# =========================================================================
print("\n--- 10. OverrideRecord dataclass ---")

from dataclasses import fields

record = OverrideRecord()
check("10.1 Record has override_id", len(record.override_id) > 0)
check("10.2 Record has timestamp", record.timestamp is not None)
check("10.3 Record granted default False", record.granted is False)
check("10.4 Record reason default empty", record.reason == "")
check("10.5 Record details default empty", record.details == {})
check("10.6 Total 5 fields", len(fields(OverrideRecord)) == 5)

record_custom = OverrideRecord(
    override_id="test-id-001",
    granted=True,
    reason="Operator consent",
    details={"mode": "REAL", "loss_count": 3},
)
check("10.7 Custom override_id", record_custom.override_id == "test-id-001")
check("10.8 Custom granted True", record_custom.granted is True)
check("10.9 Custom reason", record_custom.reason == "Operator consent")
check("10.10 Custom details", record_custom.details.get("loss_count") == 3)

# =========================================================================
# 11. Edge: double require_override()
# =========================================================================
print("\n--- 11. Edge: double require_override() ---")

og11 = OverrideGuard()
og11.require_override("First")
og11.require_override("Second")  # Second call should override first
check("11.1 Override required after double", og11.is_override_required() is True)
check("11.2 Override not granted", og11.is_override_granted() is False)

# Grant after double require
og11.grant_override("After double require")
check("11.3 Grant works after double require", og11.is_override_granted() is True)
check("11.4 Count = 1", og11.get_override_count() == 1)

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
