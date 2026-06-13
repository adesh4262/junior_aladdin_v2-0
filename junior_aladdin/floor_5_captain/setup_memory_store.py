"""Floor 5 — Setup Memory Store (Step 5.12).

Remembers:
- ACTIVE setups: currently being evaluated or armed
- REJECTED setups: why rejected, so same mistake not repeated
- FAILED zones: zones where traps occurred — avoid re-entry
- Same-zone trap count: how many times a zone has been a trap

Architecture rules (see ROADMAP_FLOOR_05 Section 12):
- Captain remembers setups across heavy cycles within the same session
- Rejected setups are tracked with rejection reasons
- Failed zones are marked to avoid re-entry
- Same-zone trap count feeds into opposite_case_engine and conviction_engine
- Session resets at the end of each trading day
- Setup memory is intraday only — not persisted across days
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.types import TradeClass


# ── SetupRecord dataclass ──────────────────────────────────────────────────


@dataclass
class SetupRecord:
    """A tracked setup in Captain's memory.

    Fields:
        setup_id: Unique identifier for this setup.
        direction: "BUY" or "SELL".
        trade_class: The assigned TradeClass.
        zone_label: Human-readable zone label (e.g., "FVG_19500", "OB_19450").
        zone_price: Approximate price level of the zone.
        source_head: Which head provided this setup.
        status: Current status (ACTIVE, REJECTED, FAILED, COMPLETED).
        rejection_reason: Why it was rejected (if REJECTED).
        created_at: When this setup was created.
        updated_at: When this setup was last updated.
    """
    setup_id: str = ""
    direction: str = ""
    trade_class: TradeClass | None = None
    zone_label: str = ""
    zone_price: float = 0.0
    source_head: str = ""
    status: str = "ACTIVE"
    rejection_reason: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


# ── ZoneMemory dataclass ──────────────────────────────────────────────────


@dataclass
class ZoneMemory:
    """Memory of a zone that has been involved in a setup.

    Fields:
        zone_label: Human-readable zone label.
        trap_count: Number of times this zone has been a trap.
        last_trap_at: When the last trap occurred.
        failed: Whether this zone is marked as failed (no re-entry).
        first_seen_at: When this zone was first tracked.
    """
    zone_label: str = ""
    trap_count: int = 0
    last_trap_at: datetime | None = None
    failed: bool = False
    first_seen_at: datetime = field(default_factory=datetime.utcnow)


# ── SetupMemoryStore ──────────────────────────────────────────────────────


class SetupMemoryStore:
    """Captain's intraday memory for setups and zone traps.

    Tracks the lifecycle of setups and maintains a history of
    zone-level trap events to avoid re-entering failed zones.

    Usage::

        store = SetupMemoryStore()
        store.store_setup(setup_id="S1", direction="BUY", ...)

        # Mark outcomes
        store.mark_rejected("S1", reason="Weak confluence")
        store.mark_failed_zone("FVG_19500")

        # Query
        count = store.get_trap_count("FVG_19500")
        if store.is_failed_zone("FVG_19500"):
            logger.warning("Avoiding failed zone")
    """

    def __init__(self) -> None:
        """Initialize the setup memory store."""
        self._setups: dict[str, SetupRecord] = {}
        self._zones: dict[str, ZoneMemory] = {}

    # ------------------------------------------------------------------
    # Setup Management
    # ------------------------------------------------------------------

    def store_setup(
        self,
        setup_id: str,
        direction: str,
        trade_class: TradeClass | None = None,
        zone_label: str = "",
        zone_price: float = 0.0,
        source_head: str = "",
    ) -> SetupRecord:
        """Store a new setup for tracking.

        Args:
            setup_id: Unique identifier for this setup.
            direction: "BUY" or "SELL".
            trade_class: The assigned TradeClass.
            zone_label: Human-readable zone label.
            zone_price: Approximate price level.
            source_head: Which head provided this setup.

        Returns:
            The newly created ``SetupRecord``.
        """
        now = datetime.utcnow()
        record = SetupRecord(
            setup_id=setup_id,
            direction=direction,
            trade_class=trade_class,
            zone_label=zone_label,
            zone_price=zone_price,
            source_head=source_head,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self._setups[setup_id] = record

        # Ensure zone is tracked
        if zone_label:
            if zone_label not in self._zones:
                self._zones[zone_label] = ZoneMemory(
                    zone_label=zone_label,
                    first_seen_at=now,
                )

        return record

    def update_setup(
        self,
        setup_id: str,
        **updates: Any,
    ) -> SetupRecord | None:
        """Update an existing setup's fields.

        Args:
            setup_id: The setup to update.
            **updates: Fields to update (e.g., status, rejection_reason).

        Returns:
            Updated ``SetupRecord``, or None if not found.
        """
        record = self._setups.get(setup_id)
        if record is None:
            return None

        for key, value in updates.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = datetime.utcnow()

        return record

    def mark_rejected(
        self,
        setup_id: str,
        reason: str,
    ) -> SetupRecord | None:
        """Mark a setup as rejected with a reason.

        Args:
            setup_id: The setup to reject.
            reason: Why the setup was rejected.

        Returns:
            Updated ``SetupRecord``, or None if not found.
        """
        return self.update_setup(
            setup_id,
            status="REJECTED",
            rejection_reason=reason,
        )

    def mark_completed(
        self,
        setup_id: str,
    ) -> SetupRecord | None:
        """Mark a setup as completed (trade executed successfully).

        Args:
            setup_id: The setup to mark.

        Returns:
            Updated ``SetupRecord``, or None if not found.
        """
        return self.update_setup(setup_id, status="COMPLETED")

    def get_setup(self, setup_id: str) -> SetupRecord | None:
        """Get a setup by ID.

        Args:
            setup_id: The setup to retrieve.

        Returns:
            ``SetupRecord`` if found, else None.
        """
        return self._setups.get(setup_id)

    def get_active_setups(self) -> list[SetupRecord]:
        """Get all currently active setups.

        Returns:
            List of ``SetupRecord`` with status ACTIVE.
        """
        return [
            s for s in self._setups.values()
            if s.status == "ACTIVE"
        ]

    def get_rejected_setups(self) -> list[SetupRecord]:
        """Get all rejected setups with their rejection reasons.

        Returns:
            List of ``SetupRecord`` with status REJECTED.
        """
        return [
            s for s in self._setups.values()
            if s.status == "REJECTED"
        ]

    def get_all_setups(self) -> list[SetupRecord]:
        """Get all setups in memory.

        Returns:
            List of all ``SetupRecord`` entries.
        """
        return list(self._setups.values())

    def get_setup_count(self) -> int:
        """Get total number of setups tracked.

        Returns:
            Integer count of all setups.
        """
        return len(self._setups)

    def get_rejected_count(self) -> int:
        """Get number of rejected setups.

        Returns:
            Integer count of rejected setups.
        """
        return len(self.get_rejected_setups())

    # ------------------------------------------------------------------
    # Zone Trap Tracking
    # ------------------------------------------------------------------

    def mark_failed_zone(self, zone_label: str) -> ZoneMemory:
        """Mark a zone as failed (trap occurred).

        Increments trap count and marks the zone as failed.

        Args:
            zone_label: The zone that failed.

        Returns:
            Updated ``ZoneMemory`` for the zone.
        """
        now = datetime.utcnow()

        if zone_label not in self._zones:
            self._zones[zone_label] = ZoneMemory(
                zone_label=zone_label,
                first_seen_at=now,
            )

        zone = self._zones[zone_label]
        zone.trap_count += 1
        zone.last_trap_at = now
        zone.failed = True

        return zone

    def get_trap_count(self, zone_label: str) -> int:
        """Get how many times a zone has been a trap.

        Args:
            zone_label: The zone to check.

        Returns:
            Trap count (0 if zone never tracked).
        """
        zone = self._zones.get(zone_label)
        return zone.trap_count if zone else 0

    def is_failed_zone(self, zone_label: str) -> bool:
        """Check if a zone is marked as failed.

        Args:
            zone_label: The zone to check.

        Returns:
            True if the zone has been a trap and is marked failed.
        """
        zone = self._zones.get(zone_label)
        return zone.failed if zone else False

    def get_all_zones(self) -> list[ZoneMemory]:
        """Get all tracked zones.

        Returns:
            List of all ``ZoneMemory`` entries.
        """
        return list(self._zones.values())

    def get_failed_zones(self) -> list[ZoneMemory]:
        """Get all zones that have failed.

        Returns:
            List of ``ZoneMemory`` entries where failed is True.
        """
        return [z for z in self._zones.values() if z.failed]

    def get_zone_count(self) -> int:
        """Get total number of zones tracked.

        Returns:
            Integer count of all zones.
        """
        return len(self._zones)

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def clear_session(self) -> None:
        """Clear all setup and zone memory for a new trading day.

        This is called at the start of each new trading session.
        All intraday memory is reset.
        """
        self._setups.clear()
        self._zones.clear()

    def has_active_setups(self) -> bool:
        """Check if there are any active setups.

        Returns:
            True if at least one setup has status ACTIVE.
        """
        return any(s.status == "ACTIVE" for s in self._setups.values())

    # ------------------------------------------------------------------
    # Summary / Utility
    # ------------------------------------------------------------------

    def get_store_summary(self) -> dict[str, Any]:
        """Get a structured summary of the store state.

        Returns:
            Dict with store summary fields.
        """
        return {
            "total_setups": self.get_setup_count(),
            "active_setups": len(self.get_active_setups()),
            "rejected_setups": self.get_rejected_count(),
            "total_zones": self.get_zone_count(),
            "failed_zones": len(self.get_failed_zones()),
            "has_active": self.has_active_setups(),
        }
