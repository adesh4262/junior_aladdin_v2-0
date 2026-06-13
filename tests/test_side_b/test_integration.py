"""Integration tests for Side B — API + Dashboard end-to-end validation.

Tests the complete data flow:
  - All route endpoints return correct response structure
  - Route responses match expected data contract schemas
  - Dashboard HTML/JS references are consistent
  - Cache-backed endpoints serve correct data
  - Command flow (POST → cache → GET reflects changes)

Reference: ROADMAP_SIDE_B Step 8.10–8.12, SIDE_B_DASHBOARD_V1_2_FINAL
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG
from junior_aladdin.side_b_api.session_cache import SessionCache, CacheTier


# ── Project paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARD_DIR = PROJECT_ROOT / "junior_aladdin" / "side_b_dashboard"


# ══════════════════════════════════════════════════════════════
#  Full Integration Fixture
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def integration_cache() -> SessionCache:
    """Fresh cache for integration tests."""
    return SessionCache(max_entries=200)


@pytest.fixture
def integration_app(integration_cache: SessionCache) -> FastAPI:
    """Create a fully-wired test app for integration testing.

    Uses a mock aggregator that returns realistic sample data
    for all 7 data sources.
    """
    app = FastAPI(title="Integration Test — Side B API")

    # Add CORS middleware (same as production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.cache = integration_cache
    app.state.config = DEFAULT_CONFIG

    # ── Mock aggregator with realistic sample data ──
    mock_agg = MagicMock()

    # Sample aggregated state (simulates a fully polled system)
    from junior_aladdin.side_b_api.data_contracts import (
        CaptainDisplayState,
        ComponentHealthDetail,
        DashboardState,
        ExecutionDisplayState,
        FloorSummaryDisplay,
        HeadReportDisplay,
        MarketDataSnapshot,
        SystemHealthSnapshot,
    )
    from junior_aladdin.shared.types import DataHealth

    sample_health = SystemHealthSnapshot(
        overall_status=DataHealth.GOOD,
        data_health_signal=DataHealth.GOOD,
        connection_status="CONNECTED",
        critical_alert_count=0,
        floors={
            "floor_1": ComponentHealthDetail(name="floor_1", state="HEALTHY"),
            "floor_2": ComponentHealthDetail(name="floor_2", state="HEALTHY"),
            "floor_3": ComponentHealthDetail(name="floor_3", state="HEALTHY"),
            "floor_4": ComponentHealthDetail(name="floor_4", state="HEALTHY"),
            "floor_5": ComponentHealthDetail(name="floor_5", state="HEALTHY"),
        },
        sides={
            "side_a": ComponentHealthDetail(name="side_a", state="HEALTHY"),
            "side_c": ComponentHealthDetail(name="side_c", state="HEALTHY"),
        },
    )

    sample_captain = CaptainDisplayState(
        mood="OBSERVER",
        decision="WAIT",
        conviction_score=0.0,
        conviction_band="REJECT",
        market_story_summary="No clear setup detected across heads.",
        reason_summary="Market in pre-open phase.",
    )

    sample_execution = ExecutionDisplayState(
        mode="ALERT",
        state="IDLE",
        capital_limit=100000.0,
    )

    sample_floor_summary = FloorSummaryDisplay(
        floor_bias="NEUTRAL",
        floor_confidence=0.45,
        active_setup_count=2,
        ready_heads=2,
        uncertain_heads=1,
        stale_heads=0,
        data_health_signal=DataHealth.GOOD,
        heads=[
            HeadReportDisplay(
                head_name="SMC",
                state="READY",
                bias="BULLISH",
                confidence=0.72,
                freshness_tag="FRESH",
                primary_setup="FVG_RETEST",
            ),
            HeadReportDisplay(
                head_name="Technical",
                state="READY",
                bias="NEUTRAL",
                confidence=0.55,
                freshness_tag="RECENT",
            ),
            HeadReportDisplay(
                head_name="ICT",
                state="UNCERTAIN",
                bias="NEUTRAL",
                confidence=0.30,
                freshness_tag="STALE",
                context_quality_score=0.42,
            ),
        ],
    )

    sample_market = MarketDataSnapshot(
        symbol="NIFTY 50",
        ltp=19500.50,
        change=125.30,
        change_percent=0.65,
        open=19400.00,
        high=19520.00,
        low=19380.00,
        prev_close=19375.20,
        volume=1250000,
        vwap=19450.75,
        session="OPEN",
    )

    sample_state = DashboardState(
        health=sample_health,
        captain=sample_captain,
        execution=sample_execution,
        floor_summary=sample_floor_summary,
        market=sample_market,
        timestamp=None,
    )

    mock_agg.get_aggregated_state.return_value = sample_state

    # get_state_snapshot returns realistic mock data for each component
    def mock_get_state_snapshot(components=None):
        if components is None:
            return {
                "floor_1": {"connection_status": "CONNECTED", "source_health": {"ltp": 19500.50}},
                "floor_2": {"data_health": "GOOD"},
                "floor_3": {"cmsp": {"key_levels": [{"price": 19500, "type": "support"}], "regime_state": {}}},
                "floor_4": {
                    "floor_summary": {
                        "floor_bias_snapshot": {"bias": "NEUTRAL"},
                        "floor_confidence_snapshot": {"confidence": 0.45},
                        "active_setup_count": 2,
                        "ready_heads_count": 2,
                        "uncertain_heads_count": 1,
                        "stale_heads_count": 0,
                    },
                    "head_reports": [
                        {"head_name": "SMC", "state": "READY", "bias": "BULLISH", "confidence": 0.72,
                         "freshness_tag": "FRESH", "primary_setup": "FVG_RETEST"},
                        {"head_name": "Technical", "state": "READY", "bias": "NEUTRAL", "confidence": 0.55,
                         "freshness_tag": "RECENT"},
                    ],
                },
                "floor_5": {
                    "captain_state": {
                        "mood": "OBSERVER",
                        "decision_state": "WAIT",
                        "conviction_band": "REJECT",
                        "market_story_summary": "No clear setup.",
                    },
                },
                "side_a": {
                    "execution_state": {
                        "mode": "ALERT",
                        "state": "IDLE",
                        "escalation_level": "NORMAL",
                    },
                },
                "side_c": {
                    "trade_history": [
                        {"trade_id": "t1", "symbol": "NIFTY", "pnl": 250.50},
                    ],
                    "decision_history": [
                        {"decision_id": "d1", "decision": "TRADE", "reason": "setup detected"},
                    ],
                    "health_events": [
                        {"event_id": "e1", "severity": "INFO", "message": "System started"},
                    ],
                },
            }
        result = {}
        for c in components:
            if c == "floor_1":
                result[c] = {"connection_status": "CONNECTED", "source_health": {"ltp": 19500.50}}
            elif c == "floor_2":
                result[c] = {"data_health": "GOOD"}
            elif c == "floor_3":
                result[c] = {"cmsp": {"key_levels": [], "regime_state": {}}, "chart_data": None}
            elif c == "floor_4":
                result[c] = {
                    "floor_summary": {"active_setup_count": 2, "ready_heads_count": 2},
                    "head_reports": [],
                }
            elif c == "floor_5":
                result[c] = {"captain_state": {"mood": "OBSERVER", "decision_state": "WAIT"}}
            elif c == "side_a":
                result[c] = {"execution_state": {"mode": "ALERT", "state": "IDLE"}}
            elif c == "side_c":
                result[c] = {
                    "trade_history": [],
                    "decision_history": [],
                    "health_events": [],
                }
            else:
                result[c] = {}
        return result

    mock_agg.get_state_snapshot.side_effect = mock_get_state_snapshot

    # Use PropertyMock for type field if needed
    # Ensure overall_status returns the enum value correctly for JSON serialization
    app.state.aggregator = mock_agg

    # Seed the cache with initial data
    integration_cache.set("control:mode", {"params": {"mode": "ALERT"}}, CacheTier.HOT)
    integration_cache.set("side_a", {"execution_state": {"mode": "ALERT", "state": "IDLE"}}, CacheTier.HOT)
    integration_cache.set("market_data", {"ltp": 19500.50, "symbol": "NIFTY"}, CacheTier.HOT)
    integration_cache.set("floor_5", {"captain_state": {"mood": "OBSERVER"}}, CacheTier.WARM)
    integration_cache.set("floor_4", {"head_reports": []}, CacheTier.WARM)

    # ── Register all route modules ──
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

    # Add built-in root endpoint
    @app.get("/")
    async def root():
        return {
            "service": "Junior Aladdin — Side B API",
            "version": "0.1.0",
            "status": "running",
        }

    return app


@pytest.fixture
def client(integration_app: FastAPI) -> TestClient:
    """TestClient for integration tests."""
    return TestClient(integration_app)


# ══════════════════════════════════════════════════════════════
#  1. Health Route Integration
# ══════════════════════════════════════════════════════════════


class TestHealthIntegration:
    """Full integration tests for /api/health routes."""

    def test_health_returns_full_snapshot(self, client):
        """GET /api/health returns all expected fields."""
        data = client.get("/api/health").json()
        assert "overall_status" in data
        assert "floors" in data
        assert "sides" in data
        assert "data_health_signal" in data
        assert "connection_status" in data
        assert "critical_alert_count" in data

    def test_health_has_all_floors(self, client):
        """Health snapshot includes all 5 floors."""
        data = client.get("/api/health").json()
        assert "floor_1" in data["floors"]
        assert "floor_2" in data["floors"]
        assert "floor_3" in data["floors"]
        assert "floor_4" in data["floors"]
        assert "floor_5" in data["floors"]

    def test_health_has_all_sides(self, client):
        """Health snapshot includes both sides."""
        data = client.get("/api/health").json()
        assert "side_a" in data["sides"]
        assert "side_c" in data["sides"]

    def test_health_data_route(self, client):
        """GET /api/health/data returns data health info."""
        data = client.get("/api/health/data").json()
        assert "data_health" in data
        assert data["data_health"] == "GOOD"

    def test_health_connections_route(self, client):
        """GET /api/health/connections returns connection status."""
        data = client.get("/api/health/connections").json()
        assert "connections" in data
        assert "overall" in data


# ══════════════════════════════════════════════════════════════
#  2. Captain Route Integration
# ══════════════════════════════════════════════════════════════


class TestCaptainIntegration:
    """Full integration tests for /api/captain routes."""

    def test_captain_state(self, client):
        """GET /api/captain/state returns all expected fields."""
        data = client.get("/api/captain/state").json()
        assert "mood" in data
        assert "decision_state" in data
        assert "conviction_band" in data
        assert "timestamp" in data
        assert data["mood"] == "OBSERVER"

    def test_captain_story(self, client):
        """GET /api/captain/story returns story summary."""
        data = client.get("/api/captain/story").json()
        assert "story_summary" in data

    def test_captain_snapshots(self, client):
        """GET /api/captain/snapshots returns a list."""
        data = client.get("/api/captain/snapshots").json()
        assert isinstance(data, list)

    def test_captain_reason(self, client):
        """GET /api/captain/reason returns reason dict."""
        data = client.get("/api/captain/reason").json()
        assert "decision" in data
        assert "reason" in data

    def test_captain_plans(self, client):
        """GET /api/captain/plans returns a list."""
        data = client.get("/api/captain/plans").json()
        assert isinstance(data, list)


# ══════════════════════════════════════════════════════════════
#  3. Head Route Integration
# ══════════════════════════════════════════════════════════════


class TestHeadsIntegration:
    """Full integration tests for /api/heads routes."""

    def test_heads_returns_floor_summary(self, client):
        """GET /api/heads returns floor_summary and heads list."""
        data = client.get("/api/heads").json()
        assert "floor_summary" in data
        assert "heads" in data
        assert isinstance(data["heads"], list)

    def test_heads_floor_summary_route(self, client):
        """GET /api/heads/floor-summary returns summary."""
        data = client.get("/api/heads/floor-summary").json()
        assert "floor_bias" in data
        assert "floor_confidence" in data
        assert "active_setup_count" in data

    def test_heads_health_route(self, client):
        """GET /api/heads/health returns per-head health."""
        data = client.get("/api/heads/health").json()
        assert "heads" in data


# ══════════════════════════════════════════════════════════════
#  4. Execution Route Integration
# ══════════════════════════════════════════════════════════════


class TestExecutionIntegration:
    """Full integration tests for /api/execution routes."""

    def test_execution_state(self, client):
        """GET /api/execution/state returns all fields."""
        data = client.get("/api/execution/state").json()
        assert "mode" in data
        assert "state" in data
        assert "escalation_level" in data
        assert "capital_limit" in data
        assert "timestamp" in data

    def test_execution_position(self, client):
        """GET /api/execution/position returns position info."""
        data = client.get("/api/execution/position").json()
        assert "active" in data

    def test_execution_orders(self, client):
        """GET /api/execution/orders returns orders list."""
        data = client.get("/api/execution/orders").json()
        assert "orders" in data
        assert "count" in data

    def test_execution_blocked(self, client):
        """GET /api/execution/blocked returns blocked actions."""
        data = client.get("/api/execution/blocked").json()
        assert "blocked_actions" in data


# ══════════════════════════════════════════════════════════════
#  5. Market Route Integration
# ══════════════════════════════════════════════════════════════


class TestMarketIntegration:
    """Full integration tests for /api/market routes."""

    def test_market_snapshot(self, client):
        """GET /api/market/snapshot returns full market data."""
        data = client.get("/api/market/snapshot").json()
        assert "symbol" in data
        assert "ltp" in data
        assert "change" in data
        assert "volume" in data
        assert "session" in data
        assert data["symbol"] == "NIFTY 50"

    def test_market_chart(self, client):
        """GET /api/market/chart returns chart data structure."""
        data = client.get("/api/market/chart").json()
        assert "chart" in data
        assert "key_levels" in data

    def test_market_session(self, client):
        """GET /api/market/session returns session data."""
        data = client.get("/api/market/session").json()
        assert "session_state" in data
        assert "regime_state" in data


# ══════════════════════════════════════════════════════════════
#  6. Memory Route Integration
# ══════════════════════════════════════════════════════════════


class TestMemoryIntegration:
    """Full integration tests for /api/memory routes."""

    def test_memory_trades(self, client):
        """GET /api/memory/trades returns trade history."""
        data = client.get("/api/memory/trades").json()
        assert "trades" in data
        assert "count" in data
        assert data["source"] == "read_model"

    def test_memory_decisions(self, client):
        """GET /api/memory/decisions returns decision history."""
        data = client.get("/api/memory/decisions").json()
        assert "decisions" in data
        assert "count" in data

    def test_memory_events(self, client):
        """GET /api/memory/events returns health events."""
        data = client.get("/api/memory/events").json()
        assert "events" in data

    def test_memory_alerts(self, client):
        """GET /api/memory/alerts returns filtered alerts."""
        data = client.get("/api/memory/alerts").json()
        assert "alerts" in data


# ══════════════════════════════════════════════════════════════
#  7. Replay Route Integration
# ══════════════════════════════════════════════════════════════


class TestReplayIntegration:
    """Full integration tests for /api/replay routes."""

    def test_replay_sessions(self, client):
        """GET /api/replay/sessions returns sessions list."""
        data = client.get("/api/replay/sessions").json()
        assert "sessions" in data
        assert "count" in data

    def test_replay_state(self, client):
        """GET /api/replay/state returns replay state."""
        data = client.get("/api/replay/state").json()
        assert "active" in data
        assert "status" in data
        assert "read_only" in data
        assert data["read_only"] is True

    def test_replay_start_stop_flow(self, client):
        """POST /api/replay/start → POST /api/replay/stop works end-to-end."""
        start = client.post("/api/replay/start", json={"speed": 1.0}).json()
        assert start["status"] == "PLAYING"
        assert start["read_only"] is True

        state = client.get("/api/replay/state").json()
        assert state["active"] is True

        stop = client.post("/api/replay/stop", json={}).json()
        assert stop["status"] == "STOPPED"
        assert stop["was_active"] is True

    def test_replay_speed_validation(self, client):
        """Invalid replay speed returns 400."""
        resp = client.post("/api/replay/speed", json={"speed": 7.0})
        assert resp.status_code == 400

    def test_replay_data_when_inactive(self, client):
        """GET /api/replay/data returns empty when inactive."""
        client.post("/api/replay/stop", json={})  # ensure stopped
        data = client.get("/api/replay/data").json()
        assert data["active"] is False


# ══════════════════════════════════════════════════════════════
#  8. Alert Route Integration
# ══════════════════════════════════════════════════════════════


class TestAlertIntegration:
    """Full integration tests for /api/alerts routes."""

    def test_active_alerts(self, client):
        """GET /api/alerts returns active alerts list."""
        data = client.get("/api/alerts").json()
        assert "alerts" in data
        assert "count" in data

    def test_alert_settings(self, client):
        """GET /api/alerts/settings returns settings."""
        data = client.get("/api/alerts/settings").json()
        assert "severity_thresholds" in data
        assert "categories_enabled" in data


# ══════════════════════════════════════════════════════════════
#  9. Control Route Integration
# ══════════════════════════════════════════════════════════════


class TestControlIntegration:
    """Full integration tests for /api/control routes."""

    def test_control_mode(self, client, integration_cache):
        """POST /api/control/mode caches the command and returns ACK."""
        resp = client.post("/api/control/mode", json={"mode": "PAPER", "reason": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["read_only"] is False

        # Verify it was cached
        cmd = integration_cache.get("control:mode")
        assert cmd is not None
        assert cmd["params"]["mode"] == "PAPER"

    def test_control_capital(self, client, integration_cache):
        """POST /api/control/capital caches capital limit."""
        resp = client.post("/api/control/capital", json={"capital_limit": 50000, "reason": "test"})
        assert resp.status_code == 200

        cmd = integration_cache.get("control:capital")
        assert cmd is not None
        assert cmd["params"]["capital_limit"] == 50000.0

    def test_control_kill_switch(self, client, integration_cache):
        """POST /api/control/kill-switch caches kill switch state."""
        resp = client.post("/api/control/kill-switch", json={"state": "SOFT", "reason": "test"})
        assert resp.status_code == 200

        cmd = integration_cache.get("control:kill_switch")
        assert cmd is not None
        assert cmd["params"]["state"] == "SOFT"

    def test_control_override(self, client, integration_cache):
        """POST /api/control/override caches override confirmation."""
        resp = client.post("/api/control/override", json={
            "override_confirmation": True,
            "reason": "manual override for test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"

        cmd = integration_cache.get("control:override")
        assert cmd is not None

    def test_control_reconnect(self, client, integration_cache):
        """POST /api/control/reconnect caches reconnect request."""
        resp = client.post("/api/control/reconnect", json={
            "target": "primary",
            "reason": "connection test",
        })
        assert resp.status_code == 200

        cmd = integration_cache.get("control:reconnect")
        assert cmd is not None
        assert cmd["params"]["target_broker"] == "primary"

    def test_control_account_reset(self, client, integration_cache):
        """POST /api/control/account/reset caches reset command."""
        resp = client.post("/api/control/account/reset", json={
            "confirm": True,
            "new_balance": 200000,
            "reason": "reset for test",
        })
        assert resp.status_code == 200

        cmd = integration_cache.get("control:account_reset")
        assert cmd is not None
        assert cmd["params"]["new_balance"] == 200000.0


# ══════════════════════════════════════════════════════════════
#  10. Dashboard Integration
# ══════════════════════════════════════════════════════════════


class TestDashboardIntegration:
    """Verify dashboard HTML references and structure."""

    def test_dashboard_index_has_all_sections(self):
        """index.html has all required UI sections."""
        html_path = DASHBOARD_DIR / "index.html"
        assert html_path.exists()
        with open(html_path, encoding="utf-8") as f:
            html = f.read()

        # Core structural elements
        assert 'id="app"' in html
        assert 'id="sidebar"' in html
        assert 'id="workspace-container"' in html
        assert 'id="right-panel"' in html
        assert 'id="top-bar"' in html
        assert 'id="bottom-bar"' in html
        assert 'id="loading-overlay"' in html
        assert 'id="error-overlay"' in html

    def test_dashboard_css_has_required_classes(self):
        """main.css has all required component classes."""
        css_path = DASHBOARD_DIR / "assets" / "css" / "main.css"
        assert css_path.exists()
        with open(css_path, encoding="utf-8") as f:
            css = f.read()

        # Critical layout classes
        assert ".app-shell" in css
        assert ".sidebar" in css
        assert ".workspace-container" in css
        assert ".panel-card" in css
        assert ".top-bar" in css
        assert ".bottom-bar" in css

        # Key component classes
        assert ".health-dot" in css
        assert ".status-tag" in css
        assert ".control-btn" in css
        assert ".skeleton" in css or ".skeleton-loading" in css

        # Animation keyframes
        assert "@keyframes" in css

        # Responsive breakpoint
        assert "@media" in css

    def test_dashboard_scripts_load_in_order(self):
        """Script loading order in index.html is correct."""
        html_path = DASHBOARD_DIR / "index.html"
        with open(html_path, encoding="utf-8") as f:
            html = f.read()

        # Find all script src attributes
        scripts = re.findall(r'<script src="([^"]+)', html)

        # Utils should load first
        utils_idx = next((i for i, s in enumerate(scripts) if "utils" in s), None)
        app_idx = next((i for i, s in enumerate(scripts) if "app.js" in s), None)

        if utils_idx is not None and app_idx is not None:
            assert utils_idx < app_idx, "Utils must load before app.js"

        # Workspace files should load before app.js
        workspace_idx = next((i for i, s in enumerate(scripts) if "workspace" in s), None)
        if workspace_idx is not None and app_idx is not None:
            assert workspace_idx < app_idx, "Workspace files must load before app.js"

        # External lightweight-charts should load first
        external_idx = next((i for i, s in enumerate(scripts) if "http" in s), None)
        if external_idx is not None and utils_idx is not None:
            assert external_idx < utils_idx, "External scripts must load first"


# ══════════════════════════════════════════════════════════════
#  11. Cache ↔ API Integration
# ══════════════════════════════════════════════════════════════


class TestCacheAPIInteration:
    """Verify cache-backed endpoints return correct data."""

    def test_get_execution_reads_from_cache(self, client, integration_cache):
        """Execution state reads mode from control cache."""
        # Set a custom mode in cache
        integration_cache.set("control:mode", {"params": {"mode": "REAL"}}, CacheTier.HOT)
        data = client.get("/api/execution/state").json()
        assert data["mode"] == "REAL"

    def test_cache_control_flow(self, client, integration_cache):
        """POST control command → cache reflects change → GET reflects it."""
        # Initial state
        data = client.get("/api/execution/state").json()
        assert data["mode"] in ("ALERT", "PAPER", "REAL")

        # Send command
        client.post("/api/control/mode", json={"mode": "PAPER", "reason": "integration test"})

        # Now GET should reflect the new mode from cache
        data = client.get("/api/execution/state").json()
        assert data["mode"] == "PAPER"


# ══════════════════════════════════════════════════════════════
#  12. Response Structure Consistency
# ══════════════════════════════════════════════════════════════


class TestResponseConsistency:
    """Verify all API responses have consistent structure."""

    def test_all_responses_have_timestamp(self, client):
        """Every endpoint with a data response includes a timestamp."""
        endpoints = [
            "/api/health",
            "/api/captain/state",
            "/api/heads",
            "/api/execution/state",
            "/api/market/snapshot",
            "/api/memory/trades",
            "/api/alerts",
            "/api/replay/state",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 200, f"{ep} returned {resp.status_code}"
            data = resp.json()
            # Some responses might be lists (captain/snapshots)
            if isinstance(data, dict):
                assert "timestamp" in data or "status" in data, f"{ep} missing timestamp/status"

    def test_error_responses_have_detail(self, client):
        """Error responses use 'detail' key (FastAPI convention)."""
        # Invalid control command
        resp = client.post("/api/control/mode", json={"mode": "INVALID"})
        assert resp.status_code == 400
        assert "detail" in resp.json()

        # Missing required body fields
        resp = client.post("/api/control/capital", json={})
        assert resp.status_code in (400, 422)
