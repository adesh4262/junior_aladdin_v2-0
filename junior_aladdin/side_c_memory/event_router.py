"""Side C Memory Layer — event router for classified store dispatch.

Classifies every incoming MemoryEnvelope by family and routes it to
the correct store (event_store, journal_store, or reference_store).
Payload-level validation happens at the ingest layer (Step 3.3);
the router performs a lightweight envelope sanity check only.

Architecture rules (LOCKED):
- Classification by family is the ONLY routing criterion.
- Append-first enforced: router does NOT modify envelope data.
- Unknown family raises ContractViolationError.
- Stores are connected via callbacks (built in Steps 3.5-3.7).
"""

from __future__ import annotations

from typing import Callable

from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_c_memory.c_types import EventFamily, MemoryEnvelope

logger = get_logger(__name__)


# =============================================================================
# Routing table (LOCKED)
# =============================================================================

_ROUTING_TABLE: dict[EventFamily, str] = {
    # Journals → journal_store
    EventFamily.TRADE_JOURNAL: "journal_store",
    EventFamily.DECISION_JOURNAL: "journal_store",
    # Operational events → event_store
    EventFamily.EXECUTION_EVENT: "event_store",
    EventFamily.HEALTH_EVENT: "event_store",
    EventFamily.OVERRIDE: "event_store",
    EventFamily.BLOCKED_ACTION: "event_store",
    # References → reference_store
    EventFamily.REPLAY_REF: "reference_store",
    EventFamily.REVIEW_REF: "reference_store",
}

#: Reverse lookup: store name → list of families routed to that store.
_STORE_FAMILIES: dict[str, list[EventFamily]] = {}
for _family, _store in _ROUTING_TABLE.items():
    _STORE_FAMILIES.setdefault(_store, []).append(_family)


# =============================================================================
# Store callbacks
# =============================================================================

#: Registered store callbacks keyed by store name.
#: Set via :func:`set_store_callback` once stores are built (Steps 3.5-3.7).
_store_callbacks: dict[str, Callable[[MemoryEnvelope], str | None]] = {}


def set_store_callback(
    store_name: str,
    callback: Callable[[MemoryEnvelope], str | None] | None,
) -> None:
    """Connect a store to the event router.

    The callback receives a ``MemoryEnvelope`` and should return a
    string identifier (e.g. event_id, journal_id, ref_id) or ``None``
    if the store rejects the envelope.

    Args:
        store_name: One of ``\"event_store\"``, ``\"journal_store\"``,
            or ``\"reference_store\"``.
        callback: A callable that accepts a ``MemoryEnvelope`` and
            returns an ID string, or ``None`` to disconnect.
    """
    if callback is not None:
        _store_callbacks[store_name] = callback
        logger.info("Store connected to router", extra={"store": store_name})
    else:
        _store_callbacks.pop(store_name, None)
        logger.info("Store disconnected from router", extra={"store": store_name})


# =============================================================================
# Public API
# =============================================================================


def get_routing_rule(family: EventFamily) -> str:
    """Get the target store name for a given event family.

    Args:
        family: The event family to look up.

    Returns:
        The store name (``\"event_store\"``, ``\"journal_store\"``,
        or ``\"reference_store\"``).

    Raises:
        ContractViolationError: If the family is not in the routing table.
    """
    store = _ROUTING_TABLE.get(family)
    if store is None:
        raise ContractViolationError(
            f"Unknown family: {family.value!r}. "
            f"No routing rule defined.",
            details={"family": family.value},
        )
    return store


def get_families_for_store(store_name: str) -> list[EventFamily]:
    """Get all families routed to a given store.

    Args:
        store_name: The store name (``\"event_store\"``, ``\"journal_store\"``,
            or ``\"reference_store\"``).

    Returns:
        List of ``EventFamily`` values routed to that store.
    """
    return list(_STORE_FAMILIES.get(store_name, []))


def list_routing_rules() -> dict[str, list[str]]:
    """List all routing rules as a human-readable dict.

    Returns:
        Dict mapping store names to lists of family value strings.
    """
    return {
        store: [f.value for f in families]
        for store, families in sorted(_STORE_FAMILIES.items())
    }


def route_event(envelope: MemoryEnvelope) -> str:
    """Route a normalised MemoryEnvelope to the correct store.

    This function is designed to be used as the callback for
    :func:`~junior_aladdin.side_c_memory.ingest_layer.set_event_router`.

    Steps:
    1. Look up the store name from the routing table.
    2. Re-validate the envelope against the write contract for its family.
    3. Forward to the corresponding store callback if connected.
    4. Log the routing decision.

    Args:
        envelope: The normalised ``MemoryEnvelope`` to route.

    Returns:
        The store name the envelope was routed to.

    Raises:
        ContractViolationError: If the family is not in the routing table
            or if the envelope fails the basic sanity check (missing
            ``envelope_id`` or ``source``).
    """
    # ── 1. Look up routing rule ───────────────────────────────────────
    store_name = get_routing_rule(envelope.family)

    # ── 2. Lightweight envelope sanity check ─────────────────────────
    # Payload validation already happened at ingest_layer.
    # Here we only verify the envelope has the minimum fields populated.
    if not envelope.envelope_id:
        raise ContractViolationError(
            "Envelope missing envelope_id",
            details={"family": envelope.family.value},
        )
    if not envelope.source:
        raise ContractViolationError(
            "Envelope missing source",
            details={"envelope_id": envelope.envelope_id},
        )

    # ── 3. Forward to store callback ──────────────────────────────────
    store_cb = _store_callbacks.get(store_name)
    if store_cb is not None:
        result_id = store_cb(envelope)
        if result_id:
            logger.info(
                "Envelope stored successfully",
                extra={
                    "envelope_id": envelope.envelope_id,
                    "store": store_name,
                    "result_id": result_id,
                },
            )
        else:
            logger.warning(
                "Store returned no ID for envelope",
                extra={
                    "envelope_id": envelope.envelope_id,
                    "store": store_name,
                },
            )
    else:
        logger.info(
            "Envelope routed (no store connected)",
            extra={
                "envelope_id": envelope.envelope_id,
                "family": envelope.family.value,
                "store": store_name,
            },
        )

    # ── 4. Log routing decision ───────────────────────────────────────
    logger.info(
        "Event routed successfully",
        extra={
            "envelope_id": envelope.envelope_id,
            "family": envelope.family.value,
            "store": store_name,
        },
    )

    return store_name
