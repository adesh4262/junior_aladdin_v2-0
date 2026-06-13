"""Pytest tests for Side B SessionCache.

Tests the in-memory three-tier cache:
  - CacheEntry creation, expiry, age
  - Basic get/set with tier awareness
  - HOT / WARM / COLD tier TTLs
  - Expiry detection and auto-cleanup
  - Eviction when max_entries exceeded
  - Invalidation (single key, tier, clear)
  - Cache stats (hits, misses, hit ratio)
  - All-keys listing
  - Edge cases (nonexistent keys, tier mismatch, empty cache)

Reference: ROADMAP_SIDE_B Step 8.3
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from junior_aladdin.side_b_api.session_cache import (
    CacheEntry,
    CacheTier,
    SessionCache,
    _now,
    _ttl_delta,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def cache() -> SessionCache:
    """Provide a fresh SessionCache for each test."""
    return SessionCache(max_entries=100)


# ══════════════════════════════════════════════════════════════
#  1. CacheEntry Tests
# ══════════════════════════════════════════════════════════════


class TestCacheEntry:
    """Verify CacheEntry creation and metadata."""

    def test_created_at_is_set(self) -> None:
        """Entry has a valid created_at timestamp."""
        entry = CacheEntry("value", CacheTier.HOT)
        assert isinstance(entry.created_at, datetime)

    def test_expires_at_is_set(self) -> None:
        """Entry has a valid expires_at timestamp."""
        entry = CacheEntry("value", CacheTier.HOT)
        assert isinstance(entry.expires_at, datetime)
        assert entry.expires_at > entry.created_at

    def test_hits_start_at_zero(self) -> None:
        """Hit counter starts at 0."""
        entry = CacheEntry("value", CacheTier.WARM)
        assert entry.hits == 0

    def test_tier_stored(self) -> None:
        """Tier is stored correctly."""
        entry = CacheEntry("value", CacheTier.COLD)
        assert entry.tier == CacheTier.COLD

    def test_is_expired_false_initially(self) -> None:
        """Entry is not expired immediately after creation."""
        entry = CacheEntry("value", CacheTier.HOT)
        assert not entry.is_expired

    def test_age_s_is_positive(self) -> None:
        """Age in seconds is positive."""
        entry = CacheEntry("value", CacheTier.HOT)
        assert entry.age_s >= 0.0


class TestTTLDelta:
    """Verify TTL delta calculations."""

    def test_hot_ttl_is_500ms(self) -> None:
        """HOT tier TTL is 500ms."""
        delta = _ttl_delta(CacheTier.HOT)
        assert delta == timedelta(milliseconds=500)

    def test_warm_ttl_is_3s(self) -> None:
        """WARM tier TTL is 3s."""
        delta = _ttl_delta(CacheTier.WARM)
        assert delta == timedelta(seconds=3)

    def test_cold_ttl_is_30s(self) -> None:
        """COLD tier TTL is 30s."""
        delta = _ttl_delta(CacheTier.COLD)
        assert delta == timedelta(seconds=30)


# ══════════════════════════════════════════════════════════════
#  2. Basic get/set Tests
# ══════════════════════════════════════════════════════════════


class TestGetSet:
    """Verify basic cache get/set operations."""

    def test_set_and_get(self, cache: SessionCache) -> None:
        """Stored value is retrievable."""
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent_key(self, cache: SessionCache) -> None:
        """Non-existent key returns None."""
        assert cache.get("no_such_key") is None

    def test_set_overwrites_existing(self, cache: SessionCache) -> None:
        """Setting the same key overwrites old value."""
        cache.set("key1", "old")
        cache.set("key1", "new")
        assert cache.get("key1") == "new"

    def test_get_with_tier_filter_match(self, cache: SessionCache) -> None:
        """get with matching tier returns value."""
        cache.set("hot_key", {"data": 1}, CacheTier.HOT)
        assert cache.get("hot_key", CacheTier.HOT) == {"data": 1}

    def test_get_with_tier_filter_mismatch(self, cache: SessionCache) -> None:
        """get with non-matching tier returns None."""
        cache.set("hot_key", {"data": 1}, CacheTier.HOT)
        assert cache.get("hot_key", CacheTier.WARM) is None

    def test_set_default_tier_is_cold(self, cache: SessionCache) -> None:
        """Default tier for set() is COLD."""
        cache.set("default_key", "val")
        entry = cache._store["default_key"]
        assert entry.tier == CacheTier.COLD

    def test_multiple_keys(self, cache: SessionCache) -> None:
        """Multiple keys can be stored and retrieved independently."""
        cache.set("a", 1, CacheTier.HOT)
        cache.set("b", 2, CacheTier.WARM)
        cache.set("c", 3, CacheTier.COLD)
        assert cache.get("a") == 1
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_dict_value(self, cache: SessionCache) -> None:
        """Dict values are stored and retrieved correctly."""
        data = {"mode": "PAPER", "capital": 100000}
        cache.set("control:mode", data, CacheTier.HOT)
        retrieved = cache.get("control:mode")
        assert retrieved["mode"] == "PAPER"
        assert retrieved["capital"] == 100000

    def test_none_value(self, cache: SessionCache) -> None:
        """None is a valid value to cache."""
        cache.set("null_key", None)
        assert cache.get("null_key") is None


# ══════════════════════════════════════════════════════════════
#  3. CacheTier Integration Tests
# ══════════════════════════════════════════════════════════════


class TestCacheTierIntegration:
    """Verify HOT/WARM/COLD tier behavior."""

    def test_hot_tier_stores_correctly(self, cache: SessionCache) -> None:
        """HOT tier entries are retrievable with HOT filter."""
        cache.set("exec", {"state": "ACTIVE"}, CacheTier.HOT)
        assert cache.get("exec", CacheTier.HOT) is not None

    def test_warm_tier_stores_correctly(self, cache: SessionCache) -> None:
        """WARM tier entries are retrievable with WARM filter."""
        cache.set("captain", {"mood": "OBSERVER"}, CacheTier.WARM)
        assert cache.get("captain", CacheTier.WARM) is not None

    def test_cold_tier_stores_correctly(self, cache: SessionCache) -> None:
        """COLD tier entries are retrievable with COLD filter."""
        cache.set("history", {"trades": []}, CacheTier.COLD)
        assert cache.get("history", CacheTier.COLD) is not None

    def test_tier_isolation_hot_warm(self, cache: SessionCache) -> None:
        """HOT entries are not visible via WARM filter."""
        cache.set("key", "hot_val", CacheTier.HOT)
        assert cache.get("key", CacheTier.WARM) is None
        assert cache.get("key", CacheTier.HOT) == "hot_val"

    def test_tier_isolation_cold_hot(self, cache: SessionCache) -> None:
        """COLD entries are not visible via HOT filter."""
        cache.set("key", "cold_val", CacheTier.COLD)
        assert cache.get("key", CacheTier.HOT) is None
        assert cache.get("key", CacheTier.COLD) == "cold_val"

    def test_without_tier_filter_returns_any_tier(self, cache: SessionCache) -> None:
        """get() without tier filter returns value regardless of tier."""
        cache.set("any_key", "val", CacheTier.HOT)
        assert cache.get("any_key") == "val"


# ══════════════════════════════════════════════════════════════
#  4. Expiry Tests
# ══════════════════════════════════════════════════════════════


class TestExpiry:
    """Verify cache expiry behavior."""

    def test_expired_entry_returns_none(self, cache: SessionCache) -> None:
        """Expired entry returns None and is removed from store."""
        cache.set("exp_key", "val", CacheTier.HOT)
        # Manually expire the entry
        entry = cache._store["exp_key"]
        entry.expires_at = _now() - timedelta(seconds=1)
        assert cache.get("exp_key") is None
        assert "exp_key" not in cache._store

    def test_expired_entry_increments_tier_misses(self, cache: SessionCache) -> None:
        """Expired entry increments the tier miss counter."""
        cache.set("exp_key", "val", CacheTier.HOT)
        entry = cache._store["exp_key"]
        entry.expires_at = _now() - timedelta(seconds=1)
        cache.get("exp_key")
        stats = cache.get_cache_stats()
        assert stats["tier_misses"]["HOT"] == 1

    def test_fresh_entry_not_expired(self, cache: SessionCache) -> None:
        """Freshly set entry is not expired."""
        cache.set("fresh", "val", CacheTier.WARM)
        assert cache.get("fresh") == "val"

    def test_hot_entry_expires_after_ttl(self, cache: SessionCache) -> None:
        """HOT entry expires after 500ms."""
        cache.set("hot", "val", CacheTier.HOT)
        entry = cache._store["hot"]
        expected_expiry = entry.created_at + timedelta(milliseconds=500)
        assert entry.expires_at == expected_expiry


# ══════════════════════════════════════════════════════════════
#  5. Eviction Tests
# ══════════════════════════════════════════════════════════════


class TestEviction:
    """Verify cache eviction when max_entries exceeded."""

    def test_evicts_oldest_when_full(self) -> None:
        """Oldest entry is evicted when max_entries reached."""
        small_cache = SessionCache(max_entries=3)
        small_cache.set("a", 1)
        small_cache.set("b", 2)
        small_cache.set("c", 3)
        # Trigger eviction
        small_cache.set("d", 4)
        assert "a" not in small_cache._store  # oldest evicted
        assert small_cache.get("d") == 4

    def test_eviction_preserves_newer_entries(self) -> None:
        """After eviction, newer entries remain."""
        small_cache = SessionCache(max_entries=3)
        small_cache.set("a", 1)
        small_cache.set("b", 2)
        small_cache.set("c", 3)
        small_cache.set("d", 4)
        assert small_cache.get("b") == 2
        assert small_cache.get("c") == 3

    def test_eviction_keeps_total_under_limit(self) -> None:
        """Total entries never exceed max_entries."""
        small_cache = SessionCache(max_entries=5)
        for i in range(10):
            small_cache.set(f"key_{i}", i)
        assert len(small_cache._store) <= 5


# ══════════════════════════════════════════════════════════════
#  6. Invalidation Tests
# ══════════════════════════════════════════════════════════════


class TestInvalidation:
    """Verify cache invalidation operations."""

    def test_invalidate_single_key(self, cache: SessionCache) -> None:
        """Invalidating a single key removes it."""
        cache.set("key", "val")
        assert cache.invalidate("key") is True
        assert cache.get("key") is None

    def test_invalidate_nonexistent(self, cache: SessionCache) -> None:
        """Invalidating a non-existent key returns False."""
        assert cache.invalidate("no_key") is False

    def test_invalidate_tier_hot(self, cache: SessionCache) -> None:
        """Invalidating HOT tier removes only HOT entries."""
        cache.set("hot_key", 1, CacheTier.HOT)
        cache.set("warm_key", 2, CacheTier.WARM)
        removed = cache.invalidate_tier(CacheTier.HOT)
        assert removed == 1
        assert cache.get("hot_key") is None
        assert cache.get("warm_key") == 2

    def test_invalidate_tier_warm(self, cache: SessionCache) -> None:
        """Invalidating WARM tier removes only WARM entries."""
        cache.set("hot_key", 1, CacheTier.HOT)
        cache.set("warm_key", 2, CacheTier.WARM)
        removed = cache.invalidate_tier(CacheTier.WARM)
        assert removed == 1
        assert cache.get("hot_key") == 1

    def test_invalidate_tier_cold(self, cache: SessionCache) -> None:
        """Invalidating COLD tier removes only COLD entries."""
        cache.set("hot_key", 1, CacheTier.HOT)
        cache.set("cold_key", 3, CacheTier.COLD)
        removed = cache.invalidate_tier(CacheTier.COLD)
        assert removed == 1
        assert cache.get("hot_key") == 1
        assert cache.get("cold_key") is None

    def test_clear_session(self, cache: SessionCache) -> None:
        """clear_session() removes all entries and resets stats."""
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear_session()
        assert len(cache._store) == 0
        stats = cache.get_cache_stats()
        assert stats["total_entries"] == 0
        assert stats["total_misses"] == 0

    def test_invalidate_all_tiers(self, cache: SessionCache) -> None:
        """Invalidating all 3 tiers removes everything."""
        cache.set("a", 1, CacheTier.HOT)
        cache.set("b", 2, CacheTier.WARM)
        cache.set("c", 3, CacheTier.COLD)
        cache.invalidate_tier(CacheTier.HOT)
        cache.invalidate_tier(CacheTier.WARM)
        cache.invalidate_tier(CacheTier.COLD)
        assert len(cache._store) == 0


# ══════════════════════════════════════════════════════════════
#  7. Cache Stats Tests
# ══════════════════════════════════════════════════════════════


class TestCacheStats:
    """Verify cache statistics reporting."""

    def test_empty_stats(self, cache: SessionCache) -> None:
        """Empty cache returns zero stats."""
        stats = cache.get_cache_stats()
        assert stats["total_entries"] == 0
        assert stats["max_entries"] == 100
        assert stats["total_hits"] == 0
        assert stats["total_misses"] == 0
        assert stats["hit_ratio"] == 0.0

    def test_stats_after_set(self, cache: SessionCache) -> None:
        """After sets, stats reflect entry counts."""
        cache.set("a", 1, CacheTier.HOT)
        cache.set("b", 2, CacheTier.WARM)
        stats = cache.get_cache_stats()
        assert stats["total_entries"] == 2
        assert stats["tier_counts"]["HOT"] == 1
        assert stats["tier_counts"]["WARM"] == 1
        assert stats["tier_counts"]["COLD"] == 0

    def test_stats_tracks_hits(self, cache: SessionCache) -> None:
        """Successful gets increment hit count."""
        cache.set("key", "val")
        cache.get("key")
        cache.get("key")
        stats = cache.get_cache_stats()
        assert stats["total_hits"] == 2

    def test_stats_tracks_misses(self, cache: SessionCache) -> None:
        """Missed gets increment miss count."""
        cache.get("no_key")
        stats = cache.get_cache_stats()
        assert stats["total_misses"] == 1
        assert stats["unknown_misses"] == 1

    def test_stats_hit_ratio(self, cache: SessionCache) -> None:
        """Hit ratio is calculated correctly."""
        cache.set("key", "val")
        cache.get("key")  # hit
        cache.get("key")  # hit
        cache.get("nope")  # miss
        stats = cache.get_cache_stats()
        assert stats["total_hits"] == 2
        assert stats["total_misses"] == 1
        assert stats["hit_ratio"] == round(2 / 3, 3)


# ══════════════════════════════════════════════════════════════
#  8. get_all_keys Tests
# ══════════════════════════════════════════════════════════════


class TestGetAllKeys:
    """Verify get_all_keys() returns correct key listing."""

    def test_empty_cache_returns_empty_list(self, cache: SessionCache) -> None:
        """Empty cache returns empty list."""
        assert cache.get_all_keys() == []

    def test_returns_all_keys(self, cache: SessionCache) -> None:
        """All stored keys are returned."""
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        keys = cache.get_all_keys()
        assert "a" in keys
        assert "b" in keys
        assert "c" in keys
        assert len(keys) == 3

    def test_keys_updated_after_invalidation(self, cache: SessionCache) -> None:
        """Keys list is updated after invalidation."""
        cache.set("a", 1)
        cache.set("b", 2)
        cache.invalidate("a")
        assert "a" not in cache.get_all_keys()
        assert "b" in cache.get_all_keys()

    def test_keys_include_colon_keys(self, cache: SessionCache) -> None:
        """Keys with special characters like colons are included."""
        cache.set("control:mode", {"mode": "ALERT"}, CacheTier.HOT)
        cache.set("floor_4", {}, CacheTier.WARM)
        keys = cache.get_all_keys()
        assert "control:mode" in keys
        assert "floor_4" in keys


# ══════════════════════════════════════════════════════════════
#  9. Edge Cases
# ══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Verify edge cases and error handling."""

    def test_empty_key_string(self, cache: SessionCache) -> None:
        """Empty string key works."""
        cache.set("", "empty_key")
        assert cache.get("") == "empty_key"

    def test_large_value(self, cache: SessionCache) -> None:
        """Large values can be cached."""
        large = {"data": list(range(1000))}
        cache.set("large", large)
        result = cache.get("large")
        assert len(result["data"]) == 1000

    def test_cache_entry_increments_on_get(self, cache: SessionCache) -> None:
        """Cache hit increments the entry's internal hit counter."""
        cache.set("key", "val", CacheTier.HOT)
        cache.get("key")  # hit 1
        cache.get("key")  # hit 2
        assert cache._store["key"].hits == 2

    def test_miss_on_empty_cache_returns_none(self, cache: SessionCache) -> None:
        """Empty cache returns None for any key."""
        assert cache.get("anything") is None

    def test_eviction_empty_cache(self) -> None:
        """_evict_one on empty cache does not error."""
        small_cache = SessionCache(max_entries=5)
        small_cache._evict_one()  # should not raise

    def test_get_after_clear(self, cache: SessionCache) -> None:
        """After clear, all keys return None."""
        cache.set("key", "val")
        cache.clear_session()
        assert cache.get("key") is None
