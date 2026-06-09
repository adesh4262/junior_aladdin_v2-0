"""Side C Memory Layer — append-first event store.

Stores operational/system events for the EXECUTION_EVENT, HEALTH_EVENT,
OVERRIDE, and BLOCKED_ACTION families.  Append-first only — no mutation,
no deletion.

Architecture rules (LOCKED):
- Append-first only — no delete, no update, no mutation methods exist.
- Queryable by family + timerange, source, severity.
- Wrong-family events are rejected with ValueError.
- This store is connected to the router via ``set_store_callback``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_c_memory.c_types import EventFamily, MemoryEnvelope

logger = get_logger(__name__)


# =============================================================================
# Supported families (LOCKED)
# =============================================================================

_SUPPORTED_FAMILIES: frozenset[EventFamily] = frozenset({
    EventFamily.EXECUTION_EVENT,
    EventFamily.HEALTH_EVENT,
    EventFamily.OVERRIDE,
    EventFamily.BLOCKED_ACTION,
})


# =============================================================================
# In-memory storage
# =============================================================================

#: Primary store: event_id → MemoryEnvelope
_store: dict[str, MemoryEnvelope] = {}

#: Secondary index: (family.value, source, severity.value) → set of event_ids
#: Used for fast lookups without scanning the full store.
_family_index: dict[str, set[str]] = {}
_source_index: dict[str, set[str]] = {}
_severity_index: dict[str, set[str]] = {}


# =============================================================================
# Public API
# =============================================================================


def append_event(envelope: MemoryEnvelope) -> str | None:
    """Append an event to the store (callback-compatible with router).

    This function signature matches what the event router expects:
    ``Callable[[MemoryEnvelope], str | None]``.

    Args:
        envelope: The normalised ``MemoryEnvelope`` to store.  Must have
            a ``family`` in ``_SUPPORTED_FAMILIES``.

    Returns:
        A unique ``event_id`` string, or ``None`` if the event could not
        be stored.

    Raises:
        ValueError: If ``envelope.family`` is not supported by this store.
    """
    if envelope.family not in _SUPPORTED_FAMILIES:
        raise ValueError(
            f"Event store does not support family {envelope.family.value!r}. "
            f"Supported: {sorted(f.value for f in _SUPPORTED_FAMILIES)}"
        )

    # Generate unique event_id
    event_id = f"evt_{uuid.uuid4().hex[:12]}"

    # Update the envelope's payload_ref to point to this event_id
    envelope.payload_ref = event_id

    # Store
    _store[event_id] = envelope

    # Update secondary indexes
    _family_index.setdefault(envelope.family.value, set()).add(event_id)
    _source_index.setdefault(envelope.source, set()).add(event_id)
    _severity_index.setdefault(envelope.severity.value, set()).add(event_id)

    logger.info(
        "Event stored",
        extra={
            "event_id": event_id,
            "envelope_id": envelope.envelope_id,
            "family": envelope.family.value,
            "source": envelope.source,
            "severity": envelope.severity.value,
        },
    )

    return event_id


def get_event(event_id: str) -> MemoryEnvelope | None:
    """Retrieve a single event by its event_id.

    Args:
        event_id: The unique event identifier.

    Returns:
        The ``MemoryEnvelope`` if found, or ``None``.
    """
    return _store.get(event_id)


def query_events(
    families: list[EventFamily] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    source: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MemoryEnvelope]:
    """Query events from the store with optional filters.

    Results are ordered by timestamp ascending.

    Args:
        families: Optional list of families to include (empty = all
            supported families).
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).
        source: Optional source name filter.
        severity: Optional severity string filter (e.g. ``"INFO"``).
        limit: Maximum number of results (default 100, max 1000).
        offset: Number of results to skip (default 0).

    Returns:
        List of matching ``MemoryEnvelope`` objects, ordered by timestamp
        ascending.
    """
    # ── 1. Determine candidate event_ids from indexes ─────────────────
    candidate_ids: set[str] | None = None

    # Family filter (use index)
    if families:
        fam_set: set[str] = set()
        for f in families:
            fam_set.update(_family_index.get(f.value, set()))
        candidate_ids = _intersect(candidate_ids, fam_set)

    # Source filter (use index)
    if source:
        src_set = _source_index.get(source, set())
        candidate_ids = _intersect(candidate_ids, src_set)

    # Severity filter (use index)
    if severity:
        sev_set = _severity_index.get(severity, set())
        candidate_ids = _intersect(candidate_ids, sev_set)

    # No filters → return all
    if candidate_ids is None:
        candidate_ids = set(_store.keys())

    # ── 2. Fetch envelopes ────────────────────────────────────────────
    results: list[MemoryEnvelope] = []
    for eid in candidate_ids:
        env = _store.get(eid)
        if env is None:
            continue

        # Timerange filter (post-filter, not indexed)
        if start_time and env.timestamp and env.timestamp < start_time:
            continue
        if end_time and env.timestamp and env.timestamp > end_time:
            continue

        results.append(env)

    # ── 3. Sort by timestamp ascending ────────────────────────────────
    results.sort(key=lambda e: e.timestamp or datetime.min)

    # ── 4. Apply offset / limit ───────────────────────────────────────
    # Note: limit=0 returns empty (roadmap compliance), negative limit returns all.
    if offset > 0:
        results = results[offset:]
    if limit >= 0:
        results = results[:limit]

    return results


def count_events(
    families: list[EventFamily] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> int:
    """Count events matching the given criteria (without fetching them).

    Args:
        families: Optional list of families to count (empty = all
            supported families).
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).

    Returns:
        Number of matching events.
    """
    # Use query_events with limit=0 to get the full, uncapped count.
    # limit=0 returns empty list (sliced), so we call with negative limit
    # which means "no limit".  This is safe because the store is in-memory.
    return len(query_events(
        families=families,
        start_time=start_time,
        end_time=end_time,
        limit=-1,  # no limit (negative = return all)
    ))


def clear() -> None:
    """Clear all events from the store (testing utility only).

    .. warning::
       This is intended for test isolation.  In production, Side C
       stores NEVER delete data.
    """
    _store.clear()
    _family_index.clear()
    _source_index.clear()
    _severity_index.clear()
    logger.info("Event store cleared")


# =============================================================================
# Internal helpers
# =============================================================================


def _intersect(
    base: set[str] | None,
    incoming: set[str],
) -> set[str]:
    """Intersect an optional base set with an incoming set.

    If ``base`` is ``None``, returns ``incoming`` (initialises the
    intersection chain).

    Args:
        base: Existing candidate set, or ``None``.
        incoming: New set to intersect with.

    Returns:
        The intersected set.
    """
    if base is None:
        return set(incoming)
    return base & incoming
