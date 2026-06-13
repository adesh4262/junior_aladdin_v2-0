"""Side B market route module.

Exposes Floor 3 market data and Floor 1 connection data for the
operator terminal's chart and ticker.

Endpoints:
    GET /api/market/snapshot — current market data (LTP, OHLC, VWAP)
    GET /api/market/chart    — OHLCV + indicator data for chart surface
    GET /api/market/session  — current session context

Reference: ROADMAP_SIDE_B Step 8.7, SIDE_B_DASHBOARD_V1_2_FINAL Section 16
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request

router = APIRouter(prefix="/api/market", tags=["market"])


# ──────────────────────────────────────────────
#  GET /api/market/snapshot
# ──────────────────────────────────────────────


@router.get("/snapshot")
async def get_market_snapshot(request: Request) -> dict[str, Any]:
    """Current market data snapshot.

    Returns LTP, OHLC, VWAP, change, session context.
    Data sourced from Floor 1 (connection) and Floor 3 (CMSP).
    """
    agg = request.app.state.aggregator
    state = agg.get_aggregated_state()

    if state is None:
        return {"status": "INITIALIZING"}

    m = state.market
    return {
        "symbol": m.symbol,
        "ltp": m.ltp,
        "change": m.change,
        "change_percent": m.change_percent,
        "open": m.open,
        "high": m.high,
        "low": m.low,
        "prev_close": m.prev_close,
        "volume": m.volume,
        "vwap": m.vwap,
        "session": m.session,
        "timestamp": m.timestamp.isoformat() if hasattr(m.timestamp, "isoformat") else "",
    }


# ──────────────────────────────────────────────
#  GET /api/market/chart
# ──────────────────────────────────────────────


@router.get("/chart")
async def get_market_chart(request: Request) -> dict[str, Any]:
    """OHLCV + indicator data for the chart surface.

    Returns chart-ready data from Floor 3 (CMSP + domain summaries).
    Includes candle data, key levels, and indicator overlays where available.
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_3"])

    chart_data = data.get("floor_3", {}).get("chart_data")
    cmsp = data.get("floor_3", {}).get("cmsp", {})
    domains = data.get("floor_3", {}).get("domain_summaries", {})

    return {
        "chart": chart_data,
        "key_levels": cmsp.get("key_levels", []),
        "regime_state": cmsp.get("regime_state", {}),
        "domain_summaries": domains,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  GET /api/market/session
# ──────────────────────────────────────────────


@router.get("/session")
async def get_market_session(request: Request) -> dict[str, Any]:
    """Current session context.

    Returns session phase, market regime, volatility state, and session
    state from the Common Market State Projection (CMSP).
    """
    agg = request.app.state.aggregator
    data = agg.get_state_snapshot(["floor_3"])

    cmsp = data.get("floor_3", {}).get("cmsp", {})

    return {
        "session_state": cmsp.get("session_state", {}),
        "regime_state": cmsp.get("regime_state", {}),
        "volatility_state": cmsp.get("volatility_state", {}),
        "price_state": cmsp.get("price_state", {}),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────


def register_routes(app: FastAPI) -> None:
    """Attach market routes to the FastAPI app."""
    app.include_router(router)
