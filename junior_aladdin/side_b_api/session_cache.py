"""Side B in-memory session cache.

Three-tier cache following the HOT / WARM / COLD attention model:

  HOT  (500ms)  — positions, prices, alerts, execution state
  WARM (3s)     — head reports, captain state, floor summary
  COLD (30s)    — reference data, logs, history (or on-demand)

Not thread-safe by default — intended for single-operator localhost use.
Add threading.Lock if background + foreground access races.

Reference: ROADMAP_SIDE_B Step 8.3, SIDE_B_DASHBOARD_V1_2_FINAL Section 21
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG


class CacheTier(Enum):
    """Refresh tier classification."""
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


# ── Default TTLs (milliseconds) ──
_TIER_TTL_MS = {
    CacheTier.HOT: DEFAULT_CONFIG.hot_refresh_ms,
    CacheTier.WARM: DEFAULT_CONFIG.warm_refresh_ms,
    CacheTier.COLD: DEFAULT_CONFIG.cold_refresh_ms,
}

_MAX_ENTRIES = DEFAULT_CONFIG.max_cache_entries


# ──────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────


def _now() -> datetime:
    return datetime.utcnow()


def _ttl_delta(tier: CacheTier) -> timedelta:
    return timedelta(milliseconds=_TIER_TTL_MS.get(tier, 30_000))


# ──────────────────────────────────────────────
#  Cache entry
# ──────────────────────────────────────────────


class CacheEntry:
    """A single cached value with tier-aware expiry metadata."""

    __slots__ = ("value", "tier", "created_at", "expires_at", "hits")

    def __init__(self, value: Any, tier: CacheTier) -> None:
        self.value = value
        self.tier = tier
        self.created_at = _now()
        self.expires_at = self.created_at + _ttl_delta(tier)
        self.hits = 0

    @property
    def is_expired(self) -> bool:
        return _now() >= self.expires_at

    @property
    def age_s(self) -> float:
        return (_now() - self.created_at).total_seconds()


# ──────────────────────────────────────────────
#  Session cache
# ──────────────────────────────────────────────


class SessionCache:
    """In-memory cache with HOT / WARM / COLD refresh tiers.

    Usage::

        cache = SessionCache()
        cache.set("execution.state", {"mode": "PAPER"}, CacheTier.HOT)
        state = cache.get("execution.state", CacheTier.HOT)
        cache.invalidate("execution.state")
        cache.clear_session()
        stats = cache.get_cache_stats()
    """

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._store: dict[str, CacheEntry] = {}
        self._misses: dict[CacheTier, int] = {t: 0 for t in CacheTier}
        self._unknown_misses: int = 0

    # ── public API ──

    def get(self, key: str, tier: CacheTier | None = None) -> Any:
        """Retrieve a cached value.

        Args:
            key: Cache key (dot-separated path recommended).
            tier: If provided, only return value if stored under this tier.

        Returns:
            The cached value, or ``None`` if missing / expired / tier-mismatch.
        """
        entry = self._store.get(key)
        if entry is None:
            self._unknown_misses += 1
            return None

        if entry.is_expired:
            del self._store[key]
            self._misses[entry.tier] += 1
            return None

        if tier is not None and entry.tier != tier:
            return None

        entry.hits += 1
        return entry.value

    def set(self, key: str, value: Any, tier: CacheTier = CacheTier.COLD) -> None:
        """Store a value under the given tier.

        Evicts the oldest entry if ``max_entries`` is exceeded.
        """
        if len(self._store) >= self._max_entries:
            self._evict_one()

        self._store[key] = CacheEntry(value, tier)

    def invalidate(self, key: str) -> bool:
        """Remove a single key from the cache.

        Returns:
            True if the key existed and was removed.
        """
        if key in self._store:
            del self._store[key]
            return True
        return False

    def invalidate_tier(self, tier: CacheTier) -> int:
        """Invalidate all entries in a given tier.

        Returns:
            Number of entries invalidated.
        """
        keys = [k for k, e in self._store.items() if e.tier == tier]
        for k in keys:
            del self._store[k]
        return len(keys)

    def clear_session(self) -> None:
        """Reset the entire cache."""
        self._store.clear()
        self._misses = {t: 0 for t in CacheTier}

    def get_cache_stats(self) -> dict[str, Any]:
        """Return cache performance statistics.

        Returns:
            Dict with total entries, per-tier counts, hit counts, miss counts.
        """
        total = len(self._store)
        tier_counts: dict[str, int] = {t.value: 0 for t in CacheTier}
        total_hits = 0
        for entry in self._store.values():
            tier_counts[entry.tier.value] += 1
            total_hits += entry.hits

        tier_misses = sum(self._misses.values())
        total_misses = tier_misses + self._unknown_misses

        return {
            "total_entries": total,
            "max_entries": self._max_entries,
            "tier_counts": tier_counts,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_ratio": (
                round(total_hits / (total_hits + total_misses), 3)
                if (total_hits + total_misses) > 0
                else 0.0
            ),
            "tier_misses": {t.value: v for t, v in self._misses.items()},
            "unknown_misses": self._unknown_misses,
        }

    def get_all_keys(self) -> list[str]:
        """Return all currently cached keys (for diagnostics)."""
        return list(self._store.keys())

    # ── internals ──

    def _evict_one(self) -> None:
        """Evict the single oldest entry (by created_at)."""
        if not self._store:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k].created_at)
        del self._store[oldest_key]


# Singleton default — modules can import this directly
_default_cache: SessionCache | None = None


def get_default_cache() -> SessionCache:
    """Return the module-level singleton session cache."""
    global _default_cache  # noqa: PLW0603
    if _default_cache is None:
        _default_cache = SessionCache()
    return _default_cache
