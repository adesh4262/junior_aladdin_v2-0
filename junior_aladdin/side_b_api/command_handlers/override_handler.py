"""Override command handler.

Routes an operator override confirmation to Floor 5's override guard.

Pattern:
    request → validate → build ControlCommand → cache → return CommandAck

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.data_contracts import CommandAck


def handle_override_request(
    cache: Any,
    reason: str,
    trade_id: str | None = None,
) -> CommandAck:
    """Validate and route an override confirmation request.

    Args:
        cache: Session cache instance (app.state.cache).
        reason: Operator rationale (required, non-empty).
        trade_id: Optional trade ID associated with the override.

    Returns:
        CommandAck with status, message, and owner_response.

    Raises:
        ValueError: If reason is empty.
    """
    if not reason.strip():
        raise ValueError("Reason required for override")

    cmd: dict[str, Any] = {
        "command_type": "request_override",
        "target": "floor_5.override_guard",
        "params": {
            "override_confirmation": True,
            "trade_id": trade_id,
            "reason": reason.strip(),
        },
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:override", cmd)

    return CommandAck(
        status="ACK",
        command_type="request_override",
        message="Override confirmed.",
        owner_response={"override_confirmed": True, "trade_id": trade_id},
    )
