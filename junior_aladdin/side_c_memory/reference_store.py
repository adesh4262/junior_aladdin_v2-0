"""Side C Memory Layer — append-first reference store.

Stores linkable references for the REPLAY_REF and REVIEW_REF families.
References are linking instruments with key-value lookup by ref_key
(e.g. ``"trade_id:123"`` → all refs for that trade).

Architecture rules (LOCKED):
- Append-first only — no delete, no update, no mutation methods exist.
- Queryable by ref_type, timerange, and ref_key.
- Key-value lookup via ``lookup_by_key`` (ref_key → list of envelopes).
- Wrong-family events are rejected with ValueError.
- This store is connected to the router via ``set_store_callback``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_c_memory.c_types import EventFamily, MemoryEnvelope

logger = get_logger(__name__)


# =============================================================================
# Supported families (LOCKED)
# =============================================================================

_SUPPORTED_FAMILIES: frozenset[EventFamily] = frozenset({
    EventFamily.REPLAY_REF,
    EventFamily.REVIEW_REF,
})


# =============================================================================
# In-memory storage
# =============================================================================

#: Primary store: ref_id → MemoryEnvelope
_store: dict[str, MemoryEnvelope] = {}

#: Secondary indexes
_family_index: dict[str, set[str]] = {}
_ref_key_index: dict[str, set[str]] = {}  # payload["ref_key"] → ref_ids


# =============================================================================
# Public API
# =============================================================================


def store_reference(envelope: MemoryEnvelope) -> str | None:
    """Store a reference record (callback-compatible with router).

    This function signature matches what the event router expects:
    ``Callable[[MemoryEnvelope], str | None]``.

    The reference's ``ref_key`` is extracted from
    ``payload.get("ref_key", "")`` and indexed for key-value lookup.

    Args:
        envelope: The normalised ``MemoryEnvelope`` to store.  Must have
            a ``family`` in ``_SUPPORTED_FAMILIES``.

    Returns:
        A unique ``ref_id`` string, or ``None`` if the record could not
        be stored.

    Raises:
        ValueError: If ``envelope.family`` is not supported by this store.
    """
    if envelope.family not in _SUPPORTED_FAMILIES:
        raise ValueError(
            f"Reference store does not support family {envelope.family.value!r}. "
            f"Supported: {sorted(f.value for f in _SUPPORTED_FAMILIES)}"
        )

    # Generate unique ref_id
    ref_id = f"ref_{uuid.uuid4().hex[:12]}"

    # Update the envelope's payload_ref to point to this ref_id
    envelope.payload_ref = ref_id

    # Store
    _store[ref_id] = envelope

    # Update secondary indexes
    _family_index.setdefault(envelope.family.value, set()).add(ref_id)

    # Index by ref_key from payload
    # (payload is NOT carried in the envelope, but ref_key is a metadata field)
    # For reference stores, we use the envelope's payload_ref as a hint.
    # In practice, the ingest layer provides the ref_key in the envelope's refs dict.
    if envelope.refs:
        ref_key = envelope.refs.get("ref_key", "")
        if ref_key:
            _ref_key_index.setdefault(str(ref_key), set()).add(ref_id)

    logger.info(
        "Reference stored",
        extra={
            "ref_id": ref_id,
            "envelope_id": envelope.envelope_id,
            "family": envelope.family.value,
        },
    )

    return ref_id


def get_reference(ref_id: str) -> MemoryEnvelope | None:
    """Retrieve a single reference by its ref_id.

    Args:
        ref_id: The unique reference identifier.

    Returns:
        The ``MemoryEnvelope`` if found, or ``None``.
    """
    return _store.get(ref_id)


def lookup_by_key(ref_key: str) -> list[MemoryEnvelope]:
    """Look up all references by a key-value ref_key.

    Checks the index first.  If the index is empty (e.g. because ref_key
    was in the payload but not carried by the envelope), falls back to a
    full-store scan on ``env.refs``.

    Args:
        ref_key: The reference key to look up (e.g. ``"trade_id:123"``).

    Returns:
        List of ``MemoryEnvelope`` objects with that ref_key, ordered by
        timestamp ascending.
    """
    ref_ids = _ref_key_index.get(ref_key, set())

    if ref_ids:
        # Index hit — fast path
        results = [_store[rid] for rid in ref_ids if rid in _store]
    else:
        # Fallback: scan all envelopes in case ref_key wasn't indexed
        # (ref_key is a payload field per write_contracts; the envelope
        #  carries only refs, not payload, so the index may be empty.)
        results = [
            env for env in _store.values()
            if env.refs.get("ref_key") == ref_key
        ]

    results.sort(key=lambda e: e.timestamp or datetime.min)
    return results


def query_references(
    ref_types: list[EventFamily] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    ref_key: str | None = None,
    limit: int = 100,
) -> list[MemoryEnvelope]:
    """Query references with optional filters.

    Results are ordered by timestamp ascending.

    Args:
        ref_types: Optional list of reference families to include
            (empty = all supported families).
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).
        ref_key: Optional ref_key to filter by (key-value lookup).
        limit: Maximum number of results (default 100).

    Returns:
        List of matching ``MemoryEnvelope`` objects, ordered by timestamp
        ascending.
    """
    # ── 1. Determine candidate ref_ids from indexes ───────────────────
    candidate_ids: set[str] | None = None

    # Family/ref_type filter (use index)
    if ref_types:
        fam_set: set[str] = set()
        for f in ref_types:
            fam_set.update(_family_index.get(f.value, set()))
        candidate_ids = _intersect(candidate_ids, fam_set)

    # Ref key filter (use index)
    if ref_key:
        key_set = _ref_key_index.get(ref_key, set())
        candidate_ids = _intersect(candidate_ids, key_set)

    # No filters → return all
    if candidate_ids is None:
        candidate_ids = set(_store.keys())

    # ── 2. Fetch envelopes ────────────────────────────────────────────
    results: list[MemoryEnvelope] = []
    for rid in candidate_ids:
        env = _store.get(rid)
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

    # ── 4. Apply limit ────────────────────────────────────────────────
    if limit >= 0:
        results = results[:limit]

    return results


def clear() -> None:
    """Clear all references from the store (testing utility only).

    .. warning::
       This is intended for test isolation.  In production, Side C
       stores NEVER delete data.
    """
    _store.clear()
    _family_index.clear()
    _ref_key_index.clear()
    logger.info("Reference store cleared")


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
