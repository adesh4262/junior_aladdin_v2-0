"""Tests: Cross-module contract alignment for Side A.

Validates that inputs/outputs across all 18 Side A modules match
expected contracts — no broken public interfaces, no missing methods,
no execution logic imported from other domains.
"""

from __future__ import annotations

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
    KillSwitch,
    BlockedActionJournal,
    ExecutionLoggingLayer,
    PaperBroker,
    RealBroker,
    DataHealthPolicy,
)


class TestSideAExports:
    """All 18 modules are properly exportable from side_a_execution."""

    def test_all_modules_importable(self) -> None:
        assert ExecutionOrchestrator is not None
        assert CaptainInterface is not None
        assert ModeRouter is not None
        assert RiskGate is not None
        assert ExecutionCore is not None
        assert ExecutionStateMachine is not None
        assert OrderLifecycleManager is not None
        assert PositionManager is not None
        assert ProtectionModel is not None
        assert ReconciliationEngine is not None
        assert IntentFingerprintStore is not None
        assert KillSwitch is not None
        assert BlockedActionJournal is not None
        assert ExecutionLoggingLayer is not None
        assert PaperBroker is not None
        assert RealBroker is not None
        assert DataHealthPolicy is not None

    def test_no_floor3_imports(self) -> None:
        """Side A must NOT import from Floor 3 calculation engines."""
        import junior_aladdin.side_a_execution as sae
        sae_dir = dir(sae)
        floor3_names = {"ict", "smc", "market_structure", "technical", "options", "macro"}
        imports = {x.lower() for x in sae_dir}
        overlap = floor3_names & imports
        assert not overlap, f"Side A imports from Floor 3: {overlap}"


class TestBrokerContract:
    """PaperBroker and RealBroker share the same brokerage interface."""

    def test_paper_broker_has_place_order(self) -> None:
        assert hasattr(PaperBroker, "place_order")

    def test_paper_broker_has_cancel_order(self) -> None:
        assert hasattr(PaperBroker, "cancel_order")

    def test_paper_broker_has_get_order_status(self) -> None:
        assert hasattr(PaperBroker, "get_order_status")

    def test_real_broker_has_place_order(self) -> None:
        assert hasattr(RealBroker, "place_order")

    def test_real_broker_has_cancel_order(self) -> None:
        assert hasattr(RealBroker, "cancel_order")

    def test_real_broker_has_get_order_status(self) -> None:
        assert hasattr(RealBroker, "get_order_status")


class TestKillSwitchContract:
    """KillSwitch exports the expected public API."""

    def test_kill_switch_methods(self) -> None:
        ks = KillSwitch()
        assert hasattr(ks, "activate_soft")
        assert hasattr(ks, "activate_critical")
        assert hasattr(ks, "deactivate")
        assert hasattr(ks, "get_active_switch")
        assert hasattr(ks, "is_entry_blocked")
        assert hasattr(ks, "is_flatten_active")
        assert hasattr(ks, "get_reason")


class TestBlockedJournalContract:
    """BlockedActionJournal exports the expected public API."""

    def test_journal_methods(self) -> None:
        j = BlockedActionJournal()
        assert hasattr(j, "record")
        assert hasattr(j, "record_block")
        assert hasattr(j, "get_by_trade")
        assert hasattr(j, "get_by_severity")
        assert hasattr(j, "get_recent")
        assert hasattr(j, "get_session_blocks")
        assert hasattr(j, "count_by_severity")
        assert hasattr(j, "get_metrics_summary")


class TestOrchestratorContract:
    """ExecutionOrchestrator exports the expected public API."""

    def test_orchestrator_methods(self) -> None:
        assert hasattr(ExecutionOrchestrator, "receive_decision")
        assert hasattr(ExecutionOrchestrator, "handle_fill")
        assert hasattr(ExecutionOrchestrator, "handle_rejection")
        assert hasattr(ExecutionOrchestrator, "handle_acknowledgement")
        assert hasattr(ExecutionOrchestrator, "trigger_emergency")
        assert hasattr(ExecutionOrchestrator, "get_state")
        assert hasattr(ExecutionOrchestrator, "trigger_exit")
        assert hasattr(ExecutionOrchestrator, "process_override")
        assert hasattr(ExecutionOrchestrator, "check_eod_close")
        assert hasattr(ExecutionOrchestrator, "periodic_reconcile")
        assert hasattr(ExecutionOrchestrator, "set_execution_mode")
        assert hasattr(ExecutionOrchestrator, "activate_kill_switch")
