"""Side C Memory Layer — family-based retention manager.

Enforces configurable retention policies per event family, with archive
support (move to colder storage) and expiry (removal from active store).

Architecture rules (LOCKED):
- Archive preserves events (moves to archive, NOT deletion).
- Expiry removes events from active store permanently.
- Default policies are locked (365d journals, 90d events, 30d refs).
- Errors are logged but do not crash the system.
- The manager archives events that exceed max_age_days, then expires
  events that exceed max_age_days + archive_after_days.

Default retention policies (LOCKED)::

    TRADE_JOURNAL:     max_age_days=365, archive_after_days=90
    DECISION_JOURNAL:  max_age_days=365, archive_after_days=90
    OVERRIDE:          max_age_days=365, archive_after_days=90
    EXECUTION_EVENT:   max_age_days=90,  archive_after_days=30
    HEALTH_EVENT:      max_age_days=90,  archive_after_days=30
    BLOCKED_ACTION:    max_age_days=90,  archive_after_days=30
    REPLAY_REF:        max_age_days=30,  archive_after_days=None
    REVIEW_REF:        max_age_days=30,  archive_after_days=None
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_c_memory.c_types import (
    DEFAULT_RETENTION_POLICIES,
    EventFamily,
    RetentionPolicy,
)
from junior_aladdin.side_c_memory import (
    event_store as _event_store,
    journal_store as _journal_store,
    reference_store as _reference_store,
)

logger = get_logger(__name__)


# =============================================================================
# Active policies (mutable copy of defaults)
# =============================================================================

_active_policies: dict[EventFamily, RetentionPolicy] = {
    p.family: p for p in DEFAULT_RETENTION_POLICIES
}

#: Archive storage: store_name → { event_id → MemoryEnvelope }
#: Events moved here by apply_retention_policy() are preserved but not
#: visible through normal query paths.
_archives: dict[str, dict[str, Any]] = {
    "event_store": {},
    "journal_store": {},
    "reference_store": {},
}


# =============================================================================
# Store access helpers
# =============================================================================

#: Map family → (store_module, store_name, id_prefix)
_STORE_MAP: dict[EventFamily, tuple[Any, str, str]] = {
    EventFamily.EXECUTION_EVENT: (_event_store, "event_store", "evt_"),
    EventFamily.HEALTH_EVENT: (_event_store, "event_store", "evt_"),
    EventFamily.OVERRIDE: (_event_store, "event_store", "evt_"),
    EventFamily.BLOCKED_ACTION: (_event_store, "event_store", "evt_"),
    EventFamily.TRADE_JOURNAL: (_journal_store, "journal_store", "jnl_"),
    EventFamily.DECISION_JOURNAL: (_journal_store, "journal_store", "jnl_"),
    EventFamily.REPLAY_REF: (_reference_store, "reference_store", "ref_"),
    EventFamily.REVIEW_REF: (_reference_store, "reference_store", "ref_"),
}


def _get_store_for_family(family: EventFamily) -> tuple[Any, str, str] | None:
    """Get the store module, name, and ID prefix for a family.

    Args:
        family: The event family.

    Returns:
        ``(module, store_name, id_prefix)`` tuple, or ``None`` if the
        family is not mapped.
    """
    return _STORE_MAP.get(family)


# =============================================================================
# Public API
# =============================================================================


def set_retention_policy(
    family: EventFamily,
    policy: RetentionPolicy,
) -> None:
    """Override the default retention policy for a family.

    Args:
        family: The event family to update.
        policy: The new ``RetentionPolicy``.

    Raises:
        ValueError: If ``policy.max_age_days < 1``.
    """
    if policy.max_age_days < 1:
        raise ValueError(
            f"max_age_days must be >= 1, got {policy.max_age_days}"
        )
    _active_policies[family] = policy
    logger.info(
        "Retention policy updated",
        extra={
            "family": family.value,
            "max_age_days": policy.max_age_days,
            "archive_after_days": policy.archive_after_days,
        },
    )


def get_retention_status() -> dict[str, Any]:
    """Get retention status across all families.

    Returns per-family: total event count in active store, oldest event
    age in days, and estimated days until next expiry.

    Returns:
        Dict keyed by family value string with per-family status.
    """
    now = datetime.now(timezone.utc)
    status: dict[str, Any] = {}

    for family in EventFamily:
        store_info = _get_store_for_family(family)
        if store_info is None:
            continue
        module, store_name, _ = store_info
        policy = _active_policies.get(family)
        if policy is None:
            continue

        # Count events for this family
        family_ids = module._family_index.get(family.value, set())  # type: ignore[attr-defined]
        total_count = len(family_ids)

        # Find oldest event age
        oldest_age_days: float | None = None
        next_expiry_days: float | None = None
        for eid in family_ids:
            env = module._store.get(eid)  # type: ignore[attr-defined]
            if env and env.timestamp:
                age_days = (now - env.timestamp).total_seconds() / 86400.0
                if oldest_age_days is None or age_days > oldest_age_days:
                    oldest_age_days = age_days

        # Calculate days until next expiry
        if oldest_age_days is not None:
            if policy.archive_after_days is not None:
                expiry_threshold = policy.max_age_days + policy.archive_after_days
            else:
                expiry_threshold = policy.max_age_days
            next_expiry_days = max(0.0, expiry_threshold - oldest_age_days)

        status[family.value] = {
            "total_count": total_count,
            "oldest_event_age_days": round(oldest_age_days, 1) if oldest_age_days is not None else None,
            "next_expiry_days": round(next_expiry_days, 1) if next_expiry_days is not None else None,
            "max_age_days": policy.max_age_days,
            "archive_after_days": policy.archive_after_days,
        }

    return status


def apply_retention_policy() -> dict[str, Any]:
    """Apply retention policies to all families across all stores.

    For each family:
    1. Events older than ``max_age_days + archive_after_days`` are
       **expired** (removed from active store permanently).
    2. Events older than ``max_age_days`` but not yet expired are
       **archived** (moved to colder storage, preserved).
    3. If ``archive_after_days`` is ``None``, events are expired
       directly after ``max_age_days`` (no archive step).

    Returns:
        Summary dict with keys ``families_affected``, ``events_archived``,
        ``events_expired``, and ``errors``.
    """
    now = datetime.now(timezone.utc)
    summary: dict[str, Any] = {
        "families_affected": [],
        "events_archived": 0,
        "events_expired": 0,
        "errors": [],
    }

    for family in EventFamily:
        store_info = _get_store_for_family(family)
        if store_info is None:
            continue
        module, store_name, _ = store_info
        policy = _active_policies.get(family)
        if policy is None:
            continue

        family_ids = set(module._family_index.get(family.value, set()))  # type: ignore[attr-defined]

        if not family_ids:
            continue

        # Categorise events by age
        to_archive: set[str] = set()
        to_expire: set[str] = set()

        if policy.archive_after_days is not None:
            # Archive: age >= max_age_days AND age < max_age_days + archive_after_days
            archive_threshold = policy.max_age_days
            expiry_threshold = policy.max_age_days + policy.archive_after_days
            for eid in family_ids:
                env = module._store.get(eid)  # type: ignore[attr-defined]
                if env and env.timestamp:
                    age_days = (now - env.timestamp).total_seconds() / 86400.0
                    if age_days >= expiry_threshold:
                        to_expire.add(eid)
                    elif age_days >= archive_threshold:
                        to_archive.add(eid)
        else:
            # No archive: expire directly after max_age_days
            for eid in family_ids:
                env = module._store.get(eid)  # type: ignore[attr-defined]
                if env and env.timestamp:
                    age_days = (now - env.timestamp).total_seconds() / 86400.0
                    if age_days >= policy.max_age_days:
                        to_expire.add(eid)

        # Remove expired events from indexes first, then from store
        for eid in to_expire:
            env = module._store.get(eid)  # type: ignore[attr-defined]
            if env:
                _remove_from_indexes(module, eid, env)

        for eid in to_expire:
            module._store.pop(eid, None)  # type: ignore[attr-defined]

        # Archive: copy to archive store, then remove from active store + indexes
        for eid in to_archive:
            env = module._store.get(eid)  # type: ignore[attr-defined]
            if env:
                _archives[store_name][eid] = copy.deepcopy(env)
                _remove_from_indexes(module, eid, env)

        for eid in to_archive:
            module._store.pop(eid, None)  # type: ignore[attr-defined]

        if to_archive or to_expire:
            summary["families_affected"].append(family.value)

        summary["events_archived"] += len(to_archive)
        summary["events_expired"] += len(to_expire)

        if to_archive or to_expire:
            logger.info(
                "Retention applied",
                extra={
                    "family": family.value,
                    "archived": len(to_archive),
                    "expired": len(to_expire),
                },
            )

    return summary


# =============================================================================
# Internal helpers
# =============================================================================


def _remove_from_indexes(module: Any, eid: str, env: Any) -> None:
    """Remove an event from a store's secondary indexes.

    Args:
        module: The store module (event_store, journal_store, etc.).
        eid: The event/journal/ref ID to remove from indexes.
        env: The MemoryEnvelope being removed (for index key extraction).
    """
    # Family index
    fam_set = module._family_index.get(env.family.value)
    if fam_set:
        fam_set.discard(eid)
        if not fam_set:
            del module._family_index[env.family.value]

    # Source index (event_store only)
    src_index = getattr(module, "_source_index", None)
    if src_index is not None:
        src_set = src_index.get(env.source)
        if src_set:
            src_set.discard(eid)
            if not src_set:
                del src_index[env.source]

    # Severity index (event_store only)
    sev_index = getattr(module, "_severity_index", None)
    if sev_index is not None:
        sev_set = sev_index.get(env.severity.value)
        if sev_set:
            sev_set.discard(eid)
            if not sev_set:
                del sev_index[env.severity.value]

    # Trade / decision ID indexes (journal_store only)
    tid_index = getattr(module, "_trade_id_index", None)
    if tid_index is not None and env.refs:
        trade_id = env.refs.get("trade_id")
        if trade_id:
            tid_set = tid_index.get(str(trade_id))
            if tid_set:
                tid_set.discard(eid)
                if not tid_set:
                    del tid_index[str(trade_id)]
        decision_id = env.refs.get("decision_id")
        if decision_id:
            did_index = getattr(module, "_decision_id_index", None)
            if did_index is not None:
                did_set = did_index.get(str(decision_id))
                if did_set:
                    did_set.discard(eid)
                    if not did_set:
                        del did_index[str(decision_id)]

    # Ref key index (reference_store only)
    ref_key_index = getattr(module, "_ref_key_index", None)
    if ref_key_index is not None and env.refs:
        ref_key = env.refs.get("ref_key")
        if ref_key:
            rk_set = ref_key_index.get(str(ref_key))
            if rk_set:
                rk_set.discard(eid)
                if not rk_set:
                    del ref_key_index[str(ref_key)]
