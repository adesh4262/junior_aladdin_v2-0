"""Account reset command handler.

Routes a paper account reset request to Side A's account manager.

Pattern:
    request → validate → build ControlCommand → cache → return CommandAck

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.data_contracts import CommandAck


def handle_account_reset_request(
    cache: Any,
    reason: str,
    new_balance: float = 100000.0,
) -> CommandAck:
    """Validate and route an account reset request.

    Args:
        cache: Session cache instance (app.state.cache).
        reason: Operator rationale (required, non-empty).
        new_balance: Starting balance after reset (default: 100000, must be positive).

    Returns:
        CommandAck with status, message, and owner_response.

    Raises:
        ValueError: If reason is empty or new_balance is not positive.
    """
    if not reason.strip():
        raise ValueError("Reason required for account reset")

    parsed_balance = float(new_balance)
    if parsed_balance <= 0:
        raise ValueError(f"New balance must be positive, got {parsed_balance}")

    cmd: dict[str, Any] = {
        "command_type": "request_account_reset",
        "target": "side_a.account_manager",
        "params": {"new_balance": parsed_balance, "reason": reason.strip()},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:account_reset", cmd)

    return CommandAck(
        status="ACK",
        command_type="request_account_reset",
        message=f"Account reset to {parsed_balance} requested.",
        owner_response={"new_balance": parsed_balance},
    )
