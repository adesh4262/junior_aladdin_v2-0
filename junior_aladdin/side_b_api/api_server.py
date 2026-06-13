"""Side B API server — FastAPI entry point.

Starts the operator terminal backend that all floor/side data sources
aggregate through, and pushes real-time updates via WebSocket.

Startup sequence:
  1. Load config (api_config)
  2. Initialize session cache
  3. Initialize data aggregator
  4. Register all route modules
  5. Start background HOT/WARM/COLD pollers
  6. Start uvicorn server

Usage:
    # From project root:
    python -m junior_aladdin.side_b_api.api_server
    # Or: uvicorn junior_aladdin.side_b_api.api_server:app --host 127.0.0.1 --port 8080 --reload

Reference: ROADMAP_SIDE_B Step 8.4
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG
from junior_aladdin.side_b_api.data_aggregator import get_default_aggregator
from junior_aladdin.side_b_api.session_cache import get_default_cache

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Lifespan — startup / shutdown
# ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup tasks → yield → shutdown tasks."""
    log.info("Side B API starting ...")

    # ── Startup ──
    cache = get_default_cache()
    aggregator = get_default_aggregator()

    # Initial full poll so the cache is seeded
    try:
        aggregator.poll_all()
        log.info("Initial data poll complete")
    except Exception:
        log.warning("Initial data poll failed — will retry on first background cycle")

    # Start background pollers
    poller_task = asyncio.create_task(_run_poller_loop(aggregator, cache))

    log.info(
        "Side B API ready — http://%s:%d",
        DEFAULT_CONFIG.host,
        DEFAULT_CONFIG.port,
    )

    yield  # Server runs here

    # ── Shutdown ──
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    log.info("Side B API stopped")


# ──────────────────────────────────────────────
#  FastAPI app
# ──────────────────────────────────────────────

app = FastAPI(
    title="Junior Aladdin — Side B API",
    description="Operator terminal backend. Aggregates data from all 5 floors and 3 sides.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend on localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_CONFIG.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount static dashboard files ──
_dashboard_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "side_b_dashboard"))
if os.path.isdir(_dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=_dashboard_path, html=True), name="dashboard")
    log.info("Dashboard UI mounted from: %s", _dashboard_path)

# ── Reference to aggregator & cache (used by route modules) ──
app.state.aggregator = get_default_aggregator()
app.state.cache = get_default_cache()
app.state.config = DEFAULT_CONFIG


# ──────────────────────────────────────────────
#  Built-in root endpoints
# ──────────────────────────────────────────────


@app.get("/")
async def root():
    """API root — returns server metadata."""
    return {
        "service": "Junior Aladdin — Side B API",
        "version": "0.1.0",
        "status": "running",
        "dashboard_url": "/dashboard/",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/debug/cache-stats")
async def cache_stats():
    """Debug endpoint — session cache performance stats."""
    cache = app.state.cache
    return cache.get_cache_stats()


@app.get("/api/debug/state")
async def debug_state():
    """Debug endpoint — return the full aggregated state (dev only)."""
    agg = app.state.aggregator
    state = agg.get_aggregated_state()
    if state is None:
        return {"status": "INITIALIZING"}
    return state


@app.get("/api/debug/cache-keys")
async def cache_keys():
    """Debug endpoint — return all cache keys with metadata.

    Returns a list of entries, each with:
    - key: str
    - tier: str (HOT/WARM/COLD)
    - age_s: float (seconds since creation)
    - hits: int
    - is_expired: bool
    """
    cache = app.state.cache
    keys = cache.get_all_keys()
    entries = []
    for key in keys:
        entry = cache._store.get(key)
        if entry:
            entries.append({
                "key": key,
                "tier": entry.tier.value,
                "age_s": entry.age_s,
                "hits": entry.hits,
                "is_expired": entry.is_expired,
                "value_preview": _truncate_preview(entry.value),
            })
    return {"entries": entries, "count": len(entries)}


@app.get("/api/debug/cache-entry/{key:path}")
async def cache_entry(key: str):
    """Debug endpoint — return a single cache entry with full value."""
    cache = app.state.cache
    entry = cache._store.get(key)
    if entry is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": f"Key '{key}' not found"})
    return {
        "key": key,
        "tier": entry.tier.value,
        "created_at": entry.created_at.isoformat(),
        "expires_at": entry.expires_at.isoformat(),
        "age_s": entry.age_s,
        "hits": entry.hits,
        "is_expired": entry.is_expired,
        "value": entry.value,
    }


@app.post("/api/debug/cache/invalidate")
async def invalidate_key(body: dict):
    """Debug endpoint — invalidate a single cache key."""
    key = body.get("key", "")
    if not key:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "'key' field is required"})
    cache = app.state.cache
    removed = cache.invalidate(key)
    return {"removed": removed, "key": key}


@app.post("/api/debug/cache/invalidate-tier")
async def invalidate_tier(body: dict):
    """Debug endpoint — invalidate all entries in a tier."""
    from junior_aladdin.side_b_api.session_cache import CacheTier
    tier_str = body.get("tier", "").upper()
    try:
        tier = CacheTier(tier_str)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": f"Invalid tier '{tier_str}'. Use HOT, WARM, or COLD"})
    cache = app.state.cache
    count = cache.invalidate_tier(tier)
    return {"removed": count, "tier": tier_str}


@app.post("/api/debug/cache/clear")
async def clear_cache():
    """Debug endpoint — clear the entire cache."""
    cache = app.state.cache
    count = len(cache._store)
    cache.clear_session()
    return {"removed": count, "message": "Cache cleared"}


def _truncate_preview(value: object, max_len: int = 200) -> str:
    """Return a truncated string preview of a value."""
    import json
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


# ──────────────────────────────────────────────
#  WebSocket — real-time push
# ──────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time data push via WebSocket.

    Connected clients receive state updates from the session cache at HOT
    frequency.  The background poller fills the cache — this handler only
    reads from it, never calls poll_*() directly.

    Supports channels: ``execution``, ``market``, ``captain``, ``health``.

    Message format (server → client)::
        {
            "channel": "execution",
            "data": { ... },
            "timestamp": "2026-06-13T10:30:00Z"
        }
    """
    await websocket.accept()
    log.info("WebSocket client connected")

    async def _push_hot():
        """Push HOT-tier cache data on every cycle."""
        while True:
            try:
                cache = app.state.cache
                hot_channels = {
                    "execution": cache.get("side_a"),
                    "market": cache.get("market_data"),
                }
                for channel, payload in hot_channels.items():
                    if payload is not None:
                        await websocket.send_json({
                            "channel": channel,
                            "data": payload,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
            except WebSocketDisconnect:
                break
            except Exception:
                pass
            await asyncio.sleep(DEFAULT_CONFIG.hot_refresh_s)

    async def _listen():
        """Listen for client messages (subscription control, future use)."""
        while True:
            try:
                msg = await websocket.receive_text()
                # Future: handle {"subscribe": ["execution", "captain"]}
            except WebSocketDisconnect:
                break

    try:
        push_task = asyncio.create_task(_push_hot())
        listen_task = asyncio.create_task(_listen())
        await asyncio.gather(push_task, listen_task)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        log.info("WebSocket client disconnected")


# ──────────────────────────────────────────────
#  Background poller
# ──────────────────────────────────────────────


async def _run_poller_loop(aggregator, cache):
    """Background loop that runs HOT (500ms), WARM (3s), COLD (30s) polls.

    Each tier maintains its own cadence and the poller tracks last-run
    timestamps so cycles don't drift or overlap.
    """
    last_hot = 0.0
    last_warm = 0.0
    last_cold = 0.0

    cfg = DEFAULT_CONFIG
    hot_s = cfg.hot_refresh_s
    warm_s = cfg.warm_refresh_s
    cold_s = cfg.cold_refresh_s

    while True:
        now = datetime.utcnow().timestamp()

        # ── HOT: 500ms — execution, market, alerts ──
        if now - last_hot >= hot_s:
            try:
                aggregator.poll_hot()
            except Exception:
                log.warning("HOT poll failed", exc_info=True)
            last_hot = now

        # ── WARM: 3s — heads, captain ──
        if now - last_warm >= warm_s:
            try:
                aggregator.poll_warm()
            except Exception:
                log.warning("WARM poll failed", exc_info=True)
            last_warm = now

        # ── COLD: 30s — full poll ──
        if now - last_cold >= cold_s:
            try:
                aggregator.poll_all()
            except Exception:
                log.warning("COLD / full poll failed", exc_info=True)
            last_cold = now

        await asyncio.sleep(0.1)  # 100ms tick — precise enough for 500ms HOT


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Register all route modules with the FastAPI app.

    Each route module exposes a ``register_routes(app)`` function.
    Call this during startup AFTER core app is configured.

    Route modules to register (in order):
        1. health_routes    (Step 8.5)
        2. captain_routes   (Step 8.6)
        3. head_routes      (Step 8.6)
        4. execution_routes (Step 8.7)
        5. market_routes    (Step 8.7)
        6. memory_routes    (Step 8.8)
        7. replay_routes    (Step 8.8)
        8. control_routes   (Step 8.9)
        9. alert_routes     (Step 8.9)
    """
    # Route modules register themselves below as they are implemented.
    from junior_aladdin.side_b_api.routes.health_routes import register_routes as reg_health
    reg_health(app)

    from junior_aladdin.side_b_api.routes.captain_routes import register_routes as reg_captain
    reg_captain(app)

    from junior_aladdin.side_b_api.routes.head_routes import register_routes as reg_heads
    reg_heads(app)

    from junior_aladdin.side_b_api.routes.execution_routes import register_routes as reg_exec
    reg_exec(app)

    from junior_aladdin.side_b_api.routes.market_routes import register_routes as reg_market
    reg_market(app)

    from junior_aladdin.side_b_api.routes.memory_routes import register_routes as reg_memory
    reg_memory(app)

    from junior_aladdin.side_b_api.routes.replay_routes import register_routes as reg_replay
    reg_replay(app)

    from junior_aladdin.side_b_api.routes.control_routes import register_routes as reg_control
    reg_control(app)

    from junior_aladdin.side_b_api.routes.alert_routes import register_routes as reg_alert
    reg_alert(app)


# Register built-in routes on startup
register_routes(app)


# ──────────────────────────────────────────────
#  CLI entry point
# ──────────────────────────────────────────────


def main() -> None:
    """Run the Side B API server via uvicorn."""
    import uvicorn

    uvicorn.run(
        "junior_aladdin.side_b_api.api_server:app",
        host=DEFAULT_CONFIG.host,
        port=DEFAULT_CONFIG.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
