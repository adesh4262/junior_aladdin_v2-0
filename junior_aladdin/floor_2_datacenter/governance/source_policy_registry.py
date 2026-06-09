"""Floor 2 Governance — source policy registry.

Provides the **SourcePolicyRegistry** class that defines and enforces
per-source policies for the Floor 2 pipeline.

Responsibilities:
- **Source registration**: Register sources with allowed feed types.
- **Policy enforcement**: Check if a source is allowed to send a feed type.
- **Validation tier mapping**: Map source+feed to validation tier.
- **Retention class mapping**: Map source+feed to retention class.
- **Default policies**: Any source can send any feed by default (no restriction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    get_validation_tier_for_feed,
    get_data_class_for_feed,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("source_policy_registry")

# Default validation tier for unknown sources
DEFAULT_VALIDATION_TIER: str = "C"


@dataclass
class SourcePolicy:
    """Policy configuration for a single data source.

    Fields:
        source: Source name (e.g., ``\"angel_one\"``, ``\"manual\"``).
        allowed_feeds: Set of feed types this source is allowed to send.
            Empty set means ALL feeds are allowed.
        default_validation_tier: Default validation tier for feeds from this source.
        is_active: Whether this source is currently active.
        metadata: Optional dict with additional policy metadata.
    """
    source: str
    allowed_feeds: set[str] = field(default_factory=set)
    default_validation_tier: str = DEFAULT_VALIDATION_TIER
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class SourcePolicyRegistry:
    """Manages per-source policies for the Floor 2 pipeline.

    Thread-safe. Controls which sources can send which feed types and
    with what validation/retention configuration.

    Typical usage::

        registry = SourcePolicyRegistry()

        # Register a source with restrictions
        registry.register_source("angel_one", allowed_feeds={"spot_tick", "options_snapshot"})

        # Check if source can send a feed
        if registry.is_feed_allowed("angel_one", "spot_tick"):
            process(packet)

        # Get validation tier for source+feed
        tier = registry.get_validation_tier("angel_one", "spot_tick")
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # source -> SourcePolicy
        self._policies: dict[str, SourcePolicy] = {}

    # ------------------------------------------------------------------
    # Source Registration
    # ------------------------------------------------------------------

    def register_source(
        self,
        source: str,
        allowed_feeds: set[str] | None = None,
        default_validation_tier: str = DEFAULT_VALIDATION_TIER,
        is_active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register or update a source policy.

        Args:
            source: The source name.
            allowed_feeds: Set of allowed feed types. ``None`` or empty = all feeds.
            default_validation_tier: Default validation tier for this source.
            is_active: Whether this source is active.
            metadata: Optional metadata dict.
        """
        with self._lock:
            self._policies[source] = SourcePolicy(
                source=source,
                allowed_feeds=allowed_feeds or set(),
                default_validation_tier=default_validation_tier,
                is_active=is_active,
                metadata=metadata or {},
            )
        logger.info(
            "Source policy registered",
            extra={
                "source": source,
                "allowed_feeds_count": len(allowed_feeds or set()),
                "tier": default_validation_tier,
            },
        )

    def remove_source(self, source: str) -> bool:
        """Remove a source policy.

        Args:
            source: The source name.

        Returns:
            ``True`` if removed, ``False`` if not found.
        """
        with self._lock:
            if source in self._policies:
                del self._policies[source]
                logger.debug("Source policy removed", extra={"source": source})
                return True
            return False

    def clear(self) -> None:
        """Remove ALL source policies."""
        with self._lock:
            self._policies.clear()
        logger.info("SourcePolicyRegistry cleared")

    # ------------------------------------------------------------------
    # Policy Lookup
    # ------------------------------------------------------------------

    def get_policy(self, source: str) -> SourcePolicy | None:
        """Get the policy for a source.

        Args:
            source: The source name.

        Returns:
            The ``SourcePolicy``, or ``None`` if not registered.
        """
        with self._lock:
            return self._policies.get(source)

    def is_source_registered(self, source: str) -> bool:
        """Check if a source is registered.

        Args:
            source: The source name.

        Returns:
            ``True`` if registered.
        """
        with self._lock:
            return source in self._policies

    def is_source_active(self, source: str) -> bool:
        """Check if a source is active.

        Unregistered sources are considered active by default.

        Args:
            source: The source name.

        Returns:
            ``True`` if active or not registered.
        """
        policy = self.get_policy(source)
        if policy is None:
            return True
        return policy.is_active

    # ------------------------------------------------------------------
    # Feed Allowance
    # ------------------------------------------------------------------

    def is_feed_allowed(self, source: str, feed_type: str) -> bool:
        """Check if a source is allowed to send a specific feed type.

        Args:
            source: The source name.
            feed_type: The feed type to check.

        Returns:
            ``True`` if allowed, ``False`` if blocked.
        """
        policy = self.get_policy(source)
        if policy is None:
            return True  # No policy = no restriction
        if not policy.is_active:
            return False
        if not policy.allowed_feeds:
            return True  # Empty set = all feeds allowed
        return feed_type in policy.allowed_feeds

    def get_allowed_feeds(self, source: str) -> set[str]:
        """Get the set of feed types a source is allowed to send.

        Returns empty set if no restrictions (all feeds allowed).

        Args:
            source: The source name.

        Returns:
            Set of allowed feed types, or empty set for unrestricted.
        """
        policy = self.get_policy(source)
        if policy is None:
            return set()  # No policy = unrestricted (empty set)
        return policy.allowed_feeds

    # ------------------------------------------------------------------
    # Validation Tier
    # ------------------------------------------------------------------

    def get_validation_tier(self, source: str, feed_type: str) -> str:
        """Get the validation tier for a source+feed combination.

        Priority:
        1. Feed type default (from ``datacenter_contracts.py``)
        2. Source default validation tier

        Args:
            source: The source name.
            feed_type: The feed type.

        Returns:
            Validation tier string (``\"A\"``, ``\"B\"``, or ``\"C\"``).
        """
        # Try feed-type-specific tier first
        feed_tier = get_validation_tier_for_feed(feed_type)
        if feed_tier != DEFAULT_VALIDATION_TIER:
            return feed_tier

        # Fall back to source default
        policy = self.get_policy(source)
        if policy:
            return policy.default_validation_tier

        # Global default
        return DEFAULT_VALIDATION_TIER

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def get_retention_class(self, source: str, feed_type: str) -> str:
        """Get the retention class (MAJOR/MINOR) for a source+feed.

        Args:
            source: The source name.
            feed_type: The feed type.

        Returns:
            ``\"MAJOR\"`` or ``\"MINOR\"``.
        """
        return get_data_class_for_feed(feed_type)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def list_sources(self) -> list[str]:
        """List all registered source names.

        Returns:
            Sorted list of source names.
        """
        with self._lock:
            return sorted(self._policies.keys())

    def list_active_sources(self) -> list[str]:
        """List all active sources.

        Returns:
            Sorted list of active source names.
        """
        sources = []
        with self._lock:
            for name, policy in self._policies.items():
                if policy.is_active:
                    sources.append(name)
        return sorted(sources)

    def count_sources(self) -> int:
        """Get the number of registered sources.

        Returns:
            Source count.
        """
        with self._lock:
            return len(self._policies)

    def report_sources(self) -> dict[str, Any]:
        """Generate a summary report of all source policies.

        Returns:
            Dict with source counts and per-source policy details.
        """
        sources = []
        with self._lock:
            for name, policy in self._policies.items():
                sources.append({
                    "source": name,
                    "allowed_feeds": sorted(policy.allowed_feeds) if policy.allowed_feeds else ["ALL"],
                    "default_tier": policy.default_validation_tier,
                    "is_active": policy.is_active,
                })

        return {
            "total_sources": len(sources),
            "active_sources": sum(1 for s in sources if s["is_active"]),
            "sources": sources,
        }
