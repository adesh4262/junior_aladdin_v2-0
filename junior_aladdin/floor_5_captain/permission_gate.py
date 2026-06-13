"""Floor 5 — Permission Gate (Step 5.4).

FIRST module in Captain's heavy cycle. If permission fails, Captain goes
to WAIT/BLOCKED and skips all further analysis.

8 checks (BLOCKED if ANY fails):
1. Market open check: market is open (not holiday/weekend/after hours)
2. Psychology block check: trade_allowed from Psychology Head (NON-OVERRIDABLE)
3. Active trade check: no second trade if one exists (one-trade rule, NON-OVERRIDABLE)
4. Data health check: data_health_signal is not CRITICAL
5. Real mode lock check: REAL mode not locked (ALERT/PAPER unaffected)
6. Mode validation: valid execution mode selected
7. Session policy check: opening/closing window restrictions
8. Capital availability: capital available > 0

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 4):
- Psychology block CANNOT be overridden by Captain (non-negotiable)
- Active trade block CANNOT be overridden (one-trade rule)
- Permission gate is the FIRST module in heavy cycle
- If permission fails → silence_reason_logger → output BLOCKED/WAIT
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    PermissionResult,
    SessionPhase,
)
from junior_aladdin.floor_5_captain.loss_lock_manager import LossLockManager
from junior_aladdin.floor_5_captain.override_guard import OverrideGuard
from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.shared.types import DataHealth, ExecutionMode, FloorSummary, HeadReport

# ── Check names (used in PermissionResult.blocked_by) ──────────────────────
_MARKET_OPEN_CHECK = "market_open"
_PSYCHOLOGY_BLOCK_CHECK = "psychology_block"
_ACTIVE_TRADE_CHECK = "active_trade"
_DATA_HEALTH_CHECK = "data_health"
_REAL_MODE_LOCK_CHECK = "real_mode_lock"
_MODE_VALIDATION_CHECK = "mode_validation"
_SESSION_POLICY_CHECK = "session_policy"
_CAPITAL_AVAILABILITY_CHECK = "capital_availability"


class PermissionGate:
    """Captain's permission gate — 8 checks that must all pass before trading.

    This is the FIRST module in the heavy cycle. If any check fails,
    Captain must NOT proceed to confluence/conviction/trade construction.

    Usage::

        gate = PermissionGate(session_policy, loss_lock_manager)
        result = gate.check_all(
            timestamp=datetime.utcnow(),
            floor_summary=floor_summary,
            psychology_report=psychology_head_report,
            active_trade=False,
            current_mode=ExecutionMode.PAPER,
            capital_available=50000.0,
        )
        if not result.allowed:
            logger.info(f"Permission denied: {result.block_reason}")
    """

    def __init__(
        self,
        session_policy: SessionPolicy,
        loss_lock_manager: LossLockManager,
        override_guard: OverrideGuard | None = None,
    ) -> None:
        """Initialize the permission gate with its dependencies.

        Args:
            session_policy: SessionPolicy instance for session-based checks.
            loss_lock_manager: LossLockManager instance for REAL mode lock check.
            override_guard: Optional OverrideGuard for operator override of REAL mode lock.
        """
        self._session_policy = session_policy
        self._loss_lock_manager = loss_lock_manager
        self._override_guard = override_guard

    # ------------------------------------------------------------------
    # Public API — main entry point
    # ------------------------------------------------------------------

    def check_all(
        self,
        timestamp: datetime | None = None,
        floor_summary: FloorSummary | None = None,
        psychology_report: HeadReport | None = None,
        active_trade: bool = False,
        current_mode: ExecutionMode | None = None,
        capital_available: float = 0.0,
    ) -> PermissionResult:
        """Run all 8 permission checks in order.

        All checks must pass for ``allowed`` to be True.
        Blocked checks are collected with their reasons in ``blocked_by``.
        The first failing check's reason becomes the primary ``block_reason``.

        Args:
            timestamp: Current UTC timestamp. If None, uses ``datetime.utcnow()``.
            floor_summary: Current Floor Summary (for data_health_signal).
            psychology_report: Psychology Head report (for trade_allowed).
                If None, psychology check passes (no report available).
            active_trade: Whether a trade is currently active.
            current_mode: Current execution mode. If None, check passes.
            capital_available: Available trading capital.

        Returns:
            PermissionResult with ``allowed`` flag, ``block_reason``,
            and ``blocked_by`` list.
        """
        dt = timestamp or datetime.utcnow()
        mode = current_mode

        # Run all 8 checks in sequence, collecting blocks
        blocked_by: list[str] = []
        primary_reason: str = ""

        # 1. Market open check
        if not self._check_market_open(dt):
            blocked_by.append(_MARKET_OPEN_CHECK)
            if not primary_reason:
                primary_reason = "Market is closed (outside trading hours or weekend)"

        # 2. Psychology block check (NON-OVERRIDABLE)
        if not self._check_psychology_block(psychology_report):
            blocked_by.append(_PSYCHOLOGY_BLOCK_CHECK)
            if not primary_reason:
                primary_reason = "Psychology head blocks trading (non-overridable)"

        # 3. Active trade check (NON-OVERRIDABLE)
        if not self._check_active_trade(active_trade):
            blocked_by.append(_ACTIVE_TRADE_CHECK)
            if not primary_reason:
                primary_reason = "Active trade exists — one-trade rule (non-overridable)"

        # 4. Data health check
        if not self._check_data_health(floor_summary):
            blocked_by.append(_DATA_HEALTH_CHECK)
            if not primary_reason:
                primary_reason = "Data health signal is CRITICAL"

        # 5. Real mode lock check
        if not self._check_real_mode_lock(mode):
            blocked_by.append(_REAL_MODE_LOCK_CHECK)
            if not primary_reason:
                primary_reason = "REAL mode is locked by loss lock manager"

        # 6. Mode validation
        if not self._check_mode_validation(mode):
            blocked_by.append(_MODE_VALIDATION_CHECK)
            if not primary_reason:
                primary_reason = "Invalid or missing execution mode"

        # 7. Session policy check
        if not self._check_session_policy(dt):
            blocked_by.append(_SESSION_POLICY_CHECK)
            if not primary_reason:
                primary_reason = "Session policy restricts trading (opening/closing window)"

        # 8. Capital availability check
        if not self._check_capital_availability(capital_available):
            blocked_by.append(_CAPITAL_AVAILABILITY_CHECK)
            if not primary_reason:
                primary_reason = f"Insufficient capital (available: {capital_available})"

        allowed = len(blocked_by) == 0
        return PermissionResult(
            allowed=allowed,
            block_reason=primary_reason if not allowed else "",
            blocked_by=blocked_by,
            timestamp=dt,
        )

    # ------------------------------------------------------------------
    # Individual check methods
    # ------------------------------------------------------------------

    def _check_market_open(self, timestamp: datetime) -> bool:
        """Check 1: Is the market currently open for trading?

        Uses SessionPolicy.is_market_open() for weekday + hours check.

        Args:
            timestamp: UTC timestamp to check.

        Returns:
            True if market is open, False otherwise.
        """
        return self._session_policy.is_market_open(timestamp)

    def _check_psychology_block(self, psychology_report: HeadReport | None) -> bool:
        """Check 2: Does Psychology Head allow trading?

        NON-OVERRIDABLE — if psychology blocks, Captain MUST NOT trade.

        Args:
            psychology_report: Psychology Head report with trade_allowed field.
                If None, the check passes (no report to block with).

        Returns:
            True if psychology allows trading, False if blocked.
        """
        if psychology_report is None:
            return True  # No psychology report available — not blocked
        return psychology_report.trade_allowed

    def _check_active_trade(self, active_trade: bool) -> bool:
        """Check 3: Is there already an active trade?

        NON-OVERRIDABLE — one-trade rule is absolute.

        Args:
            active_trade: Whether a trade is currently active.

        Returns:
            True if no active trade, False if there is one.
        """
        return not active_trade

    def _check_data_health(self, floor_summary: FloorSummary | None) -> bool:
        """Check 4: Is data health acceptable?

        Blocks only when data_health_signal is CRITICAL.

        Args:
            floor_summary: Floor Summary with data_health_signal field.
                If None, the check passes (no summary to judge from).

        Returns:
            True if data health is not CRITICAL, False if CRITICAL.
        """
        if floor_summary is None:
            return True  # No summary available — not blocked
        return floor_summary.data_health_signal != DataHealth.CRITICAL

    def _check_real_mode_lock(self, current_mode: ExecutionMode | None) -> bool:
        """Check 5: Is REAL mode locked?

        Only blocks if:
        - Current mode is REAL
        - LossLockManager reports locked state

        ALERT and PAPER modes are never affected by the loss lock.

        Args:
            current_mode: Current execution mode. If None, check passes.

        Returns:
            True if REAL mode is not locked (or not in REAL mode),
            False if REAL mode is locked.
        """
        if current_mode is None:
            return True  # No mode set — not blocked
        if current_mode != ExecutionMode.REAL:
            return True  # ALERT/PAPER mode — loss lock doesn't apply
        if not self._loss_lock_manager.is_locked():
            return True

        # Loss lock is active — check if operator override has been granted
        if self._override_guard is not None and self._override_guard.is_override_granted():
            return True

        return False

    def _check_mode_validation(self, current_mode: ExecutionMode | None) -> bool:
        """Check 6: Is the execution mode valid?

        A valid mode is one of: ALERT, PAPER, REAL.
        None or unknown values are invalid.

        Args:
            current_mode: Current execution mode. If None, check fails.

        Returns:
            True if mode is a valid ExecutionMode, False otherwise.
        """
        if current_mode is None:
            return False
        return current_mode in (ExecutionMode.ALERT, ExecutionMode.PAPER, ExecutionMode.REAL)

    def _check_session_policy(self, timestamp: datetime) -> bool:
        """Check 7: Does the session policy allow trading?

        Blocks during specific session phases based on permission strictness:
        - VERY_HIGH (CLOSING): Block — risk-aware, avoid overnight risk
        - HIGH (OPENING, LUNCH): Block — observe/context-build or defensive
        - NORMAL (GOLDEN_MORNING): Allow — strongest permission window

        Args:
            timestamp: UTC timestamp to check.

        Returns:
            True if session allows trading, False if blocked.
        """
        phase = self._session_policy.get_session_phase(timestamp)
        strictness = self._session_policy.get_permission_strictness(phase)
        return strictness == "NORMAL"

    def _check_capital_availability(self, capital_available: float) -> bool:
        """Check 8: Is capital available for trading?

        Args:
            capital_available: Current available capital.

        Returns:
            True if capital > 0, False if <= 0.
        """
        return capital_available > 0.0
