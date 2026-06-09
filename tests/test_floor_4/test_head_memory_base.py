"""Unit tests for ``head_memory_base.py`` — Floor 4 Step 4.3.

Tests the TTL-based HeadMemoryStore API:
- remember / recall / forget / clear
- TTL expiry and auto-cleanup
- clear_expired
- get_context
- Eviction at capacity
- Pre-built head configs
- MemoryItem helpers (is_expired, remaining_seconds)
- Error handling (invalid TTL)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta
from time import sleep

from junior_aladdin.floor_4_heads.head_memory_base import (
    HEAD_MACRO_MEMORY_CONFIG,
    HEAD_PSYCHOLOGY_MEMORY_CONFIG,
    HEAD_SMC_MEMORY_CONFIG,
    HEAD_ICT_MEMORY_CONFIG,
    HEAD_TECHNICAL_MEMORY_CONFIG,
    HEAD_OPTIONS_MEMORY_CONFIG,
    HeadMemoryConfig,
    HeadMemoryStore,
    MemoryItem,
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


def approx_equal(a: float, b: float, eps: float = 0.1) -> bool:
    return abs(a - b) < eps


print("=" * 60)
print("Floor 4 — Head Memory Base Tests")
print("=" * 60)

# =========================================================================
# 1. MemoryItem
# =========================================================================
print("\n--- 1. MemoryItem ---")

now = datetime.utcnow()
item = MemoryItem(key="test", value={"data": 123}, ttl_seconds=300,
                  created_at=now, expires_at=now + timedelta(seconds=300))

check("1.1 is_expired returns False for fresh item", not item.is_expired(now))
check("1.2 is_expired returns True for expired item",
      item.is_expired(now + timedelta(seconds=301)))
check("1.3 remaining_seconds ~ 300 for fresh item",
      approx_equal(item.remaining_seconds(now), 300.0))
check("1.4 remaining_seconds = 0 for expired item",
      item.remaining_seconds(now + timedelta(seconds=301)) == 0.0)

# =========================================================================
# 2. Basic remember/recall/forget
# =========================================================================
print("\n--- 2. Basic remember/recall/forget ---")

store = HeadMemoryStore()

store.remember("key1", "value1")
check("2.1 recall returns stored value", store.recall("key1") == "value1")

store.remember("key2", {"nested": "data"})
check("2.2 recall returns complex value",
      store.recall("key2") == {"nested": "data"})

result = store.forget("key1")
check("2.3 forget returns True for existing key", result)
check("2.4 recall after forget returns default",
      store.recall("key1", "default") == "default")

result = store.forget("nonexistent")
check("2.5 forget returns False for missing key", not result)

# =========================================================================
# 3. TTL expiry
# =========================================================================
print("\n--- 3. TTL expiry ---")

store2 = HeadMemoryStore()

# Item with 1-second TTL
store2.remember("short", "expires_soon", ttl_seconds=1)
check("3.1 recall before expiry returns value",
      store2.recall("short") == "expires_soon")

sleep(1.5)

check("3.2 recall after expiry returns default",
      store2.recall("short", "gone") == "gone")

# =========================================================================
# 4. clear_expired
# =========================================================================
print("\n--- 4. clear_expired ---")

store3 = HeadMemoryStore()
store3.remember("keep", "stays", ttl_seconds=300)
store3.remember("gone", "goes", ttl_seconds=1)
store3.remember("keep2", "stays2", ttl_seconds=300)

sleep(1.5)

removed = store3.clear_expired()
check("4.1 clear_expired removes expired items", removed >= 1)
check("4.2 expired item gone", store3.recall("gone") is None)
check("4.3 non-expired items remain", store3.recall("keep") == "stays")
check("4.4 second non-expired item remains", store3.recall("keep2") == "stays2")

# =========================================================================
# 5. get_context
# =========================================================================
print("\n--- 5. get_context ---")

store4 = HeadMemoryStore()
store4.remember("a", 1, ttl_seconds=300)
store4.remember("b", 2, ttl_seconds=300)
store4.remember("c", 3, ttl_seconds=1)

sleep(1.5)

ctx = store4.get_context(clear_expired_first=True)
check("5.1 get_context returns only active items", len(ctx) == 2)
check("5.2 context has key 'a'", "a" in ctx)
check("5.3 context has key 'b'", "b" in ctx)
check("5.4 context value correct", ctx["a"] == 1)
check("5.5 expired key 'c' excluded", "c" not in ctx)

# get_context without clearing
store5 = HeadMemoryStore()
store5.remember("x", 10, ttl_seconds=300)
store5.remember("y", 20, ttl_seconds=1)
sleep(1.5)
ctx5 = store5.get_context(clear_expired_first=False)
check("5.6 get_context without cleanup includes expired", "y" in ctx5)

# =========================================================================
# 6. Auto-cleanup on recall
# =========================================================================
print("\n--- 6. Auto-cleanup on recall ---")

store6 = HeadMemoryStore(config=HeadMemoryConfig(auto_cleanup=True))
store6.remember("auto", "value", ttl_seconds=1)
sleep(1.5)
check("6.1 recall returns None for expired with auto_cleanup",
      store6.recall("auto") is None)
check("6.2 expired item removed from store",
      store6.recall("auto", "not_found") == "not_found")

# Without auto-cleanup
store6b = HeadMemoryStore(config=HeadMemoryConfig(auto_cleanup=False))
store6b.remember("noauto", "value", ttl_seconds=1)
sleep(1.5)
check("6.3 recall returns None without auto-cleanup",
      store6b.recall("noauto") is None)
check("6.4 expired item stays in store without auto-cleanup",
      "noauto" in store6b.keys())

# =========================================================================
# 7. Capacity and eviction
# =========================================================================
print("\n--- 7. Capacity and eviction ---")

store7 = HeadMemoryStore(config=HeadMemoryConfig(max_items=3, default_ttl_seconds=300))
store7.remember("a", 1)
store7.remember("b", 2)
store7.remember("c", 3)
check("7.1 store count = 3", store7.count == 3)

# Adding a 4th item should evict the oldest (a)
store7.remember("d", 4)
check("7.2 store count capped at 3", store7.count == 3)
check("7.3 oldest item 'a' evicted", store7.recall("a") is None)
check("7.4 new item 'd' present", store7.recall("d") == 4)
check("7.5 'b' still present", store7.recall("b") == 2)
check("7.6 'c' still present", store7.recall("c") == 3)

# Eviction prefers expired items
store7b = HeadMemoryStore(config=HeadMemoryConfig(max_items=2, default_ttl_seconds=1))
store7b.remember("x", 10)
sleep(1.5)
store7b.remember("y", 20)  # x is now expired
store7b.remember("z", 30)  # should evict expired x first
check("7.7 expired item evicted first", store7b.recall("x") is None)
check("7.8 y still present", store7b.recall("y") == 20)
check("7.9 z present", store7b.recall("z") == 30)

# =========================================================================
# 8. clear()
# =========================================================================
print("\n--- 8. clear() ---")

store8 = HeadMemoryStore()
store8.remember("a", 1, ttl_seconds=300)
store8.remember("b", 2, ttl_seconds=300)
store8.clear()
check("8.1 clear removes all items", store8.count == 0)
check("8.2 recall after clear returns default",
      store8.recall("a", None) is None)

# =========================================================================
# 9. Invalid TTL
# =========================================================================
print("\n--- 9. Invalid TTL ---")

store9 = HeadMemoryStore()
try:
    store9.remember("bad", "value", ttl_seconds=0)
    check("9.1 TTL=0 raises ValueError", False)
except ValueError:
    check("9.1 TTL=0 raises ValueError", True)

try:
    store9.remember("bad2", "value", ttl_seconds=-1)
    check("9.2 Negative TTL raises ValueError", False)
except ValueError:
    check("9.2 Negative TTL raises ValueError", True)

# =========================================================================
# 10. active_count
# =========================================================================
print("\n--- 10. active_count ---")

store10 = HeadMemoryStore()
store10.remember("a", 1, ttl_seconds=300)
store10.remember("b", 2, ttl_seconds=300)
store10.remember("c", 3, ttl_seconds=1)
sleep(1.5)
check("10.1 active_count excludes expired", store10.active_count() == 2)

# =========================================================================
# 11. Overwrite existing key
# =========================================================================
print("\n--- 11. Overwrite ---")

store11 = HeadMemoryStore()
store11.remember("key", "old_value", ttl_seconds=300)
store11.remember("key", "new_value", ttl_seconds=300)
check("11.1 overwrite replaces value",
      store11.recall("key") == "new_value")

# =========================================================================
# 12. Pre-built configs
# =========================================================================
print("\n--- 12. Pre-built configs ---")

check("12.1 SMC config ttl=600", HEAD_SMC_MEMORY_CONFIG.default_ttl_seconds == 600)
check("12.2 ICT config ttl=600", HEAD_ICT_MEMORY_CONFIG.default_ttl_seconds == 600)
check("12.3 Technical config ttl=300",
      HEAD_TECHNICAL_MEMORY_CONFIG.default_ttl_seconds == 300)
check("12.4 Options config ttl=300",
      HEAD_OPTIONS_MEMORY_CONFIG.default_ttl_seconds == 300)
check("12.5 Macro config ttl=900",
      HEAD_MACRO_MEMORY_CONFIG.default_ttl_seconds == 900)
check("12.6 Psychology config ttl=600",
      HEAD_PSYCHOLOGY_MEMORY_CONFIG.default_ttl_seconds == 600)

# =========================================================================
# 13. Custom config via constructor
# =========================================================================
print("\n--- 13. Custom config ---")

custom_cfg = HeadMemoryConfig(default_ttl_seconds=60, max_items=5)
store13 = HeadMemoryStore(config=custom_cfg)
store13.remember("key", "val")
check("13.1 custom config applied",
      store13.recall("key") == "val")
check("13.2 max_items=5 from config",
      store13.config.max_items == 5)

# =========================================================================
# 14. recall() for non-existent key returns default
# =========================================================================
print("\n--- 14. Non-existent key ---")

store14 = HeadMemoryStore()
check("14.1 recall missing key returns default",
      store14.recall("missing", 42) == 42)
check("14.2 recall missing key returns None",
      store14.recall("missing2") is None)


# =========================================================================
# Summary
# =========================================================================
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if failed > 0:
    sys.exit(1)
else:
    sys.exit(0)
