"""Mode command handler.

Routes a mode change request (ALERT / PAPER / REAL) to Side A's mode router.

Pattern:
    request → validate → build ControlCommand → cache → return CommandAck

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.data_contracts import CommandAck

_ALLOWED_MODES = {"ALERT", "PAPER", "REAL"}


def handle_mode_request(
    cache: Any,
    mode: str,
    reason: str = "",
) -> CommandAck:
    """Validate and route a mode change request.

    Args:
        cache: Session cache instance (app.state.cache).
        mode: Target execution mode. One of ALERT, PAPER, REAL.
        reason: Optional operator rationale.

    Returns:
        CommandAck with status, message, and owner_response.

    Raises:
        ValueError: If mode is not in ALLOWED_MODES.
    """
    mode_upper = mode.upper().strip()

    if mode_upper not in _ALLOWED_MODES:
        raise ValueError(
            f"Invalid mode '{mode}'. Allowed: {sorted(_ALLOWED_MODES)}"
        )

    cmd: dict[str, Any] = {
        "command_type": "request_mode",
        "target": "side_a.mode_router",
        "params": {"mode": mode_upper, "reason": reason.strip()},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:mode", cmd)

    return CommandAck(
        status="ACK",
        command_type="request_mode",
        message=f"Mode change to {mode_upper} requested.",
        owner_response={"requested_mode": mode_upper},
    )
