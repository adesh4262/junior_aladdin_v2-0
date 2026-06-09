"""Side C Memory Layer — approved emitter registry.

Defines which floors/sides may write to Side C and which event families
each emitter is authorised to emit.

Architecture rules (LOCKED):
- Only 4 approved emitters: Floor 1, Floor 2, Floor 5, Side A.
- Each emitter can write to specific families only — no exceptions.
- Unknown emitters are rejected at the ingest layer before any write.
- Emitter identities are the single source of truth for write authorisation.

Approved emitter definitions (LOCKED):
- floor_1:  [HEALTH_EVENT]
- floor_2:  [HEALTH_EVENT, REPLAY_REF, REVIEW_REF]
- floor_5:  [DECISION_JOURNAL]
- side_a:   [TRADE_JOURNAL, EXECUTION_EVENT, BLOCKED_ACTION, OVERRIDE]
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.side_c_memory.c_types import EventFamily


# ── Locked emitter definitions ──────────────────────────────────────────────
# (emitter_id) -> { "allowed_families": list[EventFamily], "source_owner": str }

_APPROVED_EMITTERS: dict[str, dict[str, Any]] = {
    "floor_1": {
        "allowed_families": [EventFamily.HEALTH_EVENT],
        "source_owner": "Floor 1 — Market Connection",
        "description": "Connection lifecycle events, auth failures, reconnects.",
    },
    "floor_2": {
        "allowed_families": [
            EventFamily.HEALTH_EVENT,
            EventFamily.REPLAY_REF,
            EventFamily.REVIEW_REF,
        ],
        "source_owner": "Floor 2 — Data Center",
        "description": "Data health changes, replay references, review references.",
    },
    "floor_5": {
        "allowed_families": [EventFamily.DECISION_JOURNAL],
        "source_owner": "Floor 5 — Captain",
        "description": "Decision journal, conviction bands, no-trade reasons.",
    },
    "side_a": {
        "allowed_families": [
            EventFamily.TRADE_JOURNAL,
            EventFamily.EXECUTION_EVENT,
            EventFamily.BLOCKED_ACTION,
            EventFamily.OVERRIDE,
        ],
        "source_owner": "Side A — Execution",
        "description": "Trade records, order lifecycle, blocked actions, overrides.",
    },
}


# ── Public API ──────────────────────────────────────────────────────────────


def register_emitter(
    emitter_id: str,
    allowed_families: list[EventFamily],
    source_owner: str,
    description: str = "",
) -> None:
    """Register a new approved emitter.

    .. note::
       This function is provided for testing and future extensibility.
       The four locked emitters (floor_1, floor_2, floor_5, side_a) are
       pre-registered on import and should not need manual registration.

    Args:
        emitter_id: Unique emitter identifier (e.g., ``\"floor_1\"``).
        allowed_families: List of event families this emitter may write.
        source_owner: Human-readable owner description.
        description: Optional longer description of the emitter's purpose.
    """
    _APPROVED_EMITTERS[emitter_id] = {
        "allowed_families": list(allowed_families),
        "source_owner": source_owner,
        "description": description,
    }


def is_emitter_approved(emitter_id: str) -> bool:
    """Check whether an emitter ID is registered.

    Args:
        emitter_id: The emitter identifier to check.

    Returns:
        ``True`` if the emitter is registered, ``False`` otherwise.
    """
    return emitter_id in _APPROVED_EMITTERS


def get_allowed_families(emitter_id: str) -> list[EventFamily]:
    """Get the list of event families an emitter is allowed to write.

    Args:
        emitter_id: The emitter identifier.

    Returns:
        List of allowed ``EventFamily`` values.

    Raises:
        KeyError: If the emitter is not registered.
    """
    if emitter_id not in _APPROVED_EMITTERS:
        raise KeyError(f"Unknown emitter: {emitter_id!r}")
    return list(_APPROVED_EMITTERS[emitter_id]["allowed_families"])


def get_emitter_info(emitter_id: str) -> dict[str, Any] | None:
    """Get full emitter registration info.

    Args:
        emitter_id: The emitter identifier.

    Returns:
        A dict with keys ``allowed_families``, ``source_owner``, and
        ``description``, or ``None`` if the emitter is not registered.
    """
    info = _APPROVED_EMITTERS.get(emitter_id)
    if info is None:
        return None
    return {
        "emitter_id": emitter_id,
        "allowed_families": [f.value for f in info["allowed_families"]],
        "source_owner": info["source_owner"],
        "description": info.get("description", ""),
    }


def list_approved_emitters() -> list[dict[str, Any]]:
    """List all registered emitters with their details.

    Returns:
        A list of dicts, one per emitter, each containing ``emitter_id``,
        ``allowed_families``, ``source_owner``, and ``description``.
    """
    return [
        get_emitter_info(eid)
        for eid in sorted(_APPROVED_EMITTERS.keys())
    ]


def family_allowed_for_emitter(emitter_id: str, family: EventFamily) -> bool:
    """Check whether a specific family is allowed for an emitter.

    Convenience wrapper around :func:`get_allowed_families`.

    Args:
        emitter_id: The emitter identifier.
        family: The event family to check.

    Returns:
        ``True`` if the family is in the emitter's allowed list.
    """
    try:
        return family in get_allowed_families(emitter_id)
    except KeyError:
        return False
