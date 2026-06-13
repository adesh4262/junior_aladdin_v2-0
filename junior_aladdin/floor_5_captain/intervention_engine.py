"""Floor 5 — Intervention Engine (Step 5.20).

RARE Captain override during active trade. NOT for routine management.

Intervention is triggered ONLY when the original thesis is structurally broken —
never on ordinary pullbacks, minor zone wicks, normal profit taking, or routine
market noise. Routine position management belongs to Execution / Position Manager.

Intervention scenarios:
1. **Thesis break**: Original trading thesis structurally invalidated
   (zone invalidation + opposite confluence + macro shift = structural break).
2. **Regime flip**: Market regime changes fundamentally (e.g., TREND_UP → CHOP).
3. **Strong opposite confluence**: Opposite case now dominates (direction flip + high strength).
4. **Options support collapse**: Key options support disappears (for OPTIONS_PRESSURE trades).
5. **Risk emergency**: Unexpected risk event (black swan, data feed failure, etc.).

Severity levels:
- NORMAL: Minor thesis concern, can adjust (e.g., tighten SL, reduce size).
- CAUTION: Significant concern, prepare exit (e.g., hedge, exit half).
- EMERGENCY_OVERRIDE: Critical risk event, immediate action (e.g., exit NOW).

Architecture rules (see ROADMAP_FLOOR_05 Section 5.20):
- Intervention is RARE (< 5% of active trade cycles).
- NOT for routine position management.
- Consumes ActiveTradeSupervisor output for thesis health.
- Intervention_engine does NOT replace execution — it outputs an override decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.active_trade_supervisor import (
    ActiveTradeSupervisor,
    ThesisReview,
)
from junior_aladdin.floor_5_captain.captain_types import InterventionSeverity
from junior_aladdin.shared.types import CaptainDecision


# ── Intervention Decision Dataclass ──────────────────────────────────────


@dataclass
class InterventionDecision:
    """Result of an intervention evaluation.

    Fields:
        intervene: Whether intervention is warranted (RARE — only on structural breakdown).
        severity: Severity level of the intervention (NORMAL / CAUTION / EMERGENCY_OVERRIDE).
        action: Specific action to take (e.g., "CLOSE_POSITION", "HEDGE", "REDUCE_SIZE").
        reason: Human-readable explanation of why intervention was or was not triggered.
        trigger: Which scenario triggered this evaluation (e.g., "thesis_break", "risk_emergency").
        details: Dict with supporting data (e.g., concerns list, price levels, regime info).
        timestamp: When the evaluation was performed.
    """
    intervene: bool = False
    severity: InterventionSeverity = InterventionSeverity.NORMAL
    action: str = ""
    reason: str = ""
    trigger: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ── Intervention Scenario Thresholds ─────────────────────────────────────

_THESIS_BREAK_MIN_CONCERNS = 3     # 3+ concerns = structural thesis break
_REGIME_FLIP_WEAK_REGIMES = {"CHOP", "UNCLEAR", "RANGE"}
_STRONG_OPPOSITE_MIN_STRENGTH = 0.7  # Opposite case must be this strong
_EMERGENCY_PRICE_COLLAPSE_PCT = 1.5  # 1.5% sudden move = risk emergency

# Action map by severity + trigger
_ACTION_MAP: dict[str, dict[str, str]] = {
    "thesis_break": {
        "NORMAL": "TIGHTEN_STOP_LOSS",
        "CAUTION": "REDUCE_POSITION_SIZE",
        "EMERGENCY_OVERRIDE": "CLOSE_POSITION",
    },
    "regime_flip": {
        "NORMAL": "MONITOR_ONE_CANDLE",
        "CAUTION": "EXIT_HALF_POSITION",
        "EMERGENCY_OVERRIDE": "CLOSE_POSITION",
    },
    "strong_opposite_confluence": {
        "NORMAL": "ADD_PROTECTION",
        "CAUTION": "HEDGE_POSITION",
        "EMERGENCY_OVERRIDE": "CLOSE_POSITION",
    },
    "options_collapse": {
        "NORMAL": "MONITOR_CLOSELY",
        "CAUTION": "REDUCE_POSITION_SIZE",
        "EMERGENCY_OVERRIDE": "CLOSE_POSITION",
    },
    "risk_emergency": {
        "NORMAL": "ALERT_OPERATOR",
        "CAUTION": "LOCK_IN_PROFITS",
        "EMERGENCY_OVERRIDE": "IMMEDIATE_EXIT",
    },
}

# Reasons for NOT intervening on various scenarios (noise rejection)
_NOISE_REASONS: dict[str, str] = {
    "minor_zone_wick": "Minor zone wick — not an intervention event",
    "normal_pullback": "Ordinary pullback within thesis bounds — monitor only",
    "low_concern_count": f"Insufficient concerns (< {_THESIS_BREAK_MIN_CONCERNS}) for structured intervention",
    "no_structural_break": "No structural thesis break detected",
    "opposite_too_weak": "Opposite case too weak for intervention",
    "options_support_ok": "Options support still within acceptable range",
    "regime_stable": "Regime remains supportive of thesis",
}


# ── InterventionEngine ───────────────────────────────────────────────────


class InterventionEngine:
    """Evaluates whether a rare strategic override is warranted during an active trade.

    This engine is deliberately conservative — it should say NO far more often
    than YES. Intervention is reserved for structural thesis breaks, not routine
    market noise.

    Usage::

        engine = InterventionEngine()
        supervisor = ActiveTradeSupervisor()

        # Light cycle: evaluate intervention
        decision = engine.evaluate_intervention(
            supervisor=supervisor,
            active_trade=current_decision,
            current_price=19550.0,
        )

        if decision.intervene:
            logger.warning(f"Intervention: {decision.reason}")
            # Forward decision to override channel
    """

    def __init__(self) -> None:
        """Initialize the intervention engine."""
        self._history: list[InterventionDecision] = []
        self._intervention_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_intervention(
        self,
        supervisor: ActiveTradeSupervisor,
        active_trade: CaptainDecision | None = None,
        current_price: float = 0.0,
        entry_price: float = 0.0,
        zone_price: float = 0.0,
        regime: str = "",
        opposite_case_strength: float = 0.0,
        options_oi_healthy: bool = True,
        data_health_critical: bool = False,
        risk_event_detected: bool = False,
    ) -> InterventionDecision:
        """Evaluate whether intervention is warranted.

        Checks all 5 intervention scenarios and produces a structured
        decision. Intervention is RARE — only triggers on structural breaks.

        Args:
            supervisor: ActiveTradeSupervisor instance with latest thesis review.
            active_trade: The CaptainDecision for the active trade.
            current_price: Current market price.
            entry_price: Entry price of the active trade.
            zone_price: The original zone price (OB, FVG, etc.).
            regime: Current market regime string.
            opposite_case_strength: Strength of opposite case (0.0-1.0).
            options_oi_healthy: Whether options OI data looks healthy.
            data_health_critical: Whether data health is CRITICAL.
            risk_event_detected: Whether an unexpected risk event was detected.

        Returns:
            An ``InterventionDecision`` with the evaluation result.
        """
        # Gather thesis review from supervisor
        latest_review = supervisor.get_latest_review()
        concerns = latest_review.concerns if latest_review else []

        # Check all 5 scenarios
        thesis_break_result = self._check_thesis_break(latest_review, concerns)
        regime_flip_result = self._check_regime_flip(regime)
        opposite_result = self._check_strong_opposite_confluence(
            latest_review, opposite_case_strength
        )
        options_result = self._check_options_collapse(
            active_trade, options_oi_healthy
        )
        emergency_result = self._check_risk_emergency(
            data_health_critical, risk_event_detected
        )

        # Combine findings
        triggered_scenarios: list[tuple[str, str, InterventionSeverity]] = []

        if thesis_break_result[0]:
            triggered_scenarios.append(("thesis_break", thesis_break_result[1], thesis_break_result[2]))

        if regime_flip_result[0]:
            triggered_scenarios.append(("regime_flip", regime_flip_result[1], regime_flip_result[2]))

        if opposite_result[0]:
            triggered_scenarios.append(
                ("strong_opposite_confluence", opposite_result[1], opposite_result[2])
            )

        if options_result[0]:
            triggered_scenarios.append(("options_collapse", options_result[1], options_result[2]))

        if emergency_result[0]:
            triggered_scenarios.append(("risk_emergency", emergency_result[1], emergency_result[2]))

        # Determine if intervention is warranted
        if not triggered_scenarios:
            decision = InterventionDecision(
                intervene=False,
                reason=self._build_no_intervention_reason(concerns, regime),
                details={
                    "concerns": concerns,
                    "regime": regime,
                    "thesis_intact": latest_review.thesis_intact if latest_review else True,
                },
            )
            self._history.append(decision)
            return decision

        # Determine overall severity (use highest)
        severity_order = {
            InterventionSeverity.NORMAL: 0,
            InterventionSeverity.CAUTION: 1,
            InterventionSeverity.EMERGENCY_OVERRIDE: 2,
        }
        overall_severity = max(
            (s for _, _, s in triggered_scenarios),
            key=lambda x: severity_order.get(x, 0),
        )

        # Determine primary trigger and action
        primary_trigger = triggered_scenarios[0][0]
        primary_reason = triggered_scenarios[0][1]
        severity_label = overall_severity.value
        action = self._determine_action(primary_trigger, severity_label)

        # Build reason summary
        scenario_summaries = [f"{t}({s.value})" for t, r, s in triggered_scenarios]
        reason = (
            f"Intervention triggered by {len(triggered_scenarios)} scenario(s): "
            f"{', '.join(scenario_summaries)}. "
            f"Primary: {primary_reason}"
        )

        decision = InterventionDecision(
            intervene=True,
            severity=overall_severity,
            action=action,
            reason=reason,
            trigger=primary_trigger,
            details={
                "triggered_scenarios": triggered_scenarios,
                "concerns": concerns,
                "regime": regime,
                "current_price": current_price,
                "entry_price": entry_price,
                "zone_price": zone_price,
                "opposite_case_strength": opposite_case_strength,
            },
        )

        self._intervention_count += 1
        self._history.append(decision)
        return decision

    # ------------------------------------------------------------------
    # Scenario Checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_thesis_break(
        latest_review: ThesisReview | None,
        concerns: list[str],
    ) -> tuple[bool, str, InterventionSeverity]:
        """Check if the original trading thesis is structurally broken.

        Thesis is broken when multiple critical factors fail simultaneously:
        - Zone is invalid, AND
        - Opposite case strengthened, AND/OR
        - Macro context shifted

        Args:
            latest_review: The latest ThesisReview.
            concerns: List of concerns from the review.

        Returns:
            Tuple of ``(triggered, reason, severity)``.
        """
        if latest_review is None:
            return False, "", InterventionSeverity.NORMAL

        # Count critical failures
        critical_failures = sum([
            not latest_review.zone_valid,
            latest_review.opposite_case_strengthened,
            latest_review.macro_shift_detected,
        ])

        # Thesis break requires MULTIPLE failures (structural, not noise)
        if critical_failures >= 2 and len(concerns) >= _THESIS_BREAK_MIN_CONCERNS:
            severity = (
                InterventionSeverity.EMERGENCY_OVERRIDE
                if critical_failures >= 3
                else InterventionSeverity.CAUTION
            )
            return (
                True,
                f"Thesis structurally broken: {critical_failures}/3 critical failures, "
                f"{len(concerns)} concerns",
                severity,
            )

        return False, "", InterventionSeverity.NORMAL

    @staticmethod
    def _check_regime_flip(
        regime: str,
    ) -> tuple[bool, str, InterventionSeverity]:
        """Check if market regime has flipped to an unsupportive state.

        Regime flip is significant when moving FROM a trend TO a weak/chop state.

        Args:
            regime: Current market regime string.

        Returns:
            Tuple of ``(triggered, reason, severity)``.
        """
        if not regime:
            return False, "", InterventionSeverity.NORMAL

        regime_upper = regime.upper()

        if regime_upper in _REGIME_FLIP_WEAK_REGIMES:
            # CHOP and UNCLEAR are always concerning
            return (
                True,
                f"Regime flipped to {regime_upper} — thesis no longer supported",
                InterventionSeverity.CAUTION,
            )

        return False, "", InterventionSeverity.NORMAL

    @staticmethod
    def _check_strong_opposite_confluence(
        latest_review: ThesisReview | None,
        opposite_case_strength: float,
    ) -> tuple[bool, str, InterventionSeverity]:
        """Check if the opposite case now dominates.

        Opposite confluence is dangerous when:
        - Direction has flipped (opposite_case_strengthened in review), OR
        - Opposite case strength is very high.

        Args:
            latest_review: The latest ThesisReview.
            opposite_case_strength: Strength of opposite case (0.0-1.0).

        Returns:
            Tuple of ``(triggered, reason, severity)``.
        """
        if latest_review is None:
            return False, "", InterventionSeverity.NORMAL

        # Direction flip is a serious concern
        if latest_review.opposite_case_strengthened:
            severity = (
                InterventionSeverity.EMERGENCY_OVERRIDE
                if opposite_case_strength >= _STRONG_OPPOSITE_MIN_STRENGTH
                else InterventionSeverity.CAUTION
            )
            return (
                True,
                f"Opposite confluence dominates (strength: {opposite_case_strength:.2f}, "
                f"direction flipped)",
                severity,
            )

        # Very strong opposite case alone can trigger
        if opposite_case_strength >= _STRONG_OPPOSITE_MIN_STRENGTH:
            return (
                True,
                f"Strong opposite confluence detected (strength: {opposite_case_strength:.2f})",
                InterventionSeverity.CAUTION,
            )

        return False, "", InterventionSeverity.NORMAL

    @staticmethod
    def _check_options_collapse(
        active_trade: CaptainDecision | None,
        options_oi_healthy: bool,
    ) -> tuple[bool, str, InterventionSeverity]:
        """Check if options support has collapsed.

        Only relevant for OPTIONS_PRESSURE trade class.

        Args:
            active_trade: The active trade (if any).
            options_oi_healthy: Whether options OI data looks healthy.

        Returns:
            Tuple of ``(triggered, reason, severity)``.
        """
        if active_trade is None:
            return False, "", InterventionSeverity.NORMAL

        # Only check for options pressure trades
        trade_class_label = (
            active_trade.trade_class.value
            if hasattr(active_trade.trade_class, "value")
            else str(active_trade.trade_class)
        )

        if trade_class_label == "OPTIONS_PRESSURE" and not options_oi_healthy:
            return (
                True,
                "Options support collapsed — key OI walls no longer supporting thesis",
                InterventionSeverity.CAUTION,
            )

        return False, "", InterventionSeverity.NORMAL

    @staticmethod
    def _check_risk_emergency(
        data_health_critical: bool,
        risk_event_detected: bool,
    ) -> tuple[bool, str, InterventionSeverity]:
        """Check for an unexpected risk emergency.

        Risk emergencies are rare and always warrant immediate attention.

        Args:
            data_health_critical: Whether data health is CRITICAL (feed failure).
            risk_event_detected: Whether an external risk event was detected.

        Returns:
            Tuple of ``(triggered, reason, severity)``.
        """
        if data_health_critical:
            return (
                True,
                "Data health CRITICAL — feed failure may compromise position visibility",
                InterventionSeverity.EMERGENCY_OVERRIDE,
            )

        if risk_event_detected:
            return (
                True,
                "Unexpected risk event detected — immediate action recommended",
                InterventionSeverity.EMERGENCY_OVERRIDE,
            )

        return False, "", InterventionSeverity.NORMAL

    # ------------------------------------------------------------------
    # Action Selection
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_action(trigger: str, severity_label: str) -> str:
        """Determine the recommended action based on trigger and severity.

        Args:
            trigger: The primary trigger scenario name.
            severity_label: The severity level as a string (NORMAL/CAUTION/EMERGENCY_OVERRIDE).

        Returns:
            Action string (e.g., "CLOSE_POSITION", "TIGHTEN_STOP_LOSS").
        """
        trigger_map = _ACTION_MAP.get(trigger, {})
        return trigger_map.get(severity_label, "ALERT_OPERATOR")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_no_intervention_reason(
        concerns: list[str],
        regime: str,
    ) -> str:
        """Build a reason string explaining why no intervention is needed.

        Args:
            concerns: List of concerns (may be empty).
            regime: Current market regime.

        Returns:
            Human-readable reason string.
        """
        if not concerns:
            return "Thesis intact — no intervention required"

        if len(concerns) < _THESIS_BREAK_MIN_CONCERNS:
            return (
                f"Concerns present ({len(concerns)}) but below structural break threshold "
                f"({_THESIS_BREAK_MIN_CONCERNS}) — no intervention required"
            )

        regime_note = f" Regime: {regime}." if regime else ""
        return (
            f"{len(concerns)} concern(s) present but no structural break detected.{regime_note} "
            "Monitoring during light cycle."
        )

    # ------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------

    def get_intervention_history(self) -> list[InterventionDecision]:
        """Get all intervention evaluations performed this session.

        Returns:
            List of ``InterventionDecision`` entries in chronological order.
        """
        return list(self._history)

    def get_recent_interventions(
        self, count: int = 5
    ) -> list[InterventionDecision]:
        """Get the most recent N intervention evaluations.

        Args:
            count: Number of recent entries to return.

        Returns:
            List of the most recent ``InterventionDecision`` entries.
        """
        return list(self._history[-count:])

    def get_intervention_count(self) -> int:
        """Get the number of interventions that were actually triggered.

        Returns:
            Count of interventions with ``intervene=True``.
        """
        return self._intervention_count

    def get_total_evaluations(self) -> int:
        """Get the total number of evaluations performed this session.

        Returns:
            Total count of evaluations (including non-interventions).
        """
        return len(self._history)

    def get_latest_decision(self) -> InterventionDecision | None:
        """Get the most recent intervention evaluation decision.

        Returns:
            The latest ``InterventionDecision``, or None if no evaluations exist.
        """
        if not self._history:
            return None
        return self._history[-1]

    def get_portfolio_risk_summary(self) -> dict[str, Any]:
        """Get a summary of intervention activity for dashboard display.

        Returns:
            Dict with intervention activity fields.
        """
        latest = self.get_latest_decision()
        return {
            "total_evaluations": self.get_total_evaluations(),
            "intervention_count": self._intervention_count,
            "non_intervention_count": self.get_total_evaluations() - self._intervention_count,
            "latest_intervention": latest.intervene if latest else False,
            "latest_severity": latest.severity.value if latest and latest.intervene else "",
            "latest_action": latest.action if latest and latest.intervene else "",
            "latest_trigger": latest.trigger if latest and latest.intervene else "",
        }

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def clear_session(self) -> None:
        """Clear all intervention history for a new trading day."""
        self._history.clear()
        self._intervention_count = 0
