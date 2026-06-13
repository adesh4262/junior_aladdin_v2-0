"""Capital command handler.

Routes a capital limit update request to Side A's risk gate.

Pattern:
    request → validate → build ControlCommand → cache → return CommandAck

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.data_contracts import CommandAck


def handle_capital_request(
    cache: Any,
    capital_limit: float,
    reason: str = "",
) -> CommandAck:
    """Validate and route a capital limit update request.

    Args:
        cache: Session cache instance (app.state.cache).
        capital_limit: New capital limit (must be positive).
        reason: Optional operator rationale.

    Returns:
        CommandAck with status, message, and owner_response.

    Raises:
        ValueError: If capital_limit is not positive.
    """
    parsed = float(capital_limit)

    if parsed <= 0:
        raise ValueError(f"Capital limit must be positive, got {parsed}")

    cmd: dict[str, Any] = {
        "command_type": "request_capital",
        "target": "side_a.risk_gate",
        "params": {"capital_limit": parsed, "reason": reason.strip()},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:capital", cmd)

    return CommandAck(
        status="ACK",
        command_type="request_capital",
        message=f"Capital limit updated to {parsed}.",
        owner_response={"capital_limit": parsed},
    )
