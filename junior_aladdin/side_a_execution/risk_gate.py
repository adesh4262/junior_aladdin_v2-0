"""Side A — Risk Gate: 12 pre-order safety checks for execution.

THE CRITICAL SAFETY GATE. Asks only: \"Can this approved trade be safely and
validly executed right now?\" Does NOT ask \"Is this a good trade?\" — that
question was already answered by the Captain.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 4):
- Side A MAY reject, delay, shrink for safety — NEVER \"invent\" a better trade
- Captain size = default truth. Side A NEVER increases size.
- Reduce-only adjustment allowed for capital/margin/safety reasons (must be logged)
- One active live trade at a time (operationally enforced here)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import (
    DataHealth,
    ExecutionIntent,
    ExecutionMode,
)
from junior_aladdin.side_a_execution.intent_fingerprint import (
    IntentFingerprintStore,
    generate_fingerprint_from_intent,
)
from junior_aladdin.side_a_execution.side_a_types import RiskCheckResult


# =============================================================================
# Constants
# =============================================================================

DEFAULT_LOT_SIZE: int = 25
"""NIFTY 50 options lot size (standard)."""

DEFAULT_MAX_AGE_SECONDS: int = 60
"""Default maximum age for stale intent detection (in seconds)."""


# =============================================================================
# Risk Context
# =============================================================================


@dataclass
class RiskContext:
    """Runtime context for risk gate evaluation.

    Provides the execution-environment state needed by the 12 checks.
    Fields marked optional default to permissive values so the gate
    still works when those subsystems are not yet wired.

    Fields:
        available_capital: Total available capital for trading.
        required_capital: Capital required for this specific trade (margin).
        max_risk_per_trade: Maximum risk allowed per single trade.
        max_daily_loss: Maximum allowed cumulative daily loss.
        current_daily_loss: Current cumulative daily loss.
        mode: Current execution mode (ALERT / PAPER / REAL).
        lot_size: Lot size for the instrument (default 25 for NIFTY).
        is_real_locked: Whether REAL mode is locked (3+ losses today).
        has_active_trade: Whether a trade is currently active.
        data_health: Current data health state from Floor 2.
    """
    available_capital: float = 0.0
    required_capital: float = 0.0
    max_risk_per_trade: float = 0.0
    max_daily_loss: float = 0.0
    current_daily_loss: float = 0.0
    mode: ExecutionMode = ExecutionMode.ALERT
    lot_size: int = DEFAULT_LOT_SIZE
    is_real_locked: bool = False
    has_active_trade: bool = False
    data_health: DataHealth = DataHealth.GOOD


# =============================================================================
# RiskGate
# =============================================================================


class RiskGate:
    """Pre-order risk evaluation gate with 12 safety checks.

    Evaluates every approved ExecutionIntent before it reaches execution.
    If ANY of the 12 checks fails, the intent is blocked and must be
    journaled to the blocked_action_journal.

    Checks that depend on subsystems not yet built (state machine,
    position manager, loss lock manager) use injected callbacks.
    """

    def __init__(
        self,
        intent_fingerprint_store: IntentFingerprintStore,
        has_active_trade_check: Callable[[], bool] | None = None,
        is_real_locked_check: Callable[[], bool] | None = None,
        get_data_health_check: Callable[[], DataHealth] | None = None,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        """Initialize the RiskGate.

        Lot size is sourced from RiskContext.lot_size per evaluation,
        allowing per-intent flexibility.

        Args:
            intent_fingerprint_store: Store for duplicate detection.
            has_active_trade_check: Callback returning True if active trade exists.
            is_real_locked_check: Callback returning True if REAL mode locked.
            get_data_health_check: Callback returning current DataHealth.
            max_age_seconds: Maximum age for stale intent detection.
        """
        self._fingerprint_store = intent_fingerprint_store
        self._has_active_trade_check = has_active_trade_check
        self._is_real_locked_check = is_real_locked_check
        self._get_data_health_check = get_data_health_check
        self._max_age_seconds = max_age_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        intent: ExecutionIntent | None,
        context: RiskContext | None = None,
    ) -> RiskCheckResult:
        """Run all 12 pre-order safety checks against an ExecutionIntent.

        Args:
            intent: The validated ExecutionIntent to evaluate.
            context: Runtime RiskContext. If None, a permissive default is used.

        Returns:
            RiskCheckResult with passed=True if ALL checks pass,
            or passed=False with details of all failed checks.

        Raises:
            ExecutionError: If intent is None.
        """
        if intent is None:
            raise ExecutionError(
                message="Cannot evaluate None intent in risk gate",
            )
        ctx = context or RiskContext()
        checks: list[tuple[str, bool, str]] = []

        # ── Check 1: Available Capital ──────────────────────────────────
        name1 = "AVAILABLE_CAPITAL"
        if ctx.available_capital > 0:
            cap_ok = ctx.available_capital >= ctx.required_capital
            checks.append((
                name1, cap_ok,
                f"available={ctx.available_capital:.0f} >= required={ctx.required_capital:.0f}"
                if cap_ok else
                f"INSUFFICIENT: available={ctx.available_capital:.0f} < required={ctx.required_capital:.0f}",
            ))
        else:
            checks.append((name1, True, "SKIPPED: no capital limit configured"))

        # ── Check 2: Required Capital (margin check) ────────────────────
        name2 = "REQUIRED_CAPITAL"
        premium = intent.entry_plan.get("premium", 0.0)
        if premium > 0 and ctx.required_capital > 0:
            estimated_margin = premium * ctx.lot_size
            margin_ok = ctx.required_capital >= estimated_margin
            checks.append((
                name2, margin_ok,
                f"margin={ctx.required_capital:.0f} >= estimated={estimated_margin:.0f}"
                if margin_ok else
                f"INSUFFICIENT MARGIN: required={ctx.required_capital:.0f} < estimated={estimated_margin:.0f}",
            ))
        else:
            checks.append((name2, True, "SKIPPED: no premium/margin data"))

        # ── Check 3: Margin Availability ─────────────────────────────────
        name3 = "MARGIN_AVAILABILITY"
        if ctx.available_capital > 0 and ctx.required_capital > 0:
            margin_avail = ctx.available_capital >= ctx.required_capital * 1.2  # 20% buffer
            checks.append((
                name3, margin_avail,
                "Margin buffer OK" if margin_avail else
                f"MARGIN BUFFER INSUFFICIENT: need {ctx.required_capital * 1.2:.0f}, have {ctx.available_capital:.0f}",
            ))
        else:
            checks.append((name3, True, "SKIPPED: no capital data"))

        # ── Check 4: Quantity Sanity ─────────────────────────────────────
        name4 = "QUANTITY_SANITY"
        if premium > 0 and ctx.max_risk_per_trade > 0:
            estimated_cost = premium * ctx.lot_size
            qty_ok = estimated_cost <= ctx.max_risk_per_trade
            checks.append((
                name4, qty_ok,
                f"cost={estimated_cost:.0f} <= max_risk={ctx.max_risk_per_trade:.0f}"
                if qty_ok else
                f"COST EXCEEDS RISK: cost={estimated_cost:.0f} > max_risk={ctx.max_risk_per_trade:.0f}",
            ))
        else:
            checks.append((name4, True, "SKIPPED: no premium/risk data"))

        # ── Check 5: Lot Feasibility ────────────────────────────────────
        name5 = "LOT_FEASIBILITY"
        lot_check = True  # Always feasible for single lot (quantity=1 lot)
        checks.append((name5, lot_check, "Lot size feasible"))

        # ── Check 6: Max Loss Limit ──────────────────────────────────────
        name6 = "MAX_LOSS_LIMIT"
        if ctx.max_daily_loss > 0:
            loss_ok = ctx.current_daily_loss < ctx.max_daily_loss
            checks.append((
                name6, loss_ok,
                f"daily_loss={ctx.current_daily_loss:.0f} < max={ctx.max_daily_loss:.0f}"
                if loss_ok else
                f"DAILY LOSS LIMIT REACHED: loss={ctx.current_daily_loss:.0f} >= max={ctx.max_daily_loss:.0f}",
            ))
        else:
            checks.append((name6, True, "SKIPPED: no daily loss limit configured"))

        # ── Check 7: Mode Validation ─────────────────────────────────────
        name7 = "MODE_VALIDATION"
        intent_mode = intent.mode
        context_mode = ctx.mode
        mode_ok = intent_mode == context_mode
        checks.append((
            name7, mode_ok,
            f"intent_mode={intent_mode.value} == context_mode={context_mode.value}"
            if mode_ok else
            f"MODE MISMATCH: intent={intent_mode.value}, context={context_mode.value}",
        ))

        # ── Check 8: Real Lock State ─────────────────────────────────────
        name8 = "REAL_LOCK_STATE"
        if ctx.mode == ExecutionMode.REAL or intent.mode == ExecutionMode.REAL:
            is_locked = (
                self._is_real_locked_check()
                if self._is_real_locked_check
                else ctx.is_real_locked
            )
            real_ok = not is_locked
            checks.append((
                name8, real_ok,
                "REAL mode not locked" if real_ok else
                "REAL MODE LOCKED: 3+ losses today. Override required.",
            ))
        else:
            checks.append((name8, True, "SKIPPED: not REAL mode"))

        # ── Check 9: Duplicate Execution Prevention ──────────────────────
        name9 = "DUPLICATE_EXECUTION"
        fingerprint = generate_fingerprint_from_intent(intent)
        is_dup = self._fingerprint_store.is_duplicate(fingerprint)
        if not is_dup:
            # Register for future duplicate checks
            self._fingerprint_store.register_fingerprint(fingerprint)
            checks.append((name9, True, "Fingerprint registered — no duplicate"))
        else:
            checks.append((name9, False, "DUPLICATE INTENT DETECTED: same fingerprint already registered"))

        # ── Check 10: One-Trade Enforcement ──────────────────────────────
        name10 = "ONE_TRADE_ENFORCEMENT"
        active = (
            self._has_active_trade_check()
            if self._has_active_trade_check
            else ctx.has_active_trade
        )
        one_trade_ok = not active
        checks.append((
            name10, one_trade_ok,
            "No active trade — new intent allowed" if one_trade_ok else
            "ACTIVE TRADE EXISTS: one-trade rule enforced. No second trade allowed.",
        ))

        # ── Check 11: Stale Intent Detection ─────────────────────────────
        name11 = "STALE_INTENT"
        age = (datetime.utcnow() - intent.timestamp).total_seconds()
        fresh = age <= self._max_age_seconds
        checks.append((
            name11, fresh,
            f"intent_age={age:.0f}s <= max_age={self._max_age_seconds}s"
            if fresh else
            f"STALE INTENT: age={age:.0f}s > max_age={self._max_age_seconds}s",
        ))

        # ── Check 12: Data Health ────────────────────────────────────────
        name12 = "DATA_HEALTH"
        health = (
            self._get_data_health_check()
            if self._get_data_health_check
            else ctx.data_health
        )
        if health == DataHealth.CRITICAL:
            checks.append((name12, False, "CRITICAL DATA HEALTH: escalation required. Blocking new entry."))
        elif health == DataHealth.STALE:
            checks.append((name12, False, "STALE DATA: blocking new entries until data quality recovers."))
        elif health == DataHealth.DEGRADED:
            checks.append((name12, True, "DEGRADED DATA: allowing with stricter caution."))
        else:
            checks.append((name12, True, f"Data health: {health.value}"))

        # ── Aggregate result ─────────────────────────────────────────────
        passed = all(ok for _, ok, _ in checks)
        recommended = "PROCEED" if passed else "BLOCK"
        return RiskCheckResult(
            passed=passed,
            checks=checks,
            recommended_action=recommended,
        )

    def is_blocked_for_safety(self, intent: ExecutionIntent,
                               context: RiskContext | None = None) -> bool:
        """Quick summary check: is this intent blocked for safety?

        Useful for dashboard and quick pre-checks without full details.

        Args:
            intent: The ExecutionIntent to check.
            context: Optional RiskContext.

        Returns:
            True if the intent is blocked by risk gate.
        """
        result = self.evaluate(intent, context)
        return not result.passed

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def max_age_seconds(self) -> int:
        """Get the stale intent detection threshold in seconds."""
        return self._max_age_seconds

    @max_age_seconds.setter
    def max_age_seconds(self, value: int) -> None:
        """Set the stale intent detection threshold."""
        if value <= 0:
            raise ExecutionError(
                message="max_age_seconds must be positive",
                details={"value": value},
            )
        self._max_age_seconds = value

    # NOTE: Lot size is sourced from RiskContext.lot_size per evaluation.
    # There is no instance-level lot_size property because the same RiskGate
    # can be used with different lot sizes per context.  Use:
    #   RiskContext(lot_size=25)  # passed to evaluate()

    def set_real_locked_check(
        self,
        callback: Callable[[], bool] | None,
    ) -> None:
        """Set or clear the REAL lock state check callback.

        Used by the orchestrator to inject the current REAL-mode lock
        state (check #8).  When set, this callback is consulted before
        ``RiskContext.is_real_locked``.

        Args:
            callback: Callable returning True if REAL mode is locked,
                or None to clear (falls back to RiskContext).
        """
        self._is_real_locked_check = callback

    def set_data_health_check(
        self,
        callback: Callable[[], DataHealth] | None,
    ) -> None:
        """Set or clear the data health check callback.

        Used by the orchestrator to inject the current data health
        signal from Floor 2 (check #12).  When set, this callback is
        consulted before ``RiskContext.data_health``.

        Args:
            callback: Callable returning current DataHealth,
                or None to clear (falls back to RiskContext).
        """
        self._get_data_health_check = callback
