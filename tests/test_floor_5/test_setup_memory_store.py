"""Unit tests for ``setup_memory_store.py`` — Floor 5 Step 5.12.

Tests:
- SetupRecord and ZoneMemory dataclass instantiation
- store_setup() creates ACTIVE setup and tracks zone
- update_setup() modifies fields
- mark_rejected() sets status + reason
- mark_completed() sets status
- get_setup(), get_active_setups(), get_rejected_setups()
- get_all_setups(), get_setup_count(), get_rejected_count()
- mark_failed_zone() increments trap count and marks failed
- get_trap_count() returns correct count
- is_failed_zone() returns correct bool
- get_all_zones(), get_failed_zones(), get_zone_count()
- clear_session() resets all memory
- has_active_setups()
- get_store_summary() dict
- Multiple zones tracked independently
- Zone auto-created on first store_setup with zone_label
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_5_captain.setup_memory_store import (
    SetupMemoryStore,
    SetupRecord,
    ZoneMemory,
)
from junior_aladdin.shared.types import TradeClass

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


store = SetupMemoryStore()

print("=" * 60)
print("Floor 5 -- Setup Memory Store Tests")
print("=" * 60)

# =========================================================================
# 1. Dataclass instantiation
# =========================================================================
print("\n--- 1. Dataclass creation ---")

rec = SetupRecord(setup_id="S1", direction="BUY")
check("1.1 SetupRecord has setup_id", rec.setup_id == "S1")
check("1.2 SetupRecord default status ACTIVE", rec.status == "ACTIVE")
check("1.3 SetupRecord has created_at", rec.created_at is not None)

zone = ZoneMemory(zone_label="FVG_19500")
check("1.4 ZoneMemory has zone_label", zone.zone_label == "FVG_19500")
check("1.5 ZoneMemory default trap_count 0", zone.trap_count == 0)
check("1.6 ZoneMemory default failed False", zone.failed is False)

# =========================================================================
# 2. store_setup creates ACTIVE setup
# =========================================================================
print("\n--- 2. store_setup ---")

rec = store.store_setup(
    setup_id="S2",
    direction="BUY",
    trade_class=TradeClass.CONTINUATION,
    zone_label="OB_19450",
    zone_price=19450.0,
    source_head="SMC Head",
)

check("2.1 Setup ID stored", rec.setup_id == "S2")
check("2.2 Direction stored", rec.direction == "BUY")
check("2.3 Trade class stored", rec.trade_class == TradeClass.CONTINUATION)
check("2.4 Zone label stored", rec.zone_label == "OB_19450")
check("2.5 Zone price stored", rec.zone_price == 19450.0)
check("2.6 Source head stored", rec.source_head == "SMC Head")
check("2.7 Status is ACTIVE", rec.status == "ACTIVE")
check("2.8 Zone auto-created", store.get_trap_count("OB_19450") == 0)

# =========================================================================
# 3. update_setup modifies fields
# =========================================================================
print("\n--- 3. update_setup ---")

updated = store.update_setup("S2", status="REJECTED", rejection_reason="Test")
check("3.1 Update returns record", updated is not None)
check("3.2 Status changed", updated.status == "REJECTED" if updated else False)
check("3.3 Reason stored", updated.rejection_reason == "Test" if updated else False)
check("3.4 updated_at not None", updated.updated_at is not None if updated else False)

# Unknown setup returns None
check("3.5 Unknown setup returns None",
      store.update_setup("UNKNOWN", status="ACTIVE") is None)

# Reset for next tests
store.store_setup(setup_id="S2", direction="BUY")  # Re-create

# =========================================================================
# 4. mark_rejected
# =========================================================================
print("\n--- 4. mark_rejected ---")

rec = store.mark_rejected("S2", reason="Weak confluence")
check("4.1 Status set to REJECTED", rec is not None and rec.status == "REJECTED")
check("4.2 Reason stored", rec is not None and rec.rejection_reason == "Weak confluence")

# Unknown setup
check("4.3 Unknown setup returns None",
      store.mark_rejected("UNKNOWN", reason="X") is None)

# =========================================================================
# 5. mark_completed
# =========================================================================
print("\n--- 5. mark_completed ---")

store.store_setup(setup_id="S3", direction="SELL")
rec = store.mark_completed("S3")
check("5.1 Status set to COMPLETED",
      rec is not None and rec.status == "COMPLETED")

# Unknown setup
check("5.2 Unknown setup returns None",
      store.mark_completed("UNKNOWN") is None)

# =========================================================================
# 6. get_setup by ID
# =========================================================================
print("\n--- 6. get_setup ---")

rec = store.get_setup("S3")
check("6.1 Get existing setup", rec is not None and rec.setup_id == "S3")

rec = store.get_setup("UNKNOWN")
check("6.2 Get unknown setup", rec is None)

# =========================================================================
# 7. get_active_setups
# =========================================================================
print("\n--- 7. get_active_setups ---")

store.store_setup(setup_id="S4", direction="BUY", zone_label="Zone_A")
store.store_setup(setup_id="S5", direction="SELL", zone_label="Zone_B")

active = store.get_active_setups()
check("7.1 Has active setups", len(active) >= 2)
check("7.2 All active have ACTIVE status",
      all(s.status == "ACTIVE" for s in active))

# =========================================================================
# 8. get_rejected_setups
# =========================================================================
print("\n--- 8. get_rejected_setups ---")

rejected = store.get_rejected_setups()
check("8.1 Has rejected setups", len(rejected) > 0)
check("8.2 All rejected have REJECTED status",
      all(s.status == "REJECTED" for s in rejected))

# =========================================================================
# 9. get_all_setups, get_setup_count, get_rejected_count
# =========================================================================
print("\n--- 9. Setup counts ---")

all_setups = store.get_all_setups()
check("9.1 get_all_setups returns list", len(all_setups) >= 4)
check("9.2 get_setup_count > 0", store.get_setup_count() >= 4)
check("9.3 get_rejected_count > 0", store.get_rejected_count() >= 1)

# =========================================================================
# 10. Zone trap tracking
# =========================================================================
print("\n--- 10. Zone trap tracking ---")

# Mark a zone as failed
zone = store.mark_failed_zone("FVG_19500")
check("10.1 Failed zone has trap_count 1", zone.trap_count == 1)
check("10.2 Zone marked failed", zone.failed is True)
check("10.3 last_trap_at set", zone.last_trap_at is not None)

# Mark same zone again
store.mark_failed_zone("FVG_19500")
check("10.4 Second trap increments to 2",
      store.get_trap_count("FVG_19500") == 2)

# Mark another zone
store.mark_failed_zone("OB_19300")
check("10.5 Different zone tracked independently",
      store.get_trap_count("OB_19300") == 1)
check("10.6 First zone still 2",
      store.get_trap_count("FVG_19500") == 2)

# Untracked zone
check("10.7 Untracked zone has 0 traps",
      store.get_trap_count("GHOST_ZONE") == 0)

# =========================================================================
# 11. is_failed_zone
# =========================================================================
print("\n--- 11. is_failed_zone ---")

check("11.1 Failed zone is detected",
      store.is_failed_zone("FVG_19500") is True)
check("11.2 Untracked zone is not failed",
      store.is_failed_zone("GHOST_ZONE") is False)

# Active zone (tracked but not failed)
check("11.3 Active zone (Zone_A) not failed",
      store.is_failed_zone("Zone_A") is False)

# =========================================================================
# 12. get_all_zones, get_failed_zones, get_zone_count
# =========================================================================
print("\n--- 12. Zone queries ---")

all_zones = store.get_all_zones()
check("12.1 get_all_zones returns list", len(all_zones) >= 4)

failed_zones = store.get_failed_zones()
check("12.2 Failed zones > 0", len(failed_zones) > 0)
check("12.3 All failed zones have failed True",
      all(z.failed for z in failed_zones))
check("12.4 get_zone_count > 0", store.get_zone_count() >= 4)

# =========================================================================
# 13. clear_session resets all memory
# =========================================================================
print("\n--- 13. clear_session ---")

store.clear_session()
check("13.1 No setups after clear", store.get_setup_count() == 0)
check("13.2 No zones after clear", store.get_zone_count() == 0)
check("13.3 No active setups", store.has_active_setups() is False)
check("13.4 get_active_setups empty", len(store.get_active_setups()) == 0)
check("13.5 get_rejected_setups empty", len(store.get_rejected_setups()) == 0)

# =========================================================================
# 14. has_active_setups
# =========================================================================
print("\n--- 14. has_active_setups ---")

store.clear_session()
check("14.1 No active after clear", store.has_active_setups() is False)

store.store_setup(setup_id="A1", direction="BUY")
check("14.2 Active after store", store.has_active_setups() is True)

store.mark_rejected("A1", reason="Test")
check("14.3 No active after all rejected", store.has_active_setups() is False)

store.store_setup(setup_id="A2", direction="SELL")
store.mark_completed("A2")
check("14.4 COMPLETED is not ACTIVE", store.has_active_setups() is False)

# =========================================================================
# 15. get_store_summary dict
# =========================================================================
print("\n--- 15. get_store_summary ---")

store.clear_session()
store.store_setup(setup_id="X1", direction="BUY", zone_label="Z1")
store.store_setup(setup_id="X2", direction="SELL", zone_label="Z2")
store.mark_rejected("X2", reason="Weak")
store.mark_failed_zone("Z3")

summary = store.get_store_summary()
check("15.1 Summary has total_setups", summary.get("total_setups") >= 1)
check("15.2 Summary has active_setups", summary.get("active_setups") >= 1)
check("15.3 Summary has rejected_setups", summary.get("rejected_setups") >= 1)
check("15.4 Summary has total_zones", summary.get("total_zones") >= 2)
check("15.5 Summary has failed_zones", summary.get("failed_zones") >= 1)
check("15.6 Summary has has_active", summary.get("has_active") is True)

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
