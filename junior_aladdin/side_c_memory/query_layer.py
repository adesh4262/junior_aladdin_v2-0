"""Side C Memory Layer — unified query interface across all stores.

Provides family-aware retrieval across event_store, journal_store, and
reference_store.  Consumers (Side B, read_model_builder) use this layer
to query Side C data — they never access raw stores directly.

Architecture rules (LOCKED):
- Family-aware: routes each family to its correct store automatically.
- Ref-based lookups: supports trade_id / decision_id cross-store queries.
- No scoring, no ranking, no recommendation methods.
- No trade analysis, no decision analysis.
- Raises ValueError for invalid query parameters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_c_memory.c_types import EventFamily, MemoryEnvelope, MemoryQuery
from junior_aladdin.side_c_memory.event_store import query_events
from junior_aladdin.side_c_memory.journal_store import query_journals
from junior_aladdin.side_c_memory.reference_store import query_references

logger = get_logger(__name__)


# =============================================================================
# Store groupings for family-aware routing
# =============================================================================

#: Store groupings for batch queries
_JOURNAL_FAMILIES: frozenset[EventFamily] = frozenset({
    EventFamily.TRADE_JOURNAL,
    EventFamily.DECISION_JOURNAL,
})
_EVENT_FAMILIES: frozenset[EventFamily] = frozenset({
    EventFamily.EXECUTION_EVENT,
    EventFamily.HEALTH_EVENT,
    EventFamily.OVERRIDE,
    EventFamily.BLOCKED_ACTION,
})
_REFERENCE_FAMILIES: frozenset[EventFamily] = frozenset({
    EventFamily.REPLAY_REF,
    EventFamily.REVIEW_REF,
})


# =============================================================================
# Public API
# =============================================================================


def query(query_spec: MemoryQuery) -> list[MemoryEnvelope]:
    """Query events/journals/references across stores.

    Routes each requested family to its correct store, merges results,
    and sorts by timestamp ascending.

    Args:
        query_spec: A ``MemoryQuery`` dataclass with optional ``families``,
            ``start_time``, ``end_time``, ``limit``, and ``offset``.

    Returns:
        List of matching ``MemoryEnvelope`` objects, ordered by timestamp
        ascending.

    Raises:
        ValueError: If ``limit`` or ``offset`` are negative.
    """
    # ── 1. Validate ──────────────────────────────────────────────────────
    if query_spec.limit < -1:
        raise ValueError(f"limit must be >= -1, got {query_spec.limit}")
    if query_spec.offset < 0:
        raise ValueError(f"offset must be >= 0, got {query_spec.offset}")

    # Use -1 as sentinel for "no limit"
    effective_limit = query_spec.limit if query_spec.limit >= 0 else -1

    # ── 2. Determine which stores to query ───────────────────────────────
    if query_spec.families:
        journal_fams = [f for f in query_spec.families if f in _JOURNAL_FAMILIES]
        event_fams = [f for f in query_spec.families if f in _EVENT_FAMILIES]
        ref_fams = [f for f in query_spec.families if f in _REFERENCE_FAMILIES]
    else:
        # No family filter → query all stores
        journal_fams = []
        event_fams = []
        ref_fams = []

    # ── 3. Query each store ──────────────────────────────────────────────
    # NOTE: Each store is queried with limit=-1 (no truncation).
    # Truncation (offset/limit) is applied ONLY on the final merged and
    # sorted result set.  Applying per-store pagination would lose records
    # that belong to a different store's page (cross-store pagination bug).
    results: list[MemoryEnvelope] = []

    if journal_fams or (not query_spec.families):
        results.extend(
            query_journals(
                families=journal_fams if journal_fams else None,
                start_time=query_spec.start_time,
                end_time=query_spec.end_time,
                limit=-1,  # no per-store truncation
            )
        )

    if event_fams or (not query_spec.families):
        results.extend(
            query_events(
                families=event_fams if event_fams else None,
                start_time=query_spec.start_time,
                end_time=query_spec.end_time,
                limit=-1,  # no per-store truncation
            )
        )

    if ref_fams or (not query_spec.families):
        results.extend(
            query_references(
                ref_types=ref_fams if ref_fams else None,
                start_time=query_spec.start_time,
                end_time=query_spec.end_time,
                limit=-1,  # no per-store truncation
            )
        )

    # ── 4. Sort by timestamp ascending ───────────────────────────────────
    results.sort(key=lambda e: e.timestamp or datetime.min)

    # ── 5. Apply refs_filter if specified ────────────────────────────────
    if query_spec.refs_filter:
        results = [
            env for env in results
            if _match_refs_filter(env.refs, query_spec.refs_filter)
        ]

    # ── 6. Apply limit / offset on merged results ONLY ───────────────────
    if query_spec.offset > 0:
        results = results[query_spec.offset:]
    if effective_limit >= 0:
        results = results[:effective_limit]

    return results


def get_trade_history(trade_id: str) -> list[MemoryEnvelope]:
    """Get all records related to a trade.

    Queries:
    - ``journal_store`` for journals with matching ``trade_id`` ref.
    - ``event_store`` for EXECUTION_EVENT with matching ``trade_id`` ref.

    Args:
        trade_id: The trade identifier to look up.

    Returns:
        List of ``MemoryEnvelope`` objects related to the trade, ordered
        by timestamp ascending.
    """
    results: list[MemoryEnvelope] = []

    # Query journal_store for TRADE_JOURNAL with this trade_id
    results.extend(
        query_journals(
            families=list(_JOURNAL_FAMILIES),
            trade_id=trade_id,
            limit=-1,  # no limit
        )
    )

    # Query event_store for EXECUTION_EVENT with this trade_id in refs
    # Since query_events doesn't have a refs filter, we post-filter
    exec_events = query_events(
        families=[EventFamily.EXECUTION_EVENT],
        limit=-1,
    )
    results.extend(
        env for env in exec_events
        if env.refs.get("trade_id") == trade_id
    )

    results.sort(key=lambda e: e.timestamp or datetime.min)
    return results


def get_decision_history(decision_id: str) -> list[MemoryEnvelope]:
    """Get all records related to a decision.

    Queries:
    - ``journal_store`` for journals with matching ``decision_id`` ref.
    - ``reference_store`` for REVIEW_REF with matching decision_id ref_key.

    Args:
        decision_id: The decision identifier to look up.

    Returns:
        List of ``MemoryEnvelope`` objects related to the decision,
        ordered by timestamp ascending.
    """
    results: list[MemoryEnvelope] = []

    # Query journal_store for DECISION_JOURNAL with this decision_id
    results.extend(
        query_journals(
            families=[EventFamily.DECISION_JOURNAL],
            decision_id=decision_id,
            limit=-1,
        )
    )

    # Query reference_store for REVIEW_REF with ref_key matching decision_id
    ref_key = f"decision_id:{decision_id}"
    results.extend(
        query_references(
            ref_types=[EventFamily.REVIEW_REF],
            ref_key=ref_key,
            limit=-1,
        )
    )

    results.sort(key=lambda e: e.timestamp or datetime.min)
    return results


def get_health_timeline(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[MemoryEnvelope]:
    """Get all health events within a timerange.

    Args:
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).

    Returns:
        List of ``MemoryEnvelope`` objects for HEALTH_EVENT, ordered by
        timestamp ascending.
    """
    return query_events(
        families=[EventFamily.HEALTH_EVENT],
        start_time=start_time,
        end_time=end_time,
        limit=-1,  # no limit
    )


# =============================================================================
# Internal helpers
# =============================================================================


def _match_refs_filter(
    env_refs: dict[str, Any],
    refs_filter: dict[str, str],
) -> bool:
    """Check if an envelope's refs dict matches a refs_filter.

    Args:
        env_refs: The envelope's ``refs`` dict.
        refs_filter: Dict of key → value to match.

    Returns:
        ``True`` if all filter keys exist in env_refs with matching values.
    """
    for key, value in refs_filter.items():
        if str(env_refs.get(key, "")) != value:
            return False
    return True
