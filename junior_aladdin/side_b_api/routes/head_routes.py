"""Side B head route module.

Exposes Department Head (Floor 4) reports and floor summary for the
operator terminal.

Endpoints:
    GET /api/heads                — all head reports summary
    GET /api/heads/{head_name}    — specific head report detail
    GET /api/heads/floor-summary  — FloorSummary
    GET /api/heads/health         — per-head state and freshness

Reference: ROADMAP_SIDE_B Step 8.6, SIDE_B_DASHBOARD_V1_2_FINAL Section 11-12
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

router = APIRouter(prefix="/api/heads", tags=["heads"])


# ──────────────────────────────────────────────
#  GET /api/heads  —  all head reports
# ──────────────────────────────────────────────


@router.get("")
async def get_all_heads(request: Request) -> dict[str, Any]:
    """All head reports summary.

    Returns list of HeadReportDisplay objects plus the aggregate
    FloorSummaryDisplay.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    heads: list[dict[str, Any]] = []
    floor_summary: dict[str, Any] = {}

    if state is not None:
        # Build per-head display from aggregated floor_summary
        fs = state.floor_summary
        floor_summary = {
            "floor_bias": fs.floor_bias,
            "floor_confidence": fs.floor_confidence,
            "active_setup_count": fs.active_setup_count,
            "ready_heads": fs.ready_heads,
            "uncertain_heads": fs.uncertain_heads,
            "stale_heads": fs.stale_heads,
            "data_health_signal": (
                fs.data_health_signal.value
                if hasattr(fs.data_health_signal, "value")
                else str(fs.data_health_signal)
            ),
        }
        heads = [
            {
                "head_name": h.head_name,
                "state": h.state,
                "bias": h.bias,
                "confidence": h.confidence,
                "freshness_tag": h.freshness_tag,
                "context_quality_score": h.context_quality_score,
                "primary_setup": h.primary_setup,
                "backup_setup": h.backup_setup,
                "no_setup_flag": h.no_setup_flag,
            }
            for h in fs.heads
        ]

    return {
        "heads": heads,
        "floor_summary": floor_summary,
        "timestamp": datetime.utcnow().isoformat(),
    }

# ──────────────────────────────────────────────
#  GET /api/heads/floor-summary
# ──────────────────────────────────────────────


@router.get("/floor-summary")
async def get_floor_summary(request: Request) -> dict[str, Any]:
    """Aggregated FloorSummary for the cockpit strip."""
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    if state is None:
        return {"status": "INITIALIZING"}

    fs = state.floor_summary
    return {
        "floor_bias": fs.floor_bias,
        "floor_confidence": fs.floor_confidence,
        "active_setup_count": fs.active_setup_count,
        "ready_heads": fs.ready_heads,
        "uncertain_heads": fs.uncertain_heads,
        "stale_heads": fs.stale_heads,
        "data_health_signal": (
            fs.data_health_signal.value
            if hasattr(fs.data_health_signal, "value")
            else str(fs.data_health_signal)
        ),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/heads/health  —  per-head state
# ──────────────────────────────────────────────


@router.get("/health")
async def get_heads_health(request: Request) -> dict[str, Any]:
    """Per-head state and freshness summary.

    Returns each head's operational state (READY/UNCERTAIN/STALE)
    and freshness tag.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    health: dict[str, dict[str, Any]] = {}
    if state is not None:
        for h in state.floor_summary.heads:
            health[h.head_name] = {
                "state": h.state,
                "freshness_tag": h.freshness_tag,
                "confidence": h.confidence,
                "context_quality_score": h.context_quality_score,
                "no_setup_flag": h.no_setup_flag,
            }

    return {
        "heads": health,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/heads/{head_name}  —  specific head
#  WARNING: Must be defined LAST so FastAPI matches
#  fixed paths (/floor-summary, /health) before this.
# ──────────────────────────────────────────────


@router.get("/{head_name}")
async def get_head_detail(head_name: str, request: Request) -> dict[str, Any]:
    """Specific head report detail.

    Args:
        head_name: Head name, e.g. ``smc``, ``ict``, ``technical``, etc.

    Returns detailed head report or 404 if not found.
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    if state is None:
        raise HTTPException(status_code=503, detail="Aggregator not ready")

    # Match head_name case-insensitively
    target = head_name.lower()
    for h in state.floor_summary.heads:
        if h.head_name.lower() == target:
            return {
                "head_name": h.head_name,
                "state": h.state,
                "bias": h.bias,
                "confidence": h.confidence,
                "freshness_tag": h.freshness_tag,
                "context_quality_score": h.context_quality_score,
                "primary_setup": h.primary_setup,
                "backup_setup": h.backup_setup,
                "invalidation_summary": h.invalidation_summary,
                "no_setup_flag": h.no_setup_flag,
                "timestamp": datetime.utcnow().isoformat(),
            }

    known = [h.head_name for h in state.floor_summary.heads]
    raise HTTPException(
        status_code=404,
        detail=f"Unknown head '{head_name}'. Known: {known}",
    )


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach head routes to the FastAPI app."""
    app.include_router(router)
