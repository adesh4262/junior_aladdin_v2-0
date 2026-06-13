"""Pytest tests for Side B health + captain routes.

Tests:
  - GET /api/health — overall, data, connections, per-component
  - GET /api/captain — state, story, snapshots, reason, plans

Uses the same test_app pattern from test_api_server.py.

Reference: ROADMAP_SIDE_B Steps 8.5-8.6
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG
from junior_aladdin.side_b_api.data_contracts import (
    CaptainDisplayState,
    ComponentHealthDetail,
    DashboardState,
    FloorSummaryDisplay,
    HeadReportDisplay,
    MarketDataSnapshot,
)
from junior_aladdin.side_b_api.session_cache import SessionCache
from junior_aladdin.shared.types import CaptainMood, DataHealth, DecisionType, HeadState


# ══════════════════════════════════════════════════════════════
#  Helper — build a seeded DashboardState
# ══════════════════════════════════════════════════════════════


def _build_seeded_state() -> DashboardState:
    """Build a DashboardState with realistic data for route tests."""
    state = DashboardState()

    # Health
    state.health.overall_status = DataHealth.GOOD
    state.health.data_health_signal = DataHealth.GOOD
    state.health.connection_status = "CONNECTED"
    state.health.floors["floor_1"] = ComponentHealthDetail(
        name="floor_1", state="CONNECTED", detail="Angel One feed"
    )
    state.health.floors["floor_2"] = ComponentHealthDetail(
        name="floor_2", state="GOOD", detail="Data health nominal"
    )
    state.health.floors["floor_5"] = ComponentHealthDetail(
        name="floor_5", state="HEALTHY", detail="Captain active"
    )
    state.health.sides["side_a"] = ComponentHealthDetail(
        name="side_a", state="HEALTHY", detail="Execution idle"
    )
    state.health.sides["side_c"] = ComponentHealthDetail(
        name="side_c", state="HEALTHY", detail="Memory ready"
    )

    # Market
    state.market = MarketDataSnapshot(
        symbol="NIFTY 50",
        ltp=19500.50,
        change=45.20,
        change_percent=0.23,
        open=19455.30,
        high=19510.00,
        low=19450.00,
        prev_close=19455.30,
        volume=1250000,
        vwap=19480.00,
        session="OPEN",
    )

    # Captain
    state.captain = CaptainDisplayState(
        mood=CaptainMood.PATIENT,
        decision=DecisionType.WAIT,
        conviction_score=65.0,
        conviction_band="WEAK",
        market_story_summary="Bullish structure forming above VWAP",
        reason_summary="Waiting for ICT displacement confirmation",
        silence_reason=None,
        active_plan_count=1,
    )

    # Floor summary (Heads)
    state.floor_summary = FloorSummaryDisplay(
        floor_bias="BULLISH",
        floor_confidence=0.72,
        active_setup_count=2,
        ready_heads=4,
        uncertain_heads=1,
        stale_heads=1,
        data_health_signal=DataHealth.GOOD,
        heads=[
            HeadReportDisplay(
                head_name="Technical",
                state=HeadState.READY,
                bias="BULLISH",
                confidence=0.85,
                freshness_tag="FRESH",
                primary_setup="ema_bounce",
            ),
            HeadReportDisplay(
                head_name="ICT",
                state=HeadState.READY,
                bias="BULLISH",
                confidence=0.78,
                freshness_tag="FRESH",
                context_quality_score=0.82,
                primary_setup="fvg_retest",
                backup_setup="ob_entry",
            ),
            HeadReportDisplay(
                head_name="Macro",
                state=HeadState.UNCERTAIN,
                bias="NEUTRAL",
                confidence=0.45,
                freshness_tag="WARM",
                no_setup_flag=True,
            ),
        ],
    )

    return state


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def test_cache() -> SessionCache:
    return SessionCache(max_entries=100)


@pytest.fixture
def seeded_state() -> DashboardState:
    return _build_seeded_state()


@pytest.fixture
def test_app(test_cache: SessionCache, seeded_state: DashboardState) -> FastAPI:
    """Create a test FastAPI app with a seeded aggregator."""
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

    mock_agg = MagicMock()
    mock_agg.get_aggregated_state.return_value = seeded_state

    # Captain routes call get_state_snapshot(["floor_5"]) and look for
    # data["floor_5"]["captain_state"] — match the source adapter structure.
    # Derive captain snapshot from seeded_state so mock stays in sync
    cs = seeded_state.captain
    mock_agg.get_state_snapshot.return_value = {
        "floor_5": {
            "captain_state": {
                "mood": cs.mood.value if hasattr(cs.mood, "value") else str(cs.mood),
                "decision_state": cs.decision.value if hasattr(cs.decision, "value") else str(cs.decision),
                "conviction_band": cs.conviction_band,
                "market_story_summary": cs.market_story_summary,
                "silence_reason": cs.silence_reason,
                "session_phase": "",
                "real_mode_locked": False,
                "active_trade": False,
            },
            "decision_snapshots": [],
            "armed_plans": [],
        },
    }
    app.state.aggregator = mock_agg

    # Register all route modules
    from junior_aladdin.side_b_api.routes.health_routes import register_routes as reg_health
    reg_health(app)
    from junior_aladdin.side_b_api.routes.captain_routes import register_routes as reg_captain
    reg_captain(app)
    from junior_aladdin.side_b_api.routes.head_routes import register_routes as reg_heads
    reg_heads(app)

    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


# ══════════════════════════════════════════════════════════════
#  1. Health Route Tests
# ══════════════════════════════════════════════════════════════


class TestHealthRoutes:
    """Verify GET /api/health endpoints."""

    def test_health_overall(self, client: TestClient) -> None:
        """GET /api/health returns overall system health."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_status" in data
        assert "data_health_signal" in data
        assert "connection_status" in data
        assert "floors" in data
        assert "sides" in data
        assert "timestamp" in data

    def test_health_overall_values(self, client: TestClient) -> None:
        """Overall health shows GOOD status."""
        data = client.get("/api/health").json()
        assert data["overall_status"] == "GOOD"
        assert data["data_health_signal"] == "GOOD"
        assert data["connection_status"] == "CONNECTED"

    def test_health_floors_present(self, client: TestClient) -> None:
        """Floors dict contains known floors."""
        data = client.get("/api/health").json()
        assert "floor_1" in data["floors"]
        assert "floor_2" in data["floors"]
        assert "floor_5" in data["floors"]

    def test_health_sides_present(self, client: TestClient) -> None:
        """Sides dict contains known sides."""
        data = client.get("/api/health").json()
        assert "side_a" in data["sides"]
        assert "side_c" in data["sides"]

    def test_health_data_endpoint(self, client: TestClient) -> None:
        """GET /api/health/data returns data health signal."""
        resp = client.get("/api/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_health"] == "GOOD"
        assert data["source"] == "Floor 2"

    def test_health_connections_endpoint(self, client: TestClient) -> None:
        """GET /api/health/connections returns connection status."""
        resp = client.get("/api/health/connections")
        assert resp.status_code == 200
        data = resp.json()
        assert "connections" in data
        assert "overall" in data
        assert data["overall"] == "CONNECTED"
        assert "floor_1" in data["connections"]

    def test_health_component_found(self, client: TestClient) -> None:
        """GET /api/health/{component} returns component detail."""
        resp = client.get("/api/health/floor_1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "floor_1"
        assert data["state"] == "CONNECTED"
        assert "detail" in data

    def test_health_component_not_found(self, client: TestClient) -> None:
        """GET /api/health/nonexistent returns 404."""
        resp = client.get("/api/health/nonexistent")
        assert resp.status_code == 404

    def test_health_component_side_a(self, client: TestClient) -> None:
        """Side A component is found in health."""
        resp = client.get("/api/health/side_a")
        assert resp.status_code == 200
        assert resp.json()["state"] == "HEALTHY"

    def test_health_has_timestamp(self, client: TestClient) -> None:
        """Health endpoint returns an ISO timestamp."""
        data = client.get("/api/health").json()
        assert "timestamp" in data
        assert "T" in data["timestamp"]  # ISO format


# ══════════════════════════════════════════════════════════════
#  2. Captain Route Tests
# ══════════════════════════════════════════════════════════════


class TestCaptainRoutes:
    """Verify GET /api/captain endpoints."""

    def test_captain_state(self, client: TestClient) -> None:
        """GET /api/captain/state returns captain state."""
        resp = client.get("/api/captain/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mood"] == "PATIENT"
        assert data["decision_state"] == "WAIT"
        assert data["conviction_band"] == "WEAK"
        assert "market_story_summary" in data
        assert "timestamp" in data

    def test_captain_story(self, client: TestClient) -> None:
        """GET /api/captain/story returns market story."""
        resp = client.get("/api/captain/story")
        assert resp.status_code == 200
        data = resp.json()
        assert "story_summary" in data
        assert data["story_summary"] == "Bullish structure forming above VWAP"

    def test_captain_snapshots(self, client: TestClient) -> None:
        """GET /api/captain/snapshots returns list."""
        resp = client.get("/api/captain/snapshots")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_captain_reason(self, client: TestClient) -> None:
        """GET /api/captain/reason returns trade/no-trade reason."""
        resp = client.get("/api/captain/reason")
        assert resp.status_code == 200
        data = resp.json()
        assert "decision" in data
        assert "reason" in data
        assert data["decision"] == "WAIT"

    def test_captain_plans(self, client: TestClient) -> None:
        """GET /api/captain/plans returns list."""
        resp = client.get("/api/captain/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ══════════════════════════════════════════════════════════════
#  3. Head Route Tests
# ══════════════════════════════════════════════════════════════


class TestHeadRoutes:
    """Verify GET /api/heads endpoints."""

    def test_heads_all(self, client: TestClient) -> None:
        """GET /api/heads returns all head reports with floor summary."""
        resp = client.get("/api/heads")
        assert resp.status_code == 200
        data = resp.json()
        assert "heads" in data
        assert "floor_summary" in data
        assert len(data["heads"]) == 3
        assert "timestamp" in data

    def test_heads_floor_summary(self, client: TestClient) -> None:
        """GET /api/heads/floor-summary returns aggregated summary."""
        resp = client.get("/api/heads/floor-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["floor_bias"] == "BULLISH"
        assert data["floor_confidence"] == 0.72
        assert data["active_setup_count"] == 2
        assert data["ready_heads"] == 4

    def test_heads_health(self, client: TestClient) -> None:
        """GET /api/heads/health returns per-head state."""
        resp = client.get("/api/heads/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "heads" in data
        assert "Technical" in data["heads"]
        assert data["heads"]["Technical"]["state"] == "READY"

    def test_head_detail_found(self, client: TestClient) -> None:
        """GET /api/heads/{name} returns head detail."""
        resp = client.get("/api/heads/Technical")
        assert resp.status_code == 200
        data = resp.json()
        assert data["head_name"] == "Technical"
        assert data["bias"] == "BULLISH"
        assert data["confidence"] == 0.85

    def test_head_detail_case_insensitive(self, client: TestClient) -> None:
        """Head detail lookup is case-insensitive."""
        resp = client.get("/api/heads/technical")
        assert resp.status_code == 200
        assert resp.json()["head_name"] == "Technical"

    def test_head_detail_not_found(self, client: TestClient) -> None:
        """Unknown head returns 404."""
        resp = client.get("/api/heads/nonexistent")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════
#  4. Uninitialised Aggregator Tests
# ══════════════════════════════════════════════════════════════


class TestUninitialisedAggregator:
    """Verify routes handle uninitialised aggregator gracefully."""

    @pytest.fixture
    def uninit_app(self, test_cache: SessionCache) -> FastAPI:
        """App with aggregator returning None (not yet polled)."""
        app = FastAPI(title="Test — Uninitialised")
        app.state.cache = test_cache
        app.state.config = DEFAULT_CONFIG
        mock_agg = MagicMock()
        mock_agg.get_aggregated_state.return_value = None
        mock_agg.get_state_snapshot.return_value = {}
        app.state.aggregator = mock_agg

        from junior_aladdin.side_b_api.routes.health_routes import register_routes as reg_health
        reg_health(app)
        from junior_aladdin.side_b_api.routes.captain_routes import register_routes as reg_captain
        reg_captain(app)
        from junior_aladdin.side_b_api.routes.head_routes import register_routes as reg_heads
        reg_heads(app)

        return app

    @pytest.fixture
    def uninit_client(self, uninit_app: FastAPI) -> TestClient:
        return TestClient(uninit_app)

    def test_health_init(self, uninit_client: TestClient) -> None:
        """Health returns INITIALIZING when aggregator not ready."""
        data = uninit_client.get("/api/health").json()
        assert data["status"] == "INITIALIZING"

    def test_health_data_init(self, uninit_client: TestClient) -> None:
        """Health/data returns UNKNOWN when aggregator not ready."""
        data = uninit_client.get("/api/health/data").json()
        assert data["data_health"] == "UNKNOWN"

    def test_health_connections_init(self, uninit_client: TestClient) -> None:
        """Health/connections returns UNKNOWN when aggregator not ready."""
        data = uninit_client.get("/api/health/connections").json()
        assert data["overall"] == "UNKNOWN"

    def test_health_component_init(self, uninit_client: TestClient) -> None:
        """Health/{component} returns 503 when aggregator not ready."""
        resp = uninit_client.get("/api/health/floor_1")
        assert resp.status_code == 503

    def test_heads_init(self, uninit_client: TestClient) -> None:
        """Heads returns empty lists when aggregator not ready."""
        data = uninit_client.get("/api/heads").json()
        assert data["heads"] == []
        assert data["floor_summary"] == {}

    def test_captain_state_init(self, uninit_client: TestClient) -> None:
        """Captain state returns defaults when aggregator not ready."""
        data = uninit_client.get("/api/captain/state").json()
        assert data["mood"] == "OBSERVER"
        assert data["decision_state"] == "WAIT"
