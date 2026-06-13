"""Side B control route module.

Exposes operator command endpoints — **routes commands, does NOT execute.**

Every control action follows the pattern:
    request → validate → route → ack

CRITICAL: All command types use ``request_`` prefix.
Side B never uses ``execute_`` — it requests, the owner floor/side executes.

Endpoints:
    POST /api/control/mode           — change execution mode  (→ mode_handler)
    POST /api/control/capital        — update capital config  (→ capital_handler)
    POST /api/control/kill-switch    — activate/deactivate    (→ kill_switch_handler)
    POST /api/control/override       — confirm override       (→ override_handler)
    POST /api/control/reconnect      — request broker reconnect (→ reconnect_handler)
    POST /api/control/account/reset  — reset paper account    (→ account_handler)

Reference: ROADMAP_SIDE_B Step 8.9, SIDE_B_DASHBOARD_V1_2_FINAL Section 16
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

router = APIRouter(prefix="/api/control", tags=["control"])

_ALLOWED_MODES = {"ALERT", "PAPER", "REAL"}
_ALLOWED_KILL_SWITCH_STATES = {"SOFT", "CRITICAL", "OFF"}


def _build_ack(
    command_type: str,
    status: str = "ACK",
    message: str = "",
    owner_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standard CommandAck response dict."""
    return {
        "status": status,
        "command_type": command_type,
        "message": message,
        "owner_response": owner_response or {},
        "read_only": False,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  POST /api/control/mode
# ──────────────────────────────────────────────


@router.post("/mode")
async def post_control_mode(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Request execution mode change.

    Request body:
        mode (required): One of ALERT / PAPER / REAL
        reason (optional): Operator rationale

    Routes to: ``side_a.mode_router``

    .. note::
        This is a **request** — Side A's mode_router validates and
        executes the mode transition. Side B never changes mode directly.
    """
    new_mode = body.get("mode", "").upper()
    if new_mode not in _ALLOWED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{body.get('mode', '')}'. Allowed: {sorted(_ALLOWED_MODES)}",
        )

    reason = body.get("reason", "")

    # Store command in cache for async handler pickup
    cache = request.app.state.cache
    cmd = {
        "command_type": "request_mode",
        "target": "side_a.mode_router",
        "params": {"mode": new_mode, "reason": reason},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:mode", cmd)

    return _build_ack(
        command_type="request_mode",
        message=f"Mode change to {new_mode} requested.",
        owner_response={"requested_mode": new_mode},
    )


# ──────────────────────────────────────────────
#  POST /api/control/capital
# ──────────────────────────────────────────────


@router.post("/capital")
async def post_control_capital(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Request capital configuration update.

    Request body:
        capital_limit (required): New capital limit (positive float)
        reason (optional): Operator rationale

    Routes to: ``side_a.risk_gate``
    """
    capital_limit = body.get("capital_limit")
    if capital_limit is None:
        raise HTTPException(status_code=400, detail="Missing 'capital_limit' in request body")
    try:
        capital_limit = float(capital_limit)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'capital_limit' must be a number")

    if capital_limit <= 0:
        raise HTTPException(status_code=400, detail="'capital_limit' must be positive")

    reason = body.get("reason", "")

    # Store command in cache
    cache = request.app.state.cache
    cmd = {
        "command_type": "request_capital",
        "target": "side_a.risk_gate",
        "params": {"capital_limit": capital_limit, "reason": reason},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:capital", cmd)

    return _build_ack(
        command_type="request_capital",
        message=f"Capital limit updated to {capital_limit}.",
        owner_response={"capital_limit": capital_limit},
    )


# ──────────────────────────────────────────────
#  POST /api/control/kill-switch
# ──────────────────────────────────────────────


@router.post("/kill-switch")
async def post_control_kill_switch(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Activate or deactivate the kill switch.

    Request body:
        state (required): One of SOFT / CRITICAL / OFF
        reason (required): Operator rationale for kill switch action

    Routes to: ``side_a.kill_switch``

    .. warning::
        CRITICAL kill switch flattens all positions.
        Operator MUST provide a reason for SOFT or CRITICAL activation.
    """
    new_state = body.get("state", "").upper()
    if new_state not in _ALLOWED_KILL_SWITCH_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid kill-switch state '{body.get('state', '')}'. Allowed: {sorted(_ALLOWED_KILL_SWITCH_STATES)}",
        )

    reason = body.get("reason", "")
    if new_state in ("SOFT", "CRITICAL") and not reason.strip():
        raise HTTPException(
            status_code=400,
            detail="Reason required for SOFT or CRITICAL kill switch activation",
        )

    # Store command in cache
    cache = request.app.state.cache
    cmd = {
        "command_type": "request_kill_switch",
        "target": "side_a.kill_switch",
        "params": {"state": new_state, "reason": reason},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:kill_switch", cmd)

    return _build_ack(
        command_type="request_kill_switch",
        message=f"Kill switch set to {new_state}.",
        owner_response={"kill_switch_state": new_state},
    )


# ──────────────────────────────────────────────
#  POST /api/control/override
# ──────────────────────────────────────────────


@router.post("/override")
async def post_control_override(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Confirm operator override for real mode lock breach.

    Request body:
        override_confirmation (required): Boolean — operator explicitly confirms
        trade_id (optional): Associated trade ID if override is trade-specific
        reason (required): Operator rationale for override

    Routes to: ``floor_5.override_guard``
    """
    override_confirmation = body.get("override_confirmation", False)
    if not isinstance(override_confirmation, bool) or not override_confirmation:
        raise HTTPException(
            status_code=400,
            detail="Explicit 'override_confirmation: true' required",
        )

    reason = body.get("reason", "")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="Reason required for override")

    trade_id = body.get("trade_id")

    # Store command in cache
    cache = request.app.state.cache
    cmd = {
        "command_type": "request_override",
        "target": "floor_5.override_guard",
        "params": {
            "override_confirmation": True,
            "trade_id": trade_id,
            "reason": reason,
        },
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:override", cmd)

    return _build_ack(
        command_type="request_override",
        message="Override confirmed.",
        owner_response={"override_confirmed": True, "trade_id": trade_id},
    )


# ──────────────────────────────────────────────
#  POST /api/control/reconnect
# ──────────────────────────────────────────────


@router.post("/reconnect")
async def post_control_reconnect(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Request broker reconnect.

    Request body:
        target (optional): Broker name to reconnect (default: primary)
        reason (optional): Operator rationale

    Routes to: ``side_a.execution_core``
    """
    target_broker = body.get("target", "primary")
    reason = body.get("reason", "")

    # Store command in cache
    cache = request.app.state.cache
    cmd = {
        "command_type": "request_reconnect",
        "target": "side_a.execution_core",
        "params": {"target_broker": target_broker, "reason": reason},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:reconnect", cmd)

    return _build_ack(
        command_type="request_reconnect",
        message=f"Reconnect requested for broker: {target_broker}.",
        owner_response={"target_broker": target_broker},
    )


# ──────────────────────────────────────────────
#  POST /api/control/account/reset
# ──────────────────────────────────────────────


@router.post("/account/reset")
async def post_control_account_reset(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Reset paper trading account.

    Request body:
        confirm (required): Boolean — operator explicitly confirms reset
        new_balance (optional): Starting balance after reset (default: 100000)
        reason (required): Operator rationale

    Routes to: ``side_a.account_manager``
    """
    confirm = body.get("confirm", False)
    if not isinstance(confirm, bool) or not confirm:
        raise HTTPException(
            status_code=400,
            detail="Explicit 'confirm: true' required for account reset",
        )

    reason = body.get("reason", "")
    if not reason.strip():
        raise HTTPException(status_code=400, detail="Reason required for account reset")

    new_balance = body.get("new_balance", 100000)
    try:
        new_balance = float(new_balance)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'new_balance' must be a number")

    if new_balance <= 0:
        raise HTTPException(status_code=400, detail="'new_balance' must be positive")

    # Store command in cache
    cache = request.app.state.cache
    cmd = {
        "command_type": "request_account_reset",
        "target": "side_a.account_manager",
        "params": {"new_balance": new_balance, "reason": reason},
        "operator_context": "local",
        "timestamp": datetime.utcnow().isoformat(),
    }
    cache.set("control:account_reset", cmd)

    return _build_ack(
        command_type="request_account_reset",
        message=f"Account reset to {new_balance} requested.",
        owner_response={"new_balance": new_balance},
    )


# ──────────────────────────────────────────────
#  Route registration helper
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach control routes to the FastAPI app."""
    app.include_router(router)
