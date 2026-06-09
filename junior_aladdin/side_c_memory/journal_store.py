"""Side C Memory Layer — append-first journal store.

Stores durable journal records for the TRADE_JOURNAL and DECISION_JOURNAL
families.  Journal records are higher-level narrative memory with
refs-based lookup by trade_id or decision_id.

Architecture rules (LOCKED):
- Append-first only — no delete, no update, no mutation methods exist.
- Queryable by family + timerange, trade_id, decision_id.
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
    EventFamily.TRADE_JOURNAL,
    EventFamily.DECISION_JOURNAL,
})


# =============================================================================
# In-memory storage
# =============================================================================

#: Primary store: journal_id → MemoryEnvelope
_store: dict[str, MemoryEnvelope] = {}

#: Secondary indexes
_family_index: dict[str, set[str]] = {}
_trade_id_index: dict[str, set[str]] = {}    # refs["trade_id"] → journal_ids
_decision_id_index: dict[str, set[str]] = {}  # refs["decision_id"] → journal_ids


# =============================================================================
# Public API
# =============================================================================


def append_journal(envelope: MemoryEnvelope) -> str | None:
    """Append a journal record to the store (callback-compatible with router).

    This function signature matches what the event router expects:
    ``Callable[[MemoryEnvelope], str | None]``.

    Args:
        envelope: The normalised ``MemoryEnvelope`` to store.  Must have
            a ``family`` in ``_SUPPORTED_FAMILIES``.

    Returns:
        A unique ``journal_id`` string, or ``None`` if the record could
        not be stored.

    Raises:
        ValueError: If ``envelope.family`` is not supported by this store.
    """
    if envelope.family not in _SUPPORTED_FAMILIES:
        raise ValueError(
            f"Journal store does not support family {envelope.family.value!r}. "
            f"Supported: {sorted(f.value for f in _SUPPORTED_FAMILIES)}"
        )

    # Generate unique journal_id
    journal_id = f"jnl_{uuid.uuid4().hex[:12]}"

    # Update the envelope's payload_ref to point to this journal_id
    envelope.payload_ref = journal_id

    # Store
    _store[journal_id] = envelope

    # Update secondary indexes
    _family_index.setdefault(envelope.family.value, set()).add(journal_id)

    # Index by trade_id / decision_id from refs dict
    if envelope.refs:
        trade_id = envelope.refs.get("trade_id")
        if trade_id:
            _trade_id_index.setdefault(str(trade_id), set()).add(journal_id)
        decision_id = envelope.refs.get("decision_id")
        if decision_id:
            _decision_id_index.setdefault(str(decision_id), set()).add(journal_id)

    logger.info(
        "Journal stored",
        extra={
            "journal_id": journal_id,
            "envelope_id": envelope.envelope_id,
            "family": envelope.family.value,
        },
    )

    return journal_id


def get_journal(journal_id: str) -> MemoryEnvelope | None:
    """Retrieve a single journal record by its journal_id.

    Args:
        journal_id: The unique journal identifier.

    Returns:
        The ``MemoryEnvelope`` if found, or ``None``.
    """
    return _store.get(journal_id)


def query_journals(
    families: list[EventFamily] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    trade_id: str | None = None,
    decision_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MemoryEnvelope]:
    """Query journal records with optional filters.

    Supports refs-based lookup by ``trade_id`` or ``decision_id``
    (looked up from each envelope's ``refs`` dict).

    Results are ordered by timestamp ascending.

    Args:
        families: Optional list of families to include (empty = all
            supported families).
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).
        trade_id: Optional trade ID to look up via ``refs`` dict.
        decision_id: Optional decision ID to look up via ``refs`` dict.
        limit: Maximum number of results (default 100).
        offset: Number of results to skip (default 0).

    Returns:
        List of matching ``MemoryEnvelope`` objects, ordered by timestamp
        ascending.
    """
    # ── 1. Determine candidate journal_ids from indexes ───────────────
    candidate_ids: set[str] | None = None

    # Family filter (use index)
    if families:
        fam_set: set[str] = set()
        for f in families:
            fam_set.update(_family_index.get(f.value, set()))
        candidate_ids = _intersect(candidate_ids, fam_set)

    # Trade ID lookup via refs index
    if trade_id:
        tid_set = _trade_id_index.get(trade_id, set())
        candidate_ids = _intersect(candidate_ids, tid_set)

    # Decision ID lookup via refs index
    if decision_id:
        did_set = _decision_id_index.get(decision_id, set())
        candidate_ids = _intersect(candidate_ids, did_set)

    # No filters → return all
    if candidate_ids is None:
        candidate_ids = set(_store.keys())

    # ── 2. Fetch envelopes ────────────────────────────────────────────
    results: list[MemoryEnvelope] = []
    for jid in candidate_ids:
        env = _store.get(jid)
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
    # Note: limit=0 returns empty (roadmap compliance), negative returns all.
    if offset > 0:
        results = results[offset:]
    if limit >= 0:
        results = results[:limit]

    return results


def count_journals(
    families: list[EventFamily] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> int:
    """Count journal records matching the given criteria.

    Args:
        families: Optional list of families to count (empty = all
            supported families).
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).

    Returns:
        Number of matching journal records.
    """
    return len(query_journals(
        families=families,
        start_time=start_time,
        end_time=end_time,
        limit=-1,  # no limit
    ))


def clear() -> None:
    """Clear all journal records from the store (testing utility only).

    .. warning::
       This is intended for test isolation.  In production, Side C
       stores NEVER delete data.
    """
    _store.clear()
    _family_index.clear()
    _trade_id_index.clear()
    _decision_id_index.clear()
    logger.info("Journal store cleared")


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
