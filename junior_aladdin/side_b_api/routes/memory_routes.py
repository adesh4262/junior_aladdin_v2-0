"""Side B memory route module — READ MODELS ONLY.

Exposes Side C (Memory/Journal) data through its read model builders.
Never queries raw event/journal/reference stores directly.

Endpoints:
    GET /api/memory/trades     — trade history (read model)
    GET /api/memory/decisions  — decision history (read model)
    GET /api/memory/events     — health events (filtered, read model)
    GET /api/memory/alerts     — alert history (read model)

CRITICAL: All Side C queries go through Read Models ONLY.
No raw store access from API layer.

Reference: ROADMAP_SIDE_B Step 8.8, SIDE_B_DASHBOARD_V1_2_FINAL Section 20
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ──────────────────────────────────────────────
#  GET /api/memory/trades  —  trade history
# ──────────────────────────────────────────────


@router.get("/trades")
async def get_memory_trades(request: Request) -> dict[str, Any]:
    """Trade history from Side C read model.

    Returns recent trade journal entries. All data comes from
    Side C's read model builder — never raw stores.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_c"])
    trades = data.get("side_c", {}).get("trade_history", [])

    return {
        "trades": trades,
        "count": len(trades),
        "source": "read_model",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/memory/decisions  —  decision history
# ──────────────────────────────────────────────


@router.get("/decisions")
async def get_memory_decisions(request: Request) -> dict[str, Any]:
    """Decision history from Side C read model.

    Returns recent decision journal entries via read model builder.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_c"])
    decisions = data.get("side_c", {}).get("decision_history", [])

    return {
        "decisions": decisions,
        "count": len(decisions),
        "source": "read_model",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/memory/events  —  health events
# ──────────────────────────────────────────────


@router.get("/events")
async def get_memory_events(request: Request) -> dict[str, Any]:
    """Health events from Side C read model.

    Returns recent health/timeline events via read model builder.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_c"])
    events = data.get("side_c", {}).get("health_events", [])

    return {
        "events": events,
        "count": len(events),
        "source": "read_model",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/memory/alerts  —  alert history
# ──────────────────────────────────────────────


@router.get("/alerts")
async def get_memory_alerts(request: Request) -> dict[str, Any]:
    """Alert history from Side C read model.

    Returns recent health events filtered for alert-worthy severity.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["side_c"])
    events = data.get("side_c", {}).get("health_events", [])

    # Filter for CAUTION / SEVERE / CRITICAL events as alerts
    alerts = [e for e in events if isinstance(e, dict) and e.get("severity", "INFO") in ("CAUTION", "SEVERE", "CRITICAL")]

    return {
        "alerts": alerts,
        "total_events": len(events),
        "alert_count": len(alerts),
        "source": "read_model",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach memory routes to the FastAPI app."""
    app.include_router(router)
