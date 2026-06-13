"""Floor 5 — Captain Engine (Step 5.22).  Main orchestrator.

Consumes Floor 4 inputs (Floor Summary + 6 Head Reports) and runs the
full heavy cycle (24 steps on 1m candle close) or light cycle (5 steps
on every tick) to produce TRADE / WAIT / BLOCKED decisions.

Architecture rules (see ROADMAP_FLOOR_05 Sections 3, 6, 7):
- HEAVY CYCLE: full 24-step analysis on 1m candle close
- LIGHT CYCLE: ultra lightweight on every tick (NO heavy computation)
- permission_gate is called FIRST — if BLOCKED, skip to silence + output
- Captain owns CONVICTION, NOT confidence (confidence = Floor 4)
- Captain does NOT consume Floor 3 packets directly (via Floor 4 only)
- output dispatch: CaptainDecision → Side A, CaptainState → Side B,
  DecisionSnapshot → Side C
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ══════════════════════════════════════════════════════════════════════════
# LIGHT-CYCLE-SAFE IMPORTS  — used by both heavy_cycle() and light_cycle()
# ══════════════════════════════════════════════════════════════════════════

from junior_aladdin.floor_5_captain.active_trade_supervisor import (
    ActiveTradeSupervisor,
)
from junior_aladdin.floor_5_captain.armed_plan_engine import (
    ArmedPlanEngine,
    MarketDataSnapshot,
)
from junior_aladdin.floor_5_captain.captain_types import (
    CaptainInput,
    CaptainState,
    ConfluenceResult,
    ConvictionBand,
    ConvictionScore,
    DecisionState,
    MarketStory,
    NarrativeTimeline,
    OppositeCase,
    PermissionResult,
    SessionPhase,
    SilenceReason,
    conviction_score_to_band,
)
from junior_aladdin.floor_5_captain.intervention_engine import (
    InterventionEngine,
)
from junior_aladdin.floor_5_captain.loss_lock_manager import (
    LossLockManager,
)
from junior_aladdin.floor_5_captain.override_guard import (
    OverrideGuard,
)
from junior_aladdin.floor_5_captain.session_policy import (
    SessionPolicy,
)
from junior_aladdin.floor_5_captain.silence_reason_logger import (
    SilenceReasonLogger,
)
from junior_aladdin.shared.types import (
    CaptainDecision,
    CaptainMood,
    DecisionSnapshot,
    DecisionType,
    ExecutionMode,
    FloorSummary,
    HeadReport,
    TradeClass,
)

# ══════════════════════════════════════════════════════════════════════════
# HEAVY-CYCLE-ONLY IMPORTS  — only used by heavy_cycle() / __init__
# Adding these to light_cycle() would be a CI violation.
# ══════════════════════════════════════════════════════════════════════════

from junior_aladdin.floor_5_captain.confidence_decay_engine import (
    ConfidenceDecayEngine,
)
from junior_aladdin.floor_5_captain.confluence_engine import (
    ConfluenceEngine,
)
from junior_aladdin.floor_5_captain.conviction_engine import (
    ConvictionEngine,
)
from junior_aladdin.floor_5_captain.decision_snapshot_writer import (
    DecisionSnapshotWriter,
    SnapContext,
)
from junior_aladdin.floor_5_captain.market_story_engine import (
    MarketStoryEngine,
)
from junior_aladdin.floor_5_captain.narrative_timeline_engine import (
    NarrativeTimelineEngine,
)
from junior_aladdin.floor_5_captain.opposite_case_engine import (
    OppositeCaseEngine,
)
from junior_aladdin.floor_5_captain.personality_engine import (
    PersonalityEngine,
)
from junior_aladdin.floor_5_captain.permission_gate import (
    PermissionGate,
)
from junior_aladdin.floor_5_captain.setup_expiry_manager import (
    SetupExpiryManager,
)
from junior_aladdin.floor_5_captain.setup_memory_store import (
    SetupMemoryStore,
)
from junior_aladdin.floor_5_captain.trade_class_engine import (
    TradeClassEngine,
)
from junior_aladdin.floor_5_captain.trade_constructor import (
    TradeConstructor,
    TradePlan,
)
from junior_aladdin.floor_5_captain.trade_idea_generator import (
    TradeIdeaGenerator,
)


# ── HeavyCycleOutput (aggregated heavy cycle result) ─────────────────────


@dataclass
class HeavyCycleOutput:
    """Aggregated output from a full heavy cycle execution.

    Fields:
        decision: The final CaptainDecision (for Side A).
        captain_state: Current CaptainState (for Side B dashboard).
        decision_snapshot: Frozen DecisionSnapshot (for Side C memory).
        conviction_score: The computed ConvictionScore.
        market_story: The built MarketStory.
        confluence_result: The computed ConfluenceResult.
        opposite_case: The analyzed OppositeCase.
        permission_result: The PermissionResult from the gate.
        trade_plan: The constructed TradePlan (if TRADE).
        has_trade: Whether a TRADE decision was produced.
        is_blocked: Whether the permission gate blocked.
        execution_time_ms: Approximate heavy cycle duration in ms.
        completed_at: When the heavy cycle finished.
    """
    decision: CaptainDecision | None = None
    captain_state: CaptainState | None = None
    decision_snapshot: DecisionSnapshot | None = None
    conviction_score: ConvictionScore | None = None
    market_story: MarketStory | None = None
    confluence_result: ConfluenceResult | None = None
    opposite_case: OppositeCase | None = None
    permission_result: PermissionResult | None = None
    trade_plan: TradePlan | None = None
    has_trade: bool = False
    is_blocked: bool = False
    execution_time_ms: float = 0.0
    completed_at: datetime = field(default_factory=datetime.utcnow)


# ── LightCycleOutput (aggregated light cycle result) ─────────────────────


@dataclass
class LightCycleOutput:
    """Aggregated output from a light cycle tick.

    Light cycle is intentionally lightweight — only armed plan watching,
    thesis review, and intervention evaluation.

    Fields:
        plan_triggered: Whether an armed plan was triggered.
        triggered_plan_id: ID of the triggered plan (if any).
        intervention_decision: The intervention evaluation result.
        thesis_intact: Whether the active trade thesis is still intact.
        has_concerns: Whether the thesis review found concerns.
        has_active_trade: Whether there is an active trade being monitored.
        checked_at: When the light cycle ran.
    """
    plan_triggered: bool = False
    triggered_plan_id: str = ""
    intervention_decision: Any = None  # InterventionDecision or None
    thesis_intact: bool = True
    has_concerns: bool = False
    has_active_trade: bool = False
    checked_at: datetime = field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════
# CaptainEngine
# ══════════════════════════════════════════════════════════════════════════


class CaptainEngine:
    """Captain's main orchestrator — runs heavy and light cycles.

    Heavy cycle (24 steps) is called on every 1m candle close.
    Light cycle (5 steps) is called on every tick.

    Usage::

        engine = CaptainEngine()

        # Heavy cycle (candle close):
        output = engine.heavy_cycle(
            captain_input=floor_4_input,
            current_price=19550.0,
            current_mode=ExecutionMode.PAPER,
            capital_available=50000.0,
            candle_index=142,
        )

        if output.has_trade:
            # Forward output.decision → Side A
            # Forward output.captain_state → Side B dashboard
            # Forward output.decision_snapshot → Side C memory
            pass

        # Light cycle (every tick):
        tick_output = engine.light_cycle(
            current_price=19551.0,
            candle_index=142,
        )
        if tick_output.plan_triggered:
            # Forward triggered plan → execution
            pass
    """

    def __init__(self) -> None:
        """Initialize the Captain Engine with all sub-engines.

        Creates instances of every module in the correct dependency order.
        """
        # Phase A: Foundation engines (no dependencies on each other)
        self.session_policy = SessionPolicy()
        self.loss_lock_manager = LossLockManager()
        self.override_guard = OverrideGuard()
        self.setup_memory = SetupMemoryStore()
        self.silence_logger = SilenceReasonLogger()
        self.snapshot_writer = DecisionSnapshotWriter()
        self.narrative_timeline = NarrativeTimelineEngine()
        self.active_trade_supervisor = ActiveTradeSupervisor()
        self.intervention_engine = InterventionEngine()

        # Phase B: Engines with simple dependencies
        self.permission_gate = PermissionGate(
            session_policy=self.session_policy,
            loss_lock_manager=self.loss_lock_manager,
            override_guard=self.override_guard,
        )
        self.market_story_engine = MarketStoryEngine(
            session_policy=self.session_policy,
        )

        # Phase C: Independent analysis engines
        self.confluence_engine = ConfluenceEngine()
        self.opposite_case_engine = OppositeCaseEngine()
        self.conviction_engine = ConvictionEngine()
        self.personality_engine = PersonalityEngine()
        self.trade_class_engine = TradeClassEngine()
        self.trade_idea_generator = TradeIdeaGenerator()
        self.setup_expiry = SetupExpiryManager()
        self.confidence_decay = ConfidenceDecayEngine()

        # Phase D: Engines with multiple dependencies
        self.armed_plan_engine = ArmedPlanEngine(
            setup_store=self.setup_memory,
        )
        self.trade_constructor = TradeConstructor(
            trade_class_engine=self.trade_class_engine,
        )

        # ── Runtime state ─────────────────────────────────────────────
        self._active_trade: CaptainDecision | None = None
        self._current_story: MarketStory | None = None
        self._current_confluence: ConfluenceResult | None = None
        self._current_permission: PermissionResult | None = None
        self._current_scores: ConvictionScore | None = None
        self._current_opposite: OppositeCase | None = None
        self._current_trade_idea: Any = None
        self._current_trade_class_assignment: Any = None
        self._candle_index: int = 0
        self._session_start: datetime | None = None
        self._cycles_without_trade: int = 0
        self._recent_loss: bool = False
        self._recent_loss_cycles: int = 0
        self._cooldown_remaining: int = 0

    # ══════════════════════════════════════════════════════════════════
    # HEAVY CYCLE (24 steps, called on 1m candle close)
    # ══════════════════════════════════════════════════════════════════

    def heavy_cycle(
        self,
        captain_input: CaptainInput | None = None,
        current_price: float = 0.0,
        current_mode: ExecutionMode = ExecutionMode.PAPER,
        capital_available: float = 0.0,
        candle_index: int = 0,
        timestamp: datetime | None = None,
        atm_strike: float = 19500.0,
        lot_size: int = 50,
        zone_info: dict[str, Any] | None = None,
    ) -> HeavyCycleOutput:
        """Run the full 24-step heavy cycle on every 1m candle close.

        Args:
            captain_input: The Floor 4 input with FloorSummary + head_reports + system_context.
            current_price: Current market price for this candle.
            current_mode: Current execution mode (ALERT / PAPER / REAL).
            capital_available: Available trading capital.
            candle_index: Current 1m candle index from session start.
            timestamp: Override timestamp for deterministic testing.
                If None, uses ``datetime.utcnow()``.
            atm_strike: Current ATM strike price for trade construction.
            lot_size: Contract lot size for premium estimation.
            zone_info: Optional zone info (label, price, type) for trade construction.

        Returns:
            A ``HeavyCycleOutput`` with all cycle results and the final decision.
        """
        start_time = timestamp or datetime.utcnow()
        self._candle_index = candle_index
        inp = captain_input or CaptainInput()
        floor_summary = inp.floor_summary
        head_reports = inp.head_reports
        system_ctx = inp.system_context
        dt = start_time

        # Determine session phase
        session_phase = self.session_policy.get_session_phase(dt)

        # ── Step 0a: Daily loss counter reset ─────────────────────────
        self.loss_lock_manager.check_and_reset_if_new_day(dt.date())

        # ── Step 1: Permission Gate ──────────────────────────────────
        psychology_report = head_reports.get("Psychology Head") if head_reports else None
        permission_result = self.permission_gate.check_all(
            timestamp=dt,
            floor_summary=floor_summary,
            psychology_report=psychology_report,
            active_trade=self._active_trade is not None,
            current_mode=current_mode,
            capital_available=capital_available,
        )
        self._current_permission = permission_result

        # ── Step 2: If BLOCKED → log silence, skip to output ─────────
        is_blocked = not permission_result.allowed
        if is_blocked:
            decision, captain_state = self._handle_blocked(
                permission_result=permission_result,
                psychology_report=psychology_report,
                session_phase=session_phase,
            )
            return HeavyCycleOutput(
                decision=decision,
                captain_state=captain_state,
                permission_result=permission_result,
                is_blocked=True,
                execution_time_ms=self._elapsed_ms(start_time),
                completed_at=datetime.utcnow(),
            )

        # ── Step 3a: Capture previous regime for shift detection ────
        previous_regime = self._current_story.regime if self._current_story else None

        # ── Step 3b: Market Story Engine ────────────────────────────
        market_story = self.market_story_engine.build_story(
            floor_summary=floor_summary,
            head_reports=head_reports,
            timestamp=dt,
        )
        self._current_story = market_story

        # ── Step 4: Narrative Timeline Update + Regime Shift Detection ─
        self.narrative_timeline.add_event(
            event_type="milestone",
            details=f"Candle {candle_index} — {market_story.regime} regime, "
                    f"{market_story.bias} bias",
            price_level=current_price,
            timestamp=dt,
        )
        self.narrative_timeline.update_from_market_story(
            regime=market_story.regime,
            session_phase=session_phase.value,
            previous_regime=previous_regime,
        )

        # ── Step 5: Read Floor Summary FIRST (summary-first workflow) ─
        # Already done — floor_summary is available from input.

        # ── Step 6: Decide drill-down necessity ─────────────────────
        needs_drill_down = self._decide_drill_down(
            floor_summary=floor_summary,
            head_reports=head_reports,
        )

        # ── Step 7: If drill-down needed — mark as examined ──────────
        # In production, this would trigger head-level report reading.
        # For now, we track the decision for snapshot context.
        drill_down_reports: dict[str, Any] = {}
        if needs_drill_down and head_reports:
            # Extract individual head details for deeper context
            for name, report in head_reports.items():
                if name != "Psychology Head":
                    drill_down_reports[name] = {
                        "bias": report.bias.value,
                        "confidence": report.confidence,
                        "state": report.state.value,
                        "freshness_tag": report.freshness_tag.value,
                    }

        # ── Step 8: Apply report trust weighting ────────────────────
        # ConfluenceEngine handles this internally via _compute_trust_weight.

        # ── Step 9: Apply stale core head logic ─────────────────────
        core_heads_stale = self._check_stale_core_heads(head_reports)
        # core_heads_stale feeds into conviction adjustment at Step 13a

        # ── Step 10: Evaluate NO_SETUP intelligence ─────────────────
        setup_presence = self._evaluate_setup_presence(floor_summary)
        # setup_presence feeds into conviction adjustment at Step 13a

        # ── Step 11: Confluence Engine ──────────────────────────────
        confluence_result = self.confluence_engine.compute_confluence(
            head_reports=head_reports,
            timestamp=dt,
        )
        self._current_confluence = confluence_result

        # ── Step 12: Opposite Case Engine ───────────────────────────
        trade_direction = self._direction_from_confluence(confluence_result)
        opposite_case = self.opposite_case_engine.analyze(
            proposed_direction=trade_direction,
            head_reports=head_reports,
            timestamp=dt,
        )
        self._current_opposite = opposite_case

        # ── Step 13: Conviction Engine ──────────────────────────────
        conviction_scores = self.conviction_engine.compute_scores(
            permission_result=permission_result,
            confluence_result=confluence_result,
            opposite_case=opposite_case,
            market_story=market_story,
            psychology_report=psychology_report,
            session_policy=self.session_policy,
            timestamp=dt,
        )
        self._current_scores = conviction_scores

        # ── Step 14: Trade Idea Generator ───────────────────────────
        trade_idea = self.trade_idea_generator.generate_idea(
            confluence_result=confluence_result,
            market_story=market_story,
            conviction_score=conviction_scores,
            psychology_report=psychology_report,
            timestamp=dt,
        )
        self._current_trade_idea = trade_idea

        # ── Step 14a: Personality Engine (mood determination) ────────
        # Called early so mood is available for trade class selection
        # and decision snapshot (V2 plan Section 41: mood BEFORE trade class).
        mood = self.personality_engine.determine_mood(
            conviction_band=conviction_scores.conviction_band
            if conviction_scores else ConvictionBand.REJECT,
            session_phase=session_phase,
            market_story=market_story,
            active_trade_exists=self._active_trade is not None,
            permission_allowed=permission_result.allowed,
            has_setups=trade_idea is not None and bool(trade_idea.direction),
            recent_loss=self._recent_loss,
        )

        # ── Step 15: Trade Class Engine ─────────────────────────────
        trade_class_assignment = self.trade_class_engine.assign_trade_class(
            trade_idea=trade_idea,
            market_story=market_story,
            confluence_result=confluence_result,
        )
        self._current_trade_class_assignment = trade_class_assignment

        # ── Step 13a: Apply stale-core-head + NO_SETUP adjustments ───
        # These signals were computed earlier but need to modify scores
        # after conviction_engine runs since it doesn't accept them as
        # direct inputs.
        if conviction_scores:
            # Stale core head penalty: SMC/ICT stale → reduce conviction
            if core_heads_stale:
                # Core structural heads stale — significantly reduce faith
                penalty = 15.0 if conviction_scores.conviction_band in (
                    ConvictionBand.TRADABLE, ConvictionBand.STRONG, ConvictionBand.ELITE,
                ) else 5.0
                conviction_scores.conviction_score = max(0.0, conviction_scores.conviction_score - penalty)
                conviction_scores.no_trade_score = min(100.0, conviction_scores.no_trade_score + penalty * 0.5)

            # NO_SETUP intelligence: adjust no-trade score
            if setup_presence == "STALE_NO_SETUP":
                # Stale silence — heads can't be trusted, increase caution
                conviction_scores.no_trade_score = min(100.0, conviction_scores.no_trade_score + 20.0)
                conviction_scores.conviction_score = max(0.0, conviction_scores.conviction_score - 5.0)
            elif setup_presence == "UNCERTAIN_NO_SETUP":
                # Uncertain silence — not healthy, increase caution modestly
                conviction_scores.no_trade_score = min(100.0, conviction_scores.no_trade_score + 10.0)

            # Recompute conviction band after all adjustments
            conviction_scores.conviction_band = conviction_score_to_band(
                conviction_scores.conviction_score,
            )

        # ── Step 16: Setup Memory Store Update ──────────────────────
        if trade_idea and trade_idea.direction:
            self._update_setup_memory(
                trade_idea=trade_idea,
                confluence_result=confluence_result,
            )

        # ── Step 17: Armed Plan Engine (build/update) ───────────────
        trade_class_obj = (
            trade_class_assignment.trade_class
            if trade_class_assignment
            else None
        )
        if trade_idea and trade_idea.direction and trade_class_obj and self._cooldown_remaining <= 0:
            self._build_armed_plan(
                direction=trade_idea.direction,
                trade_class=trade_class_obj,
                confluence_result=confluence_result,
                current_price=current_price,
                zone_info=zone_info,
            )

        # ── Step 18: Setup Expiry Manager — purge expired plans ─────
        active_plans = self.armed_plan_engine.get_active_plans()
        expired_plans = self.setup_expiry.purge_expired(
            items=active_plans,
            current_candle_index=candle_index,
        )
        for expired in expired_plans:
            self.armed_plan_engine.expire_plan(expired.plan_id)

        # ── Step 19: Confidence Decay Engine ───────────────────────
        # Gradually lowers conviction as cycles pass without a trade.
        # Different trade classes decay at different rates.
        if conviction_scores and self._cycles_without_trade > 0:
            decay_result = self.confidence_decay.apply_decay(
                conviction_score=conviction_scores.conviction_score,
                trade_class=trade_class_obj,
                elapsed_candles=self._cycles_without_trade,
            )
            conviction_scores.conviction_score = decay_result.decayed_score
            conviction_scores.conviction_band = conviction_score_to_band(
                decay_result.decayed_score,
            )

        # ── Step 20: Active Trade Supervisor Review (if active) ─────
        if self._active_trade is not None:
            self.active_trade_supervisor.review_thesis(
                active_trade=self._active_trade,
                current_market_story=market_story,
                current_price=current_price,
                zone_price=(zone_info or {}).get("price", 0.0),
                zone_label=(zone_info or {}).get("label", ""),
                current_confluence=confluence_result,
                original_confluence_direction=confluence_result.dominant_direction
                if confluence_result else "",
            )

        # ── Step 21: Trade Constructor (if TRADE approved) ──────────
        # Decrement cooldown counter each cycle (stays at 0)
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        trade_plan: TradePlan | None = None
        if self._cooldown_remaining > 0:
            should_trade = False  # Cooldown active — no new trades
        else:
            should_trade = self._should_trade(conviction_scores)

        if should_trade and trade_direction:
            trade_plan = self.trade_constructor.construct_trade(
                direction=trade_direction,
                trade_class_assignment=trade_class_assignment,
                conviction_score=conviction_scores,
                confluence_result=confluence_result,
                market_story=market_story,
                capital_limit=capital_available,
                atm_strike=atm_strike,
                lot_size=lot_size,
                current_price=current_price,
                zone_info=zone_info,
            )

        # ── Auto-clear recent_loss after 5 cycles without a new loss ─
        if self._recent_loss:
            self._recent_loss_cycles += 1
            if self._recent_loss_cycles >= 5:
                self._recent_loss = False
                self._recent_loss_cycles = 0

        # ── Step 22a: Build Final Decision first (temp snapshot_id) ──
        decision = self._build_decision(
            trade_plan=trade_plan,
            conviction_scores=conviction_scores,
            market_story=market_story,
            mood=mood,
            snapshot_id="",
        )

        # ── Step 22b: Decision Snapshot with REAL decision content ──
        snapshot = self._write_snapshot(
            decision=decision,
            market_story=market_story,
            confluence_result=confluence_result,
            conviction_scores=conviction_scores,
            trade_plan=trade_plan,
            opposite_case=opposite_case,
            mood=mood,
            drill_down_reports=drill_down_reports,
            session_phase=session_phase,
            permission_result=permission_result,
        )

        # ── Link decision to snapshot ──────────────────────────────
        decision.snapshot_id = snapshot.snapshot_id

        # ── Step 23: Silence Reason Logger (if no trade) ───────────
        if not should_trade or not trade_plan or not trade_plan.is_constructable:
            self._log_silence_reason(
                decision=decision,
                conviction_scores=conviction_scores,
                opposite_case=opposite_case,
                confluence_result=confluence_result,
                market_story=market_story,
            )

        # ── Update active trade state ──────────────────────────────
        if should_trade and trade_plan and trade_plan.is_constructable:
            self._active_trade = decision
            self._cycles_without_trade = 0  # Reset decay counter on trade
        else:
            self._cycles_without_trade += 1  # Increment decay counter

        # ── Build CaptainState for Side B ──────────────────────────
        captain_state = self._build_captain_state(
            mood=mood,
            decision=decision,
            conviction_scores=conviction_scores,
            market_story=market_story,
            session_phase=session_phase,
        )

        return HeavyCycleOutput(
            decision=decision,
            captain_state=captain_state,
            decision_snapshot=snapshot,
            conviction_score=conviction_scores,
            market_story=market_story,
            confluence_result=confluence_result,
            opposite_case=opposite_case,
            permission_result=permission_result,
            trade_plan=trade_plan,
            has_trade=decision.decision == DecisionType.TRADE
            if decision else False,
            is_blocked=False,
            execution_time_ms=self._elapsed_ms(start_time),
            completed_at=datetime.utcnow(),
        )

    # ── Heavy Cycle: Steps 2 (Blocked Path) ─────────────────────────────

    def _handle_blocked(
        self,
        permission_result: PermissionResult,
        psychology_report: HeadReport | None,
        session_phase: SessionPhase,
    ) -> tuple[CaptainDecision, CaptainState]:
        """Handle a BLOCKED permission gate result.

        Logs the silence reason and produces a BLOCKED decision.

        Args:
            permission_result: The blocking PermissionResult.
            psychology_report: Psychology Head report (for psych block detection).
            session_phase: Current session phase.

        Returns:
            Tuple of ``(CaptainDecision, CaptainState)``.
        """
        # Determine the silence reason from the first block
        blocked_by = permission_result.blocked_by
        silence_reason = SilenceReason.PSYCHOLOGY_BLOCK

        if "active_trade" in blocked_by:
            silence_reason = SilenceReason.ACTIVE_TRADE_EXISTS
        elif "real_mode_lock" in blocked_by:
            silence_reason = SilenceReason.REAL_MODE_LOCK
        elif "psychology_block" in blocked_by:
            silence_reason = SilenceReason.PSYCHOLOGY_BLOCK
        elif "data_health" in blocked_by:
            silence_reason = SilenceReason.DEAD_MARKET
        elif "capital_availability" in blocked_by:
            silence_reason = SilenceReason.CAPITAL_MISMATCH
        elif "session_policy" in blocked_by:
            silence_reason = SilenceReason.DEAD_MARKET
        elif "market_open" in blocked_by:
            silence_reason = SilenceReason.DEAD_MARKET
        elif "mode_validation" in blocked_by:
            silence_reason = SilenceReason.CAPITAL_MISMATCH

        self.silence_logger.log_reason(
            decision="BLOCKED",
            reason=silence_reason,
            details=permission_result.block_reason,
            source="permission_gate",
        )

        decision = CaptainDecision(
            decision=DecisionType.BLOCKED,
            action="",
            option_side="",
            selected_strike="",
            trade_class=TradeClass.SCALP,
            reason_summary=permission_result.block_reason,
            silence_reason=silence_reason.value,
        )

        captain_state = self._build_captain_state(
            mood=CaptainMood.OBSERVER,
            decision=decision,
            conviction_scores=None,
            market_story=None,
            session_phase=session_phase,
        )

        return decision, captain_state

    # ── Heavy Cycle: Step 6 (Drill-Down Decision) ───────────────────────

    @staticmethod
    def _decide_drill_down(
        floor_summary: FloorSummary | None,
        head_reports: dict[str, HeadReport] | None,
    ) -> bool:
        """Decide whether drill-down into individual head reports is needed.

        Drill-down is required when:
        - Conflict is present among heads
        - Core heads (SMC/ICT) are stale
        - Setup presence is UNCERTAIN_NO_SETUP or STALE_NO_SETUP
        - High conviction candidate requires deeper validation

        Args:
            floor_summary: Current Floor Summary.
            head_reports: Dict of head reports (may be partial or None).

        Returns:
            True if drill-down is warranted.
        """
        if floor_summary is None:
            return True  # No summary — drill down for safety

        # Conflict → drill-down
        if floor_summary.conflict_present:
            return True

        # Stale warning → drill-down (may affect core heads)
        if floor_summary.stale_warning_present:
            return True

        # Stale core head (SMC/ICT) → drill-down
        if floor_summary.core_head_health_snapshot:
            for head_name in ("SMC Head", "ICT Head"):
                health = floor_summary.core_head_health_snapshot.get(head_name, {})
                if isinstance(health, dict) and health.get("state") in ("STALE", "UNCERTAIN"):
                    return True

        # Check setup presence context
        if floor_summary.setup_absence_context in ("UNCERTAIN_NO_SETUP", "STALE_NO_SETUP"):
            return True

        # High confidence candidate — drill-down for validation
        if floor_summary.floor_confidence_snapshot:
            avg_conf = floor_summary.floor_confidence_snapshot.get("average_confidence", 0.0)
            if avg_conf >= 0.8:
                return True  # High confidence — verify with detailed head data

        return False

    # ── Heavy Cycle: Step 9 (Stale Core Heads) ──────────────────────────

    @staticmethod
    def _check_stale_core_heads(
        head_reports: dict[str, HeadReport] | None,
    ) -> bool:
        """Check if core heads (SMC, ICT) are stale.

        Args:
            head_reports: Dict of head reports.

        Returns:
            True if either SMC or ICT head is stale.
        """
        if head_reports is None:
            return False

        for name in ("SMC Head", "ICT Head"):
            report = head_reports.get(name)
            if report is not None and report.state.value == "STALE":
                return True

        return False

    # ── Heavy Cycle: Step 10 (NO_SETUP Intelligence) ────────────────────

    @staticmethod
    def _evaluate_setup_presence(
        floor_summary: FloorSummary | None,
    ) -> str:
        """Evaluate the NO_SETUP intelligence from Floor Summary.

        Distinguishes between:
        - READY_NO_SETUP: Heads are ready but no setup found (healthy patience)
        - UNCERTAIN_NO_SETUP: Heads uncertain — wait for clarity
        - STALE_NO_SETUP: Heads stale — need fresh data
        - HAS_SETUP: Setups exist

        Args:
            floor_summary: Current Floor Summary.

        Returns:
            Setup presence string: ``HAS_SETUP``, ``READY_NO_SETUP``,
            ``UNCERTAIN_NO_SETUP``, ``STALE_NO_SETUP``, or ``UNKNOWN``.
        """
        if floor_summary is None:
            return "UNKNOWN"

        # If setup_presence is directly available in FloorSummary, use it
        presence = getattr(floor_summary, "setup_presence", None)
        if presence is not None:
            return presence

        # Fallback: infer from head states
        if floor_summary.active_setup_count > 0:
            return "HAS_SETUP"

        if floor_summary.setup_absence_context:
            return floor_summary.setup_absence_context

        # Infer from head counts
        if floor_summary.ready_heads_count >= 3:
            return "READY_NO_SETUP"
        if floor_summary.uncertain_heads_count >= 2:
            return "UNCERTAIN_NO_SETUP"
        if floor_summary.stale_heads_count >= 2:
            return "STALE_NO_SETUP"

        return "UNKNOWN"

    # ── Heavy Cycle: Step 16 (Setup Memory Update) ──────────────────────

    def _update_setup_memory(
        self,
        trade_idea: Any,
        confluence_result: ConfluenceResult | None,
    ) -> None:
        """Update setup memory store with the current trade idea.

        Args:
            trade_idea: The TradeIdea from trade_idea_generator.
            confluence_result: Confluence result for setup source.
        """
        if not trade_idea.direction:
            return

        source = trade_idea.setup_source or (
            confluence_result.aligned_heads[0]
            if confluence_result and confluence_result.aligned_heads
            else "unknown"
        )

        self.setup_memory.store_setup(
            setup_id=f"hc_{self._candle_index}_{trade_idea.direction}",
            direction=trade_idea.direction,
            trade_class=trade_idea.trade_class_suggestion,
            source_head=source,
        )

    # ── Heavy Cycle: Step 17 (Armed Plan Build) ─────────────────────────

    def _build_armed_plan(
        self,
        direction: str,
        trade_class: TradeClass,
        confluence_result: ConfluenceResult,
        current_price: float,
        zone_info: dict[str, Any] | None = None,
    ) -> None:
        """Build an armed conditional plan from heavy cycle outputs.

        Args:
            direction: Trade direction (BUY/SELL).
            trade_class: Assigned TradeClass.
            confluence_result: Confluence result (for originating heads).
            current_price: Current price for trigger conditions.
            zone_info: Optional zone info for trigger/expiry conditions.
        """
        zone = zone_info or {}
        zone_price = zone.get("price", current_price)

        # Build trigger condition based on trade direction
        if direction == "BUY":
            trigger = {"type": "above", "level": zone_price}
            invalidation = zone_price * 0.995  # 0.5% below
        else:
            trigger = {"type": "below", "level": zone_price}
            invalidation = zone_price * 1.005  # 0.5% above

        # Expiry condition based on trade class
        expiry_candles = self.setup_expiry.get_expiry_candles(trade_class)
        if expiry_candles > 0:
            expiry = {
                "type": "candles",
                "count": expiry_candles,
                "created_at_candle": self._candle_index,
            }
        else:
            expiry = {
                "type": "time",
                "minutes": 30,  # Fallback: 30-minute expiry
            }

        self.armed_plan_engine.create_plan(
            direction=direction,
            setup_class=trade_class.value,
            trigger_condition=trigger,
            expiry_condition=expiry,
            invalidation_level=invalidation,
            originating_heads=confluence_result.aligned_heads,
            zone_label=zone.get("label", ""),
            candle_index=self._candle_index,
        )

    # ── Heavy Cycle: Step 21 (Should Trade?) ────────────────────────────

    @staticmethod
    def _should_trade(
        conviction_scores: ConvictionScore | None,
    ) -> bool:
        """Determine if the system should proceed to trade construction.

        A trade is considered viable when conviction is TRADABLE+ and
        the no-trade score doesn't dominate.

        Args:
            conviction_scores: The computed ConvictionScore.

        Returns:
            True if the system should proceed to trade construction.
        """
        if conviction_scores is None:
            return False

        band = conviction_scores.conviction_band
        if band not in (
            ConvictionBand.TRADABLE,
            ConvictionBand.STRONG,
            ConvictionBand.ELITE,
        ):
            return False

        # No-trade score must not dominate — conviction MUST be the stronger signal
        return conviction_scores.conviction_score > conviction_scores.no_trade_score

    # ── Heavy Cycle: Step 22 (Decision Snapshot) ────────────────────────

    def _write_snapshot(
        self,
        decision: CaptainDecision,
        market_story: MarketStory | None,
        confluence_result: ConfluenceResult | None,
        conviction_scores: ConvictionScore | None,
        trade_plan: TradePlan | None,
        opposite_case: OppositeCase | None,
        mood: CaptainMood,
        drill_down_reports: dict[str, Any] | None = None,
        session_phase: SessionPhase = SessionPhase.OPENING,
        permission_result: PermissionResult | None = None,
    ) -> DecisionSnapshot:
        """Write a decision snapshot for audit / Side C.

        Args:
            decision: The final CaptainDecision.
            market_story: Current MarketStory.
            confluence_result: ConfluenceResult.
            conviction_scores: ConvictionScore.
            trade_plan: The TradePlan (if any).
            opposite_case: OppositeCase.
            mood: Current CaptainMood.
            drill_down_reports: Detailed head report data (if drill-down was performed).
            session_phase: Current session phase.
            permission_result: PermissionResult.

        Returns:
            The frozen ``DecisionSnapshot``.
        """
        context = SnapContext(
            market_story_summary=market_story.summary if market_story else "",
            narrative_timeline_excerpt=self.narrative_timeline.get_excerpt(
                max_events=3,
                include_labels=True,
            ),
            heads_summary=drill_down_reports or {},
            armed_plan_reference=self._get_armed_plan_ref(),
            conviction_score=conviction_scores.conviction_score if conviction_scores else 0.0,
            invalidation={
                "level": trade_plan.invalidation_level if trade_plan else 0.0,
                "stop_loss": trade_plan.stop_loss_plan if trade_plan else {},
                "opposite_strength": opposite_case.strength if opposite_case else 0.0,
            },
            decision_reason=decision.reason_summary if decision else "",
            silence_reason=decision.silence_reason if decision else "",
            session_context={
                "session_phase": session_phase.value,
                "regime": market_story.regime if market_story else "",
                "bias": market_story.bias if market_story else "",
                "candle_index": self._candle_index,
                "permission_allowed": permission_result.allowed if permission_result else False,
            },
            capital_context={
                "permission_score": conviction_scores.permission_score if conviction_scores else 0.0,
                "no_trade_score": conviction_scores.no_trade_score if conviction_scores else 0.0,
            },
            mood=mood,
        )
        return self.snapshot_writer.write_snapshot(context)

    # ── Heavy Cycle: Step 23 (Silence Reason Logger) ────────────────────

    def _log_silence_reason(
        self,
        decision: CaptainDecision,
        conviction_scores: ConvictionScore | None,
        opposite_case: OppositeCase | None,
        confluence_result: ConfluenceResult | None,
        market_story: MarketStory | None,
    ) -> None:
        """Log structured silence reasons when no trade is produced.

        Args:
            decision: The CaptainDecision (WAIT or REJECT).
            conviction_scores: Computed ConvictionScore.
            opposite_case: OppositeCase analysis.
            confluence_result: ConfluenceResult.
            market_story: Current market story.
        """
        silence_reason = SilenceReason.WEAK_CONVICTION
        details = ""

        if conviction_scores is None:
            silence_reason = SilenceReason.INSUFFICIENT_CONFLUENCE
            details = "No conviction scores computed"
        elif conviction_scores.conviction_band in (
            ConvictionBand.REJECT, ConvictionBand.WEAK
        ):
            if opposite_case and opposite_case.strength > 0.7:
                silence_reason = SilenceReason.WEAK_CONVICTION
                details = f"Opposite case dominates (strength: {opposite_case.strength:.2f})"
            elif confluence_result and confluence_result.conflict_present:
                silence_reason = SilenceReason.INSUFFICIENT_CONFLUENCE
                details = "Heads in conflict — insufficient confluence"
            elif conviction_scores.no_trade_score > conviction_scores.conviction_score:
                silence_reason = SilenceReason.WEAK_CONVICTION
                details = "No-trade score exceeds conviction score"
            else:
                details = f"Conviction too low ({conviction_scores.conviction_band.value}, {conviction_scores.conviction_score:.0f})"
        elif market_story and market_story.regime in ("CHOP", "UNCLEAR"):
            silence_reason = SilenceReason.DEAD_MARKET
            details = f"Choppy / unclear market regime ({market_story.regime})"
        else:
            details = f"No viable setup found (conviction: {conviction_scores.conviction_band.value if conviction_scores else 'N/A'})"

        self.silence_logger.log_reason(
            decision="WAIT",
            reason=silence_reason,
            details=details,
            source="captain_engine",
        )

    # ══════════════════════════════════════════════════════════════════
    # LIGHT CYCLE (5 steps, called on every tick)
    # ══════════════════════════════════════════════════════════════════

    def light_cycle(
        self,
        current_price: float = 0.0,
        candle_index: int = 0,
        regime: str = "",
        opposite_case_strength: float = 0.0,
        options_oi_healthy: bool = True,
        data_health_critical: bool = False,
        risk_event_detected: bool = False,
    ) -> LightCycleOutput:
        """Run the lightweight light cycle on every tick.

        Does NOT perform heavy computation — only watches armed plans,
        reviews active trade thesis, and evaluates intervention need.

        Args:
            current_price: Current tick price.
            candle_index: Current candle index (for plan expiry).
            regime: Current market regime (from latest heavy cycle).
            opposite_case_strength: Current opposite case strength (0.0-1.0).
            options_oi_healthy: Whether options OI looks healthy.
            data_health_critical: Whether data feed is CRITICAL.
            risk_event_detected: Whether a risk event was flagged.

        Returns:
            A ``LightCycleOutput`` with tick-level results.
        """
        market_data = MarketDataSnapshot(
            price=current_price,
            timestamp=datetime.utcnow(),
        )

        # ── Step 1: Watch Armed Plans ──────────────────────────────
        watch_result = self.armed_plan_engine.watch_plans(
            market_data=market_data,
            candle_index=candle_index,
        )

        # ── Step 2: Active Trade Thesis Review ─────────────────────
        thesis_intact = True
        has_concerns = False
        if self._active_trade is not None:
            # Light thesis review (quick check only)
            has_concerns = self.active_trade_supervisor.should_intervene()
            latest = self.active_trade_supervisor.get_latest_review()
            if latest is not None:
                thesis_intact = latest.thesis_intact
                has_concerns = len(latest.concerns) > 0

        # ── Step 3: Intervention Review ────────────────────────────
        intervention_decision = None
        if self._active_trade is not None:
            intervention_decision = self.intervention_engine.evaluate_intervention(
                supervisor=self.active_trade_supervisor,
                active_trade=self._active_trade,
                current_price=current_price,
                regime=regime,
                opposite_case_strength=opposite_case_strength,
                options_oi_healthy=options_oi_healthy,
                data_health_critical=data_health_critical,
                risk_event_detected=risk_event_detected,
            )

        # ── Step 4: Output on Trigger ──────────────────────────────
        triggered_plan_id = ""
        if watch_result.has_trigger and watch_result.triggered_plans:
            triggered_plan_id = watch_result.triggered_plans[0].plan_id

        # ── Step 5: Output on Intervention ─────────────────────────
        # (Handled by parent — the intervention decision is returned)

        return LightCycleOutput(
            plan_triggered=watch_result.has_trigger,
            triggered_plan_id=triggered_plan_id,
            intervention_decision=intervention_decision,
            thesis_intact=thesis_intact,
            has_concerns=has_concerns,
            has_active_trade=self._active_trade is not None,
            checked_at=datetime.utcnow(),
        )

    # ══════════════════════════════════════════════════════════════════
    # Decision & State Builders
    # ══════════════════════════════════════════════════════════════════

    def _build_decision(
        self,
        trade_plan: TradePlan | None,
        conviction_scores: ConvictionScore | None,
        market_story: MarketStory | None,
        mood: CaptainMood = CaptainMood.OBSERVER,
        snapshot_id: str = "",
    ) -> CaptainDecision:
        """Build the final CaptainDecision from heavy cycle outputs.

        Args:
            trade_plan: The TradePlan (if constructed).
            conviction_scores: Current ConvictionScore.
            market_story: Current market story (for reason context).
            mood: Current CaptainMood.
            snapshot_id: Pre-generated snapshot ID for linking.

        Returns:
            A fully populated ``CaptainDecision``.
        """
        if trade_plan and trade_plan.is_constructable:
            return self.trade_constructor.to_captain_decision(
                plan=trade_plan,
                conviction_score=conviction_scores,
                reason_summary=(
                    f"TRADE {trade_plan.direction} {trade_plan.option_side} "
                    f"{trade_plan.selected_strike} [{trade_plan.strike_type}]"
                    f" | Class: {trade_plan.trade_class.value if trade_plan.trade_class else '?'}"
                    f" | Regime: {market_story.regime if market_story else '?'}"
                ),
                snapshot_id=snapshot_id,
            )

        # No trade — produce WAIT decision
        band = conviction_scores.conviction_band if conviction_scores else ConvictionBand.REJECT
        return CaptainDecision(
            decision=DecisionType.WAIT,
            action="",
            option_side="",
            selected_strike="",
            trade_class=TradeClass.SCALP,
            permission_score=conviction_scores.permission_score if conviction_scores else 0.0,
            conviction_score=conviction_scores.conviction_score if conviction_scores else 0.0,
            no_trade_score=conviction_scores.no_trade_score if conviction_scores else 0.0,
            reason_summary=(
                f"WAIT — {band.value} conviction"
                f" ({conviction_scores.conviction_score:.0f}/{conviction_scores.no_trade_score:.0f})"
                if conviction_scores else "WAIT — No conviction data"
            ),
            silence_reason=band.value,
        )

    def _build_captain_state(
        self,
        mood: CaptainMood,
        decision: CaptainDecision,
        conviction_scores: ConvictionScore | None,
        market_story: MarketStory | None,
        session_phase: SessionPhase,
    ) -> CaptainState:
        """Build CaptainState for Side B dashboard.

        Args:
            mood: Current CaptainMood.
            decision: The final CaptainDecision.
            conviction_scores: Current ConvictionScore.
            market_story: Current MarketStory.
            session_phase: Current session phase.

        Returns:
            A fully populated ``CaptainState``.
        """
        band = conviction_scores.conviction_band if conviction_scores else ConvictionBand.REJECT
        return CaptainState(
            mood=mood,
            active_trade=decision.decision == DecisionType.TRADE,
            decision_state=DecisionState.TRADE
            if decision.decision == DecisionType.TRADE
            else DecisionState.WAIT,
            conviction_band=band,
            market_story_summary=market_story.summary if market_story else "",
            silence_reason=decision.silence_reason or "",
            session_phase=session_phase,
            real_mode_locked=self.loss_lock_manager.is_locked()
        )

    # ══════════════════════════════════════════════════════════════════
    # Query Methods
    # ══════════════════════════════════════════════════════════════════

    def get_active_trade(self) -> CaptainDecision | None:
        """Get the currently active trade, if any.

        Returns:
            The active ``CaptainDecision``, or None.
        """
        return self._active_trade

    def get_current_state(self) -> dict[str, Any]:
        """Get a summary of the engine's current runtime state.

        Returns:
            Dict with key runtime state fields.
        """
        latest_snap = self.snapshot_writer.get_latest_snapshot()
        return {
            "has_active_trade": self._active_trade is not None,
            "active_plans": self.armed_plan_engine.get_plan_count(),
            "snapshot_count": self.snapshot_writer.get_snapshot_count(),
            "silence_count": self.silence_logger.get_reason_count(),
            "candle_index": self._candle_index,
            "latest_snapshot_id": latest_snap.snapshot_id if latest_snap else "",
        }

    def get_engine_summary(self) -> dict[str, Any]:
        """Get a comprehensive summary of all engine subsystems.

        Returns:
            Dict with subsystem summaries.
        """
        latest_snap = self.snapshot_writer.get_latest_snapshot()
        return {
            "armed_plans": self.armed_plan_engine.get_engine_summary(),
            "setup_memory": self.setup_memory.get_store_summary(),
            "silence_logger": self.silence_logger.get_logger_summary(),
            "snapshot_writer": {
                "total_snapshots": self.snapshot_writer.get_snapshot_count(),
                "latest_id": latest_snap.snapshot_id if latest_snap else "",
            },
            "narrative_timeline": self.narrative_timeline.get_timeline_summary(),
            "active_trade": self._active_trade is not None,
            "candle_index": self._candle_index,
        }

    # ══════════════════════════════════════════════════════════════════
    # Session Management
    # ══════════════════════════════════════════════════════════════════

    def start_session(self, timestamp: datetime | None = None) -> None:
        """Start a new trading session — reset all intraday state.

        Args:
            timestamp: Session start timestamp. If None, uses ``datetime.utcnow()``.
        """
        self._session_start = timestamp or datetime.utcnow()
        self._active_trade = None
        self._candle_index = 0
        self._cycles_without_trade = 0
        self._recent_loss = False
        self._recent_loss_cycles = 0
        self._cooldown_remaining = 0
        self._current_story = None
        self._current_confluence = None
        self._current_permission = None
        self._current_scores = None
        self._current_opposite = None
        self._current_trade_idea = None
        self._current_trade_class_assignment = None

        self.session_policy = SessionPolicy()
        self.loss_lock_manager = LossLockManager()
        self.override_guard = OverrideGuard()
        self.setup_memory.clear_session()
        self.silence_logger.clear_session()
        self.snapshot_writer.clear_session()
        self.narrative_timeline.clear_session()
        self.armed_plan_engine.clear_session()
        self.active_trade_supervisor.clear_session()
        self.intervention_engine.clear_session()

        self.narrative_timeline.add_event(
            event_type="session_start",
            details=f"Trading session started",
            timestamp=self._session_start,
        )

    def on_trade_complete(self, trade_class: TradeClass | None = None) -> None:
        """Called when an active trade is completed/exited.

        Clears the active trade reference, sets a cooldown period before
        the next trade can be initiated (prevents revenge trading).
        Resets supervisor state but does NOT reset the full session.

        Args:
            trade_class: The TradeClass of the completed trade, used to
                determine cooldown duration from class metadata.
                If None, uses a default cooldown of 2 candles.
        """
        if self._active_trade is not None:
            self.narrative_timeline.add_event(
                event_type="trade_exited",
                details="Active trade completed or exited",
            )
        self._active_trade = None
        self.active_trade_supervisor.clear_active_trade()

        # Set cooldown based on trade class metadata
        if trade_class is not None:
            metadata = self.trade_class_engine.get_metadata(trade_class)
            if metadata is not None:
                self._cooldown_remaining = metadata.cooldown_candles
            else:
                self._cooldown_remaining = 2  # Fallback
        else:
            self._cooldown_remaining = 2  # Default cooldown

    def record_loss(self, details: dict[str, Any] | None = None) -> None:
        """Record a losing trade with the loss lock manager.

        Also sets the recent_loss flag so the personality engine can
        switch to DEFENSIVE mood on the next heavy cycle.
        Called by the parent orchestrator when a trade results in a loss.

        Args:
            details: Optional metadata about the losing trade
                (trade_id, symbol, pnl, strike, trade_class, exit_reason, etc.).
        """
        self.loss_lock_manager.record_loss(details=details)
        self._recent_loss = True
        self._recent_loss_cycles = 0

    # ══════════════════════════════════════════════════════════════════
    # Internal Helpers
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _direction_from_confluence(
        confluence_result: ConfluenceResult | None,
    ) -> str:
        """Extract trade direction from confluence result.

        Args:
            confluence_result: ConfluenceResult.

        Returns:
            ``BUY`` for BULLISH, ``SELL`` for BEARISH, ``""`` otherwise.
        """
        if confluence_result is None:
            return ""
        direction = confluence_result.dominant_direction
        if direction == "BULLISH":
            return "BUY"
        elif direction == "BEARISH":
            return "SELL"
        return ""

    def _get_armed_plan_ref(self) -> str | None:
        """Get the most recently created armed plan ID, if any.

        Returns:
            Plan ID string, or None.
        """
        plans = self.armed_plan_engine.get_active_plans()
        if plans:
            return plans[-1].plan_id
        # Check for any triggered plan
        triggered = self.armed_plan_engine.get_triggered_plan()
        if triggered:
            return triggered.plan_id
        return None

    @staticmethod
    def _elapsed_ms(start: datetime) -> float:
        """Calculate milliseconds elapsed since start time.

        Args:
            start: Start datetime.

        Returns:
            Elapsed time in milliseconds.
        """
        return (datetime.utcnow() - start).total_seconds() * 1000.0
