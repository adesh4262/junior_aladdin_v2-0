"""Integration tests: Full Side A end-to-end paper flow.

Tests the complete execution pipeline from Captain decision to trade close
using the paper broker path: intent → risk → order → fill → protect →
manage → exit → close.

All tests use mocked modules injected into ExecutionOrchestrator.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from junior_aladdin.shared.types import (
    CaptainDecision,
    DecisionType,
    ExecutionIntent,
    ExecutionMode,
    TradeClass,
)
from junior_aladdin.side_a_execution import (
    ExecutionOrchestrator,
    CaptainInterface,
    ModeRouter,
    RiskGate,
    ExecutionCore,
    ExecutionStateMachine,
    OrderLifecycleManager,
    PositionManager,
    ProtectionModel,
    ReconciliationEngine,
    IntentFingerprintStore,
    PaperBroker,
    DataHealthPolicy,
    BlockedActionJournal,
    KillSwitch,
)
from junior_aladdin.side_a_execution.side_a_types import (
    ExecutionMajorState,
    KillSwitchState,
    RiskCheckResult,
)
from junior_aladdin.side_a_execution.mode_router import ModeRouter, RoutingResult
from junior_aladdin.side_a_execution.risk_gate import RiskGate, RiskContext
from junior_aladdin.side_a_execution.reconciliation_engine import (
    ReconciliationEngine,
    ReconcileResult,
    ReconcileOutcome,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def broker():
    return PaperBroker(random_seed=42, rejection_rate=0.0)


@pytest.fixture
def captain_interface():
    return CaptainInterface()


@pytest.fixture
def mode_router():
    return ModeRouter(initial_mode=ExecutionMode.PAPER)


@pytest.fixture
def intent_fingerprint_store():
    return IntentFingerprintStore()


@pytest.fixture
def risk_gate(intent_fingerprint_store):
    return RiskGate(intent_fingerprint_store=intent_fingerprint_store)


@pytest.fixture
def state_machine():
    return ExecutionStateMachine()


@pytest.fixture
def olm():
    return OrderLifecycleManager()


@pytest.fixture
def pm():
    return PositionManager()


@pytest.fixture
def protection_model(olm, pm):
    return ProtectionModel(order_lifecycle_manager=olm, position_manager=pm)


@pytest.fixture
def reconciliation_engine(pm, olm):
    return ReconciliationEngine(position_manager=pm, order_lifecycle_manager=olm)


@pytest.fixture
def execution_core(state_machine, broker):
    return ExecutionCore(state_machine=state_machine, broker=broker)


@pytest.fixture
def data_health_policy():
    return DataHealthPolicy()


@pytest.fixture
def kill_switch():
    return KillSwitch()


@pytest.fixture
def blocked_journal():
    return BlockedActionJournal()


@pytest.fixture
def log_events():
    events = []

    def callback(event_type, data):
        events.append((event_type, data))

    return events


@pytest.fixture
def orchestrator(
    captain_interface,
    mode_router,
    risk_gate,
    state_machine,
    execution_core,
    olm,
    pm,
    protection_model,
    reconciliation_engine,
    intent_fingerprint_store,
    broker,
    data_health_policy,
    kill_switch,
    blocked_journal,
    log_events,
):
    orch = ExecutionOrchestrator(
        captain_interface=captain_interface,
        mode_router=mode_router,
        risk_gate=risk_gate,
        state_machine=state_machine,
        execution_core=execution_core,
        order_lifecycle_manager=olm,
        position_manager=pm,
        protection_model=protection_model,
        reconciliation_engine=reconciliation_engine,
        intent_fingerprint_store=intent_fingerprint_store,
        broker=broker,
        data_health_policy=data_health_policy,
        kill_switch=kill_switch,
        blocked_journal=blocked_journal,
        on_log_callback=log_events,
    )
    return orch


def _make_decision(trade_id: str = "INT-T001") -> CaptainDecision:
    return CaptainDecision(
        decision=DecisionType.TRADE,
        action="BUY",
        option_side="CE",
        selected_strike="18500",
        trade_class=TradeClass.CONTINUATION,
        entry_plan={
            "trigger": "level_break",
            "zone": "support",
            "confirmation": "candle_close",
            "price": 150.0,
            "premium": 150.0,
        },
        invalidation_level=145.0,
        stop_loss_plan={"price": 148.0, "type": "fixed"},
        target_plan={"price": 155.0, "targets": [{"price": 155.0, "qty_pct": 100}]},
        snapshot_id=trade_id,
        reason_summary="Test trade",
    )


# =============================================================================
# Tests: Full Paper Flow
# =============================================================================


class TestFullPaperFlow:
    """Complete intent → risk → order → fill → protect → manage → exit → close."""

    def test_full_trade_lifecycle(self, orchestrator):
        """Full end-to-end: decision accepted → filled → protected → managing → exit → closed."""
        decision = _make_decision()
        result = orchestrator.receive_decision(
            decision=decision,
            system_context={"mode": ExecutionMode.PAPER},
            risk_context=RiskContext(
                available_capital=100000,
                required_capital=5000,
                max_risk_per_trade=10000,
                mode=ExecutionMode.PAPER,
            ),
        )
        assert result.accepted is True
        assert result.execution_path == "PAPER"
        assert result.order_id is not None

        # Simulate fill after broker ack
        order_id = result.order_id
        fill_data = {
            "order_id": order_id,
            "trade_id": result.trade_id,
            "filled_qty": 1,
            "price": 150.0,
            "remaining_qty": 0,
        }
        fill_result = orchestrator.handle_fill(order_id, fill_data)
        assert fill_result.handled is True
        assert fill_result.fill_data is not None
        assert fill_result.fill_data.filled_qty == 1

        # Position should be open
        pos = orchestrator._pm.get_position(result.trade_id)
        assert pos is not None
        assert pos.filled_qty == 1
        assert pos.direction == "BUY"

        # Protection should be staged
        assert orchestrator._protection_staged is True

        # Exit and close
        exit_ok = orchestrator.trigger_exit(result.trade_id, exit_price=155.0)
        assert exit_ok is True
        assert orchestrator._state_machine.state == ExecutionMajorState.CLOSED

    def test_alert_fires_for_every_intent(self, orchestrator, log_events):
        """ALERT notification fires for every decision regardless of mode."""
        decision = _make_decision(trade_id="ALERT-T001")
        result = orchestrator.receive_decision(
            decision=decision,
            system_context={"mode": ExecutionMode.PAPER},
        )
        assert result.alert_fired is True

    def test_risk_gate_blocks_insufficient_capital(self, orchestrator):
        """Risk gate blocks when capital is insufficient."""
        decision = _make_decision()
        result = orchestrator.receive_decision(
            decision=decision,
            risk_context=RiskContext(
                available_capital=100,
                required_capital=50000,
                max_risk_per_trade=1000,
                mode=ExecutionMode.PAPER,
            ),
        )
        assert result.accepted is False
        assert "Risk gate" in result.rejection_reason


class TestKillSwitchIntegration:
    """Kill switch orchestrator integration."""

    def test_soft_kill_switch_blocks_new_entries(self, orchestrator, broker):
        """SOFT kill switch: new intents blocked, existing trade continues."""
        ks = orchestrator._kill_switch
        assert ks is not None
        ks.activate_soft("Testing soft block")
        assert ks.is_entry_blocked() is True

        decision = _make_decision(trade_id="KS-001")
        result = orchestrator.receive_decision(
            decision=decision,
            system_context={"mode": ExecutionMode.PAPER},
        )
        assert result.accepted is False

    def test_critical_kill_switch_flattens(self, orchestrator):
        """CRITICAL kill switch triggers flatten."""
        ks = orchestrator._kill_switch
        assert ks is not None
        ks.activate_critical("Testing critical flatten")
        assert ks.is_flatten_active() is True

    def test_can_deactivate_kill_switch(self, orchestrator):
        """Deactivation restores normal operation."""
        ks = orchestrator._kill_switch
        assert ks is not None
        ks.activate_soft("test")
        assert ks.is_entry_blocked() is True
        ks.deactivate("done testing")
        assert ks.is_entry_blocked() is False


class TestOverrideIntegration:
    """Override pathway integration."""

    def test_override_reduce_size(self, orchestrator):
        """REDUCE_SIZE override reduces position."""
        decision = _make_decision()
        result = orchestrator.receive_decision(
            decision=decision,
            system_context={"mode": ExecutionMode.PAPER},
            risk_context=RiskContext(
                available_capital=100000,
                required_capital=5000,
                max_risk_per_trade=10000,
                mode=ExecutionMode.PAPER,
            ),
        )
        assert result.accepted is True

        # Fill first
        fill_data = {
            "order_id": result.order_id,
            "trade_id": result.trade_id,
            "filled_qty": 1,
            "price": 150.0,
            "remaining_qty": 0,
        }
        orchestrator.handle_fill(result.order_id, fill_data)

        # Override: reduce size
        result = orchestrator.process_override(
            trade_id=result.trade_id,
            override_type="REDUCE_SIZE",
            override_data={"qty": 1, "price": 155.0},
        )
        assert result["applied"] is True

    def test_override_tighten_sl(self, orchestrator):
        """TIGHTEN_SL override tightens stop-loss."""
        decision = _make_decision()
        result = orchestrator.receive_decision(
            decision=decision,
            system_context={"mode": ExecutionMode.PAPER},
            risk_context=RiskContext(
                available_capital=100000,
                required_capital=5000,
                max_risk_per_trade=10000,
                mode=ExecutionMode.PAPER,
            ),
        )
        assert result.accepted is True

        # Fill first
        fill_data = {
            "order_id": result.order_id,
            "trade_id": result.trade_id,
            "filled_qty": 1,
            "price": 150.0,
            "remaining_qty": 0,
        }
        orchestrator.handle_fill(result.order_id, fill_data)

        # Tighten SL
        result = orchestrator.process_override(
            trade_id=result.trade_id,
            override_type="TIGHTEN_SL",
            override_data={"sl_price": 149.0},
        )
        assert result["applied"] is True


class TestEODClose:
    """EOD close integration."""

    def test_eod_close_skips_when_no_trade(self, orchestrator):
        """EOD close returns SKIPPED when no active trade."""
        result = orchestrator.check_eod_close()
        assert result["closed"] is False
        assert result["reason"] == "SKIPPED"

    def test_eod_close_no_position(self, orchestrator):
        """EOD close returns SKIPPED when trade exists but no position."""
        orchestrator._current_trade_id = "GHOST"
        result = orchestrator.check_eod_close()
        assert result["closed"] is False
