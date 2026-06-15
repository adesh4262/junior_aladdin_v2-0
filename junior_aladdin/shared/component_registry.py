"""Junior Aladdin — Shared Component Registry.

SINGLE FACTORY that creates and caches ALL subsystem instances.
Every floor/side imports from HERE instead of creating fresh instances.

Why this exists (BRUTAL_DEEP_SCAN FINDING #2):
    Side B's data_sources/*.py were doing:
        try:
            orchestrator = ExecutionOrchestrator()  # ← 11 required args!
        except Exception:
            pass  # ← silently swallowed TypeError!

    This meant Dashboard always got empty defaults (0.0, "", IDLE).

Solution:
    ComponentRegistry creates instances ONCE with all dependencies injected,
    then shares them across ALL consumers (SystemRunner, Side B data sources,
    Side C memory, etc.).

Usage:
    from junior_aladdin.shared.component_registry import get_registry

    registry = get_registry()
    
    # Get shared instances
    engine = registry.get_captain_engine()
    orchestrator = registry.get_orchestrator()
    auth = registry.get_auth_manager()
    health = registry.get_source_health_monitor()
    router = registry.get_ingress_router()
    broker = registry.get_broker()
    
    # Dashboard data access
    from junior_aladdin.shared.component_registry import get_registry
    state = get_registry().get_orchestrator().get_state()
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from junior_aladdin.shared.system_config import get_system_config

log = logging.getLogger(__name__)


# =============================================================================
# Specialised sub-registry for Captain Engine
# =============================================================================


class _CaptainRegistry:
    """Factory + cache for Captain Engine and its sub-engines.

    CaptainEngine.__init__() creates 16+ sub-engines internally when called
    with no args.  This registry ensures we only create them ONCE and
    share the instance across SystemRunner and Side B data sources.
    """

    def __init__(self) -> None:
        self._engine: Any = None

    def get_engine(self) -> Any:
        """Get the shared CaptainEngine singleton (lazy-created)."""
        if self._engine is None:
            from junior_aladdin.floor_5_captain.captain_engine import CaptainEngine
            self._engine = CaptainEngine()
            log.info("CaptainEngine created (singleton)")
        return self._engine

    def get_armed_plan_engine(self) -> Any:
        """Get ArmedPlanEngine from the CaptainEngine instance."""
        engine = self.get_engine()
        return engine.armed_plan_engine

    def get_snapshot_writer(self) -> Any:
        """Get DecisionSnapshotWriter from CaptainEngine."""
        engine = self.get_engine()
        return engine.snapshot_writer

    def get_active_trade_supervisor(self) -> Any:
        """Get ActiveTradeSupervisor from CaptainEngine."""
        engine = self.get_engine()
        return engine.active_trade_supervisor

    def get_setup_memory(self) -> Any:
        """Get SetupMemoryStore from CaptainEngine."""
        engine = self.get_engine()
        return engine.setup_memory


# =============================================================================
# Specialised sub-registry for Side A (Execution) Orchestrator
# =============================================================================


class _ExecutionRegistry:
    """Factory + cache for ExecutionOrchestrator and ALL its 11+ dependencies.

    ExecutionOrchestrator.__init__() requires:
        - captain_interface: CaptainInterface
        - mode_router: ModeRouter
        - risk_gate: RiskGate
        - state_machine: ExecutionStateMachine
        - execution_core: ExecutionCore (with injected broker)
        - order_lifecycle_manager: OrderLifecycleManager
        - position_manager: PositionManager
        - protection_model: ProtectionModel
        - reconciliation_engine: ReconciliationEngine
        - intent_fingerprint_store: IntentFingerprintStore
        - broker: BrokerProtocol
        - data_health_policy: DataHealthPolicy (optional)
        - kill_switch: KillSwitch (optional)
        - blocked_journal: BlockedActionJournal (optional)
        - on_log_callback (optional)

    This registry creates all of these ONCE with proper wiring.
    """

    def __init__(self, captain_engine: Any) -> None:
        self._captain_engine = captain_engine
        self._orchestrator: Any = None
        self._paper_broker: Any = None
        self._real_broker: Any = None
        self._execution_core: Any = None
        self._fingerprint_store: Any = None
        self._mode_router: Any = None

    def get_broker(self) -> Any:
        """Get a paper broker instance (default for testing/paper mode).

        Creates a PaperBroker if not yet created.
        """
        if self._paper_broker is None:
            from junior_aladdin.side_a_execution.paper_broker import PaperBroker
            self._paper_broker = PaperBroker()
            log.info("PaperBroker created (singleton)")
        return self._paper_broker

    def get_real_broker(self) -> Any:
        """Get a real broker instance (for REAL mode).

        Requires Angel One credentials from SystemConfig.
        Creates a RealBroker if not yet created.
        Returns None if credentials are missing.
        """
        if self._real_broker is None:
            try:
                from junior_aladdin.side_a_execution.real_broker import RealBroker
                config = get_system_config()
                creds = config.get_angel_one_credentials()
                if creds["client_id"] and creds["api_key"]:
                    self._real_broker = RealBroker(
                        client_id=creds["client_id"],
                        api_key=creds["api_key"],
                    )
                    log.info("RealBroker created (singleton)")
                else:
                    log.warning("Cannot create RealBroker — missing Angel One credentials")
                    return None
            except ImportError:
                log.warning("RealBroker not available (smartapi SDK missing)")
                return None
        return self._real_broker

    def get_mode_router(self) -> Any:
        """Get shared ModeRouter (cached)."""
        if self._mode_router is None:
            from junior_aladdin.side_a_execution.mode_router import ModeRouter
            self._mode_router = ModeRouter()
        return self._mode_router

    def get_risk_gate(self) -> Any:
        """Get shared RiskGate with dependencies injected."""
        from junior_aladdin.side_a_execution.risk_gate import RiskGate
        return RiskGate(
            intent_fingerprint_store=self.get_intent_fingerprint_store(),
        )

    def get_state_machine(self) -> Any:
        """Get shared ExecutionStateMachine."""
        from junior_aladdin.side_a_execution.execution_state_machine import (
            ExecutionStateMachine,
        )
        return ExecutionStateMachine()

    def get_order_lifecycle_manager(self) -> Any:
        """Get shared OrderLifecycleManager."""
        from junior_aladdin.side_a_execution.order_lifecycle_manager import (
            OrderLifecycleManager,
        )
        return OrderLifecycleManager()

    def get_position_manager(self) -> Any:
        """Get shared PositionManager."""
        from junior_aladdin.side_a_execution.position_manager import PositionManager
        return PositionManager()

    def get_protection_model(self) -> Any:
        """Get shared ProtectionModel with dependencies injected."""
        from junior_aladdin.side_a_execution.protection_model import ProtectionModel
        return ProtectionModel(
            order_lifecycle_manager=self.get_order_lifecycle_manager(),
            position_manager=self.get_position_manager(),
        )

    def get_reconciliation_engine(self) -> Any:
        """Get shared ReconciliationEngine with dependencies injected."""
        from junior_aladdin.side_a_execution.reconciliation_engine import (
            ReconciliationEngine,
        )
        return ReconciliationEngine(
            position_manager=self.get_position_manager(),
            order_lifecycle_manager=self.get_order_lifecycle_manager(),
        )

    def get_intent_fingerprint_store(self) -> Any:
        """Get shared IntentFingerprintStore (cached)."""
        if self._fingerprint_store is None:
            from junior_aladdin.side_a_execution.intent_fingerprint import (
                IntentFingerprintStore,
            )
            self._fingerprint_store = IntentFingerprintStore()
        return self._fingerprint_store

    def get_captain_interface(self) -> Any:
        """Get shared CaptainInterface."""
        from junior_aladdin.side_a_execution.captain_interface import (
            CaptainInterface,
        )
        return CaptainInterface()

    def get_data_health_policy(self) -> Any:
        """Get shared DataHealthPolicy."""
        from junior_aladdin.side_a_execution.data_health_policy import (
            DataHealthPolicy,
        )
        return DataHealthPolicy()

    def get_kill_switch(self) -> Any:
        """Get shared KillSwitch."""
        from junior_aladdin.side_a_execution.kill_switch import KillSwitch
        return KillSwitch()

    def get_blocked_journal(self) -> Any:
        """Get shared BlockedActionJournal."""
        from junior_aladdin.side_a_execution.blocked_action_journal import (
            BlockedActionJournal,
        )
        return BlockedActionJournal()

    def get_execution_core(self, state_machine: Any | None = None) -> Any:
        """Get shared ExecutionCore with broker + state_machine injected (cached).

        Uses PaperBroker by default (REAL broker swapped by SystemRunner).

        Args:
            state_machine: Optional ExecutionStateMachine. If not provided,
                uses the shared instance from get_state_machine().
        """
        if self._execution_core is None:
            from junior_aladdin.side_a_execution.execution_core import ExecutionCore
            sm = state_machine or self.get_state_machine()
            self._execution_core = ExecutionCore(
                broker=self.get_broker(),
                state_machine=sm,
            )
        return self._execution_core

    def get_orchestrator(self) -> Any:
        """Get the shared ExecutionOrchestrator singleton (lazy-created).

        Creates ALL 11+ dependencies and injects them.
        This is the fix for BRUTAL_DEEP_SCAN FINDING #2 — no more
        ``try: ExecutionOrchestrator()`` with zero args!
        """
        if self._orchestrator is None:
            from junior_aladdin.side_a_execution.execution_orchestrator import (
                ExecutionOrchestrator,
            )

            state_machine = self.get_state_machine()

            self._orchestrator = ExecutionOrchestrator(
                captain_interface=self.get_captain_interface(),
                mode_router=self.get_mode_router(),
                risk_gate=self.get_risk_gate(),
                state_machine=state_machine,
                execution_core=self.get_execution_core(state_machine),
                order_lifecycle_manager=self.get_order_lifecycle_manager(),
                position_manager=self.get_position_manager(),
                protection_model=self.get_protection_model(),
                reconciliation_engine=self.get_reconciliation_engine(),
                intent_fingerprint_store=self.get_intent_fingerprint_store(),
                broker=self.get_broker(),
                data_health_policy=self.get_data_health_policy(),
                kill_switch=self.get_kill_switch(),
                blocked_journal=self.get_blocked_journal(),
            )
            log.info("ExecutionOrchestrator created (singleton) — all 11+ deps injected")
        return self._orchestrator

    def switch_broker(self, broker_type: str) -> bool:
        """Switch the broker in ExecutionCore (paper → real or vice versa).

        Called by SystemRunner when mode changes between PAPER and REAL.

        Args:
            broker_type: "paper" or "real"

        Returns:
            True if broker was switched, False if not possible.
        """
        orchestrator = self.get_orchestrator()
        if broker_type == "real":
            real_broker = self.get_real_broker()
            if real_broker is None:
                return False
            # ExecutionCore has set_broker() method
            if hasattr(orchestrator._execution_core, "set_broker"):
                orchestrator._execution_core.set_broker(real_broker)
                log.info("Switched to REAL broker")
                return True
        else:
            paper_broker = self.get_broker()
            if hasattr(orchestrator._execution_core, "set_broker"):
                orchestrator._execution_core.set_broker(paper_broker)
                log.info("Switched to PAPER broker")
                return True
        return False


# =============================================================================
# Specialised sub-registry for Floor 1 (Connection)
# =============================================================================


class _Floor1Registry:
    """Factory + cache for Floor 1 connection components."""

    def __init__(self) -> None:
        self._auth_manager: Any = None
        self._source_health_monitor: Any = None
        self._ingress_router: Any = None
        self._angel_one_adapter: Any = None

    def get_auth_manager(self) -> Any:
        """Get shared AuthManager (lazy-created)."""
        if self._auth_manager is None:
            from junior_aladdin.floor_1_connection.auth_manager import AuthManager
            self._auth_manager = AuthManager()
            log.info("AuthManager created (singleton)")
        return self._auth_manager

    def get_source_health_monitor(self) -> Any:
        """Get shared SourceHealthMonitor (lazy-created).

        Uses a fixed connection ID "angel_one".
        """
        if self._source_health_monitor is None:
            from junior_aladdin.floor_1_connection.source_health import (
                SourceHealthMonitor,
            )
            self._source_health_monitor = SourceHealthMonitor(connection_id="angel_one")
            log.info("SourceHealthMonitor created (singleton)")
        return self._source_health_monitor

    def get_angel_one_adapter(self) -> Any:
        """Get shared AngelOneAdapter with auth_manager + health_monitor injected."""
        if self._angel_one_adapter is None:
            from junior_aladdin.floor_1_connection.source_adapters import (
                AngelOneAdapter,
            )
            self._angel_one_adapter = AngelOneAdapter(
                auth_manager=self.get_auth_manager(),
                health_monitor=self.get_source_health_monitor(),
            )
            log.info("AngelOneAdapter created (singleton)")
        return self._angel_one_adapter

    def get_ingress_router(self) -> Any:
        """Get shared IngressRouter with all adapters wired (lazy-created).

        Source adapters:
            - angel_one: AngelOneAdapter (for live WebSocket ticks)
            - manual: ManualSourceAdapter (for manual ingress)

        Feed adapters:
            - spot_tick: SpotFeedAdapter
            - options_snapshot: OptionsFeedAdapter
            - vix_tick: VixFeedAdapter
            - macro_data: MacroFeedAdapter (stub)
            - calendar_event: CalendarFeedAdapter (stub)
        """
        if self._ingress_router is None:
            from junior_aladdin.floor_1_connection.ingress_router import IngressRouter
            from junior_aladdin.floor_1_connection.source_adapters import (
                ManualSourceAdapter,
            )
            from junior_aladdin.floor_1_connection.feed_adapters import (
                CalendarFeedAdapter,
                MacroFeedAdapter,
                OptionsFeedAdapter,
                SpotFeedAdapter,
                VixFeedAdapter,
            )

            angel_one = self.get_angel_one_adapter()

            self._ingress_router = IngressRouter(
                source_adapters={
                    "angel_one": angel_one,
                    "manual": ManualSourceAdapter(),
                },
                feed_adapters={
                    "spot_tick": SpotFeedAdapter(),
                    "options_snapshot": OptionsFeedAdapter(),
                    "vix_tick": VixFeedAdapter(),
                    "macro_data": MacroFeedAdapter(),
                    "calendar_event": CalendarFeedAdapter(),
                },
            )
            log.info("IngressRouter created with AngelOneAdapter + all feed adapters wired")
        return self._ingress_router


# =============================================================================
# Specialised sub-registry for Floor 4 (Heads)
# =============================================================================


class _Floor4Registry:
    """Factory + cache for Floor 4 (Department Heads) components."""

    def __init__(self) -> None:
        self._floor_summary_builder: Any = None

    def get_floor_summary_builder(self) -> Any:
        """Get shared FloorSummaryBuilder (lazy-created)."""
        if self._floor_summary_builder is None:
            from junior_aladdin.floor_4_heads.floor_summary_builder import (
                FloorSummaryBuilder,
            )
            self._floor_summary_builder = FloorSummaryBuilder()
            log.info("FloorSummaryBuilder created (singleton)")
        return self._floor_summary_builder


# =============================================================================
# Specialised sub-registry for Floor 3 (Calculation Engines)
# =============================================================================


class _Floor3Registry:
    """Factory + cache for Floor 3 calculation engine orchestrator."""

    def __init__(self) -> None:
        self._orchestrator: Any = None

    def get_orchestrator(self) -> Any:
        """Get shared F3Orchestrator singleton."""
        if self._orchestrator is None:
            from junior_aladdin.floor_3_calculations.f3_orchestrator import (
                handle_calculation_cycle,
            )
            self._orchestrator = handle_calculation_cycle
            log.info("F3Orchestrator registered (singleton)")
        return self._orchestrator


# =============================================================================
# Top-level ComponentRegistry
# =============================================================================


class ComponentRegistry:
    """Top-level registry that initialises and serves ALL subsystem singletons.

    Usage:
        from junior_aladdin.shared.component_registry import get_registry

        registry = get_registry()

        # Execution
        orch = registry.get_orchestrator()
        broker = registry.get_broker()

        # Captain
        captain = registry.get_captain_engine()

        # Floor 1
        auth = registry.get_auth_manager()
        health = registry.get_source_health_monitor()
        router = registry.get_ingress_router()

        # Floor 4
        summary_builder = registry.get_floor_summary_builder()

        # System config
        config = registry.get_system_config()
    """

    def __init__(self) -> None:
        self._config = get_system_config()
        self._captain = _CaptainRegistry()
        self._floor1 = _Floor1Registry()
        self._floor3 = _Floor3Registry()
        self._floor4 = _Floor4Registry()

        # Execution registry depends on Captain engine (for CaptainInterface)
        captain_engine = self._captain.get_engine()
        self._execution = _ExecutionRegistry(captain_engine)

    # ── System Config ──────────────────────────────────────────────────

    def get_system_config(self) -> Any:
        """Get the shared SystemConfig singleton."""
        return self._config

    # ── Captain ────────────────────────────────────────────────────────

    def get_captain_engine(self) -> Any:
        """Get the shared CaptainEngine singleton."""
        return self._captain.get_engine()

    def get_armed_plan_engine(self) -> Any:
        """Get ArmedPlanEngine from CaptainEngine."""
        return self._captain.get_armed_plan_engine()

    def get_snapshot_writer(self) -> Any:
        """Get DecisionSnapshotWriter from CaptainEngine."""
        return self._captain.get_snapshot_writer()

    # ── Execution ──────────────────────────────────────────────────────

    def get_orchestrator(self) -> Any:
        """Get the shared ExecutionOrchestrator singleton.

        All 11+ dependencies are created and injected automatically.
        """
        return self._execution.get_orchestrator()

    def get_broker(self) -> Any:
        """Get the shared PaperBroker singleton."""
        return self._execution.get_broker()

    def get_real_broker(self) -> Any:
        """Get the shared RealBroker singleton (or None if no credentials)."""
        return self._execution.get_real_broker()

    def get_execution_registry(self) -> _ExecutionRegistry:
        """Get the execution sub-registry (for broker switching)."""
        return self._execution

    # ── Floor 1 ────────────────────────────────────────────────────────

    def get_auth_manager(self) -> Any:
        """Get the shared AuthManager singleton."""
        return self._floor1.get_auth_manager()

    def get_source_health_monitor(self) -> Any:
        """Get the shared SourceHealthMonitor singleton."""
        return self._floor1.get_source_health_monitor()

    def get_angel_one_adapter(self) -> Any:
        """Get the shared AngelOneAdapter singleton.

        This adapter has auth_manager + health_monitor injected and
        can establish the SmartAPI WebSocket for live tick data.
        """
        return self._floor1.get_angel_one_adapter()

    def get_ingress_router(self) -> Any:
        """Get the shared IngressRouter singleton."""
        return self._floor1.get_ingress_router()

    # ── Floor 3 ────────────────────────────────────────────────────────

    def get_f3_orchestrator(self) -> Any:
        """Get the Floor 3 calculation cycle orchestrator.

        Returns the handle_calculation_cycle function which:
        1. Accepts a CalculationInput
        2. Routes to domain engines based on market phase
        3. Returns an OutputContract with signals + Floor3Summary
        """
        return self._floor3.get_orchestrator()

    # ── Floor 4 ────────────────────────────────────────────────────────

    def get_floor_summary_builder(self) -> Any:
        """Get the shared FloorSummaryBuilder singleton."""
        return self._floor4.get_floor_summary_builder()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean up all resources.

        Called on system shutdown by SystemRunner.
        """
        log.info("ComponentRegistry shutting down ...")
        # Flush any pending state
        try:
            self._captain.get_engine()
        except Exception:
            pass
        log.info("ComponentRegistry shutdown complete")


# Module-level singleton
_registry: ComponentRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ComponentRegistry:
    """Return the module-level singleton ComponentRegistry.

    Thread-safe — uses a dedicated lock for first-time initialisation.
    """
    global _registry  # noqa: PLW0603
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ComponentRegistry()
                log.info("ComponentRegistry initialised")
    return _registry
