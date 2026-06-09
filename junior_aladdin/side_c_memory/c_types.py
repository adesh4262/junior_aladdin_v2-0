"""Side C Memory Layer — custom types and dataclasses.

This file defines Side C specific types for the memory layer:
event envelopes, query contracts, retention policies, and read model summaries.

Architecture rules (LOCKED):
- Side C stores facts, does NOT create truth.
- Side C may summarise, may NOT score/rank/recommend/analyze.
- Append-first only — no mutation, no deletion.
- Correction = new event (no silent mutation).

All core shared types (``MemoryEvent``, ``MemoryEventFamily``, ``Severity``)
are imported from ``shared/types.py`` — the single source of truth.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.types import (
    MemoryEventFamily,
    Severity,
)

#: Convenience alias: the 8 locked event families.
EventFamily = MemoryEventFamily


@dataclass
class MemoryEnvelope:
    """Normalised envelope that wraps every event entering Side C.

    The ingest layer creates this from raw event data before routing to
    the correct store.  Every event stored in Side C has an envelope.

    Fields:
        envelope_id: Globally unique identifier for this envelope.
        family: Event family classification (routing key to store).
        event_type: Specific type within the family.
        source: Emitting floor/side name (e.g. ``\"floor_1\"``).
        emitter: Specific emitter ID from the emitter registry.
        timestamp: When the event occurred (UTC).
        severity: Event severity level.
        refs: Dict of reference links (e.g., ``{\"trade_id\": \"T123\"}``).
        payload_ref: Reference to the payload location (e.g., event_id,
            journal_id, or ref_id after storage).
    """

    envelope_id: str = ""
    family: EventFamily = EventFamily.HEALTH_EVENT
    event_type: str = ""
    source: str = ""
    emitter: str = ""
    timestamp: datetime | None = None
    severity: Severity = Severity.INFO
    refs: dict[str, Any] = field(default_factory=dict)
    payload_ref: str = ""

    def __post_init__(self) -> None:
        """Auto-generate envelope_id if not set."""
        if not self.envelope_id:
            self.envelope_id = f"env_{uuid.uuid4().hex[:12]}"


@dataclass
class MemoryQuery:
    """Query parameters for retrieving events from Side C stores.

    Fields:
        families: List of event families to include (empty = all families).
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).
        refs_filter: Optional dict of ref key → value to filter by
            (e.g., ``{\"trade_id\": \"T123\"}``).
        limit: Maximum number of results to return (default 100).
        offset: Number of results to skip (for pagination, default 0).
    """

    families: list[EventFamily] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    refs_filter: dict[str, str] | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class RetentionPolicy:
    """Retention configuration for a single event family.

    Fields:
        family: The event family this policy applies to.
        max_age_days: Events older than this are archived or expired.
            Must be >= 1.
        archive_after_days: If set, events are moved to archive (not
            deleted) after this many days.  If ``None``, events are
            deleted outright after max_age_days.
    """

    family: EventFamily = EventFamily.HEALTH_EVENT
    max_age_days: int = 90
    archive_after_days: int | None = 30


@dataclass
class ReadModelSummary:
    """Lightweight read model / projection for Side B consumption.

    Side B NEVER consumes raw stores — only these summaries.

    Fields:
        family: Which event family this summary covers.
        timerange: ``(start, end)`` datetime tuple for the covered period.
        event_count: Number of events in this summary.
        summary_data: Family-specific aggregated data dict.
            - trade_history: ``{\"trade_id\", \"entry\", \"exit\", \"pnl\", \"mode\"}``
            - decision_review: ``{\"conviction_band\", \"reason\"}``
            - health_timeline: ``{\"transitions\", \"severity_counts\"}``
            - override_history: ``{\"override_count\", \"reasons\"}``
            - blocked_actions: ``{\"block_count\", \"severity_breakdown\"}``
    """

    family: EventFamily = EventFamily.HEALTH_EVENT
    timerange: tuple[datetime, datetime] | None = None
    event_count: int = 0
    summary_data: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Default retention policies (LOCKED)
# =============================================================================

DEFAULT_RETENTION_POLICIES: list[RetentionPolicy] = [
    RetentionPolicy(family=EventFamily.TRADE_JOURNAL, max_age_days=365, archive_after_days=90),
    RetentionPolicy(family=EventFamily.DECISION_JOURNAL, max_age_days=365, archive_after_days=90),
    RetentionPolicy(family=EventFamily.OVERRIDE, max_age_days=365, archive_after_days=90),
    RetentionPolicy(family=EventFamily.EXECUTION_EVENT, max_age_days=90, archive_after_days=30),
    RetentionPolicy(family=EventFamily.HEALTH_EVENT, max_age_days=90, archive_after_days=30),
    RetentionPolicy(family=EventFamily.BLOCKED_ACTION, max_age_days=90, archive_after_days=30),
    RetentionPolicy(family=EventFamily.REPLAY_REF, max_age_days=30, archive_after_days=None),
    RetentionPolicy(family=EventFamily.REVIEW_REF, max_age_days=30, archive_after_days=None),
]
