"""Side B captain route module.

Exposes Captain (Floor 5) state and decision data for the operator terminal.

Endpoints:
    GET /api/captain/state      — CaptainDisplayState (mood, decision, conviction)
    GET /api/captain/story      — current market story summary
    GET /api/captain/snapshots  — recent decision snapshots
    GET /api/captain/reason     — trade/no-trade reason
    GET /api/captain/plans      — active armed plans

Reference: ROADMAP_SIDE_B Step 8.6, SIDE_B_DASHBOARD_V1_2_FINAL Section 11-12
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request

router = APIRouter(prefix="/api/captain", tags=["captain"])


# ──────────────────────────────────────────────
#  GET /api/captain/state
# ──────────────────────────────────────────────


@router.get("/state")
async def get_captain_state(request: Request) -> dict[str, Any]:
    """Current Captain state — mood, decision, conviction band, market story.

    Data source: Floor 5 via data aggregator (WARM refresh tier).
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_5"])
    cs = data.get("floor_5", {}).get("captain_state", {})

    return {
        "mood": cs.get("mood", "OBSERVER"),
        "decision_state": cs.get("decision_state", "WAIT"),
        "conviction_band": cs.get("conviction_band", "REJECT"),
        "market_story_summary": cs.get("market_story_summary", ""),
        "silence_reason": cs.get("silence_reason", ""),
        "session_phase": cs.get("session_phase", ""),
        "real_mode_locked": cs.get("real_mode_locked", False),
        "active_trade": cs.get("active_trade", False),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/captain/story
# ──────────────────────────────────────────────


@router.get("/story")
async def get_captain_story(request: Request) -> dict[str, Any]:
    """Current market story summary from Captain."""
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_5"])
    cs = data.get("floor_5", {}).get("captain_state", {})

    return {
        "story_summary": cs.get("market_story_summary", ""),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/captain/snapshots
# ──────────────────────────────────────────────


@router.get("/snapshots")
async def get_captain_snapshots(request: Request) -> list[dict[str, Any]]:
    """Recent decision snapshots from Captain."""
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_5"])
    snapshots = data.get("floor_5", {}).get("decision_snapshots", [])
    return snapshots


# ──────────────────────────────────────────────
#  GET /api/captain/reason
# ──────────────────────────────────────────────


@router.get("/reason")
async def get_captain_reason(request: Request) -> dict[str, Any]:
    """Trade or no-trade reason from Captain.

    If a trade is active, returns trade reason.
    If no trade (WAIT/BLOCKED), returns no-trade classification and silence reason.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_5"])
    cs = data.get("floor_5", {}).get("captain_state", {})

    silence = cs.get("silence_reason", "")
    decision = cs.get("decision_state", "WAIT")

    reason = cs.get("market_story_summary", "")
    if silence:
        reason = silence

    return {
        "decision": decision,
        "reason": reason,
        "silence_reason": silence or None,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/captain/plans
# ──────────────────────────────────────────────


@router.get("/plans")
async def get_captain_plans(request: Request) -> list[dict[str, Any]]:
    """Active armed plans from Captain."""
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_5"])
    plans = data.get("floor_5", {}).get("armed_plans", [])
    return plans


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach captain routes to the FastAPI app."""
    app.include_router(router)
