"""Side C Memory Layer — write contracts per event family.

Defines mandatory fields, optional fields, field types, and payload schemas
for every event family.  Used by ingest_layer and event_router for runtime
validation.

Architecture rules (LOCKED):
- EVERY event entering Side C MUST match its family's write contract.
- Missing mandatory fields → rejection with logged error (Severity.CAUTION).
- Wrong field types → rejection with logged error.
- Contracts are the single source of truth for event structure.
- No event family may have zero mandatory fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.types import Severity
from junior_aladdin.side_c_memory.c_types import EventFamily


# =============================================================================
# Write contract definition
# =============================================================================


@dataclass
class FieldSpec:
    """Schema for a single field in a write contract.

    Fields:
        type_: Expected Python type for the field value.
        description: Human-readable description of the field.
        required_in_payload: If ``True``, this field must be present
            inside ``payload`` dict (not top-level).
    """

    type_: type
    description: str = ""
    required_in_payload: bool = False


@dataclass
class WriteContract:
    """Complete write contract for one event family.

    Fields:
        family: The event family this contract applies to.
        mandatory_fields: Dict of field name → ``FieldSpec`` that MUST
            be present in the event data dict.
        optional_fields: Dict of field name → ``FieldSpec`` that MAY be
            present in the event data dict.
        payload_schema: Dict of payload key → ``FieldSpec`` that defines
            the expected structure of the ``payload`` dict.
        description: Human-readable description of this family's events.
    """

    family: EventFamily
    mandatory_fields: dict[str, FieldSpec] = field(default_factory=dict)
    optional_fields: dict[str, FieldSpec] = field(default_factory=dict)
    payload_schema: dict[str, FieldSpec] = field(default_factory=dict)
    description: str = ""


# =============================================================================
# Common base fields
# =============================================================================

_TOP_LEVEL_MANDATORY: dict[str, FieldSpec] = {
    "event_type": FieldSpec(type_=str, description="Event type identifier within the family"),
    "source": FieldSpec(type_=str, description="Emitting floor/side name"),
    "emitter": FieldSpec(type_=str, description="Emitter ID from emitter registry"),
    "family": FieldSpec(type_=str, description="Event family string (must match contract family)"),
    "timestamp": FieldSpec(type_=str, description="ISO-8601 UTC timestamp string"),
    "severity": FieldSpec(type_=str, description="Severity level (INFO/CAUTION/SEVERE/CRITICAL)"),
    "payload": FieldSpec(type_=dict, description="Family-specific payload dict"),
}

_TOP_LEVEL_OPTIONAL: dict[str, FieldSpec] = {
    "refs": FieldSpec(type_=dict, description="Optional reference links dict"),
}


# =============================================================================
# Write contract definitions (LOCKED)
# =============================================================================

_WRITE_CONTRACTS: dict[EventFamily, WriteContract] = {
    # ------------------------------------------------------------------
    # TRADE_JOURNAL — Side A emits after trade completion
    # ------------------------------------------------------------------
    EventFamily.TRADE_JOURNAL: WriteContract(
        family=EventFamily.TRADE_JOURNAL,
        description="Trade record emitted by Side A after trade completion.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "trade_id": FieldSpec(type_=str, description="Unique trade identifier", required_in_payload=True),
            "entry": FieldSpec(type_=(int, float), description="Entry price", required_in_payload=True),
            "exit": FieldSpec(type_=(int, float), description="Exit price", required_in_payload=True),
            "pnl": FieldSpec(type_=(int, float), description="Profit / loss", required_in_payload=True),
            "mode": FieldSpec(type_=str, description="Execution mode (ALERT/PAPER/REAL)", required_in_payload=True),
            "option_side": FieldSpec(type_=str, description="Option side (CE/PE)"),
            "strike": FieldSpec(type_=(int, float), description="Strike price"),
            "quantity": FieldSpec(type_=int, description="Quantity traded"),
            "duration_seconds": FieldSpec(type_=(int, float), description="Trade duration in seconds"),
            "tags": FieldSpec(type_=list, description="Optional tags for categorisation"),
        },
    ),
    # ------------------------------------------------------------------
    # DECISION_JOURNAL — Floor 5 emits on every Captain decision
    # ------------------------------------------------------------------
    EventFamily.DECISION_JOURNAL: WriteContract(
        family=EventFamily.DECISION_JOURNAL,
        description="Decision record emitted by Floor 5 (Captain) on every decision cycle.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "decision": FieldSpec(type_=str, description="Captain decision (TRADE/WAIT/BLOCKED)", required_in_payload=True),
            "conviction_band": FieldSpec(type_=str, description="Conviction band (STRONG/MODERATE/WEAK)", required_in_payload=True),
            "trade_class": FieldSpec(type_=str, description="Trade class (SCALP/CONTINUATION/REVERSAL/...)"),
            "reason": FieldSpec(type_=str, description="Decision reasoning summary", required_in_payload=True),
            "action": FieldSpec(type_=str, description="Trade action (BUY/SELL)"),
            "option_side": FieldSpec(type_=str, description="Option side (CE/PE)"),
            "selected_strike": FieldSpec(type_=str, description="Selected strike price"),
            "no_trade_score": FieldSpec(type_=(int, float), description="No-trade conviction score"),
            "mood": FieldSpec(type_=str, description="Captain mood at decision time"),
            "heads_aligned": FieldSpec(type_=int, description="Number of aligned department heads"),
        },
    ),
    # ------------------------------------------------------------------
    # EXECUTION_EVENT — Side A emits on order lifecycle changes
    # ------------------------------------------------------------------
    EventFamily.EXECUTION_EVENT: WriteContract(
        family=EventFamily.EXECUTION_EVENT,
        description="Order / execution lifecycle event emitted by Side A.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "order_id": FieldSpec(type_=str, description="Order identifier", required_in_payload=True),
            "action": FieldSpec(type_=str, description="Order action (BUY/SELL)", required_in_payload=True),
            "status": FieldSpec(type_=str, description="Order status (PLACED/FILLED/CANCELLED/REJECTED)", required_in_payload=True),
            "option_side": FieldSpec(type_=str, description="Option side (CE/PE)"),
            "strike": FieldSpec(type_=(int, float), description="Strike price"),
            "quantity": FieldSpec(type_=int, description="Order quantity"),
            "price": FieldSpec(type_=(int, float), description="Fill or limit price"),
            "rejection_reason": FieldSpec(type_=str, description="Reason if order was rejected"),
            "mode": FieldSpec(type_=str, description="Execution mode (ALERT/PAPER/REAL)"),
            "trade_id": FieldSpec(type_=str, description="Associated trade ID if available"),
        },
    ),
    # ------------------------------------------------------------------
    # HEALTH_EVENT — Floor 1 / Floor 2 emit on state changes
    # ------------------------------------------------------------------
    EventFamily.HEALTH_EVENT: WriteContract(
        family=EventFamily.HEALTH_EVENT,
        description="System health / data quality event emitted by Floor 1 or Floor 2.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "state": FieldSpec(type_=str, description="Health state (HEALTHY/DEGRADED/STALE/AUTH_FAILED/DISCONNECTED)", required_in_payload=True),
            "source_name": FieldSpec(type_=str, description="Affected source or component name", required_in_payload=True),
            "latency_ms": FieldSpec(type_=(int, float), description="Latency in milliseconds"),
            "heartbeat_age_s": FieldSpec(type_=(int, float), description="Seconds since last heartbeat"),
            "reconnect_count": FieldSpec(type_=int, description="Reconnect attempt count"),
            "error_message": FieldSpec(type_=str, description="Error details if health degraded"),
            "data_health": FieldSpec(type_=str, description="Data health level (GOOD/CAUTION/DEGRADED/CRITICAL)"),
        },
    ),
    # ------------------------------------------------------------------
    # OVERRIDE — Side A emits on manual intervention
    # ------------------------------------------------------------------
    EventFamily.OVERRIDE: WriteContract(
        family=EventFamily.OVERRIDE,
        description="Manual intervention / override event emitted by Side A.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "reason": FieldSpec(type_=str, description="Override reason", required_in_payload=True),
            "override_type": FieldSpec(type_=str, description="Type of override (PARAMETER/ACTION/DECISION)", required_in_payload=True),
            "original_value": FieldSpec(type_=str, description="Value before override"),
            "new_value": FieldSpec(type_=str, description="Value after override"),
            "overridden_by": FieldSpec(type_=str, description="Who/what triggered the override"),
            "trade_id": FieldSpec(type_=str, description="Associated trade ID if applicable"),
        },
    ),
    # ------------------------------------------------------------------
    # BLOCKED_ACTION — Side A emits on blocked orders/actions
    # ------------------------------------------------------------------
    EventFamily.BLOCKED_ACTION: WriteContract(
        family=EventFamily.BLOCKED_ACTION,
        description="Blocked order or action event emitted by Side A.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "reason": FieldSpec(type_=str, description="Why the action was blocked", required_in_payload=True),
            "action": FieldSpec(type_=str, description="The blocked action (BUY/SELL/OVERRIDE)", required_in_payload=True),
            "block_level": FieldSpec(type_=str, description="Block severity level (SOFT/HARD)", required_in_payload=True),
            "option_side": FieldSpec(type_=str, description="Option side if applicable"),
            "strike": FieldSpec(type_=(int, float), description="Strike price if applicable"),
            "quantity": FieldSpec(type_=int, description="Quantity if applicable"),
            "trigger_source": FieldSpec(type_=str, description="What triggered the block"),
        },
    ),
    # ------------------------------------------------------------------
    # REPLAY_REF — Floor 2 emits on replay session creation
    # ------------------------------------------------------------------
    EventFamily.REPLAY_REF: WriteContract(
        family=EventFamily.REPLAY_REF,
        description="Replay reference event emitted by Floor 2 linking a replay session to trade/decision IDs.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "ref_key": FieldSpec(type_=str, description="Reference key (e.g., trade_id:xxx)", required_in_payload=True),
            "replay_session_id": FieldSpec(type_=str, description="Floor 2 replay session ID", required_in_payload=True),
            "replay_range_start": FieldSpec(type_=str, description="Replay start timestamp (ISO-8601)"),
            "replay_range_end": FieldSpec(type_=str, description="Replay end timestamp (ISO-8601)"),
            "source": FieldSpec(type_=str, description="Original source floor"),
            "packet_count": FieldSpec(type_=int, description="Number of packets in replay range"),
        },
    ),
    # ------------------------------------------------------------------
    # REVIEW_REF — Floor 2 emits on audit/review session
    # ------------------------------------------------------------------
    EventFamily.REVIEW_REF: WriteContract(
        family=EventFamily.REVIEW_REF,
        description="Review / audit reference event emitted by Floor 2 linking review sessions to data ranges.",
        mandatory_fields=_TOP_LEVEL_MANDATORY.copy(),
        optional_fields=_TOP_LEVEL_OPTIONAL.copy(),
        payload_schema={
            "ref_key": FieldSpec(type_=str, description="Reference key (e.g., decision_id:xxx)", required_in_payload=True),
            "review_session_id": FieldSpec(type_=str, description="Review session ID", required_in_payload=True),
            "review_range_start": FieldSpec(type_=str, description="Review start timestamp (ISO-8601)"),
            "review_range_end": FieldSpec(type_=str, description="Review end timestamp (ISO-8601)"),
            "review_type": FieldSpec(type_=str, description="Review type (SCHEDULED/EVENT_TRIGGERED/MANUAL)"),
            "findings_count": FieldSpec(type_=int, description="Number of findings in the review"),
        },
    ),
}


# =============================================================================
# Public API
# =============================================================================


def get_write_contract(family: EventFamily) -> WriteContract:
    """Get the write contract for a specific event family.

    Args:
        family: The event family to look up.

    Returns:
        The ``WriteContract`` for that family.

    Raises:
        KeyError: If the family has no write contract defined.
    """
    if family not in _WRITE_CONTRACTS:
        raise KeyError(f"No write contract defined for family: {family!r}")
    return _WRITE_CONTRACTS[family]


def list_contract_families() -> list[EventFamily]:
    """Get all event families that have write contracts defined.

    Returns:
        Sorted list of ``EventFamily`` values.
    """
    return sorted(_WRITE_CONTRACTS.keys(), key=lambda f: f.value)


def validate_event_for_family(
    event_data: dict[str, Any],
    family: EventFamily,
) -> tuple[bool, list[str]]:
    """Validate event data against the write contract for the given family.

    Checks:
    1. Family-specific contract exists.
    2. All top-level mandatory fields are present with correct types.
    3. ``payload`` dict contains all required payload fields with correct types.
    4. ``severity`` value is a valid ``Severity`` enum member (case-insensitive).
    5. ``family`` string matches the contract family.

    Args:
        event_data: The raw event data dict to validate.
        family: The expected event family.

    Returns:
        ``(is_valid, errors)`` tuple:
        - ``is_valid``: ``True`` if the event passes all contract checks.
        - ``errors``: List of human-readable error messages (empty if valid).
    """
    errors: list[str] = []

    try:
        contract = get_write_contract(family)
    except KeyError:
        errors.append(f"No write contract defined for family: {family!r}")
        return False, errors

    # ── 1. Check family field matches contract ────────────────────────
    actual_family = event_data.get("family", "")
    if actual_family != family.value:
        errors.append(
            f"Family mismatch: expected {family.value!r}, got {actual_family!r}"
        )

    # ── 2. Check top-level mandatory fields ───────────────────────────
    for field_name, spec in contract.mandatory_fields.items():
        if field_name not in event_data:
            errors.append(f"Missing mandatory top-level field: {field_name!r}")
        elif not isinstance(event_data[field_name], spec.type_):
            errors.append(
                f"Field {field_name!r}: expected type {spec.type_.__name__}, "
                f"got {type(event_data[field_name]).__name__}"
            )

    # ── 3. Check severity is valid enum value ─────────────────────────
    severity_val = event_data.get("severity")
    if severity_val is not None:
        valid_severities = {s.value for s in Severity}
        if severity_val not in valid_severities:
            errors.append(
                f"Invalid severity: {severity_val!r}. "
                f"Must be one of {sorted(valid_severities)}"
            )

    # ── 4. Check payload schema ───────────────────────────────────────
    payload = event_data.get("payload")
    if payload is not None:
        if not isinstance(payload, dict):
            errors.append(
                f"Field 'payload': expected type dict, got {type(payload).__name__}"
            )
        else:
            for field_name, spec in contract.payload_schema.items():
                if spec.required_in_payload and field_name not in payload:
                    errors.append(
                        f"Missing required payload field: {field_name!r}"
                    )
                elif field_name in payload and not isinstance(
                    payload[field_name], spec.type_
                ):
                    errors.append(
                        f"Payload field {field_name!r}: expected type "
                        f"{spec.type_.__name__}, "
                        f"got {type(payload[field_name]).__name__}"
                    )

    # ── 5. Check refs is a dict if present ────────────────────────────
    refs = event_data.get("refs")
    if refs is not None and not isinstance(refs, dict):
        errors.append(f"Field 'refs': expected type dict, got {type(refs).__name__}")

    return len(errors) == 0, errors
