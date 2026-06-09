"""Floor 2 Raw Storage — raw retention manager.

Manages retention policies for raw data based on ``DataClass``
(MAJOR / MINOR) and feed type.

Architecture rules:
- Retention is DYNAMIC — different data classes have different lifetimes.
- Tier 1 (MAJOR): tick data, options chain, OI snapshots → longer retention.
- Tier 2 (MINOR): support feeds, auxiliary, secondary → shorter retention.
- Works with both :class:`OriginalRawStore` and :class:`NormalizedRawStore`.
- Policies can be overridden per feed type for fine-grained control.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    get_data_class_for_feed,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("raw_retention_manager")

# ── Default retention durations (seconds) ─────────────────────────────
DEFAULT_MAJOR_RETENTION_S: int = 7 * 24 * 3600      # 7 days
DEFAULT_MINOR_RETENTION_S: int = 1 * 24 * 3600      # 1 day
DEFAULT_UNKNOWN_RETENTION_S: int = 24 * 3600        # 1 day fallback


class RawRetentionManager:
    """Manages retention policies for raw data stores.

    Supports per-feed-type overrides on top of the default MAJOR/MINOR
    classification.

    Typical usage::

        manager = RawRetentionManager()

        # Check retention for a feed type
        duration = manager.get_retention_duration_s("spot_tick")  # 604800

        # Override retention for a specific feed type
        manager.set_policy("macro_data", duration_s=3600)

        # Get expired packet IDs from a store
        expired = manager.get_expired_ids(store)

        # Purge expired packets from a store
        purged = manager.purge_expired(store)
    """

    def __init__(
        self,
        major_retention_s: int = DEFAULT_MAJOR_RETENTION_S,
        minor_retention_s: int = DEFAULT_MINOR_RETENTION_S,
    ) -> None:
        """Initialise the retention manager.

        Args:
            major_retention_s: Default retention in seconds for MAJOR data.
            minor_retention_s: Default retention in seconds for MINOR data.
        """
        self._major_retention_s = major_retention_s
        self._minor_retention_s = minor_retention_s

        # Per-feed-type overrides (feed_type -> duration_s)
        self._overrides: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Policy management
    # ------------------------------------------------------------------

    def set_policy(self, feed_type: str, duration_s: int) -> None:
        """Set a custom retention policy for a specific feed type.

        Args:
            feed_type: The feed type (e.g., ``\"spot_tick\"``).
            duration_s: Retention duration in seconds.
        """
        self._overrides[feed_type] = duration_s
        logger.info(
            "Retention policy set",
            extra={
                "feed_type": feed_type,
                "duration_s": duration_s,
            },
        )

    def remove_policy(self, feed_type: str) -> bool:
        """Remove a custom retention policy, reverting to default.

        Args:
            feed_type: The feed type to reset.

        Returns:
            ``True`` if a policy was removed, ``False`` if none existed.
        """
        if feed_type in self._overrides:
            del self._overrides[feed_type]
            logger.info("Retention policy removed", extra={"feed_type": feed_type})
            return True
        return False

    def clear_policies(self) -> None:
        """Remove ALL custom retention policies."""
        self._overrides.clear()
        logger.info("All custom retention policies cleared")

    # ------------------------------------------------------------------
    # Retention queries
    # ------------------------------------------------------------------

    def get_retention_duration_s(self, feed_type: str) -> int:
        """Get the retention duration in seconds for a given feed type.

        Priority:
        1. Per-feed-type override (if set)
        2. DataClass default (MAJOR / MINOR)
        3. Unknown fallback (1 day)

        Args:
            feed_type: The feed type to look up.

        Returns:
            Retention duration in seconds.
        """
        # 1. Override
        if feed_type in self._overrides:
            return self._overrides[feed_type]

        # 2. DataClass default
        data_class = get_data_class_for_feed(feed_type)
        if data_class == "MAJOR":
            return self._major_retention_s
        elif data_class == "MINOR":
            return self._minor_retention_s

        # 3. Unknown fallback
        return DEFAULT_UNKNOWN_RETENTION_S

    def get_expiry_cutoff(self, feed_type: str) -> datetime:
        """Calculate the expiry cutoff datetime for a given feed type.

        Any packet stored before this cutoff is considered expired.

        Args:
            feed_type: The feed type to calculate for.

        Returns:
            The cutoff :class:`datetime` (timezone-aware UTC).
        """
        duration_s = self.get_retention_duration_s(feed_type)
        return datetime.now(timezone.utc) - timedelta(seconds=duration_s)

    def is_expired(self, stored_at: datetime | None, feed_type: str) -> bool:
        """Check whether a packet is expired based on its stored time and feed type.

        Args:
            stored_at: When the packet was stored (can be None for unknown).
            feed_type: The feed type of the packet.

        Returns:
            ``True`` if the packet is expired, ``False`` otherwise.
        """
        if stored_at is None:
            return False
        cutoff = self.get_expiry_cutoff(feed_type)
        # Ensure both datetimes are tz-aware for comparison
        if stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=timezone.utc)
        return stored_at < cutoff

    # ------------------------------------------------------------------
    # Bulk operations on stores
    # ------------------------------------------------------------------

    def get_expired_ids(self, store: Any) -> list[str]:
        """Get IDs of all expired packets from a raw store.

        Works with both :class:`OriginalRawStore` and
        :class:`NormalizedRawStore` — any store that exposes a ``packet_ids``
        property and a ``get(packet_id)`` method returning a dict with
        ``timestamp``/``stored_at`` and ``feed_type`` fields.

        Args:
            store: A raw store instance.

        Returns:
            List of expired ``packet_id`` values.
        """
        expired: list[str] = []
        for pid in store.packet_ids:
            record = store.get(pid)
            if record is None:
                continue
            feed_type = record.get("feed_type", "unknown")
            stored_at = record.get("timestamp") or record.get("ingested_at") or record.get("stored_at")
            if self.is_expired(stored_at, feed_type):
                expired.append(pid)
        return expired

    def purge_expired(self, store: Any) -> int:
        """Delete all expired packets from a raw store.

        Args:
            store: A raw store instance with ``delete(packet_id)``.

        Returns:
            Number of packets purged.
        """
        expired = self.get_expired_ids(store)
        purged = 0
        for pid in expired:
            if store.delete(pid):
                purged += 1
        if purged:
            logger.info(
                "Purged expired packets",
                extra={"count": purged},
            )
        return purged

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report_policies(self) -> dict[str, Any]:
        """Return a summary of all current retention policies.

        Returns:
            Dict with default MAJOR/MINOR durations and any overrides.
        """
        return {
            "default_major_s": self._major_retention_s,
            "default_minor_s": self._minor_retention_s,
            "overrides": dict(self._overrides),
        }
