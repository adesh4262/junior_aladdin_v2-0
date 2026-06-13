"""Tests for mode_router — ALERT routing, PAPER/REAL path routing, mode transition governance."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import ExecutionIntent, ExecutionMode, TradeClass
from junior_aladdin.side_a_execution.mode_router import ModeRouter, RoutingResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_intent() -> ExecutionIntent:
    """A sample ExecutionIntent for routing tests."""
    return ExecutionIntent(
        trade_id="trade_snap_001",
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
    )


@pytest.fixture
def alert_router() -> ModeRouter:
    """ModeRouter initialized in ALERT mode."""
    return ModeRouter(initial_mode=ExecutionMode.ALERT)


@pytest.fixture
def paper_router() -> ModeRouter:
    """ModeRouter initialized in PAPER mode."""
    return ModeRouter(initial_mode=ExecutionMode.PAPER)


@pytest.fixture
def real_router() -> ModeRouter:
    """ModeRouter initialized in REAL mode."""
    return ModeRouter(initial_mode=ExecutionMode.REAL)


@pytest.fixture
def no_active_trade_check() -> MagicMock:
    """A mock has_active_trade_check that returns False (no active trade)."""
    mock = MagicMock(return_value=False)
    return mock


@pytest.fixture
def active_trade_check() -> MagicMock:
    """A mock has_active_trade_check that returns True (active trade exists)."""
    mock = MagicMock(return_value=True)
    return mock


# =============================================================================
# Tests: is_alert_active
# =============================================================================


def test_is_alert_always_active() -> None:
    """is_alert_active always returns True (ALERT is always active)."""
    assert ModeRouter.is_alert_active() is True


# =============================================================================
# Tests: get_current_mode
# =============================================================================


def test_get_current_mode_alert(alert_router: ModeRouter) -> None:
    """get_current_mode returns ALERT for alert router."""
    assert alert_router.get_current_mode() == ExecutionMode.ALERT


def test_get_current_mode_paper(paper_router: ModeRouter) -> None:
    """get_current_mode returns PAPER for paper router."""
    assert paper_router.get_current_mode() == ExecutionMode.PAPER


def test_get_current_mode_real(real_router: ModeRouter) -> None:
    """get_current_mode returns REAL for real router."""
    assert real_router.get_current_mode() == ExecutionMode.REAL


# =============================================================================
# Tests: route_intent — ALERT mode
# =============================================================================


def test_route_intent_alert_fires_always(
    alert_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """ALERT always fires regardless of mode."""
    result = alert_router.route_intent(sample_intent)
    assert result.alert_fired is True
    assert "dashboard" in result.alert_targets
    assert "log" in result.alert_targets


def test_route_intent_alert_no_execution_path(
    alert_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """In ALERT mode, execution_path is NONE (no execution path)."""
    result = alert_router.route_intent(sample_intent)
    assert result.execution_path == "NONE"
    assert result.mode == ExecutionMode.ALERT


def test_route_intent_alert_returns_trade_id(
    alert_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """Routing result includes the trade ID for traceability."""
    result = alert_router.route_intent(sample_intent)
    assert result.trade_id == "trade_snap_001"


# =============================================================================
# Tests: route_intent — PAPER mode
# =============================================================================


def test_route_intent_paper_fires_alert(
    paper_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """In PAPER mode, ALERT still fires."""
    result = paper_router.route_intent(sample_intent)
    assert result.alert_fired is True


def test_route_intent_paper_execution_path(
    paper_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """In PAPER mode, execution_path is PAPER."""
    result = paper_router.route_intent(sample_intent)
    assert result.execution_path == "PAPER"
    assert result.mode == ExecutionMode.PAPER


# =============================================================================
# Tests: route_intent — REAL mode
# =============================================================================


def test_route_intent_real_fires_alert(
    real_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """In REAL mode, ALERT still fires."""
    result = real_router.route_intent(sample_intent)
    assert result.alert_fired is True


def test_route_intent_real_execution_path(
    real_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """In REAL mode, execution_path is REAL."""
    result = real_router.route_intent(sample_intent)
    assert result.execution_path == "REAL"
    assert result.mode == ExecutionMode.REAL


# =============================================================================
# Tests: route_intent — error path
# =============================================================================


def test_route_intent_none_raises(
    alert_router: ModeRouter,
) -> None:
    """Routing None intent raises ExecutionError."""
    with pytest.raises(ExecutionError, match="None"):
        alert_router.route_intent(None)  # type: ignore[arg-type]


# =============================================================================
# Tests: set_mode — no active trade
# =============================================================================


def test_set_mode_alert_to_paper(no_active_trade_check: MagicMock) -> None:
    """Switching from ALERT to PAPER when no active trade succeeds."""
    router = ModeRouter(
        initial_mode=ExecutionMode.ALERT,
        has_active_trade_check=no_active_trade_check,
    )
    assert router.set_mode(ExecutionMode.PAPER) is True
    assert router.get_current_mode() == ExecutionMode.PAPER


def test_set_mode_paper_to_real(no_active_trade_check: MagicMock) -> None:
    """Switching from PAPER to REAL when no active trade succeeds."""
    router = ModeRouter(
        initial_mode=ExecutionMode.PAPER,
        has_active_trade_check=no_active_trade_check,
    )
    assert router.set_mode(ExecutionMode.REAL) is True
    assert router.get_current_mode() == ExecutionMode.REAL


def test_set_mode_real_to_paper(no_active_trade_check: MagicMock) -> None:
    """Switching from REAL to PAPER when no active trade succeeds."""
    router = ModeRouter(
        initial_mode=ExecutionMode.REAL,
        has_active_trade_check=no_active_trade_check,
    )
    assert router.set_mode(ExecutionMode.PAPER) is True
    assert router.get_current_mode() == ExecutionMode.PAPER


def test_set_mode_same_mode_is_noop(no_active_trade_check: MagicMock) -> None:
    """Switching to the same mode returns True and doesn't change mode."""
    router = ModeRouter(
        initial_mode=ExecutionMode.PAPER,
        has_active_trade_check=no_active_trade_check,
    )
    assert router.set_mode(ExecutionMode.PAPER) is True
    assert router.get_current_mode() == ExecutionMode.PAPER
    # The callback should NOT be called for same-mode transitions
    no_active_trade_check.assert_not_called()


# =============================================================================
# Tests: set_mode — active trade blocks transition
# =============================================================================


def test_set_mode_blocked_during_active_trade(active_trade_check: MagicMock) -> None:
    """Switching mode during an active trade returns False."""
    router = ModeRouter(
        initial_mode=ExecutionMode.PAPER,
        has_active_trade_check=active_trade_check,
    )
    assert router.set_mode(ExecutionMode.REAL) is False
    # Mode should remain unchanged
    assert router.get_current_mode() == ExecutionMode.PAPER


def test_set_mode_blocked_alert_to_real(active_trade_check: MagicMock) -> None:
    """Switching from ALERT to REAL during active trade returns False."""
    router = ModeRouter(
        initial_mode=ExecutionMode.ALERT,
        has_active_trade_check=active_trade_check,
    )
    assert router.set_mode(ExecutionMode.REAL) is False
    assert router.get_current_mode() == ExecutionMode.ALERT


def test_set_mode_blocked_uses_callback(active_trade_check: MagicMock) -> None:
    """The has_active_trade_check callback is called during mode switch."""
    router = ModeRouter(
        initial_mode=ExecutionMode.PAPER,
        has_active_trade_check=active_trade_check,
    )
    assert router.set_mode(ExecutionMode.REAL) is False
    active_trade_check.assert_called_once()


# =============================================================================
# Tests: set_mode — without callback (no active trade assumed)
# =============================================================================


def test_set_mode_without_callback_allows_transition() -> None:
    """Without has_active_trade_check, mode transitions are always allowed."""
    router = ModeRouter(initial_mode=ExecutionMode.PAPER)
    assert router.set_mode(ExecutionMode.REAL) is True
    assert router.get_current_mode() == ExecutionMode.REAL


# =============================================================================
# Tests: set_mode — error path
# =============================================================================


def test_set_mode_none_raises(no_active_trade_check: MagicMock) -> None:
    """Setting mode to None raises ExecutionError (invalid arg)."""
    router = ModeRouter(
        initial_mode=ExecutionMode.ALERT,
        has_active_trade_check=no_active_trade_check,
    )
    with pytest.raises(ExecutionError, match="Invalid mode"):
        router.set_mode(None)  # type: ignore[arg-type]


def test_set_mode_invalid_type_raises(no_active_trade_check: MagicMock) -> None:
    """Setting mode to a non-ExecutionMode value raises ExecutionError."""
    router = ModeRouter(
        initial_mode=ExecutionMode.ALERT,
        has_active_trade_check=no_active_trade_check,
    )
    with pytest.raises(ExecutionError, match="Invalid mode"):
        router.set_mode("PAPER")  # type: ignore[arg-type]


# =============================================================================
# Tests: RoutingResult
# =============================================================================


def test_routing_result_defaults() -> None:
    """RoutingResult defaults to ALERT fired, no execution path."""
    result = RoutingResult()
    assert result.alert_fired is True
    assert result.execution_path == "NONE"
    assert result.mode == ExecutionMode.ALERT
    assert "dashboard" in result.alert_targets
    assert "log" in result.alert_targets


# =============================================================================
# Tests: integration-style — full routing flow
# =============================================================================


def test_routing_flow_alert(
    alert_router: ModeRouter,
    sample_intent: ExecutionIntent,
) -> None:
    """Full routing flow in ALERT mode."""
    # ALERT always active
    assert alert_router.is_alert_active() is True

    # Route intent
    result = alert_router.route_intent(sample_intent)
    assert result.alert_fired is True
    assert result.execution_path == "NONE"

    # Mode can still be queried
    assert alert_router.get_current_mode() == ExecutionMode.ALERT


def test_routing_flow_paper_then_switch(
    paper_router: ModeRouter,
    sample_intent: ExecutionIntent,
    no_active_trade_check: MagicMock,
) -> None:
    """Routing in PAPER, then switching to REAL and routing again."""
    # Route in PAPER
    result1 = paper_router.route_intent(sample_intent)
    assert result1.execution_path == "PAPER"

    # Switch to REAL
    paper_router.set_mode(ExecutionMode.REAL)

    # Route in REAL
    result2 = paper_router.route_intent(sample_intent)
    assert result2.execution_path == "REAL"

    # ALERT fires in both
    assert result1.alert_fired is True
    assert result2.alert_fired is True


# =============================================================================
# Tests: intent mode vs router mode
# =============================================================================


def test_router_ignores_intent_mode(
    sample_intent: ExecutionIntent,
) -> None:
    """Router uses its own mode, not the intent's mode field."""
    # Create intent with mode=REAL but router in PAPER
    sample_intent.mode = ExecutionMode.REAL
    router = ModeRouter(initial_mode=ExecutionMode.PAPER)

    result = router.route_intent(sample_intent)
    # Router should route to PAPER (its own mode), not REAL
    assert result.execution_path == "PAPER"
    assert result.mode == ExecutionMode.PAPER
