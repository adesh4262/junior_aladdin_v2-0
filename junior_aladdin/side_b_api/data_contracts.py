"""Side B API response data contracts.

Every API route returns one of these schemas as its JSON response.
All schemas are dataclasses, consistent with shared/types.py.

Reference: ROADMAP_SIDE_B Step 8.1, SIDE_B_DASHBOARD_V1_2_FINAL Sections 13–28
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.types import (
    CaptainMood,
    DataHealth,
    DecisionType,
    ExecutionMode,
    HeadState,
    LifecycleState,
    Severity,
)


# ══════════════════════════════════════════════════════════════
#  1. System Health
# ══════════════════════════════════════════════════════════════


@dataclass
class ComponentHealthDetail:
    """Per-component health state (one floor or side)."""
    name: str
    state: str  # HEALTHY / DEGRADED / STALE / UNAVAILABLE / LOCKED / SILENT
    lifecycle: LifecycleState = LifecycleState.HEALTHY
    last_update: datetime | None = None
    detail: str = ""


@dataclass
class SystemHealthSnapshot:
    """Top-level system health — first-glance operator information."""
    overall_status: DataHealth = DataHealth.GOOD
    floors: dict[str, ComponentHealthDetail] = field(default_factory=dict)
    sides: dict[str, ComponentHealthDetail] = field(default_factory=dict)
    data_health_signal: DataHealth = DataHealth.GOOD
    connection_status: str = "CONNECTED"
    critical_alert_count: int = 0


# ══════════════════════════════════════════════════════════════
#  2. Captain
# ══════════════════════════════════════════════════════════════


@dataclass
class CaptainDisplayState:
    """Captain state as shown in the cockpit — never recalculated."""
    mood: CaptainMood = CaptainMood.OBSERVER
    decision: DecisionType = DecisionType.WAIT
    conviction_score: float = 0.0
    conviction_band: str = "REJECT"  # REJECT / WEAK / TRADABLE / STRONG / ELITE
    market_story_summary: str = ""
    reason_summary: str = ""
    silence_reason: str | None = None
    active_plan_count: int = 0
    no_trade_classification: str | None = None  # SETUP_ABSENT / CONFLICT / HEALTH / ...
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CaptainStoryDisplay:
    """Market story + narrative timeline for the explainability panel."""
    story_summary: str = ""
    narrative_timeline: list[str] = field(default_factory=list)
    last_update: datetime = field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
#  3. Execution
# ══════════════════════════════════════════════════════════════


@dataclass
class PositionDisplay:
    """Active position summary."""
    symbol: str = ""
    direction: str = ""  # BUY / SELL
    filled_qty: int = 0
    avg_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    sl_price: float | None = None
    target_price: float | None = None
    trade_class: str = ""
    duration_minutes: int = 0


@dataclass
class OrderDisplay:
    """Single order in the lifecycle chain."""
    order_id: str = ""
    status: str = ""  # PLACED / ACK / PARTIAL / FILLED / CANCELLED / REJECTED
    side: str = ""
    qty: int = 0
    filled_qty: int = 0
    price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionDisplayState:
    """Execution layer state as shown in the cockpit."""
    mode: ExecutionMode = ExecutionMode.ALERT
    state: str = "IDLE"
    substate: str = ""
    position: PositionDisplay | None = None
    orders: list[OrderDisplay] = field(default_factory=list)
    blocked_actions: list[dict[str, Any]] = field(default_factory=list)
    escalation_level: str = "NORMAL"  # NORMAL / CAUTION / SEVERE / EMERGENCY
    unknown_reconcile: bool = False
    is_locked: bool = False
    kill_switch_state: str = "NORMAL"
    capital_limit: float | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
#  4. Heads
# ══════════════════════════════════════════════════════════════


@dataclass
class HeadReportDisplay:
    """Single head report for the dashboard — never recalculated."""
    head_name: str = ""
    state: HeadState = HeadState.READY
    bias: str = "NEUTRAL"
    confidence: float = 0.0  # 0.0–1.0
    freshness_tag: str = "FRESH"
    context_quality_score: float | None = None  # SMC / ICT only
    primary_setup: str | None = None
    backup_setup: str | None = None
    invalidation_summary: str = ""
    no_setup_flag: bool = False  # Macro / Psychology heads


@dataclass
class FloorSummaryDisplay:
    """Aggregated floor summary for the cockpit strip."""
    floor_bias: str = "NEUTRAL"
    floor_confidence: float = 0.0
    active_setup_count: int = 0
    ready_heads: int = 0
    uncertain_heads: int = 0
    stale_heads: int = 0
    data_health_signal: DataHealth = DataHealth.GOOD
    heads: list[HeadReportDisplay] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
#  5. Market
# ══════════════════════════════════════════════════════════════


@dataclass
class MarketDataSnapshot:
    """Current market data snapshot for the chart + ticker."""
    symbol: str = "NIFTY 50"
    ltp: float = 0.0
    change: float = 0.0
    change_percent: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    volume: int = 0
    vwap: float = 0.0
    session: str = ""  # PRE_OPEN / OPEN / LUNCH / CLOSING / POST_CLOSE
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
#  6. Alerts
# ══════════════════════════════════════════════════════════════


@dataclass
class AlertEntry:
    """Single alert for the alert feed."""
    alert_id: str = ""
    severity: Severity = Severity.INFO
    category: str = ""  # EXECUTION / HEALTH / RISK / GOVERNANCE / OPERATOR
    message: str = ""
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False


# ══════════════════════════════════════════════════════════════
#  7. Controls
# ══════════════════════════════════════════════════════════════


@dataclass
class ControlCommand:
    """Operator command structure — every command uses `request_` prefix."""
    command_type: str = ""  # request_mode / request_capital / request_kill_switch / ...
    target: str = ""  # side_a.mode_router / side_a.kill_switch / floor_5.override_guard / ...
    params: dict[str, Any] = field(default_factory=dict)
    operator_context: str = "local"
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CommandAck:
    """Acknowledgement returned after routing a command to its owner."""
    status: str = "ACK"  # ACK / REJECT / PENDING
    command_type: str = ""
    message: str = ""
    owner_response: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
#  8. Replay
# ══════════════════════════════════════════════════════════════


@dataclass
class ReplaySessionConfig:
    """Configuration for a replay workspace session."""
    session_id: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    speed: float = 1.0  # 1x, 2x, 5x, 10x
    data_sources: list[str] = field(default_factory=list)
    status: str = "STOPPED"  # STOPPED / PLAYING / PAUSED


# ══════════════════════════════════════════════════════════════
#  9. Workspace
# ══════════════════════════════════════════════════════════════


@dataclass
class WorkspaceState:
    """Current dashboard workspace state."""
    current_workspace: str = "cockpit"  # cockpit / replay / review / diagnostics
    sub_views: dict[str, Any] = field(default_factory=dict)
    expanded_panels: list[str] = field(default_factory=list)
    active_drilldown: str | None = None


# ══════════════════════════════════════════════════════════════
#  10. Top-Level Dashboard State
# ══════════════════════════════════════════════════════════════


@dataclass
class DashboardState:
    """Complete dashboard state — returned by data_aggregator.

    This is the union of all data sources polled in the current cycle.
    """
    health: SystemHealthSnapshot = field(default_factory=SystemHealthSnapshot)
    captain: CaptainDisplayState = field(default_factory=CaptainDisplayState)
    execution: ExecutionDisplayState = field(default_factory=ExecutionDisplayState)
    floor_summary: FloorSummaryDisplay = field(default_factory=FloorSummaryDisplay)
    market: MarketDataSnapshot = field(default_factory=MarketDataSnapshot)
    alerts: list[AlertEntry] = field(default_factory=list)
    workspace: WorkspaceState = field(default_factory=WorkspaceState)
    timestamp: datetime = field(default_factory=datetime.utcnow)
