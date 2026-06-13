"""Side B health route module.

Exposes system health endpoints for the operator terminal.

Endpoints:
    GET /api/health          — overall SystemHealthSnapshot
    GET /api/health/{component} — per-component health detail
    GET /api/health/data     — data health signal from Floor 2
    GET /api/health/connections — connection status per source

Reference: ROADMAP_SIDE_B Step 8.5, SIDE_B_DASHBOARD_V1_2_FINAL Section 13
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

from junior_aladdin.side_b_api.data_contracts import (
    ComponentHealthDetail,
    SystemHealthSnapshot,
)

router = APIRouter(prefix="/api/health", tags=["health"])


# ──────────────────────────────────────────────
#  GET /api/health  —  overall system health
# ──────────────────────────────────────────────


@router.get("")
async def get_system_health(request: Request) -> dict[str, Any]:
    """Overall system health summary.

    Returns the last known SystemHealthSnapshot from the aggregator.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()
    if state is None:
        return {
            "status": "INITIALIZING",
            "message": "Aggregator has not completed first poll",
            "timestamp": datetime.utcnow().isoformat(),
        }

    health = state.health
    return {
        "overall_status": (
            health.overall_status.value
            if hasattr(health.overall_status, "value")
            else str(health.overall_status)
        ),
        "data_health_signal": (
            health.data_health_signal.value
            if hasattr(health.data_health_signal, "value")
            else str(health.data_health_signal)
        ),
        "connection_status": health.connection_status,
        "critical_alert_count": health.critical_alert_count,
        "floors": {
            name: {
                "state": comp.state,
                "lifecycle": (
                    comp.lifecycle.value
                    if hasattr(comp.lifecycle, "value")
                    else str(comp.lifecycle)
                ),
                "detail": comp.detail,
            }
            for name, comp in health.floors.items()
        },
        "sides": {
            name: {
                "state": comp.state,
                "detail": comp.detail,
            }
            for name, comp in health.sides.items()
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/health/data  —  data health signal
# ──────────────────────────────────────────────


@router.get("/data")
async def get_data_health(request: Request) -> dict[str, Any]:
    """Data health signal from Floor 2.

    Returns the data health enum value and validation statistics.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    if state is None:
        return {"data_health": "UNKNOWN", "source": "Floor 2"}

    health = state.health
    return {
        "data_health": (
            health.data_health_signal.value
            if hasattr(health.data_health_signal, "value")
            else str(health.data_health_signal)
        ),
        "source": "Floor 2",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/health/connections  —  connection status
# ──────────────────────────────────────────────


@router.get("/connections")
async def get_connections(request: Request) -> dict[str, Any]:
    """Connection status per source.

    Returns the connection status of Floor 1 sources and any other
    connection-relevant components.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    if state is None:
        return {"connections": {}, "overall": "UNKNOWN"}

    # Gather connection states from known components
    connections: dict[str, str] = {}
    overall = "CONNECTED"

    for name, comp in state.health.floors.items():
        connections[name] = comp.state
        if comp.state in ("DISCONNECTED", "UNAVAILABLE", "ERROR", "CRITICAL"):
            overall = "DEGRADED"

    for name, comp in state.health.sides.items():
        connections[name] = comp.state

    return {
        "connections": connections,
        "overall": overall,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/health/{component}  —  per-component
#  WARNING: Must be defined LAST so FastAPI matches
#  fixed paths (/data, /connections) before this.
# ──────────────────────────────────────────────


@router.get("/{component}")
async def get_component_health(component: str, request: Request) -> dict[str, Any]:
    """Per-component health detail.

    Args:
        component: Component name, e.g. ``floor_1``, ``side_a``, ``floor_5``.

    Returns component health detail or 404 if unknown.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    if state is None:
        raise HTTPException(status_code=503, detail="Aggregator not ready")

    # Search floors first, then sides
    comp: ComponentHealthDetail | None = state.health.floors.get(component)
    if comp is None:
        comp = state.health.sides.get(component)

    if comp is None:
        known = list(state.health.floors.keys()) + list(state.health.sides.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Unknown component '{component}'. Known: {known}",
        )

    return {
        "name": comp.name,
        "state": comp.state,
        "lifecycle": (
            comp.lifecycle.value
            if hasattr(comp.lifecycle, "value")
            else str(comp.lifecycle)
        ),
        "last_update": comp.last_update.isoformat() if comp.last_update else None,
        "detail": comp.detail,
    }


# ──────────────────────────────────────────────
#  Route registration helper
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach health routes to the FastAPI app."""
    app.include_router(router)
