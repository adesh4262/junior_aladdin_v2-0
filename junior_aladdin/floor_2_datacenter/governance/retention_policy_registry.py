"""Floor 2 Governance — retention policy registry.

Provides the **RetentionPolicyRegistry** class that maps data classes
(MAJOR/MINOR) to retention TTLs, with per-feed-type overrides.

Works alongside ``RawRetentionManager`` but is config-driven and
registry-based rather than hardcoded per-feed.

Responsibilities:
- **Default TTLs**: MAJOR = 7 days, MINOR = 1 day.
- **Per-feed overrides**: Custom TTLs for specific feed types.
- **Policy lookup**: Get retention TTL for any feed type.
- **Reporting**: Summarise all current policies.
"""

from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    get_data_class_for_feed,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("retention_policy_registry")

# Default retention durations (seconds)
DEFAULT_MAJOR_RETENTION_S: int = 7 * 24 * 3600      # 7 days
DEFAULT_MINOR_RETENTION_S: int = 1 * 24 * 3600      # 1 day
DEFAULT_UNKNOWN_RETENTION_S: int = 24 * 3600        # 1 day fallback


class RetentionPolicyRegistry:
    """Registry-based retention policy management.

    Maps data classes and feed types to retention TTLs.

    Typical usage::

        registry = RetentionPolicyRegistry()
        ttl = registry.get_retention_s("spot_tick")    # 604800 (7 days)
        ttl = registry.get_retention_s("macro_data")   # 86400 (1 day)

        registry.set_policy("macro_data", 3600)        # Override to 1 hour
        registry.remove_policy("macro_data")           # Revert to default
    """

    def __init__(
        self,
        major_retention_s: int = DEFAULT_MAJOR_RETENTION_S,
        minor_retention_s: int = DEFAULT_MINOR_RETENTION_S,
    ) -> None:
        """Initialise the retention policy registry.

        Args:
            major_retention_s: Default retention in seconds for MAJOR data.
            minor_retention_s: Default retention in seconds for MINOR data.
        """
        self._lock = Lock()
        self._major_retention_s = major_retention_s
        self._minor_retention_s = minor_retention_s
        # per-feed-type overrides: feed_type -> duration_s
        self._overrides: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Policy Management
    # ------------------------------------------------------------------

    def set_policy(self, feed_type: str, duration_s: int) -> None:
        """Set a custom retention policy for a specific feed type.

        Args:
            feed_type: The feed type (e.g., ``\"spot_tick\"``).
            duration_s: Retention duration in seconds.
        """
        with self._lock:
            self._overrides[feed_type] = duration_s
        logger.info(
            "Retention policy set",
            extra={"feed_type": feed_type, "duration_s": duration_s},
        )

    def set_policy_many(self, policies: dict[str, int]) -> int:
        """Set multiple retention policies at once.

        Args:
            policies: Dict of ``{feed_type: duration_s}``.

        Returns:
            Number of policies set.
        """
        with self._lock:
            self._overrides.update(policies)
        logger.info("Retention policies set", extra={"count": len(policies)})
        return len(policies)

    def remove_policy(self, feed_type: str) -> bool:
        """Remove a custom retention policy, reverting to default.

        Args:
            feed_type: The feed type to reset.

        Returns:
            ``True`` if removed, ``False`` if none existed.
        """
        with self._lock:
            if feed_type in self._overrides:
                del self._overrides[feed_type]
                logger.debug("Retention policy removed", extra={"feed_type": feed_type})
                return True
            return False

    def clear_policies(self) -> None:
        """Remove ALL custom retention policies."""
        with self._lock:
            self._overrides.clear()
        logger.info("All custom retention policies cleared")

    def clear(self) -> None:
        """Reset everything to defaults."""
        with self._lock:
            self._overrides.clear()
            self._major_retention_s = DEFAULT_MAJOR_RETENTION_S
            self._minor_retention_s = DEFAULT_MINOR_RETENTION_S
        logger.info("RetentionPolicyRegistry reset to defaults")

    # ------------------------------------------------------------------
    # Policy Lookup
    # ------------------------------------------------------------------

    def get_retention_s(self, feed_type: str) -> int:
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
        with self._lock:
            # 1. Override
            if feed_type in self._overrides:
                return self._overrides[feed_type]

        # 2. DataClass default (outside lock - no shared state access)
        data_class = get_data_class_for_feed(feed_type)
        if data_class == "MAJOR":
            return self._major_retention_s
        elif data_class == "MINOR":
            return self._minor_retention_s

        # 3. Unknown fallback
        return DEFAULT_UNKNOWN_RETENTION_S

    def get_retention_timedelta(self, feed_type: str) -> timedelta:
        """Get the retention duration as a timedelta.

        Args:
            feed_type: The feed type to look up.

        Returns:
            ``timedelta`` for the retention duration.
        """
        return timedelta(seconds=self.get_retention_s(feed_type))

    def get_retention_display(self, feed_type: str) -> str:
        """Get a human-readable retention duration string.

        Args:
            feed_type: The feed type to look up.

        Returns:
            String like ``\"7 days\"``, ``\"1 day\"``, ``\"1 hour\"``.
        """
        seconds = self.get_retention_s(feed_type)
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        if days > 0:
            return f"{days} day(s)" if days == 1 else f"{days} days"
        if hours > 0:
            return f"{hours} hour(s)" if hours == 1 else f"{hours} hours"
        return f"{seconds} seconds"

    def has_override(self, feed_type: str) -> bool:
        """Check if a feed type has a custom override.

        Args:
            feed_type: The feed type to check.

        Returns:
            ``True`` if an override exists.
        """
        with self._lock:
            return feed_type in self._overrides

    def list_overrides(self) -> dict[str, int]:
        """List all current overrides.

        Returns:
            Dict of ``{feed_type: duration_s}``.
        """
        with self._lock:
            return dict(self._overrides)

    def get_data_class_ttl(self, data_class_name: str) -> int:
        """Get the default TTL for a data class.

        Args:
            data_class_name: ``\"MAJOR\"`` or ``\"MINOR\"``.

        Returns:
            TTL in seconds.
        """
        if data_class_name == "MAJOR":
            return self._major_retention_s
        return self._minor_retention_s

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report_policies(self) -> dict[str, Any]:
        """Generate a summary report of all retention policies.

        Returns:
            Dict with defaults, overrides, and per-feed resolution.
        """
        return {
            "default_major_s": self._major_retention_s,
            "default_minor_s": self._minor_retention_s,
            "default_major_display": self._format_duration(self._major_retention_s),
            "default_minor_display": self._format_duration(self._minor_retention_s),
            "overrides": dict(self._overrides),
            "override_count": len(self._overrides),
        }

    def report_feed_retention(self, feed_type: str) -> dict[str, Any]:
        """Get a detailed retention report for a single feed type.

        Args:
            feed_type: The feed type to report on.

        Returns:
            Dict with feed type, retention TTL, source (override/dataclass/default).
        """
        has_override = self.has_override(feed_type)
        ttl = self.get_retention_s(feed_type)
        data_class = get_data_class_for_feed(feed_type)

        if has_override:
            source = "override"
        elif data_class != "MINOR":
            source = f"dataclass_{data_class}"
        else:
            source = "default"

        return {
            "feed_type": feed_type,
            "retention_s": ttl,
            "retention_display": self.get_retention_display(feed_type),
            "source": source,
            "data_class": data_class,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format seconds into a human-readable string."""
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        if days > 0:
            return f"{days} day(s)" if days == 1 else f"{days} days"
        if hours > 0:
            return f"{hours} hour(s)" if hours == 1 else f"{hours} hours"
        return f"{seconds} seconds"
