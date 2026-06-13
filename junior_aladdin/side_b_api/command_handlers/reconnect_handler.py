"""Reconnect command handler.

Routes a broker reconnect request to Side A's execution core.

Pattern:
    request → validate → build ControlCommand → cache → return CommandAck

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.data_contracts import CommandAck


def handle_reconnect_request(
    cache: Any,
    target_broker: str = "primary",
    reason: str = "",
) -> CommandAck:
    """Validate and route a broker reconnect request.

    Args:
        cache: Session cache instance (app.state.cache).
        target_broker: Broker name to reconnect (default: "primary").
        reason: Optional operator rationale.

    Returns:
        CommandAck with status, message, and owner_response.
    """
    target = target_broker.strip() or "primary"

    cmd: dict[str, Any] = {
        "command_type": "request_reconnect",
        "target": "side_a.execution_core",
        "params": {"target_broker": target, "reason": reason.strip()},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:reconnect", cmd)

    return CommandAck(
        status="ACK",
        command_type="request_reconnect",
        message=f"Reconnect requested for broker: {target}.",
        owner_response={"target_broker": target},
    )
