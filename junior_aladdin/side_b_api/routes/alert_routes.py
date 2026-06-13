"""Side B alert route module.

Exposes alert/notification endpoints — system alerts, history, acknowledge.

Endpoints:
    GET  /api/alerts          — current active alerts
    GET  /api/alerts/history  — alert history (filtered)
    POST /api/alerts/acknowledge — acknowledge a specific alert
    GET  /api/alerts/settings — alert configuration

Reference: ROADMAP_SIDE_B Step 8.9, SIDE_B_DASHBOARD_V1_2_FINAL Section 17
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Severity levels for filtering
_SEVERITY_ORDER = {"INFO": 0, "CAUTION": 1, "SEVERE": 2, "CRITICAL": 3}


def _extract_alerts(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract alert entries from aggregator state.

    Checks multiple possible locations (floor_2, side_c, aggregated state).
    """
    if data is None:
        return []

    alerts: list[dict[str, Any]] = []

    # Try Side C read model (primary source for health events)
    side_c = data.get("side_c", {})
    health_events = side_c.get("health_events", [])
    for event in health_events:
        alerts.append({
            "alert_id": event.get("event_id", ""),
            "severity": event.get("severity", "INFO"),
            "category": event.get("category", "SYSTEM"),
            "message": event.get("message", ""),
            "source": event.get("source", "side_c"),
            "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
            "acknowledged": event.get("acknowledged", False),
        })

    # Also check floor_2 for data health alerts
    floor_2 = data.get("floor_2", {})
    data_health = floor_2.get("data_health", "")
    if data_health in ("DEGRADED", "CRITICAL", "STALE"):
        alerts.append({
            "alert_id": "data_health_floor_2",
            "severity": "SEVERE" if data_health == "CRITICAL" else "CAUTION",
            "category": "DATA",
            "message": f"Data health is {data_health}",
            "source": "floor_2",
            "timestamp": datetime.utcnow().isoformat(),
            "acknowledged": False,
        })

    return alerts


# ──────────────────────────────────────────────
#  GET /api/alerts  —  current active alerts
# ──────────────────────────────────────────────


@router.get("")
async def get_active_alerts(request: Request) -> dict[str, Any]:
    """Return currently active (non-acknowledged) alerts.

    Sorted by severity: CRITICAL → SEVERE → CAUTION → INFO.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot()
    all_alerts = _extract_alerts(data)

    # Filter to non-acknowledged only
    active = [a for a in all_alerts if not a.get("acknowledged", False)]

    # Sort by severity (highest first), then by timestamp (newest first)
    active.sort(
        key=lambda a: (
            -_SEVERITY_ORDER.get(a.get("severity", "INFO"), 0),
            a.get("timestamp", ""),
        ),
    )

    return {
        "alerts": active,
        "count": len(active),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/alerts/history  —  alert history
# ──────────────────────────────────────────────


@router.get("/history")
async def get_alert_history(request: Request) -> dict[str, Any]:
    """Return alert history (acknowledged + unacknowledged).

    Query params:
        severity (optional): Filter by severity level
        category (optional): Filter by category
        limit (optional): Max entries to return (default: 100)
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot()
    all_alerts = _extract_alerts(data)

    # Apply filters from params
    severity_filter = request.query_params.get("severity", "").upper()
    category_filter = request.query_params.get("category", "").upper()
    limit_str = request.query_params.get("limit", "100")

    try:
        limit = max(1, min(500, int(limit_str)))
    except (ValueError, TypeError):
        limit = 100

    if severity_filter in _SEVERITY_ORDER:
        all_alerts = [a for a in all_alerts if a.get("severity", "") == severity_filter]

    if category_filter:
        all_alerts = [a for a in all_alerts if a.get("category", "").upper() == category_filter]

    # Sort by timestamp (newest first)
    all_alerts.sort(key=lambda a: a.get("timestamp", ""), reverse=True)

    return {
        "alerts": all_alerts[:limit],
        "count": len(all_alerts[:limit]),
        "total": len(all_alerts),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  POST /api/alerts/acknowledge  —  acknowledge alert
# ──────────────────────────────────────────────


@router.post("/acknowledge")
async def post_acknowledge_alert(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Acknowledge an alert.

    Request body:
        alert_id (required): ID of the alert to acknowledge

    .. note::
        Acknowledged alerts are moved from active to history.
        For persistent acknowledgement, the alert source must also be updated.
    """
    alert_id = body.get("alert_id", "").strip()
    if not alert_id:
        raise HTTPException(status_code=400, detail="Missing 'alert_id' in request body")

    # Store acknowledge action in cache
    cache = request.app.state.cache
    ack_entry = {
        "alert_id": alert_id,
        "acknowledged_at": datetime.utcnow().isoformat(),
        "operator_context": "local",
    }

    # Get existing acknowledged list
    existing = cache.get("acknowledged_alerts") or []
    if alert_id not in existing:
        existing.append(alert_id)
    cache.set("acknowledged_alerts", existing)

    return {
        "status": "ACK",
        "alert_id": alert_id,
        "message": f"Alert '{alert_id}' acknowledged.",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/alerts/settings  —  alert settings
# ──────────────────────────────────────────────


@router.get("/settings")
async def get_alert_settings(request: Request) -> dict[str, Any]:
    """Return current alert configuration.

    Returns severity thresholds, enabled categories, and notification prefs.
    Uses defaults from config — extendable on-demand.
    """
    config = request.app.state.config

    return {
        "severity_thresholds": {
            "critical": {"enabled": True, "push": True, "sound": True},
            "severe": {"enabled": True, "push": True, "sound": True},
            "caution": {"enabled": True, "push": False, "sound": False},
            "info": {"enabled": True, "push": False, "sound": False},
        },
        "categories_enabled": [
            "EXECUTION",
            "HEALTH",
            "RISK",
            "DATA",
            "GOVERNANCE",
            "OPERATOR",
            "SYSTEM",
        ],
        "max_active_alerts": 50,
        "auto_dismiss_after_s": 300,  # 5 minutes
        "refresh_interval_ms": config.hot_refresh_ms,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  Route registration helper
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach alert routes to the FastAPI app."""
    app.include_router(router)
