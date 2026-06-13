"""Junior Aladdin — Floor 5: Captain.

Floor 5 is the supreme decision brain of the Junior Aladdin system.  Captain
consumes interpreted expert intelligence from Floor 4 (Floor Summary + 6 Head
Reports), applies weighted confluence, checks opposite case, builds conviction,
creates armed conditional plans, and outputs TRADE / WAIT / BLOCKED decisions.

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 1):
- QUALITY = Floor 3 (NOT Captain)
- CONFIDENCE = Floor 4 (NOT Captain)
- CONVICTION = Floor 5 (Captain owns this)
- Captain owns CONVICTION, decision approval, no-trade reasoning
- Captain does NOT recalculate quality or confidence — it judges them
- Captain does NOT consume Floor 3 packets as routine input
- Silence (WAIT / BLOCKED) is a valid, actively reasoned output
"""

# =============================================================================
# captain_types — enums, dataclasses, helpers
# =============================================================================

from junior_aladdin.floor_5_captain.captain_types import (
    ArmedPlanState,
    CaptainInput,
    CaptainState,
    ConfluenceResult,
    ConvictionBand,
    ConvictionScore,
    DecisionState,
    InterventionSeverity,
    MarketStory,
    NarrativeTimeline,
    NarrativeTimelineEvent,
    OppositeCase,
    PermissionResult,
    ReportTrustTier,
    SessionPhase,
    SilenceReason,
    conviction_score_to_band,
    get_aggression_modifier,
    get_permission_strictness,
    get_session_phase_from_time,
)

# =============================================================================
# session_policy — session-adaptive aggression / permission
# =============================================================================

from junior_aladdin.floor_5_captain.session_policy import (
    SessionPolicy,
)

# =============================================================================
# loss_lock_manager + override_guard — loss tracking & lock
# =============================================================================

from junior_aladdin.floor_5_captain.loss_lock_manager import (
    LossLockManager,
)
from junior_aladdin.floor_5_captain.override_guard import (
    OverrideGuard,
)

# =============================================================================
# permission_gate — 8-condition permission check
# =============================================================================

from junior_aladdin.floor_5_captain.permission_gate import (
    PermissionGate,
)

# =============================================================================
# market_story_engine — current market context builder
# =============================================================================

from junior_aladdin.floor_5_captain.market_story_engine import (
    MarketStoryEngine,
)

# =============================================================================
# narrative_timeline_engine — intraday event-chain memory
# =============================================================================

from junior_aladdin.floor_5_captain.narrative_timeline_engine import (
    NarrativeTimelineEngine,
)

# =============================================================================
# confluence_engine — weighted head alignment
# =============================================================================

from junior_aladdin.floor_5_captain.confluence_engine import (
    ConfluenceEngine,
)

# =============================================================================
# opposite_case_engine — pre-mortem failure analysis
# =============================================================================

from junior_aladdin.floor_5_captain.opposite_case_engine import (
    OppositeCaseEngine,
)

# =============================================================================
# conviction_engine — permission + conviction + no-trade scores
# =============================================================================

from junior_aladdin.floor_5_captain.conviction_engine import (
    ConvictionEngine,
)

# =============================================================================
# personality_engine — Captain mood determination
# =============================================================================

from junior_aladdin.floor_5_captain.personality_engine import (
    PersonalityEngine,
)

# =============================================================================
# trade_class_engine — trade class assignment
# =============================================================================

from junior_aladdin.floor_5_captain.trade_class_engine import (
    TradeClassEngine,
)

# =============================================================================
# setup_memory_store — active / rejected / failed setup memory
# =============================================================================

from junior_aladdin.floor_5_captain.setup_memory_store import (
    SetupMemoryStore,
)

# =============================================================================
# trade_idea_generator — synthesizes trade ideas from confluence + story
# =============================================================================

from junior_aladdin.floor_5_captain.trade_idea_generator import (
    TradeIdeaGenerator,
)

# =============================================================================
# armed_plan_engine — conditional plan creation + lifecycle
# =============================================================================

from junior_aladdin.floor_5_captain.armed_plan_engine import (
    ArmedPlanEngine,
)

# =============================================================================
# setup_expiry_manager — setup validity windows by trade class
# =============================================================================

from junior_aladdin.floor_5_captain.setup_expiry_manager import (
    SetupExpiryManager,
)

# =============================================================================
# confidence_decay_engine — gradual conviction decay
# =============================================================================

from junior_aladdin.floor_5_captain.confidence_decay_engine import (
    ConfidenceDecayEngine,
)

# =============================================================================
# trade_constructor — direction, strike, entry, SL, targets
# =============================================================================

from junior_aladdin.floor_5_captain.trade_constructor import (
    TradeConstructor,
    TradePlan,
)

# =============================================================================
# silence_reason_logger — structured WAIT / BLOCKED / REJECT reasons
# =============================================================================

from junior_aladdin.floor_5_captain.silence_reason_logger import (
    SilenceReasonLogger,
    SilenceRecord,
)

# =============================================================================
# decision_snapshot_writer — freeze decision state for audit
# =============================================================================

from junior_aladdin.floor_5_captain.decision_snapshot_writer import (
    DecisionSnapshotWriter,
    SnapContext,
)

# =============================================================================
# active_trade_supervisor — thesis integrity tracking during active trades
# =============================================================================

from junior_aladdin.floor_5_captain.active_trade_supervisor import (
    ActiveTradeSupervisor,
    ThesisReview,
)

# =============================================================================
# intervention_engine — rare strategic override during active trades
# =============================================================================

from junior_aladdin.floor_5_captain.intervention_engine import (
    InterventionDecision,
    InterventionEngine,
)

# =============================================================================
# captain_engine — heavy + light cycle orchestrator
# =============================================================================

from junior_aladdin.floor_5_captain.captain_engine import (
    CaptainEngine,
    HeavyCycleOutput,
    LightCycleOutput,
)


__all__ = [
    # captain_types
    "ArmedPlanState",
    "CaptainInput",
    "CaptainState",
    "ConfluenceResult",
    "ConvictionBand",
    "ConvictionScore",
    "DecisionState",
    "InterventionSeverity",
    "MarketStory",
    "NarrativeTimeline",
    "NarrativeTimelineEvent",
    "OppositeCase",
    "PermissionResult",
    "ReportTrustTier",
    "SessionPhase",
    "SilenceReason",
    "conviction_score_to_band",
    "get_aggression_modifier",
    "get_permission_strictness",
    "get_session_phase_from_time",
    # session_policy
    "SessionPolicy",
    # loss_lock_manager + override_guard
    "LossLockManager",
    "OverrideGuard",
    # permission_gate
    "PermissionGate",
    # market_story_engine
    "MarketStoryEngine",
    # narrative_timeline_engine
    "NarrativeTimelineEngine",
    # confluence_engine
    "ConfluenceEngine",
    # opposite_case_engine
    "OppositeCaseEngine",
    # conviction_engine
    "ConvictionEngine",
    # personality_engine
    "PersonalityEngine",
    # trade_class_engine
    "TradeClassEngine",
    # setup_memory_store
    "SetupMemoryStore",
    # trade_idea_generator
    "TradeIdeaGenerator",
    # armed_plan_engine
    "ArmedPlanEngine",
    # setup_expiry_manager
    "SetupExpiryManager",
    # confidence_decay_engine
    "ConfidenceDecayEngine",
    # trade_constructor
    "TradeConstructor",
    "TradePlan",
    # silence_reason_logger
    "SilenceReasonLogger",
    "SilenceRecord",
    # decision_snapshot_writer
    "DecisionSnapshotWriter",
    "SnapContext",
    # active_trade_supervisor
    "ActiveTradeSupervisor",
    "ThesisReview",
    # intervention_engine
    "InterventionDecision",
    "InterventionEngine",
    # captain_engine
    "CaptainEngine",
    "HeavyCycleOutput",
    "LightCycleOutput",
]
