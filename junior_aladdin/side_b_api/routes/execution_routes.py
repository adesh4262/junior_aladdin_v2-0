"""Side B execution route module.

Exposes Side A (Execution Layer) state and lifecycle data for the
operator terminal.

Endpoints:
    GET /api/execution/state    — ExecutionDisplayState
    GET /api/execution/position — active position detail
    GET /api/execution/orders   — order lifecycle state
    GET /api/execution/blocked  — recent blocked actions
    GET /api/execution/logs     — execution logs (filtered)

Reference: ROADMAP_SIDE_B Step 8.7, SIDE_B_DASHBOARD_V1_2_FINAL Section 11
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request

router = APIRouter(prefix="/api/execution", tags=["execution"])


# ──────────────────────────────────────────────
#  GET /api/execution/state
# ──────────────────────────────────────────────


@router.get("/state")
async def get_execution_state(request: Request) -> dict[str, Any]:
    """Current execution state — mode, state machine state, escalation,
    kill-switch, position summary, orders, and blocked actions.

    Data source: Side A via data aggregator (HOT refresh tier).
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_a"])
    es = data.get("side_a", {}).get("execution_state", {})

    cache = request.app.state.cache

    # Read from control cache first, fall back to raw source
    # ── Mode ──
    mode = es.get("mode", "ALERT")
    try:
        cmd = cache.get("control:mode")
        if cmd and "params" in cmd and cmd["params"].get("mode"):
            mode = cmd["params"]["mode"]
    except Exception:
        pass

    # ── Kill switch ──
    kill_switch_state = es.get("kill_switch_state", "NORMAL")
    try:
        cmd = cache.get("control:kill_switch")
        if cmd and "params" in cmd and cmd["params"].get("state"):
            kill_switch_state = cmd["params"]["state"]
    except Exception:
        pass

    # ── Capital limit ──
    capital_limit = es.get("capital_limit")
    if capital_limit is None:
        try:
            cmd = cache.get("control:capital")
            if cmd and "params" in cmd:
                capital_limit = cmd["params"].get("capital_limit")
        except Exception:
            pass

    return {
        "mode": mode,
        "state": es.get("state", "IDLE"),
        "escalation_level": es.get("escalation_level", "NORMAL"),
        "kill_switch_state": kill_switch_state,
        "capital_limit": capital_limit,
        "position": es.get("position"),
        "orders": es.get("orders", []),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/execution/position
# ──────────────────────────────────────────────


@router.get("/position")
async def get_execution_position(request: Request) -> dict[str, Any]:
    """Active position detail.

    Returns position info (direction, filled_qty, avg_price, SL, TGT, P&L)
    or empty dict if no active position.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_a"])
    es = data.get("side_a", {}).get("execution_state", {})
    pos = es.get("position")

    if pos is None:
        return {
            "active": False,
            "position": None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    return {
        "active": True,
        "position": pos,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/execution/orders
# ──────────────────────────────────────────────


@router.get("/orders")
async def get_execution_orders(request: Request) -> dict[str, Any]:
    """Order lifecycle state — all active orders for the current trade."""
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_a"])
    es = data.get("side_a", {}).get("execution_state", {})
    orders = es.get("orders", [])
    return {
        "orders": orders,
        "count": len(orders),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/execution/blocked
# ──────────────────────────────────────────────


@router.get("/blocked")
async def get_execution_blocked(request: Request) -> dict[str, Any]:
    """Recent blocked actions from the BlockedActionJournal."""
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_a"])
    blocked = data.get("side_a", {}).get("blocked_actions", [])
    return {
        "blocked_actions": blocked,
        "count": len(blocked),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/execution/logs
# ──────────────────────────────────────────────


@router.get("/logs")
async def get_execution_logs(request: Request) -> dict[str, Any]:
    """Execution logs (filtered).

    Returns recent execution log entries from Side A's logging layer.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_a"])
    logs = data.get("side_a", {}).get("execution_logs", [])

    return {
        "logs": logs,
        "count": len(logs),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach execution routes to the FastAPI app."""
    app.include_router(router)
