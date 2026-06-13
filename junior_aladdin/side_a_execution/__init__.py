"""Junior Aladdin — Side A: Execution Layer.

Side A is the tactical execution layer.  Captain decides — Side A executes.
Side A receives Captain's approved execution intent, runs pre-execution safety
checks through the Risk Gate, manages the full order lifecycle, communicates
with broker/simulator, maintains position truth, and enforces capital
protection rules.

Architecture rules (LOCKED):
- Side A executes, it does NOT decide
- Side A never creates trades (receives approved intent only)
- Side A never increases size (reduce-only for safety)
- Broker truth = final live authority
- ONE active live trade at a time
- ALERT always active, PAPER / REAL execution switch
"""

from junior_aladdin.side_a_execution.blocked_action_journal import (
    BlockedActionJournal,
)
from junior_aladdin.side_a_execution.captain_interface import CaptainInterface
from junior_aladdin.side_a_execution.data_health_policy import DataHealthPolicy
from junior_aladdin.side_a_execution.execution_core import (
    AckData,
    BrokerProtocol,
    ExecutionCore,
    FillData,
    OrderSubmission,
)
from junior_aladdin.side_a_execution.execution_logging_layer import (
    ExecutionLoggingLayer,
)
from junior_aladdin.side_a_execution.execution_orchestrator import (
    DecisionResult,
    BrokerEventResult,
    ExecutionOrchestrator,
)
from junior_aladdin.side_a_execution.execution_state_machine import (
    ExecutionEvent,
    ExecutionStateMachine,
)
from junior_aladdin.side_a_execution.intent_fingerprint import (
    IntentFingerprintStore,
    generate_fingerprint_from_intent,
)
from junior_aladdin.side_a_execution.kill_switch import KillSwitch
from junior_aladdin.side_a_execution.mode_router import (
    ModeRouter,
    RoutingResult,
)
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    OrderLifecycleManager,
    OrderState,
)
from junior_aladdin.side_a_execution.paper_broker import (
    PaperBroker,
    PaperPosition,
)
from junior_aladdin.side_a_execution.real_broker import RealBroker
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
from junior_aladdin.side_a_execution.side_a_types import (
    BlockedActionRecord,
    DataHealthExecutionResponse,
    EscalationLevel,
    ExecutionMajorState,
    ExecutionSnapshot,
    KillSwitchState,
    OrderRecord,
    PositionState,
    ReconcileOutcome,
    ReconciliationRecord,
    RiskCheckResult,
    can_receive_new_intent,
    default_risk_check_result,
    is_execution_active,
)

__all__ = [
    # ── ORCHESTRATOR (PRIMARY API) ──
    "ExecutionOrchestrator",
    "DecisionResult",
    "BrokerEventResult",
    # ── CAPTAIN ──
    "CaptainInterface",
    # ── ROUTING ──
    "ModeRouter",
    "RoutingResult",
    # ── SAFETY ──
    "RiskGate",
    "RiskContext",
    "RiskCheckResult",
    "default_risk_check_result",
    "IntentFingerprintStore",
    "generate_fingerprint_from_intent",
    "DataHealthPolicy",
    "DataHealthExecutionResponse",
    "KillSwitch",
    "KillSwitchState",
    "BlockedActionJournal",
    "BlockedActionRecord",
    # ── STATE MACHINE ──
    "ExecutionStateMachine",
    "ExecutionEvent",
    "ExecutionMajorState",
    # ── EXECUTION ──
    "ExecutionCore",
    "BrokerProtocol",
    "OrderSubmission",
    "AckData",
    "FillData",
    # ── ORDER LIFECYCLE ──
    "OrderLifecycleManager",
    "OrderState",
    "OrderRecord",
    # ── POSITION ──
    "PositionManager",
    "PositionState",
    # ── PROTECTION ──
    "ProtectionModel",
    # ── RECONCILIATION ──
    "ReconciliationEngine",
    "ReconcileResult",
    "ReconcileOutcome",
    "ReconciliationRecord",
    # ── BROKERS ──
    "PaperBroker",
    "PaperPosition",
    "RealBroker",
    # ── LOGGING ──
    "ExecutionLoggingLayer",
    # ── HELPERS ──
    "is_execution_active",
    "can_receive_new_intent",
    "EscalationLevel",
    "ExecutionSnapshot",
]
