"""Side C Memory Layer — read contracts per query type.

Defines mandatory params, optional params, and response schemas for every
query type supported by the query layer.  Used to validate incoming queries
before they reach the stores.

Architecture rules (LOCKED):
- EVERY consumer query MUST match its query type's read contract.
- Missing mandatory params → validation failure with error message.
- Wrong param types → validation failure.
- Contracts are the single source of truth for query structure.
- No query type may have zero mandatory params.

Query types (5):
- trade_history: requires trade_id OR timerange
- decision_review: requires decision_id OR timerange
- health_timeline: requires timerange (mandatory)
- override_history: requires timerange (mandatory), optional override_type filter
- blocked_actions: requires timerange (mandatory), optional severity filter
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.side_c_memory.c_types import MemoryQuery


# =============================================================================
# Read contract definition
# =============================================================================


@dataclass
class ReadContract:
    """Schema definition for a single query type.

    Fields:
        query_type: Unique identifier for the query type
            (e.g. ``"trade_history"``).
        mandatory_params: Dict of param name → expected Python type
            that MUST be present in the query to be valid.
        optional_params: Dict of param name → expected Python type
            that MAY be present in the query.
        response_description: Human-readable description of the
            expected response format.
        description: Human-readable description of what this query
            type retrieves.
    """

    query_type: str
    mandatory_params: dict[str, type] = field(default_factory=dict)
    optional_params: dict[str, type] = field(default_factory=dict)
    response_description: str = ""
    description: str = ""


# =============================================================================
# Read contract definitions (LOCKED)
# =============================================================================

_READ_CONTRACTS: dict[str, ReadContract] = {
    "trade_history": ReadContract(
        query_type="trade_history",
        description="Retrieve all Side C records related to a specific trade.",
        mandatory_params={
            "trade_id": str,
        },
        optional_params={
            "start_time": datetime,
            "end_time": datetime,
        },
        response_description="List of MemoryEnvelope objects (trade journal + linked execution events).",
    ),
    "decision_review": ReadContract(
        query_type="decision_review",
        description="Retrieve all Side C records related to a specific decision.",
        mandatory_params={
            "decision_id": str,
        },
        optional_params={
            "start_time": datetime,
            "end_time": datetime,
        },
        response_description="List of MemoryEnvelope objects (decision journal + linked review refs).",
    ),
    "health_timeline": ReadContract(
        query_type="health_timeline",
        description="Retrieve health events within a timerange.",
        mandatory_params={
            "start_time": datetime,
            "end_time": datetime,
        },
        optional_params={
            "severity": str,
            "source": str,
        },
        response_description="List of HEALTH_EVENT MemoryEnvelope objects, ordered by timestamp ascending.",
    ),
    "override_history": ReadContract(
        query_type="override_history",
        description="Retrieve override events within a timerange.",
        mandatory_params={
            "start_time": datetime,
            "end_time": datetime,
        },
        optional_params={
            "override_type": str,
        },
        response_description="List of OVERRIDE MemoryEnvelope objects with reasons and metadata.",
    ),
    "blocked_actions": ReadContract(
        query_type="blocked_actions",
        description="Retrieve blocked action events within a timerange.",
        mandatory_params={
            "start_time": datetime,
            "end_time": datetime,
        },
        optional_params={
            "severity": str,
        },
        response_description="List of BLOCKED_ACTION MemoryEnvelope objects with reasons and severity breakdown.",
    ),
}


# =============================================================================
# Public API
# =============================================================================


def get_read_contract(query_type: str) -> ReadContract:
    """Get the read contract for a specific query type.

    Args:
        query_type: The query type identifier
            (e.g. ``"trade_history"``, ``"health_timeline"``).

    Returns:
        The ``ReadContract`` for that query type.

    Raises:
        KeyError: If the query type has no read contract defined.
    """
    if query_type not in _READ_CONTRACTS:
        raise KeyError(f"No read contract defined for query type: {query_type!r}")
    return _READ_CONTRACTS[query_type]


def list_query_types() -> list[str]:
    """Get all query types that have read contracts defined.

    Returns:
        Sorted list of query type strings.
    """
    return sorted(_READ_CONTRACTS.keys())


def validate_query(
    query: MemoryQuery,
    query_type: str,
) -> tuple[bool, list[str]]:
    """Validate a MemoryQuery against the read contract for the given query type.

    Checks:
    1. A read contract exists for the query type.
    2. All mandatory params are satisfied (either via MemoryQuery fields
       or via refs_filter).
    3. If ``start_time`` and ``end_time`` are mandatory, they must be set.

    Args:
        query: The ``MemoryQuery`` to validate.
        query_type: The expected query type (e.g. ``"trade_history"``).

    Returns:
        ``(is_valid, errors)`` tuple:
        - ``is_valid``: ``True`` if the query passes all contract checks.
        - ``errors``: List of human-readable error messages (empty if valid).
    """
    errors: list[str] = []

    try:
        contract = get_read_contract(query_type)
    except KeyError:
        errors.append(f"No read contract defined for query type: {query_type!r}")
        return False, errors

    # Check mandatory params
    for param_name, expected_type in contract.mandatory_params.items():
        if param_name == "trade_id":
            # Must be in refs_filter
            if not query.refs_filter or "trade_id" not in query.refs_filter:
                errors.append(
                    f"Missing mandatory param: 'trade_id' must be provided "
                    f"via refs_filter['trade_id']"
                )
        elif param_name == "decision_id":
            # Must be in refs_filter
            if not query.refs_filter or "decision_id" not in query.refs_filter:
                errors.append(
                    f"Missing mandatory param: 'decision_id' must be provided "
                    f"via refs_filter['decision_id']"
                )
        elif param_name == "start_time":
            if query.start_time is None:
                errors.append(f"Missing mandatory param: 'start_time' must be set")
        elif param_name == "end_time":
            if query.end_time is None:
                errors.append(f"Missing mandatory param: 'end_time' must be set")

    return len(errors) == 0, errors
