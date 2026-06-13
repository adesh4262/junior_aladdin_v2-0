"""Pytest tests for Side B execution + market routes.

Tests:
  - GET /api/execution — state, position, orders, blocked, logs
  - GET /api/market — snapshot, chart, session

Reference: ROADMAP_SIDE_B Step 8.7
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG
from junior_aladdin.side_b_api.data_contracts import (
    DashboardState,
    ExecutionDisplayState,
    MarketDataSnapshot,
)
from junior_aladdin.side_b_api.session_cache import CacheTier, SessionCache
from junior_aladdin.shared.types import ExecutionMode


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def test_cache() -> SessionCache:
    return SessionCache(max_entries=100)


@pytest.fixture
def app_with_state(test_cache: SessionCache) -> FastAPI:
    """Create app with a seeded DashboardState for execution + market."""
    app = FastAPI(title="Test — Side B Routes")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.cache = test_cache
    app.state.config = DEFAULT_CONFIG

    # Build seeded state
    state = DashboardState()

    state.execution = ExecutionDisplayState(
        mode=ExecutionMode.PAPER,
        state="MONITORING",
        escalation_level="NORMAL",
        kill_switch_state="NORMAL",
        capital_limit=500000.0,
        position={
            "trade_id": "trade_001",
            "direction": "BUY",
            "filled_qty": 75,
            "avg_price": 19520.0,
        },
        orders=[
            {"order_id": "ord_001", "status": "FILLED", "side": "BUY", "qty": 50, "filled_qty": 50, "price": 19520.0},
            {"order_id": "ord_002", "status": "WORKING", "side": "BUY", "qty": 25, "filled_qty": 0, "price": 19530.0},
        ],
        blocked_actions=[{"action": "increase_size", "reason": "Risk gate limit exceeded"}],
    )

    state.market = MarketDataSnapshot(
        symbol="NIFTY 50",
        ltp=19550.00,
        change=45.20,
        change_percent=0.23,
        open=19455.30,
        high=19580.00,
        low=19450.00,
        prev_close=19455.30,
        volume=1250000,
        vwap=19480.00,
        session="OPEN",
    )

    # Seed cache with Side A data so get_state_snapshot works
    test_cache.set("side_a", {
        "execution_state": {
            "mode": "PAPER",
            "state": "MONITORING",
            "escalation_level": "NORMAL",
            "kill_switch_state": "NORMAL",
            "capital_limit": 500000.0,
            "position": {
                "trade_id": "trade_001",
                "direction": "BUY",
                "filled_qty": 75,
                "avg_price": 19520.0,
            },
            "orders": [
                {"order_id": "ord_001", "status": "FILLED", "side": "BUY", "qty": 50, "filled_qty": 50, "price": 19520.0},
                {"order_id": "ord_002", "status": "WORKING", "side": "BUY", "qty": 25, "filled_qty": 0, "price": 19530.0},
            ],
        },
        "blocked_actions": [{"action": "increase_size", "reason": "Risk gate limit exceeded"}],
        "execution_logs": [{"event": "order_placed", "details": {"order_id": "ord_001"}}],
    }, CacheTier.HOT)

    mock_agg = MagicMock()
    mock_agg.get_aggregated_state.return_value = state
    mock_agg.get_state_snapshot.return_value = {
        "side_a": test_cache.get("side_a"),
        "floor_3": {
            "cmsp": {
                "key_levels": [19450, 19500, 19550],
                "regime_state": {"type": "TRENDING"},
                "session_state": {"phase": "OPEN"},
                "volatility_state": {"regime": "LOW"},
                "price_state": {"trend": "BULLISH"},
            },
            "chart_data": {"candles": [{"open": 19500, "close": 19550, "high": 19580, "low": 19450}], "indicators": {}},
            "domain_summaries": {"smc": {"state": "BULLISH"}},
        },
    }
    app.state.aggregator = mock_agg

    from junior_aladdin.side_b_api.routes.execution_routes import register_routes as reg_exec
    reg_exec(app)
    from junior_aladdin.side_b_api.routes.market_routes import register_routes as reg_market
    reg_market(app)

    return app


@pytest.fixture
def client(app_with_state: FastAPI) -> TestClient:
    return TestClient(app_with_state)


# ══════════════════════════════════════════════════════════════
#  1. Execution Route Tests
# ══════════════════════════════════════════════════════════════


class TestExecutionRoutes:
    """Verify GET /api/execution endpoints."""

    def test_execution_state(self, client: TestClient) -> None:
        """GET /api/execution/state returns execution state."""
        resp = client.get("/api/execution/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "PAPER"
        assert data["state"] == "MONITORING"
        assert data["escalation_level"] == "NORMAL"
        assert data["kill_switch_state"] == "NORMAL"
        assert data["capital_limit"] == 500000.0
        assert "timestamp" in data

    def test_execution_state_has_position(self, client: TestClient) -> None:
        """Execution state includes position data."""
        data = client.get("/api/execution/state").json()
        pos = data["position"]
        assert pos is not None
        assert pos["trade_id"] == "trade_001"
        assert pos["direction"] == "BUY"
        assert pos["filled_qty"] == 75

    def test_execution_state_has_orders(self, client: TestClient) -> None:
        """Execution state includes orders list."""
        data = client.get("/api/execution/state").json()
        orders = data["orders"]
        assert len(orders) == 2
        assert orders[0]["order_id"] == "ord_001"
        assert orders[1]["order_id"] == "ord_002"

    def test_execution_position_active(self, client: TestClient) -> None:
        """GET /api/execution/position returns active position."""
        resp = client.get("/api/execution/position")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["position"]["trade_id"] == "trade_001"

    def test_execution_orders(self, client: TestClient) -> None:
        """GET /api/execution/orders returns order list."""
        resp = client.get("/api/execution/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["orders"]) == 2

    def test_execution_blocked(self, client: TestClient) -> None:
        """GET /api/execution/blocked returns blocked actions."""
        resp = client.get("/api/execution/blocked")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert "blocked_actions" in data

    def test_execution_logs(self, client: TestClient) -> None:
        """GET /api/execution/logs returns execution logs."""
        resp = client.get("/api/execution/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert data["count"] >= 1


# ══════════════════════════════════════════════════════════════
#  2. Market Route Tests
# ══════════════════════════════════════════════════════════════


class TestMarketRoutes:
    """Verify GET /api/market endpoints."""

    def test_market_snapshot(self, client: TestClient) -> None:
        """GET /api/market/snapshot returns market data."""
        resp = client.get("/api/market/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NIFTY 50"
        assert data["ltp"] == 19550.00
        assert data["change"] == 45.20
        assert data["change_percent"] == 0.23
        assert data["session"] == "OPEN"
        assert "timestamp" in data

    def test_market_snapshot_has_ohlc(self, client: TestClient) -> None:
        """Market snapshot includes OHLCV fields."""
        data = client.get("/api/market/snapshot").json()
        assert "open" in data
        assert "high" in data
        assert "low" in data
        assert "prev_close" in data
        assert "volume" in data
        assert "vwap" in data

    def test_market_chart(self, client: TestClient) -> None:
        """GET /api/market/chart returns chart data."""
        resp = client.get("/api/market/chart")
        assert resp.status_code == 200
        data = resp.json()
        assert "chart" in data
        assert "key_levels" in data
        assert "regime_state" in data
        assert "domain_summaries" in data
        assert data["key_levels"] == [19450, 19500, 19550]
        assert data["regime_state"]["type"] == "TRENDING"

    def test_market_session(self, client: TestClient) -> None:
        """GET /api/market/session returns session context."""
        resp = client.get("/api/market/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_state" in data
        assert "regime_state" in data
        assert "volatility_state" in data
        assert "price_state" in data
        assert data["session_state"]["phase"] == "OPEN"


# ══════════════════════════════════════════════════════════════
#  3. Uninitialised Tests
# ══════════════════════════════════════════════════════════════


class TestUninitialised:
    """Verify routes handle uninitialised aggregator gracefully."""

    @pytest.fixture
    def uninit_app(self, test_cache: SessionCache) -> FastAPI:
        app = FastAPI(title="Test — Uninitialised")
        app.state.cache = test_cache
        app.state.config = DEFAULT_CONFIG
        mock_agg = MagicMock()
        mock_agg.get_aggregated_state.return_value = None
        mock_agg.get_state_snapshot.return_value = {}
        app.state.aggregator = mock_agg

        from junior_aladdin.side_b_api.routes.execution_routes import register_routes as reg_exec
        reg_exec(app)
        from junior_aladdin.side_b_api.routes.market_routes import register_routes as reg_market
        reg_market(app)
        return app

    @pytest.fixture
    def uninit_client(self, uninit_app: FastAPI) -> TestClient:
        return TestClient(uninit_app)

    def test_snapshot_init(self, uninit_client: TestClient) -> None:
        """Market snapshot returns INITIALIZING when aggregator not ready."""
        data = uninit_client.get("/api/market/snapshot").json()
        assert data["status"] == "INITIALIZING"

    def test_execution_state_init(self, uninit_client: TestClient) -> None:
        """Execution state returns defaults when aggregator not ready."""
        data = uninit_client.get("/api/execution/state").json()
        assert data["mode"] == "ALERT"
        assert data["state"] == "IDLE"

    def test_execution_position_init(self, uninit_client: TestClient) -> None:
        """Execution position returns no active position when aggregator not ready."""
        data = uninit_client.get("/api/execution/position").json()
        assert data["active"] is False
        assert data["position"] is None
