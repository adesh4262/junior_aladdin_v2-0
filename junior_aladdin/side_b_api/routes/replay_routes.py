"""Side B replay route module — READ-ONLY.

Exposes replay workspace endpoints for the operator terminal.
Replay is strictly read-only — no execution commands accepted.

Endpoints:
    GET    /api/replay/sessions — available replay sessions
    POST   /api/replay/start    — start replay session
    POST   /api/replay/stop     — stop replay session
    POST   /api/replay/speed    — set replay speed
    GET    /api/replay/state    — current replay state
    GET    /api/replay/data     — replay data stream

CRITICAL: Replay workspace is READ-ONLY. No execution from replay.

Reference: ROADMAP_SIDE_B Step 8.8, SIDE_B_DASHBOARD_V1_2_FINAL Section 18
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

router = APIRouter(prefix="/api/replay", tags=["replay"])

# Allowed replay speeds (shared by POST /start and POST /speed)
REPLAY_ALLOWED_SPEEDS: list[float] = [0.5, 1.0, 2.0, 5.0, 10.0]

# In-memory replay session state (per roadmap: session cache, no persistence)
_active_replay: dict[str, Any] = {
    "active": False,
    "session_id": None,
    "speed": 1.0,
    "status": "STOPPED",
    "start_time": None,
    "end_time": None,
}


# ──────────────────────────────────────────────
#  GET /api/replay/sessions
# ──────────────────────────────────────────────


@router.get("/sessions")
async def get_replay_sessions(request: Request) -> dict[str, Any]:
    """Available replay sessions.

    Returns a list of replay sessions that can be loaded.
    Data sourced from Floor 2 replay engine metadata.
    """
    sessions: list[dict[str, Any]] = []

    try:
        agg = request.app.state.aggregator
        data = agg.get_state_snapshot(["floor_2"])
        replay_status = data.get("floor_2", {}).get("replay_status", {})

        # If Floor 2 has active replay metadata, surface it
        if replay_status:
            sessions.append({
                "session_id": data.get("floor_2", {}).get("replay_session_id", "unknown"),
                "status": "AVAILABLE",
                "source": "Floor 2",
            })
    except Exception:
        pass

    return {
        "sessions": sessions,
        "count": len(sessions),
        "active_session": _active_replay.get("session_id"),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  POST /api/replay/start
# ──────────────────────────────────────────────


@router.post("/start")
async def start_replay(request: Request) -> dict[str, Any]:
    """Start a replay session.

    Request body (optional):
        session_id: str — specific session to replay
        start_time: str (ISO) — override start
        end_time: str (ISO) — override end

    Returns the new replay session state.
    READ-ONLY: This endpoint starts a replay view session only.
    No execution commands are accepted through replay.
    """
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        pass

    # Validate speed before applying (consistent with POST /speed)
    requested_speed = float(body.get("speed", 1.0))
    if requested_speed not in REPLAY_ALLOWED_SPEEDS:
        raise HTTPException(
            status_code=400,
            detail=f"Speed must be one of {REPLAY_ALLOWED_SPEEDS}, got {requested_speed}",
        )

    _active_replay["active"] = True
    _active_replay["session_id"] = body.get("session_id", f"replay_{int(datetime.utcnow().timestamp())}")
    _active_replay["status"] = "PLAYING"
    _active_replay["speed"] = requested_speed
    _active_replay["start_time"] = body.get("start_time")
    _active_replay["end_time"] = body.get("end_time")

    return {
        "status": "PLAYING",
        "session_id": _active_replay["session_id"],
        "speed": _active_replay["speed"],
        "message": "Replay started — workspace is READ-ONLY, no execution",
        "read_only": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  POST /api/replay/stop
# ──────────────────────────────────────────────


@router.post("/stop")
async def stop_replay(request: Request) -> dict[str, Any]:
    """Stop the current replay session."""
    was_active = _active_replay["active"]
    _active_replay["active"] = False
    _active_replay["status"] = "STOPPED"

    return {
        "status": "STOPPED",
        "was_active": was_active,
        "session_id": _active_replay["session_id"],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  POST /api/replay/speed
# ──────────────────────────────────────────────


@router.post("/speed")
async def set_replay_speed(request: Request) -> dict[str, Any]:
    """Set replay playback speed.

    Request body: {"speed": 2.0}
    Allowed speeds: 0.5, 1.0, 2.0, 5.0, 10.0
    """
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    speed = float(body.get("speed", 1.0))

    # Validate allowed speeds (shared constant with POST /start)
    if speed not in REPLAY_ALLOWED_SPEEDS:
        raise HTTPException(
            status_code=400,
            detail=f"Speed must be one of {REPLAY_ALLOWED_SPEEDS}, got {speed}",
        )

    _active_replay["speed"] = speed

    return {
        "status": _active_replay["status"],
        "speed": speed,
        "session_id": _active_replay["session_id"],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/replay/state
# ──────────────────────────────────────────────


@router.get("/state")
async def get_replay_state(request: Request) -> dict[str, Any]:
    """Current replay session state."""
    return {
        "active": _active_replay["active"],
        "session_id": _active_replay["session_id"],
        "speed": _active_replay["speed"],
        "status": _active_replay["status"],
        "start_time": _active_replay["start_time"],
        "end_time": _active_replay["end_time"],
        "read_only": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/replay/data
# ──────────────────────────────────────────────


@router.get("/data")
async def get_replay_data(request: Request) -> dict[str, Any]:
    """Replay data stream for the current session.

    Returns sampled data from Floor 2 replay engine if available,
    or empty result if no active session.
    """
    if not _active_replay["active"]:
        return {
            "active": False,
            "data": [],
            "message": "No active replay session",
            "timestamp": datetime.utcnow().isoformat(),
        }

    replay_data: list[dict[str, Any]] = []

    try:
        agg = request.app.state.aggregator
        data = agg.get_state_snapshot(["floor_2"])
        replay_status = data.get("floor_2", {}).get("replay_status", {})
        if isinstance(replay_status, dict):
            replay_data = [replay_status]
    except Exception:
        pass

    return {
        "active": True,
        "session_id": _active_replay["session_id"],
        "speed": _active_replay["speed"],
        "data": replay_data,
        "data_points": len(replay_data),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach replay routes to the FastAPI app."""
    app.include_router(router)
