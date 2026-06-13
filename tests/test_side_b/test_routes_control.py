"""Pytest tests for Side B control routes.

Tests all 6 POST /api/control endpoints:
  - POST /api/control/mode           — execution mode change
  - POST /api/control/capital        — capital limit update
  - POST /api/control/kill-switch    — kill switch activation
  - POST /api/control/override       — operator override
  - POST /api/control/reconnect      — broker reconnect
  - POST /api/control/account/reset  — paper account reset

Each tests:
  - Success path (valid params → 200 + ACK)
  - Validation errors (invalid params → 400)
  - Cache interaction (command stored in cache)

Reference: ROADMAP_SIDE_B Step 8.9
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG
from junior_aladdin.side_b_api.session_cache import SessionCache


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def test_cache() -> SessionCache:
    return SessionCache(max_entries=100)


@pytest.fixture
def test_app(test_cache: SessionCache) -> FastAPI:
    """Create a test FastAPI app with control routes registered."""
    app = FastAPI(title="Test — Side B Control Routes")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.cache = test_cache
    app.state.config = DEFAULT_CONFIG
    app.state.aggregator = MagicMock()

    from junior_aladdin.side_b_api.routes.control_routes import register_routes as reg_control
    reg_control(app)

    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


# ══════════════════════════════════════════════════════════════
#  1. POST /api/control/mode
# ══════════════════════════════════════════════════════════════


class TestControlMode:
    """POST /api/control/mode — execution mode change."""

    def test_success_alert(self, client: TestClient) -> None:
        """ALERT mode returns ACK."""
        resp = client.post("/api/control/mode", json={"mode": "ALERT", "reason": "Test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["command_type"] == "request_mode"

    def test_success_paper(self, client: TestClient) -> None:
        """PAPER mode returns ACK."""
        resp = client.post("/api/control/mode", json={"mode": "PAPER"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACK"

    def test_success_real(self, client: TestClient) -> None:
        """REAL mode with reason returns ACK."""
        resp = client.post("/api/control/mode", json={"mode": "REAL", "reason": "Going live"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert "REAL" in data["message"]

    def test_invalid_mode_returns_400(self, client: TestClient) -> None:
        """Invalid mode string returns 400."""
        resp = client.post("/api/control/mode", json={"mode": "INVALID"})
        assert resp.status_code == 400

    def test_empty_mode_returns_400(self, client: TestClient) -> None:
        """Empty mode string returns 400."""
        resp = client.post("/api/control/mode", json={"mode": ""})
        assert resp.status_code == 400

    def test_mode_stored_in_cache(self, client: TestClient, test_cache: SessionCache) -> None:
        """Mode command is stored in cache under control:mode."""
        client.post("/api/control/mode", json={"mode": "PAPER", "reason": "Paper test"})
        cmd = test_cache.get("control:mode")
        assert cmd is not None
        assert cmd["params"]["mode"] == "PAPER"

    def test_response_has_expected_fields(self, client: TestClient) -> None:
        """Response has all expected fields."""
        resp = client.post("/api/control/mode", json={"mode": "ALERT"})
        data = resp.json()
        assert "command_type" in data
        assert "message" in data
        assert "owner_response" in data
        assert "timestamp" in data
        assert data["command_type"] == "request_mode"


# ══════════════════════════════════════════════════════════════
#  2. POST /api/control/capital
# ══════════════════════════════════════════════════════════════


class TestControlCapital:
    """POST /api/control/capital — capital limit update."""

    def test_success_positive_integer(self, client: TestClient) -> None:
        """Positive integer capital limit returns ACK."""
        resp = client.post("/api/control/capital", json={"capital_limit": 500000, "reason": "Setting capital"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["command_type"] == "request_capital"

    def test_success_positive_float(self, client: TestClient) -> None:
        """Float capital limit is accepted."""
        resp = client.post("/api/control/capital", json={"capital_limit": 250000.50})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACK"

    def test_missing_capital_limit_returns_400(self, client: TestClient) -> None:
        """Missing capital_limit returns 400."""
        resp = client.post("/api/control/capital", json={"reason": "test"})
        assert resp.status_code == 400

    def test_zero_capital_returns_400(self, client: TestClient) -> None:
        """Zero capital limit returns 400."""
        resp = client.post("/api/control/capital", json={"capital_limit": 0})
        assert resp.status_code == 400

    def test_negative_capital_returns_400(self, client: TestClient) -> None:
        """Negative capital limit returns 400."""
        resp = client.post("/api/control/capital", json={"capital_limit": -1000})
        assert resp.status_code == 400

    def test_capital_stored_in_cache(self, client: TestClient, test_cache: SessionCache) -> None:
        """Capital command is stored in cache under control:capital."""
        client.post("/api/control/capital", json={"capital_limit": 300000})
        cmd = test_cache.get("control:capital")
        assert cmd is not None
        assert cmd["params"]["capital_limit"] == 300000.0


# ══════════════════════════════════════════════════════════════
#  3. POST /api/control/kill-switch
# ══════════════════════════════════════════════════════════════


class TestControlKillSwitch:
    """POST /api/control/kill-switch — kill switch activation."""

    def test_success_soft_with_reason(self, client: TestClient) -> None:
        """SOFT kill switch with reason returns ACK."""
        resp = client.post("/api/control/kill-switch", json={"state": "SOFT", "reason": "Testing soft kill"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["command_type"] == "request_kill_switch"

    def test_success_critical_with_reason(self, client: TestClient) -> None:
        """CRITICAL kill switch with reason returns ACK."""
        resp = client.post("/api/control/kill-switch", json={"state": "CRITICAL", "reason": "Emergency"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACK"

    def test_success_off(self, client: TestClient) -> None:
        """OFF kill switch returns ACK (no reason required)."""
        resp = client.post("/api/control/kill-switch", json={"state": "OFF", "reason": ""})
        assert resp.status_code == 200

    def test_soft_missing_reason_returns_400(self, client: TestClient) -> None:
        """SOFT without reason returns 400."""
        resp = client.post("/api/control/kill-switch", json={"state": "SOFT", "reason": ""})
        assert resp.status_code == 400

    def test_critical_missing_reason_returns_400(self, client: TestClient) -> None:
        """CRITICAL without reason returns 400."""
        resp = client.post("/api/control/kill-switch", json={"state": "CRITICAL", "reason": "   "})
        assert resp.status_code == 400

    def test_invalid_state_returns_400(self, client: TestClient) -> None:
        """Invalid kill switch state returns 400."""
        resp = client.post("/api/control/kill-switch", json={"state": "HARD", "reason": "test"})
        assert resp.status_code == 400

    def test_kill_switch_stored_in_cache(self, client: TestClient, test_cache: SessionCache) -> None:
        """Kill switch command is stored in cache under control:kill_switch."""
        client.post("/api/control/kill-switch", json={"state": "OFF", "reason": ""})
        cmd = test_cache.get("control:kill_switch")
        assert cmd is not None
        assert cmd["params"]["state"] == "OFF"


# ══════════════════════════════════════════════════════════════
#  4. POST /api/control/override
# ══════════════════════════════════════════════════════════════


class TestControlOverride:
    """POST /api/control/override — operator override."""

    def test_success_with_reason(self, client: TestClient) -> None:
        """Override with reason returns ACK."""
        resp = client.post("/api/control/override", json={
            "override_confirmation": True,
            "reason": "Override required",
            "trade_id": "trade_123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["command_type"] == "request_override"

    def test_success_without_trade_id(self, client: TestClient) -> None:
        """Override without trade_id works."""
        resp = client.post("/api/control/override", json={
            "override_confirmation": True,
            "reason": "System override",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACK"

    def test_missing_confirmation_returns_400(self, client: TestClient) -> None:
        """Missing override_confirmation returns 400."""
        resp = client.post("/api/control/override", json={"reason": "test"})
        assert resp.status_code == 400

    def test_false_confirmation_returns_400(self, client: TestClient) -> None:
        """False override_confirmation returns 400."""
        resp = client.post("/api/control/override", json={
            "override_confirmation": False,
            "reason": "test",
        })
        assert resp.status_code == 400

    def test_empty_reason_returns_400(self, client: TestClient) -> None:
        """Empty reason returns 400."""
        resp = client.post("/api/control/override", json={
            "override_confirmation": True,
            "reason": "",
        })
        assert resp.status_code == 400

    def test_override_stored_in_cache(self, client: TestClient, test_cache: SessionCache) -> None:
        """Override command is stored in cache under control:override."""
        client.post("/api/control/override", json={
            "override_confirmation": True,
            "reason": "Cache test",
        })
        cmd = test_cache.get("control:override")
        assert cmd is not None
        assert cmd["params"]["override_confirmation"] is True


# ══════════════════════════════════════════════════════════════
#  5. POST /api/control/reconnect
# ══════════════════════════════════════════════════════════════


class TestControlReconnect:
    """POST /api/control/reconnect — broker reconnect."""

    def test_success_default_broker(self, client: TestClient) -> None:
        """Default brokerner is 'primary'."""
        resp = client.post("/api/control/reconnect", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["command_type"] == "request_reconnect"

    def test_success_custom_broker(self, client: TestClient) -> None:
        """Custom broker target works."""
        resp = client.post("/api/control/reconnect", json={
            "target": "angel_one",
            "reason": "Reconnecting",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACK"

    def test_reconnect_stored_in_cache(self, client: TestClient, test_cache: SessionCache) -> None:
        """Reconnect command is stored in cache under control:reconnect."""
        client.post("/api/control/reconnect", json={"target": "primary"})
        cmd = test_cache.get("control:reconnect")
        assert cmd is not None
        assert cmd["params"]["target_broker"] == "primary"


# ══════════════════════════════════════════════════════════════
#  6. POST /api/control/account/reset
# ══════════════════════════════════════════════════════════════


class TestControlAccountReset:
    """POST /api/control/account/reset — paper account reset."""

    def test_success_with_reason(self, client: TestClient) -> None:
        """Account reset with confirm + reason returns ACK."""
        resp = client.post("/api/control/account/reset", json={
            "confirm": True,
            "reason": "Resetting paper account",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["command_type"] == "request_account_reset"

    def test_success_custom_balance(self, client: TestClient) -> None:
        """Custom balance is accepted."""
        resp = client.post("/api/control/account/reset", json={
            "confirm": True,
            "reason": "Fresh start",
            "new_balance": 50000,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACK"

    def test_missing_confirm_returns_400(self, client: TestClient) -> None:
        """Missing confirm returns 400."""
        resp = client.post("/api/control/account/reset", json={"reason": "test"})
        assert resp.status_code == 400

    def test_false_confirm_returns_400(self, client: TestClient) -> None:
        """False confirm returns 400."""
        resp = client.post("/api/control/account/reset", json={
            "confirm": False,
            "reason": "test",
        })
        assert resp.status_code == 400

    def test_empty_reason_returns_400(self, client: TestClient) -> None:
        """Empty reason returns 400."""
        resp = client.post("/api/control/account/reset", json={
            "confirm": True,
            "reason": "",
        })
        assert resp.status_code == 400

    def test_negative_balance_returns_400(self, client: TestClient) -> None:
        """Negative balance returns 400."""
        resp = client.post("/api/control/account/reset", json={
            "confirm": True,
            "reason": "test",
            "new_balance": -1000,
        })
        assert resp.status_code == 400

    def test_account_reset_stored_in_cache(self, client: TestClient, test_cache: SessionCache) -> None:
        """Account reset command is stored in cache under control:account_reset."""
        client.post("/api/control/account/reset", json={
            "confirm": True,
            "reason": "Cache test",
        })
        cmd = test_cache.get("control:account_reset")
        assert cmd is not None
        assert cmd["params"]["new_balance"] == 100000.0


# ══════════════════════════════════════════════════════════════
#  7. Cross-Endpoint Tests
# ══════════════════════════════════════════════════════════════


class TestCrossEndpoint:
    """Verify multiple control endpoints work with the same cache."""

    def test_all_endpoints_independent(self, client: TestClient) -> None:
        """All 6 endpoints write to different cache keys."""
        r1 = client.post("/api/control/mode", json={"mode": "ALERT"})
        r2 = client.post("/api/control/capital", json={"capital_limit": 500000})
        r3 = client.post("/api/control/kill-switch", json={"state": "OFF", "reason": ""})
        r4 = client.post("/api/control/override", json={"override_confirmation": True, "reason": "test"})
        r5 = client.post("/api/control/reconnect", json={})
        r6 = client.post("/api/control/account/reset", json={"confirm": True, "reason": "test"})

        assert all(r.status_code == 200 for r in (r1, r2, r3, r4, r5, r6))
        commands = [r.json()["command_type"] for r in (r1, r2, r3, r4, r5, r6)]
        assert commands == [
            "request_mode", "request_capital", "request_kill_switch",
            "request_override", "request_reconnect", "request_account_reset",
        ]

    def test_invalid_json_returns_422(self, client: TestClient) -> None:
        """Invalid JSON body returns 422."""
        resp = client.post("/api/control/mode", json="not_a_dict")
        assert resp.status_code == 422
