"""Kill-switch command handler.

Routes a kill-switch activation/deactivation request to Side A.

Pattern:
    request → validate → build ControlCommand → cache → return CommandAck

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.data_contracts import CommandAck

_ALLOWED_KILL_SWITCH_STATES = {"SOFT", "CRITICAL", "OFF"}


def handle_kill_switch_request(
    cache: Any,
    state: str,
    reason: str,
) -> CommandAck:
    """Validate and route a kill-switch state change request.

    Args:
        cache: Session cache instance (app.state.cache).
        state: Target kill-switch state. One of SOFT, CRITICAL, OFF.
        reason: Operator rationale (required for SOFT and CRITICAL).

    Returns:
        CommandAck with status, message, and owner_response.

    Raises:
        ValueError: If state is invalid or reason missing for non-OFF states.
    """
    state_upper = state.upper().strip()

    if state_upper not in _ALLOWED_KILL_SWITCH_STATES:
        raise ValueError(
            f"Invalid kill-switch state '{state}'. "
            f"Allowed: {sorted(_ALLOWED_KILL_SWITCH_STATES)}"
        )

    if state_upper in ("SOFT", "CRITICAL") and not reason.strip():
        raise ValueError(
            "Reason required for SOFT or CRITICAL kill switch activation"
        )

    cmd: dict[str, Any] = {
        "command_type": "request_kill_switch",
        "target": "side_a.kill_switch",
        "params": {"state": state_upper, "reason": reason.strip()},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:kill_switch", cmd)

    return CommandAck(
        status="ACK",
        command_type="request_kill_switch",
        message=f"Kill switch set to {state_upper}.",
        owner_response={"kill_switch_state": state_upper},
    )
