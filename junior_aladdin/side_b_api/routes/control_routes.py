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

from junior_aladdin.side_b_api.command_handlers import (
    handle_account_reset_request,
    handle_capital_request,
    handle_kill_switch_request,
    handle_mode_request,
    handle_override_request,
    handle_reconnect_request,
)

router = APIRouter(prefix="/api/control", tags=["control"])


def _ack_to_dict(ack: Any) -> dict[str, Any]:
    """Convert a CommandAck dataclass to a response dict."""
    return {
        "status": ack.status,
        "command_type": ack.command_type,
        "message": ack.message,
        "owner_response": ack.owner_response,
        "read_only": False,
        "timestamp": ack.timestamp.isoformat() if hasattr(ack.timestamp, 'isoformat') else datetime.utcnow().isoformat(),
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
    new_mode = body.get("mode", "")
    reason = body.get("reason", "")

    try:
        ack = handle_mode_request(request.app.state.cache, new_mode, reason)
        return _ack_to_dict(ack)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    reason = body.get("reason", "")

    try:
        ack = handle_capital_request(request.app.state.cache, capital_limit, reason)
        return _ack_to_dict(ack)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    new_state = body.get("state", "")
    reason = body.get("reason", "")

    try:
        ack = handle_kill_switch_request(request.app.state.cache, new_state, reason)
        return _ack_to_dict(ack)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    trade_id = body.get("trade_id")

    try:
        ack = handle_override_request(request.app.state.cache, reason, trade_id)
        return _ack_to_dict(ack)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    try:
        ack = handle_reconnect_request(request.app.state.cache, target_broker, reason)
        return _ack_to_dict(ack)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    new_balance = body.get("new_balance", 100000)
    if new_balance is None:
        raise HTTPException(status_code=400, detail="'new_balance' must not be null")
    try:
        new_balance = float(new_balance)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'new_balance' must be a number")

    try:
        ack = handle_account_reset_request(request.app.state.cache, reason, new_balance)
        return _ack_to_dict(ack)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────────────────────────────────────
#  Route registration helper
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach control routes to the FastAPI app."""
    app.include_router(router)
