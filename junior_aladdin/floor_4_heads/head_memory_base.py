"""Floor 4 — Head Memory Base.

Common memory interface for all Department Heads.

Memory depth is HEAD-SPECIFIC:
- SMC: longer structural memory (multi-session)
- Psychology: mainly intraday behaviour memory
- Options: session + recent shift memory
- Macro: current day + prior carryover context
- Technical: recent trend shifts, MTF evolution
- ICT: previous day context, displacement history

All memory items have a TTL (time-to-live). Expired items are
removed by ``clear_expired()`` before report generation.

Design principles:
- Memory should NOT bloat — keep only domain-relevant state.
- Stale items must be removable explicitly.
- Each head configures its own default TTL via ``HeadMemoryConfig``.

Usage::

    from junior_aladdin.floor_4_heads.head_memory_base import HeadMemoryStore

    store = HeadMemoryStore()
    store.remember("last_structure", {"type": "BULLISH"}, ttl_seconds=300)
    data = store.recall("last_structure")  # → {"type": "BULLISH"} or None
    store.clear_expired()
    context = store.get_context()  # → dict of all active items
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


# =============================================================================
# Memory Item
# =============================================================================


@dataclass
class MemoryItem:
    """A single memory entry stored by a Head.

    Fields:
        key: Unique identifier for this memory item.
        value: The stored data (any serializable type).
        ttl_seconds: Time-to-live in seconds from creation.
        created_at: When this item was stored (UTC).
        expires_at: When this item expires (UTC). Computed from
            ``created_at + ttl_seconds``.
    """
    key: str
    value: Any
    ttl_seconds: int
    created_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        """Check whether this memory item has expired.

        Args:
            now: Current time. Uses ``datetime.utcnow()`` if None.

        Returns:
            ``True`` if the item's expiration time has passed.
        """
        check_time = now or datetime.utcnow()
        return check_time >= self.expires_at

    def remaining_seconds(self, now: datetime | None = None) -> float:
        """Seconds until this item expires (0.0 if already expired).

        Args:
            now: Current time. Uses ``datetime.utcnow()`` if None.

        Returns:
            Positive float if still alive, 0.0 if expired.
        """
        check_time = now or datetime.utcnow()
        remaining = (self.expires_at - check_time).total_seconds()
        return max(0.0, remaining)


# =============================================================================
# Head Memory Config
# =============================================================================


@dataclass
class HeadMemoryConfig:
    """Default memory configuration for a Head.

    Each Head type specifies its own defaults based on its memory needs.
    The Head can override TTL per-call to ``remember()``.

    Fields:
        default_ttl_seconds: Default TTL for items stored without explicit TTL.
        max_items: Maximum number of items before oldest are evicted.
            ``0`` means unlimited.
        auto_cleanup: Whether to automatically remove expired items on
            ``recall()`` and ``get_context()``.
    """
    default_ttl_seconds: int = 300       # 5 minutes default
    max_items: int = 100                  # cap at 100 items
    auto_cleanup: bool = True


# ── Pre-built configs for each head type ────────────────────────────────────

HEAD_SMC_MEMORY_CONFIG = HeadMemoryConfig(
    default_ttl_seconds=600,    # 10 min — structural memory lasts longer
    max_items=150,
)

HEAD_ICT_MEMORY_CONFIG = HeadMemoryConfig(
    default_ttl_seconds=600,    # 10 min — displacement/PD context
    max_items=150,
)

HEAD_TECHNICAL_MEMORY_CONFIG = HeadMemoryConfig(
    default_ttl_seconds=300,    # 5 min — trend shifts, VWAP history
    max_items=100,
)

HEAD_OPTIONS_MEMORY_CONFIG = HeadMemoryConfig(
    default_ttl_seconds=300,    # 5 min — OI behaviour, wall shifts
    max_items=80,
)

HEAD_MACRO_MEMORY_CONFIG = HeadMemoryConfig(
    default_ttl_seconds=900,    # 15 min — event context, carryover
    max_items=50,
)

HEAD_PSYCHOLOGY_MEMORY_CONFIG = HeadMemoryConfig(
    default_ttl_seconds=600,    # 10 min — intraday behaviour markers
    max_items=100,
)


# =============================================================================
# Memory Store
# =============================================================================


class HeadMemoryStore:
    """TTL-based memory store for a single Department Head.

    Thread-safe within a single head (heads are single-threaded by design).

    Args:
        config: ``HeadMemoryConfig`` controlling TTL, capacity, cleanup policy.
            If ``None``, uses default (5 min TTL, 100 items max).

    Example::

        store = HeadMemoryStore(config=SMC_MEMORY_CONFIG)

        # Store with default TTL
        store.remember("structure", {"type": "BULLISH", "valid": True})

        # Store with custom TTL
        store.remember("fvg_map", {"levels": [19500, 19600]}, ttl_seconds=120)

        # Retrieve
        data = store.recall("structure")

        # Forget
        store.forget("structure")

        # Get all active context
        ctx = store.get_context()

        # Clear expired
        store.clear_expired()
    """

    def __init__(self, config: HeadMemoryConfig | None = None) -> None:
        self._config = config or HeadMemoryConfig()
        self._items: dict[str, MemoryItem] = {}

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def config(self) -> HeadMemoryConfig:
        """The memory configuration for this store."""
        return self._config

    @property
    def count(self) -> int:
        """Number of items currently in the store (including expired)."""
        return len(self._items)

    def active_count(self, now: datetime | None = None) -> int:
        """Number of non-expired items in the store.

        Args:
            now: Current time. Uses ``datetime.utcnow()`` if None.
        """
        check_time = now or datetime.utcnow()
        return sum(
            1 for item in self._items.values() if not item.is_expired(check_time)
        )

    # ── Core API ────────────────────────────────────────────────────────

    def remember(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store a value with a TTL.

        If ``key`` already exists, it is overwritten (and its TTL resets).

        Args:
            key: Unique identifier.
            value: Value to store.
            ttl_seconds: TTL in seconds. Uses ``config.default_ttl_seconds``
                if ``None``.

        Raises:
            ValueError: If ``ttl_seconds`` is provided and <= 0.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._config.default_ttl_seconds
        if ttl <= 0:
            raise ValueError(f"ttl_seconds must be > 0, got {ttl}")

        now = datetime.utcnow()
        item = MemoryItem(
            key=key,
            value=value,
            ttl_seconds=ttl,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )

        # Evict oldest if at capacity
        if len(self._items) >= self._config.max_items and key not in self._items:
            self._evict_oldest()

        self._items[key] = item

    def recall(self, key: str, default: Any = None) -> Any:
        """Retrieve a stored value by key.

        If ``config.auto_cleanup`` is ``True``, expired items are silently
        removed and treated as misses.

        Args:
            key: The item's unique identifier.
            default: Value to return if the key is not found or expired.

        Returns:
            The stored value, or ``default`` if not found or expired.
        """
        item = self._items.get(key)
        if item is None:
            return default

        if item.is_expired():
            if self._config.auto_cleanup:
                self.forget(key)
            return default

        return item.value

    def forget(self, key: str) -> bool:
        """Remove a specific item from memory.

        Args:
            key: The item's unique identifier.

        Returns:
            ``True`` if the item existed and was removed, ``False`` otherwise.
        """
        if key in self._items:
            del self._items[key]
            return True
        return False

    def clear_expired(self, now: datetime | None = None) -> int:
        """Remove all expired items from memory.

        Should be called before ``get_context()`` during report generation.

        Args:
            now: Current time. Uses ``datetime.utcnow()`` if None.

        Returns:
            Number of items removed.
        """
        check_time = now or datetime.utcnow()
        expired_keys = [
            key for key, item in self._items.items()
            if item.is_expired(check_time)
        ]
        for key in expired_keys:
            del self._items[key]
        return len(expired_keys)

    def get_context(
        self,
        clear_expired_first: bool = True,
    ) -> dict[str, Any]:
        """Return all active (non-expired) memory items as a plain dict.

        Designed to be consumed by Heads during report generation.

        Args:
            clear_expired_first: Whether to clean expired items before
                building the context dict. Default ``True``.

        Returns:
            A dict mapping keys to their stored values (expired items
            are excluded).
        """
        if clear_expired_first:
            self.clear_expired()

        return {
            key: item.value
            for key, item in self._items.items()
        }

    def keys(self) -> list[str]:
        """Return all stored keys (including expired)."""
        return list(self._items.keys())

    def clear(self) -> None:
        """Remove all items from memory."""
        self._items.clear()

    # ── Internal ────────────────────────────────────────────────────────

    def _evict_oldest(self) -> None:
        """Remove the single oldest item (by ``created_at``) from the store.

        Used when the store is at capacity and a new key is being inserted.
        Expired items are evicted first; if none exist, the chronologically
        oldest item is removed.
        """
        if not self._items:
            return

        # Prefer to evict expired items first
        expired = [
            (key, item) for key, item in self._items.items()
            if item.is_expired()
        ]
        if expired:
            oldest_expired = min(expired, key=lambda kv: kv[1].created_at)
            del self._items[oldest_expired[0]]
            return

        # Evict the chronologically oldest item
        oldest_key = min(self._items, key=lambda k: self._items[k].created_at)
        del self._items[oldest_key]
