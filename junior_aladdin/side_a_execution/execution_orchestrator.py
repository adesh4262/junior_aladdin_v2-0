"""Side A — Execution Orchestrator: Top-level coordinator wiring all 12 modules.

The central nervous system of Side A. Wires the Captain interface, mode router,
intent fingerprint, risk gate, state machine, execution core (with injected
broker), order lifecycle manager, position manager, protection model, and
reconciliation engine into a single unified execution pipeline.

Architecture rules (LOCKED — see ROADMAP_SIDE_A):
- Side A executes, it does NOT decide
- Side A never creates trades (receives approved intent only)
- Side A never increases size (reduce-only for safety)
- Broker truth = final live authority
- ONE active live trade at a time
- ALERT always active, PAPER / REAL execution switch
- ALL state changes go through execution_state_machine
- Protection must be established as early as practical

Ownership:
- ExecutionOrchestrator = top-level coordinator / pipeline owner
- All sub-modules are injected (testable, swappable)
- Captain = rare strategic override authority
- Dashboard / Side C consume ExecutionSnapshot from get_state()

Flow:
    CaptainDecision
        → CaptainInterface.receive_intent() → ExecutionIntent
        → ModeRouter.route_intent() → ALERT fires + PAPER/REAL path
        → IntentFingerprintStore.check() → duplicate prevention
        → RiskGate.evaluate() → 12 pre-order checks
        → ExecutionStateMachine.transition(CAPTAIN_INTENT → RISK_PASSED)
        → ExecutionCore.submit_order() → broker gets order
        → ProtectionModel.stage_protection() → SL/TGT after fill
        → PositionManager tracks position
        → OrderLifecycleManager tracks order states
        → ReconciliationEngine detects/resolves mismatches
        → Broker events (fill, ack, rejection) processed through pipeline
        → ExecutionSnapshot produced for Side B/C
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import (
    CaptainDecision,
    DataHealth,
    ExecutionIntent,
    ExecutionMode,
    Severity,
)
from junior_aladdin.side_a_execution.captain_interface import CaptainInterface
from junior_aladdin.side_a_execution.data_health_policy import DataHealthPolicy
from junior_aladdin.side_a_execution.execution_core import (
    BrokerProtocol,
    ExecutionCore,
    FillData,
    OrderSubmission,
)
from junior_aladdin.side_a_execution.execution_state_machine import (
    ExecutionEvent,
    ExecutionStateMachine,
)
from junior_aladdin.side_a_execution.intent_fingerprint import (
    IntentFingerprintStore,
)
from junior_aladdin.side_a_execution.mode_router import (
    ModeRouter,
    RoutingResult,
)
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    OrderLifecycleManager,
    OrderState,
)
from junior_aladdin.side_a_execution.position_manager import PositionManager
from junior_aladdin.side_a_execution.protection_model import ProtectionModel
from junior_aladdin.side_a_execution.reconciliation_engine import (
    ReconciliationEngine,
    ReconcileResult,
)
from junior_aladdin.side_a_execution.risk_gate import (
    RiskContext,
    RiskGate,
)
from junior_aladdin.side_a_execution.blocked_action_journal import (
    BlockedActionJournal,
)
from junior_aladdin.side_a_execution.kill_switch import KillSwitch
from junior_aladdin.side_a_execution.side_a_types import (
    BlockedActionRecord,
    EscalationLevel,
    ExecutionMajorState,
    ExecutionSnapshot,
    KillSwitchState,
    OrderRecord,
    PositionState,
    ReconcileOutcome,
    RiskCheckResult,
)


# =============================================================================
# Orchestrator Result Types
# =============================================================================


@dataclass
class DecisionResult:
    """Result of processing a Captain decision through the execution pipeline.

    Fields:
        accepted: Whether the decision was accepted for execution.
        trade_id: The trade ID (if accepted).
        alert_fired: Whether the ALERT notification was sent.
        execution_path: The execution path (PAPER / REAL / NONE).
        risk_result: The RiskCheckResult from pre-order evaluation.
        routing_result: The RoutingResult from mode routing.
        order_id: The broker-assigned order ID (if order was submitted).
        rejection_reason: Why the decision was rejected (if not accepted).
        timestamp: When the decision was processed.
    """
    accepted: bool = False
    trade_id: str = ""
    alert_fired: bool = True
    execution_path: str = "NONE"
    risk_result: RiskCheckResult | None = None
    routing_result: RoutingResult | None = None
    order_id: str = ""
    rejection_reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BrokerEventResult:
    """Result of processing an incoming broker event.

    Fields:
        handled: Whether the event was handled.
        event_type: The type of broker event processed.
        trade_id: The associated trade ID.
        order_id: The associated order ID.
        new_state: Updated execution major state after event.
        fill_data: The FillData (if fill event).
        reconcile_result: The ReconcileResult (if triggered).
        error: Error message (if handling failed).
    """
    handled: bool = False
    event_type: str = ""
    trade_id: str = ""
    order_id: str = ""
    new_state: ExecutionMajorState | None = None
    fill_data: FillData | None = None
    reconcile_result: ReconcileResult | None = None
    error: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# ExecutionOrchestrator
# =============================================================================


class ExecutionOrchestrator:
    """Top-level coordinator that wires all Side A modules into a pipeline.

    Accepts Captain decisions, routes them through the execution pipeline,
    manages position lifecycle, handles broker events, and produces
    ExecutionSnapshot for downstream consumers.

    Usage::

        # Construction (modules injected)
        orchestrator = ExecutionOrchestrator(
            captain_interface=captain,
            mode_router=router,
            risk_gate=gate,
            state_machine=sm,
            execution_core=core,
            order_lifecycle_manager=olm,
            position_manager=pm,
            protection_model=pmodel,
            reconciliation_engine=recon,
            intent_fingerprint_store=fp_store,
            broker=broker_instance,
        )

        # Accept a Captain decision
        result = orchestrator.receive_decision(
            decision=cap_decision,
            system_context={"mode": ExecutionMode.PAPER, ...},
        )

        # Handle incoming broker events
        orchestrator.handle_fill(order_id="ORD001", fill_data={...})
        orchestrator.handle_acknowledgement(order_id="ORD001", ack_data={...})
        orchestrator.handle_rejection(order_id="ORD001", reason="TIMEOUT")

        # Emergency actions
        orchestrator.trigger_emergency("FLATTEN")

        # Reconciliation
        orchestrator.reconcile_trade(trade_id="TRADE-001", broker_data={...})
        orchestrator.handle_reconnect(broker_data={...})

        # Snapshot for dashboard / Side C
        snapshot = orchestrator.get_state()
    """

    def __init__(
        self,
        captain_interface: CaptainInterface,
        mode_router: ModeRouter,
        risk_gate: RiskGate,
        state_machine: ExecutionStateMachine,
        execution_core: ExecutionCore,
        order_lifecycle_manager: OrderLifecycleManager,
        position_manager: PositionManager,
        protection_model: ProtectionModel,
        reconciliation_engine: ReconciliationEngine,
        intent_fingerprint_store: IntentFingerprintStore,
        broker: BrokerProtocol,
        data_health_policy: DataHealthPolicy | None = None,
        kill_switch: KillSwitch | None = None,
        blocked_journal: BlockedActionJournal | None = None,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the ExecutionOrchestrator with injected sub-modules.

        Args:
            captain_interface: For receiving and validating Captain decisions.
            mode_router: For ALERT/PAPER/REAL routing.
            risk_gate: For 12 pre-order safety checks.
            state_machine: For execution lifecycle state transitions.
            execution_core: For broker order submission and event handling.
            order_lifecycle_manager: For order state tracking and SL/TGT linkage.
            position_manager: For position truth management.
            protection_model: For SL/TGT staging after fill.
            reconciliation_engine: For detect → resolve mismatch cycles.
            intent_fingerprint_store: For duplicate intent prevention.
            broker: Injected broker instance (paper or real).
            data_health_policy: Optional data health policy mapper.
            on_log_callback: Called for all orchestration events.
        """
        self._captain = captain_interface
        self._mode_router = mode_router
        self._risk_gate = risk_gate
        self._state_machine = state_machine
        self._execution_core = execution_core
        self._olm = order_lifecycle_manager
        self._pm = position_manager
        self._protection_model = protection_model
        self._reconciliation_engine = reconciliation_engine
        self._fingerprint_store = intent_fingerprint_store
        self._broker = broker
        self._data_health_policy = data_health_policy or DataHealthPolicy()
        self._kill_switch = kill_switch
        self._blocked_journal = blocked_journal
        self._on_log_callback = on_log_callback

        # Internal tracking (used when kill_switch/blocked_journal not injected)
        self._blocked_actions: list[BlockedActionRecord] = []
        self._current_trade_id: str | None = None
        self._current_intent: ExecutionIntent | None = None
        self._primary_order_id: str | None = None
        self._protection_staged: bool = False
        # Use injected kill_switch state if available, else internal
        self._kill_switch_state: KillSwitchState = (
            kill_switch.get_active_switch() if kill_switch else KillSwitchState.NORMAL
        )
        self._escalation_level: EscalationLevel = EscalationLevel.NORMAL
        self._last_reconcile_time: datetime = datetime.utcnow()
        self._reconcile_interval_seconds: float = 30.0  # Periodic reconcile every 30s
        self._current_data_health: DataHealth = DataHealth.GOOD  # Updated by Floor 2 signal

        # Wire up active trade check for mode router so trades block mode switches
        self._mode_router.set_has_active_trade_check(self._has_active_trade)

        # Wire up kill switch check for risk gate (check #8 — real lock state)
        if kill_switch is not None:
            self._risk_gate.set_real_locked_check(kill_switch.is_entry_blocked)
            # Wire circuit breaker to auto-activate kill switch on consecutive failures
            self._execution_core.set_circuit_breaker_callback(
                lambda data: kill_switch.activate_soft(
                    reason=data.get("reason", "Circuit breaker tripped"),
                )
                if kill_switch.is_entry_blocked() is False
                else None
            )

        # Wire data health check callback for risk gate check #12
        self._risk_gate.set_data_health_check(lambda: self._current_data_health)

    # ------------------------------------------------------------------
    # Main Pipeline: Captain Decision → Execution
    # ------------------------------------------------------------------

    def receive_decision(
        self,
        decision: CaptainDecision,
        system_context: dict[str, Any] | None = None,
        risk_context: RiskContext | None = None,
    ) -> DecisionResult:
        """Process a Captain decision through the full execution pipeline.

        The pipeline sequence:
        1. CaptainInterface.receive_intent() → ExecutionIntent
        2. ModeRouter.route_intent() → ALERT fires
        3. RiskGate.evaluate() → 12 pre-order checks
        4. State machine: CAPTAIN_INTENT → RISK_PASSED (if checks pass)
        5. ExecutionCore.submit_order() → broker receives order
        6. OrderLifecycleManager.register_order() → order tracked
        7. On fill: PositionManager opens position
        8. On fill: ProtectionModel.stage_protection() → SL/TGT linked

        Args:
            decision: The CaptainDecision from Floor 5.
            system_context: Optional runtime context dict (mode, capital, etc.).
            risk_context: Optional RiskContext for risk gate evaluation.

        Returns:
            DecisionResult with acceptance status and pipeline details.
        """
        # --- Step 0: Validate state machine can receive new intent ---
        if not self._state_machine.can_receive_new_intent():
            reason = f"Cannot receive intent in state: {self._state_machine.state.value}"
            self._log("DECISION_REJECTED", {
                "reason": reason,
                "state": self._state_machine.state.value,
            })
            return DecisionResult(
                accepted=False,
                rejection_reason=reason,
            )

        # --- Step 1: Translate CaptainDecision → ExecutionIntent ---
        try:
            intent = self._captain.receive_intent(decision, system_context)
        except ExecutionError as e:
            self._log("DECISION_REJECTED", {
                "reason": f"CaptainInterface rejected: {e}",
                "details": e.details,
            })
            return DecisionResult(
                accepted=False,
                rejection_reason=str(e),
            )

        self._current_intent = intent

        # --- Step 2: Route through ModeRouter (ALERT always fires) ---
        routing = self._mode_router.route_intent(intent)

        # If ALERT-only mode, no execution path
        if routing.execution_path == "NONE":
            self._log("DECISION_ALERT_ONLY", {
                "trade_id": intent.trade_id,
                "mode": intent.mode.value,
            })
            return DecisionResult(
                accepted=True,
                trade_id=intent.trade_id,
                alert_fired=routing.alert_fired,
                execution_path="NONE",
                routing_result=routing,
            )

        # --- Step 3: Risk Gate evaluation (12 pre-order checks) ---
        risk_result = self._risk_gate.evaluate(intent, risk_context)
        if not risk_result.passed:
            self._record_blocked_action(intent.trade_id, risk_result)
            self._log("DECISION_BLOCKED", {
                "trade_id": intent.trade_id,
                "reason": "Risk gate blocked execution",
                "failed_checks": risk_result.get_failed_checks(),
            })
            return DecisionResult(
                accepted=False,
                trade_id=intent.trade_id,
                alert_fired=routing.alert_fired,
                execution_path=routing.execution_path,
                risk_result=risk_result,
                routing_result=routing,
                rejection_reason="Risk gate blocked execution",
            )

        # --- Step 4: Transition state machine: IDLE → INTENT_RECEIVED ---
        try:
            self._state_machine.transition(
                ExecutionEvent.CAPTAIN_INTENT,
                details={"trade_id": intent.trade_id},
            )
        except ExecutionError as e:
            self._log("DECISION_FAILED", {
                "trade_id": intent.trade_id,
                "error": str(e),
            })
            return DecisionResult(
                accepted=False,
                trade_id=intent.trade_id,
                rejection_reason=f"State machine rejected: {e}",
            )

        # --- Step 5: Transition state machine: INTENT_RECEIVED → RISK_PASSED ---
        try:
            self._state_machine.transition(
                ExecutionEvent.RISK_PASSED,
                details={"risk_passed": True, "trade_id": intent.trade_id},
            )
        except ExecutionError as e:
            self._log("DECISION_FAILED", {
                "trade_id": intent.trade_id,
                "error": f"Risk passed transition failed: {e}",
            })
            return DecisionResult(
                accepted=False,
                trade_id=intent.trade_id,
                rejection_reason=str(e),
            )

        # --- Step 6: Build OrderSubmission and submit via ExecutionCore ---
        try:
            order_sub = self._build_order_submission(intent)
            order_id = self._execution_core.submit_order(order_sub)
            self._current_trade_id = intent.trade_id
            self._primary_order_id = order_id
        except ExecutionError as e:
            # Transition to FAILED if order submission fails
            if self._state_machine.can_transition(ExecutionEvent.RISK_FAILED):
                self._state_machine.transition(
                    ExecutionEvent.RISK_FAILED,
                    details={"error": str(e), "trade_id": intent.trade_id},
                )
            self._log("ORDER_SUBMIT_FAILED", {
                "trade_id": intent.trade_id,
                "error": str(e),
            })
            return DecisionResult(
                accepted=True,
                trade_id=intent.trade_id,
                alert_fired=routing.alert_fired,
                execution_path=routing.execution_path,
                risk_result=risk_result,
                routing_result=routing,
                rejection_reason=f"Order submission failed: {e}",
            )

        # --- Step 7: Register the primary order with OLM ---
        try:
            order_record = self._olm.get_order(order_id)
            if order_record is None:
                olm_order = OrderRecord(
                    order_id=order_id,
                    trade_id=intent.trade_id,
                    state=OrderState.PLACED,
                    side=intent.action,
                    quantity=1,  # Default lot count
                    price=intent.entry_plan.get("price", 0.0),
                    sl_price=intent.stop_loss_plan.get("price"),
                    target_price=intent.target_plan.get("price"),
                )
                self._olm.register_order(olm_order)
            else:
                # Already registered by execution core callback — just log
                self._log("ORDER_ALREADY_REGISTERED", {
                    "order_id": order_id,
                    "trade_id": intent.trade_id,
                })
        except ExecutionError as e:
            self._log("ORDER_REGISTER_FAILED", {
                "order_id": order_id,
                "trade_id": intent.trade_id,
                "error": str(e),
            })
            # Non-fatal — execution continues with unregistered order

        self._log("DECISION_ACCEPTED", {
            "trade_id": intent.trade_id,
            "order_id": order_id,
            "execution_path": routing.execution_path,
            "mode": intent.mode.value,
        })

        return DecisionResult(
            accepted=True,
            trade_id=intent.trade_id,
            alert_fired=routing.alert_fired,
            execution_path=routing.execution_path,
            risk_result=risk_result,
            routing_result=routing,
            order_id=order_id,
        )

    # ------------------------------------------------------------------
    # Broker Event Handlers
    # ------------------------------------------------------------------

    def handle_fill(
        self,
        order_id: str,
        fill_data: dict[str, Any],
    ) -> BrokerEventResult:
        """Handle an incoming fill event from the broker.

        Pipeline:
        1. ExecutionCore.handle_fill() → FillData + state machine transition
        2. PositionManager opens/updates position
        3. ProtectionModel stages SL/TGT (first fill only)
        4. OrderLifecycleManager processes fill

        Args:
            order_id: The filled order ID.
            fill_data: Raw fill data from the broker.

        Returns:
            BrokerEventResult with fill details and updated state.
        """
        # --- Step 1: Process fill through ExecutionCore ---
        try:
            fill = self._execution_core.handle_fill(order_id, fill_data)
        except ExecutionError as e:
            self._log("FILL_HANDLE_FAILED", {
                "order_id": order_id,
                "error": str(e),
            })
            return BrokerEventResult(
                handled=False,
                event_type="FILL",
                order_id=order_id,
                error=str(e),
            )

        trade_id = fill.trade_id

        # --- Step 2: Update position via PM ---
        existing_position = self._pm.get_position(trade_id)
        if existing_position is None:
            # First fill — open position through PM (handles both partial and full fills)
            try:
                self._pm.open_position(
                    trade_id=trade_id,
                    direction=self._current_intent.action if self._current_intent else "BUY",
                    filled_qty=fill.filled_qty,
                    price=fill.price,
                )
            except ExecutionError as e:
                self._log("FILL_POSITION_OPEN_FAILED", {
                    "trade_id": trade_id,
                    "error": str(e),
                })
        else:
            # Existing position — incremental fill update
            try:
                self._pm.update_fill(
                    trade_id=trade_id,
                    additional_qty=fill.filled_qty,
                    price=fill.price,
                )
            except ExecutionError as e:
                self._log("FILL_POSITION_UPDATE_FAILED", {
                    "trade_id": trade_id,
                    "error": str(e),
                })

        # Set SL and target from intent data if available
        if self._current_intent is not None:
            sl_price = self._current_intent.stop_loss_plan.get("price")
            if sl_price is not None and sl_price > 0:
                try:
                    self._pm.set_sl(trade_id, sl_price)
                except ExecutionError:
                    pass  # May already be set or position not yet opened
            target_price = self._current_intent.target_plan.get("price")
            if target_price is not None and target_price > 0:
                try:
                    self._pm.set_target(trade_id, target_price)
                except ExecutionError:
                    pass

        # --- Step 3: Stage protection (first full fill or every partial) ---
        if not self._protection_staged and self._primary_order_id:
            position = self._pm.get_position(trade_id)
            if position is not None and position.filled_qty > 0:
                try:
                    prot_result = self._protection_model.stage_protection(
                        position=position,
                        trade_id=trade_id,
                        primary_order_id=self._primary_order_id,
                    )
                    self._protection_staged = True

                    # Transition state machine to PROTECTED
                    if self._state_machine.can_transition(ExecutionEvent.PROTECTION_STAGED):
                        self._state_machine.transition(
                            ExecutionEvent.PROTECTION_STAGED,
                            details={
                                "trade_id": trade_id,
                                "sl_order": prot_result["linkage"].sl_order_id,
                                "tgt_order": prot_result["linkage"].tgt_order_id,
                            },
                        )

                    self._log("PROTECTION_STAGED", {
                        "trade_id": trade_id,
                        "sl_order_id": prot_result["linkage"].sl_order_id,
                        "tgt_order_id": prot_result["linkage"].tgt_order_id,
                    })
                except ExecutionError as e:
                    self._log("PROTECTION_STAGE_FAILED", {
                        "trade_id": trade_id,
                        "error": str(e),
                    })

        # --- Step 4: Process fill through OLM ---
        try:
            self._olm.handle_partial_fill(
                order_id=order_id,
                filled_qty=fill.filled_qty,
                price=fill.price,
            )
        except ExecutionError as e:
            self._log("OLM_FILL_FAILED", {
                "order_id": order_id,
                "error": str(e),
            })

        self._log("FILL_PROCESSED", {
            "trade_id": trade_id,
            "order_id": order_id,
            "filled_qty": fill.filled_qty,
            "price": fill.price,
            "is_partial": fill.is_partial,
        })

        return BrokerEventResult(
            handled=True,
            event_type="FILL",
            trade_id=trade_id,
            order_id=order_id,
            new_state=self._state_machine.state,
            fill_data=fill,
        )

    def handle_acknowledgement(
        self,
        order_id: str,
        ack_data: dict[str, Any],
    ) -> BrokerEventResult:
        """Handle an incoming order acknowledgement from the broker.

        Args:
            order_id: The acknowledged order ID.
            ack_data: Acknowledgement data from the broker.

        Returns:
            BrokerEventResult with acknowledgement details.
        """
        try:
            ack = self._execution_core.handle_acknowledgement(order_id, ack_data)
        except ExecutionError as e:
            return BrokerEventResult(
                handled=False,
                event_type="ACK",
                order_id=order_id,
                error=str(e),
            )

        # Update OLM order state if order is tracked
        try:
            self._olm.update_state(order_id, OrderState.ACKNOWLEDGED)
        except ExecutionError:
            # May already be acknowledged or order not registered
            pass

        # Retrieve trade_id from OLM or execution core
        order = self._olm.get_order(order_id)
        trade_id = order.trade_id if order else ""

        self._log("ACKNOWLEDGEMENT_PROCESSED", {
            "order_id": order_id,
            "trade_id": trade_id,
        })

        return BrokerEventResult(
            handled=True,
            event_type="ACK",
            trade_id=trade_id,
            order_id=order_id,
            new_state=self._state_machine.state,
        )

    def handle_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> BrokerEventResult:
        """Handle an order rejection from the broker.

        Delegates to ExecutionCore for retry logic. If the rejection
        is non-recoverable and ends the trade, logs the failure.

        Args:
            order_id: The rejected order ID.
            reason: The rejection reason.

        Returns:
            BrokerEventResult with rejection details.
        """
        order = self._olm.get_order(order_id)
        trade_id = order.trade_id if order else ""

        try:
            self._execution_core.handle_rejection(order_id, reason)
        except ExecutionError as e:
            self._log("REJECTION_HANDLE_FAILED", {
                "order_id": order_id,
                "reason": reason,
                "error": str(e),
            })
            return BrokerEventResult(
                handled=False,
                event_type="REJECTION",
                order_id=order_id,
                trade_id=trade_id,
                error=str(e),
            )

        # Update OLM order state
        if order:
            try:
                self._olm.update_state(order_id, OrderState.REJECTED)
            except ExecutionError:
                pass

        self._log("REJECTION_PROCESSED", {
            "order_id": order_id,
            "trade_id": trade_id,
            "reason": reason,
        })

        return BrokerEventResult(
            handled=True,
            event_type="REJECTION",
            trade_id=trade_id,
            order_id=order_id,
            new_state=self._state_machine.state,
        )

    # ------------------------------------------------------------------
    # Emergency Actions
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Periodic Reconciliation
    # ------------------------------------------------------------------

    def periodic_reconcile(self) -> list[ReconcileResult]:
        """Run reconciliation on all active trades that need it.

        Called by the orchestrator's event loop or by an external
        scheduler (e.g., async loop or Side B periodic refresh).
        Checks elapsed time since last reconcile and skips if not
        enough time has passed to avoid hammering the broker.

        Returns:
            List of ReconcileResult, one per reconciled trade.
            Empty list if no reconciliation was needed.
        """
        now = datetime.utcnow()
        elapsed = (now - self._last_reconcile_time).total_seconds()

        if elapsed < self._reconcile_interval_seconds:
            return []

        self._last_reconcile_time = now

        if not self._current_trade_id:
            return []  # No active trade to reconcile

        if not self._state_machine.is_active():
            return []  # State machine not in active state

        results: list[ReconcileResult] = []

        # Reconcile the current trade if it has a position
        position = self._pm.get_position(self._current_trade_id) if self._current_trade_id else None
        if position is not None and position.filled_qty > 0:
            # Build broker_data from the consistency view
            consistency = self._pm.get_consistency_view(self._current_trade_id)
            broker_data = {
                "position": consistency.get("position", {}),
                "orders": [],
            }
            if self._primary_order_id:
                order = self._olm.get_order(self._primary_order_id)
                if order:
                    broker_data["orders"] = [{
                        "order_id": order.order_id,
                        "state": order.state.value,
                        "side": order.side,
                        "quantity": order.quantity,
                        "filled_qty": order.filled_qty,
                        "price": order.price,
                    }]

            try:
                result = self.reconcile_trade(self._current_trade_id, broker_data)
                results.append(result)
            except ExecutionError as e:
                self._log("PERIODIC_RECONCILE_FAILED", {
                    "trade_id": self._current_trade_id,
                    "error": str(e),
                })

        self._log("PERIODIC_RECONCILE", {
            "trade_id": self._current_trade_id,
            "results_count": len(results),
            "state": self._state_machine.state.value,
        })

        return results

    def set_reconcile_interval(self, seconds: float) -> None:
        """Set the periodic reconciliation interval.

        Args:
            seconds: Minimum seconds between reconciliation cycles.
        """
        if seconds < 1.0:
            raise ValueError(f"Reconcile interval must be >= 1.0s, got {seconds}")
        self._reconcile_interval_seconds = seconds

    def trigger_emergency(self, action: str) -> bool:
        """Trigger an emergency action (FLATTEN or LOCK).

        FLATTEN: Emergency flatten — closes ALL positions immediately.
        LOCK: Critical lock — freezes execution, no new trades allowed.

        Args:
            action: "FLATTEN" or "LOCK".

        Returns:
            True if the action was applied, False if not applicable.
        """
        if action == "FLATTEN":
            if self._state_machine.can_transition(ExecutionEvent.EMERGENCY_FLATTEN):
                self._state_machine.transition(
                    ExecutionEvent.EMERGENCY_FLATTEN,
                    details={"action": "emergency_flatten"},
                )
                self._escalation_level = EscalationLevel.EMERGENCY
                self._kill_switch_state = KillSwitchState.CRITICAL_ACTIVE

                # Close any active position
                if self._current_trade_id:
                    position = self._pm.get_position(self._current_trade_id)
                    if position and position.filled_qty > 0:
                        self._pm.close_position(
                            trade_id=self._current_trade_id,
                            close_qty=position.filled_qty,
                            close_price=0.0,  # Market price — filled later
                        )

                self._log("EMERGENCY_FLATTEN", {
                    "trade_id": self._current_trade_id,
                    "new_state": self._state_machine.state.value,
                })
                return True

        elif action == "LOCK":
            if self._state_machine.can_transition(ExecutionEvent.CRITICAL_LOCK):
                self._state_machine.transition(
                    ExecutionEvent.CRITICAL_LOCK,
                    details={"action": "critical_lock"},
                )
                self._escalation_level = EscalationLevel.EMERGENCY
                self._kill_switch_state = KillSwitchState.CRITICAL_ACTIVE

                self._log("CRITICAL_LOCK", {
                    "new_state": self._state_machine.state.value,
                })
                return True

        self._log("EMERGENCY_SKIPPED", {
            "action": action,
            "current_state": self._state_machine.state.value,
            "reason": "Cannot transition from current state",
        })
        return False

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile_trade(
        self,
        trade_id: str,
        broker_data: dict[str, Any],
    ) -> ReconcileResult:
        """Run a full reconciliation cycle for a trade.

        Delegates to ReconciliationEngine and handles state machine
        transitions based on outcome:

        - MATCH / MISMATCH_RESOLVED while in UNKNOWN_PENDING_RECONCILE:
          transitions back to MANAGING or PROTECTED (whichever is valid).
        - MISMATCH_ESCALATED while in UNKNOWN_PENDING_RECONCILE:
          transitions to FAILED via RECONCILE_UNRECOVERABLE.
        - MISMATCH_ESCALATED in any other state:
          raises escalation level to SEVERE.

        Args:
            trade_id: The trade to reconcile.
            broker_data: Broker truth data dict.

        Returns:
            ReconcileResult with outcome and actions taken.
        """
        result = self._reconciliation_engine.reconcile(trade_id, broker_data)

        is_unknown = (
            self._state_machine.state == ExecutionMajorState.UNKNOWN_PENDING_RECONCILE
        )

        if result.outcome == ReconcileOutcome.MISMATCH_ESCALATED:
            if is_unknown:
                # UNKNOWN → escalate to FAILED
                if self._state_machine.can_transition(ExecutionEvent.RECONCILE_UNRECOVERABLE):
                    self._state_machine.transition(
                        ExecutionEvent.RECONCILE_UNRECOVERABLE,
                        details={"trade_id": trade_id, "outcome": result.outcome.value},
                    )
            else:
                # Escalation without UNKNOWN state → raise severity
                self._escalation_level = EscalationLevel.SEVERE
                self._log("RECONCILE_ESCALATED", {
                    "trade_id": trade_id,
                    "mismatches": result.mismatches,
                })

        elif is_unknown and result.outcome in (
            ReconcileOutcome.MATCH,
            ReconcileOutcome.MISMATCH_RESOLVED,
        ):
            # UNKNOWN → successfully reconciled: transition to MANAGING or PROTECTED
            # Check if protection is active → use PROTECTED, otherwise use MANAGING
            position = self._pm.get_position(trade_id)
            is_protected = (
                position is not None
                and position.sl_price is not None
                and position.sl_price > 0
            )

            if is_protected and self._state_machine.can_transition(
                ExecutionEvent.RECONCILE_SUCCESS_PROTECTED,
            ):
                self._state_machine.transition(
                    ExecutionEvent.RECONCILE_SUCCESS_PROTECTED,
                    details={"trade_id": trade_id, "outcome": result.outcome.value},
                )
            elif self._state_machine.can_transition(
                ExecutionEvent.RECONCILE_SUCCESS_MANAGING,
            ):
                self._state_machine.transition(
                    ExecutionEvent.RECONCILE_SUCCESS_MANAGING,
                    details={"trade_id": trade_id, "outcome": result.outcome.value},
                )

        self._log("RECONCILE_COMPLETE", {
            "trade_id": trade_id,
            "outcome": result.outcome.value,
        })

        return result

    def handle_reconnect(
        self,
        broker_data: dict[str, Any],
    ) -> list[ReconcileResult]:
        """Handle a broker reconnection by re-reconciling all active trades.

        Args:
            broker_data: Dict of trade_id -> broker state data.

        Returns:
            List of ReconcileResult, one per active trade.
        """
        results = self._reconciliation_engine.handle_reconnect(broker_data)

        # Check for escalated results
        for r in results:
            if r.outcome == ReconcileOutcome.MISMATCH_ESCALATED:
                self._escalation_level = EscalationLevel.SEVERE
                break

        self._log("RECONNECT_COMPLETE", {
            "trade_count": len(results),
        })

        return results

    # ------------------------------------------------------------------
    # Exits & Closes (from Captain/management signals)
    # ------------------------------------------------------------------

    def trigger_exit(self, trade_id: str, exit_price: float = 0.0) -> bool:
        """Trigger an exit for a trade (e.g., SL hit, target reached).

        Transitions the state machine through the exit chain to CLOSED.
        Handles non-MANAGING states by attempting intermediate transitions
        (PROTECTION_STAGED → MANAGEMENT_BEGINS → EXIT_TRIGGERED) in a
        while loop that continues until EXIT_TRIGGERED is available or
        no more progress can be made.

        Args:
            trade_id: The trade to exit.
            exit_price: The exit price (0 = market price).

        Returns:
            True if the exit was processed, False if not applicable.
        """
        # Keep trying intermediate transitions until EXIT_TRIGGERED is available
        # or no more progress can be made
        while not self._state_machine.can_transition(ExecutionEvent.EXIT_TRIGGERED):
            progressed = False
            for event in [
                ExecutionEvent.MANAGEMENT_BEGINS,
                ExecutionEvent.PROTECTION_STAGED,
            ]:
                if self._state_machine.can_transition(event):
                    self._state_machine.transition(
                        event,
                        details={"reason": "exit_chain", "trade_id": trade_id},
                    )
                    progressed = True
                    break
            if not progressed:
                self._log("EXIT_SKIPPED", {
                    "trade_id": trade_id,
                    "state": self._state_machine.state.value,
                    "reason": "Cannot transition to EXITING",
                })
                return False

        self._state_machine.transition(
            ExecutionEvent.EXIT_TRIGGERED,
            details={"trade_id": trade_id, "exit_price": exit_price},
        )

        # Close position if still active
        position = self._pm.get_position(trade_id)
        if position and position.filled_qty > 0:
            close_qty = position.filled_qty
            self._pm.close_position(
                trade_id=trade_id,
                close_qty=close_qty,
                close_price=exit_price if exit_price > 0 else position.avg_price,
            )

        # Transition to CLOSED
        if self._state_machine.can_transition(ExecutionEvent.CLOSE_COMPLETE):
            self._state_machine.transition(
                ExecutionEvent.CLOSE_COMPLETE,
                details={"trade_id": trade_id, "exit_price": exit_price},
            )

        # Reset tracking
        self._protection_staged = False
        self._current_trade_id = None
        self._current_intent = None
        self._primary_order_id = None

        self._log("EXIT_COMPLETE", {
            "trade_id": trade_id,
            "exit_price": exit_price,
        })

        return True

    # ------------------------------------------------------------------
    # State Queries
    # ------------------------------------------------------------------

    def get_state(self) -> ExecutionSnapshot:
        """Get a complete snapshot of the current execution state.

        Produces ExecutionSnapshot for Side B (Dashboard) and Side C (Memory).

        Returns:
            ExecutionSnapshot with current state, position, orders, and risk info.
        """
        # Get current position
        position: PositionState | None = None
        if self._current_trade_id:
            position = self._pm.get_position(self._current_trade_id)

        # Get active orders
        if self._current_trade_id:
            orders = self._olm.get_active_orders_for_trade(self._current_trade_id)
        else:
            orders = []

        # Build risk status summary
        risk_status: dict[str, Any] = {
            "has_active_trade": self._current_trade_id is not None,
            "mode": self._mode_router.get_current_mode().value,
            "escalation_level": self._escalation_level.value,
            "kill_switch": self._kill_switch_state.value,
            "protection_staged": self._protection_staged,
        }

        # Get recent blocked actions (last 10)
        recent_blocked = [
            {
                "timestamp": ba.timestamp.isoformat(),
                "trade_id": ba.trade_id,
                "reason": ba.block_reason,
                "severity": ba.severity.value,
            }
            for ba in self._blocked_actions[-10:]
        ]

        # Get transition history summary
        history = self._state_machine.get_transition_history()
        transition_summary = [
            {
                "from": h.from_state,
                "event": h.event,
                "to": h.to_state,
                "timestamp": h.timestamp.isoformat(),
            }
            for h in history[-20:]  # Last 20 transitions
        ]

        return ExecutionSnapshot(
            state=self._state_machine.state,
            position=position,
            orders=orders,
            risk_status=risk_status,
            mode=self._mode_router.get_current_mode(),
            escalation_level=self._escalation_level,
            kill_switch_state=self._kill_switch_state,
            blocked_actions=recent_blocked,
        )

    def get_trade_context(self) -> dict[str, Any]:
        """Get lightweight trade context for downstream consumers.

        Returns:
            Dict with current trade ID, intent, and protection status.
        """
        protected = False
        if self._current_trade_id:
            protected = self._protection_model.is_protected(self._current_trade_id)

        return {
            "current_trade_id": self._current_trade_id,
            "has_active_intent": self._current_intent is not None,
            "protection_staged": self._protection_staged,
            "is_protected": protected,
            "state": self._state_machine.state.value,
        }

    # ------------------------------------------------------------------
    # Override Pathway
    # ------------------------------------------------------------------

    def process_override(
        self,
        trade_id: str,
        override_type: str,
        override_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process a Captain/operator override for an active trade.

        The override pathway follows the locked architecture rules:
        - Override is exit/risk-side only (no entry override after execution start)
        - Allowed: size reduction, SL tighten, risk reduction, emergency exit
        - Not allowed: new entry override, direction change
        - Every override MUST be logged and state-updated
        - Override aftereffect: temporary caution flag may remain

        Args:
            trade_id: The trade to override.
            override_type: Type of override:
                - "REDUCE_SIZE": Reduce position size (exit portion)
                - "TIGHTEN_SL": Move stop-loss closer
                - "RISK_REDUCTION": Reduce risk exposure
                - "EMERGENCY_EXIT": Immediate full exit
            override_data: Override-specific parameters:
                - REDUCE_SIZE: {"qty": int, "price": float}
                - TIGHTEN_SL: {"sl_price": float}
                - RISK_REDUCTION: {"qty": int} (partial exit)
                - EMERGENCY_EXIT: {"price": float} (market exit)

        Returns:
            Dict with:
                - 'applied': bool, whether override was applied
                - 'action': str, what was done
                - 'trade_id': str, the trade involved
                - 'timestamp': str, when override occurred

        Raises:
            ExecutionError: If override type is invalid, trade not found,
                or no active position to override.
        """
        if not trade_id:
            raise ExecutionError(
                message="Cannot process override without trade_id",
            )

        if not override_type:
            raise ExecutionError(
                message="Cannot process override without override_type",
            )

        if not self._current_trade_id or self._current_trade_id != trade_id:
            raise ExecutionError(
                message=f"No active trade found for override: {trade_id}",
            )

        position = self._pm.get_position(trade_id)
        if position is None or position.filled_qty <= 0:
            raise ExecutionError(
                message=f"No position to override for trade: {trade_id}",
            )

        data = override_data or {}
        action_desc = ""
        applied = False

        try:
            if override_type == "REDUCE_SIZE":
                qty = data.get("qty", 0)
                price = data.get("price", 0.0)
                if qty <= 0 or qty >= position.filled_qty:
                    self._pm.close_position(trade_id, close_price=price if price > 0 else position.avg_price)
                    action_desc = f"Full position close via override (qty={position.filled_qty})"
                else:
                    self._pm.partial_exit(trade_id, exit_qty=qty, exit_price=price if price > 0 else position.avg_price)
                    action_desc = f"Size reduced by {qty} via override"
                applied = True

            elif override_type == "TIGHTEN_SL":
                sl_price = data.get("sl_price", 0.0)
                if sl_price <= 0:
                    raise ExecutionError(
                        message="TIGHTEN_SL override requires sl_price > 0",
                    )
                self._pm.set_sl(trade_id, sl_price)
                action_desc = f"SL tightened to {sl_price} via override"
                applied = True

            elif override_type == "RISK_REDUCTION":
                qty = data.get("qty", 0)
                if qty <= 0:
                    raise ExecutionError(
                        message="RISK_REDUCTION override requires qty > 0",
                    )
                self._pm.partial_exit(
                    trade_id,
                    exit_qty=min(qty, position.filled_qty),
                    exit_price=data.get("price", position.avg_price),
                )
                action_desc = f"Risk reduced by {qty} via override"
                applied = True

            elif override_type == "EMERGENCY_EXIT":
                price = data.get("price", 0.0)
                self.trigger_exit(trade_id, exit_price=price if price > 0 else position.avg_price)
                action_desc = "Emergency exit via override"
                applied = True

            else:
                raise ExecutionError(
                    message=f"Unknown override type: {override_type}",
                    details={
                        "valid_types": ["REDUCE_SIZE", "TIGHTEN_SL", "RISK_REDUCTION", "EMERGENCY_EXIT"],
                    },
                )

        except ExecutionError:
            raise
        except Exception as e:
            raise ExecutionError(
                message=f"Override failed: {e}",
                details={"override_type": override_type, "trade_id": trade_id},
                original_exception=e,
            )

        # Log the override
        self._log("OVERRIDE_APPLIED", {
            "trade_id": trade_id,
            "override_type": override_type,
            "action": action_desc,
            "data": data,
        })

        # Set caution flag as override aftereffect
        self._escalation_level = EscalationLevel.CAUTION

        return {
            "applied": applied,
            "action": action_desc,
            "trade_id": trade_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # EOD Close
    # ------------------------------------------------------------------

    def check_eod_close(self, current_time: datetime | None = None) -> dict[str, Any]:
        """Check whether it's time to close positions for end-of-day.

        NIFTY 50 market closes at 3:30 PM IST.  Side A positions should
        be closed before this time (default: 3:15 PM IST = EOD_CLOSE_TIME).
        On expiry days, an earlier close window applies (default: 3:00 PM).

        Called by the orchestrator's event loop or by an external
        scheduler.  Safely handles the case where no active trade exists.

        Args:
            current_time: Current time (defaults to datetime.utcnow()).
                If provided with timezone info, conversion logic applies.

        Returns:
            Dict with:
                - 'closed': bool, whether any position was closed
                - 'reason': str, why (EOD_CLOSE, EXPIRY_CLOSE, SKIPPED)
                - 'trade_id': str or None
        """
        now = current_time or datetime.utcnow()

        if not self._current_trade_id:
            return {"closed": False, "reason": "SKIPPED", "trade_id": None}

        position = self._pm.get_position(self._current_trade_id)
        if position is None or position.status == "CLOSED":
            self._current_trade_id = None
            return {"closed": False, "reason": "SKIPPED", "trade_id": None}

        # Check if it's time to close
        #
        # Timezone note: India Standard Time (IST) is UTC+5:30 year-round
        # (no DST).  The close times below are expressed in UTC:
        #   EOD close: 3:15 PM IST = 9:45 AM UTC
        #   Expiry day close: 3:00 PM IST = 9:30 AM UTC
        #
        # ``check_eod_close`` always compares against ``datetime.utcnow()``
        # (or the passed-in ``current_time``, which should also be UTC).
        # If ``current_time`` is timezone-aware, only the hour/minute parts
        # are compared — timezone conversion is caller's responsibility.
        eod_hour, eod_min = 9, 45  # 3:15 PM IST
        expiry_hour, expiry_min = 9, 30  # 3:00 PM IST

        # Determine which close time applies (V1: always use EOD close)
        close_hour = eod_hour
        close_min = eod_min
        close_reason = "EOD_CLOSE"

        # Check if current time >= close time
        if now.hour > close_hour or (now.hour == close_hour and now.minute >= close_min):
            # Time to close
            self.trigger_exit(self._current_trade_id, exit_price=position.avg_price)

            self._log("EOD_CLOSE_EXECUTED", {
                "trade_id": self._current_trade_id,
                "reason": close_reason,
                "position_qty": position.filled_qty,
                "avg_price": position.avg_price,
            })

            return {
                "closed": True,
                "reason": close_reason,
                "trade_id": self._current_trade_id,
            }

        return {"closed": False, "reason": "NOT_YET", "trade_id": self._current_trade_id}

    # ------------------------------------------------------------------
    # Mode Management
    # ------------------------------------------------------------------

    def set_execution_mode(self, new_mode: ExecutionMode) -> bool:
        """Change the execution mode (ALERT/PAPER/REAL).

        Transition is blocked if an active trade exists.

        Args:
            new_mode: The target execution mode.

        Returns:
            True if mode was changed, False if blocked.
        """
        result = self._mode_router.set_mode(new_mode)
        if result:
            self._log("MODE_CHANGED", {
                "new_mode": new_mode.value,
            })
        else:
            self._log("MODE_CHANGE_BLOCKED", {
                "new_mode": new_mode.value,
                "reason": "Active trade exists",
            })
        return result

    def get_execution_mode(self) -> ExecutionMode:
        """Get the current execution mode.

        Returns:
            The current ExecutionMode.
        """
        return self._mode_router.get_current_mode()

    # ------------------------------------------------------------------
    # Kill Switch
    # ------------------------------------------------------------------

    def activate_kill_switch(
        self,
        level: KillSwitchState,
        reason: str = "",
    ) -> bool:
        """Activate or deactivate the kill switch.

        SOFT_ACTIVE: Blocks new entries. Existing protected trades continue.
        CRITICAL_ACTIVE: Flatten path + freeze execution. Emergency only.
        NORMAL: No kill switch active.

        Args:
            level: The kill switch activation level.
            reason: Optional reason for the activation.

        Returns:
            True if the kill switch was changed, False if invalid transition.
        """
        # Delegate to injected kill_switch if available
        if self._kill_switch is not None:
            if level == KillSwitchState.SOFT_ACTIVE:
                return self._kill_switch.activate_soft(reason or "Operator SOFT activation")
            elif level == KillSwitchState.CRITICAL_ACTIVE:
                return self._kill_switch.activate_critical(reason or "Operator CRITICAL activation")
            elif level == KillSwitchState.NORMAL:
                return self._kill_switch.deactivate(reason or "Operator deactivation")
            return False

        # Fallback: internal kill switch management
        if level == self._kill_switch_state:
            return True  # No-op

        if level == KillSwitchState.CRITICAL_ACTIVE:
            return self.trigger_emergency("FLATTEN")

        if level == KillSwitchState.SOFT_ACTIVE:
            self._kill_switch_state = KillSwitchState.SOFT_ACTIVE
            self._escalation_level = EscalationLevel.CAUTION
            self._log("KILL_SWITCH_SOFT", {"reason": reason})
            return True

        if level == KillSwitchState.NORMAL:
            self._kill_switch_state = KillSwitchState.NORMAL
            self._escalation_level = EscalationLevel.NORMAL
            self._log("KILL_SWITCH_NORMAL", {"reason": reason})
            return True

        return False

    def get_kill_switch_state(self) -> KillSwitchState:
        """Get the current kill switch state.

        Returns:
            The current KillSwitchState.
        """
        if self._kill_switch is not None:
            return self._kill_switch.get_active_switch()
        return self._kill_switch_state

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _has_active_trade(self) -> bool:
        """Check whether there is currently an active trade.

        Checks BOTH the current trade ID AND the position manager
        to catch orphaned positions where state machine says IDLE
        but position manager still has an open position.

        Returns:
            True if a trade is in progress.
        """
        if self._current_trade_id is not None:
            return True
        # Double-check position manager for orphaned positions
        active_positions = self._pm.get_active_positions()
        return len(active_positions) > 0

    def _build_order_submission(self, intent: ExecutionIntent) -> OrderSubmission:
        """Build an OrderSubmission from an ExecutionIntent.

        Args:
            intent: The validated ExecutionIntent.

        Returns:
            An OrderSubmission ready for the broker.
        """
        return OrderSubmission.from_execution_intent(intent)

    def _record_blocked_action(
        self,
        trade_id: str,
        risk_result: RiskCheckResult,
    ) -> None:
        """Record a blocked action for the blocked action journal.

        Args:
            trade_id: The trade that was blocked.
            risk_result: The RiskCheckResult with failure details.
        """
        failed = risk_result.get_failed_checks()
        reasons = [f"{name}: {reason}" for name, reason in failed]
        record = BlockedActionRecord(
            trade_id=trade_id,
            block_reason=" | ".join(reasons) if reasons else "Risk gate blocked",
            mode=self._mode_router.get_current_mode(),
            severity=Severity.CAUTION,
            details={"failed_checks": failed},
        )

        # Delegate to injected blocked_journal if available
        if self._blocked_journal is not None:
            self._blocked_journal.record(record)
        else:
            self._blocked_actions.append(record)
            # Cap the list to prevent unbounded growth
            if len(self._blocked_actions) > 100:
                self._blocked_actions = self._blocked_actions[-100:]

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event being logged.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
