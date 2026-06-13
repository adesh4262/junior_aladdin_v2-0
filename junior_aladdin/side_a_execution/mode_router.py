"""Side A — Mode Router: ALERT always active + PAPER/REAL execution path routing.

This module decides where an approved execution intent goes.
It does NOT judge or modify the trade — it routes based on current mode.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 5 & 6):
- ALERT is always active in ALL modes (ALERT/PAPER/REAL)
- ALERT fires BEFORE PAPER/REAL routing (dashboard always sees every intent)
- PAPER mode → route through paper_broker flow
- REAL mode → route through real_broker flow
- Mode transition is BLOCKED during an active trade
- Mode Router does NOT judge the trade or interpret market meaning
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import ExecutionIntent, ExecutionMode


# =============================================================================
# Routing Result
# =============================================================================


@dataclass
class RoutingResult:
    """Result of routing an ExecutionIntent through the ModeRouter.

    ALERT path always fires regardless of mode.
    Execution path (PAPER/REAL) depends on current mode.

    Fields:
        alert_fired: Whether the ALERT notification was fired (always True).
        alert_targets: List of ALERT delivery targets (e.g., \"dashboard\", \"log\").
        execution_path: The target execution path: \"PAPER\", \"REAL\", or \"NONE\".
        mode: The current execution mode at routing time.
        trade_id: The trade ID for traceability.
        timestamp: When the routing occurred.
    """
    alert_fired: bool = True
    alert_targets: list[str] = field(default_factory=lambda: ["dashboard", "log"])
    execution_path: str = "NONE"
    mode: ExecutionMode = ExecutionMode.ALERT
    trade_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# ModeRouter
# =============================================================================


class ModeRouter:
    """Routes approved execution intents based on current execution mode.

    ALERT path is always active — it fires for EVERY intent regardless of mode.
    PAPER/REAL execution paths depend on the current mode setting.

    Mode transition governance:
    - Mode switch is blocked if an active trade exists
    - ALERT mode is conceptual (no execution path, only notifications)
    - PAPER ↔ REAL transitions are governed

    The has_active_trade_check callback allows the orchestrator to inject
    the current active trade state. If not provided, mode transitions are
    always allowed (no active trade assumed).
    """

    def __init__(
        self,
        initial_mode: ExecutionMode = ExecutionMode.ALERT,
        has_active_trade_check: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize the ModeRouter.

        Args:
            initial_mode: The starting execution mode (default ALERT).
            has_active_trade_check: Optional callable returning True if an
                active trade exists. Used to enforce mode transition governance.
        """
        self._mode = initial_mode
        self._has_active_trade_check = has_active_trade_check
        self._alert_targets = ["log", "dashboard"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route_intent(self, intent: ExecutionIntent) -> RoutingResult:
        """Route an ExecutionIntent based on current mode.

        ALERT notification ALWAYS fires — this is the first action.
        Then the intent is routed to the appropriate execution path
        based on current mode.

        Args:
            intent: The validated ExecutionIntent to route.

        Returns:
            A RoutingResult with alert and execution path information.

        Raises:
            ExecutionError: If intent is None or invalid.
        """
        if intent is None:
            raise ExecutionError(
                message="Cannot route None intent",
                details={"mode": self._mode.value},
            )

        # Determine execution path based on current mode
        execution_path = self._resolve_execution_path()

        return RoutingResult(
            alert_fired=True,
            alert_targets=list(self._alert_targets),
            execution_path=execution_path,
            mode=self._mode,
            trade_id=intent.trade_id,
        )

    def set_mode(self, new_mode: ExecutionMode) -> bool:
        """Change the current execution mode.

        Mode transition is blocked if:
        - An active trade exists (checked via has_active_trade_check callback)
        - The new mode is the same as current mode (no-op, returns True)

        Returns False (no exception) for blocked transitions so callers
        can handle them gracefully. Only raises for truly invalid args.

        Args:
            new_mode: The target ExecutionMode to switch to.

        Returns:
            True if mode was changed, False if blocked.

        Raises:
            ExecutionError: If new_mode is None or invalid type.
        """
        if new_mode is None or not isinstance(new_mode, ExecutionMode):
            raise ExecutionError(
                message="Invalid mode transition target",
                details={
                    "new_mode": str(new_mode),
                    "current_mode": self._mode.value,
                },
            )

        # No-op if same mode
        if new_mode == self._mode:
            return True

        # Block transition if active trade exists (returns False, no exception)
        if self._is_active_trade():
            return False

        self._mode = new_mode
        return True

    def get_current_mode(self) -> ExecutionMode:
        """Get the current execution mode.

        Returns:
            The current ExecutionMode.
        """
        return self._mode

    @staticmethod
    def is_alert_active() -> bool:
        """Check whether the ALERT path is active.

        ALERT is ALWAYS active in ALL modes. This never returns False.

        Returns:
            Always True (ALERT is always active).
        """
        return True

    def set_has_active_trade_check(
        self,
        callback: Callable[[], bool] | None,
    ) -> None:
        """Set or clear the active trade check callback.

        This callback is used to enforce mode transition governance
        (blocking mode switches when a trade is active).

        Args:
            callback: Callable returning True if an active trade exists,
                or None to clear.
        """
        self._has_active_trade_check = callback

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_execution_path(self) -> str:
        """Resolve the execution path for the current mode.

        Returns:
            \"PAPER\", \"REAL\", or \"NONE\" (for ALERT mode).
        """
        path_map = {
            ExecutionMode.ALERT: "NONE",  # ALERT has no execution path
            ExecutionMode.PAPER: "PAPER",
            ExecutionMode.REAL: "REAL",
        }
        return path_map.get(self._mode, "NONE")

    def _is_active_trade(self) -> bool:
        """Check whether there is currently an active trade.

        Uses the injected has_active_trade_check callback if available.
        Falls back to False if no callback was provided.

        Returns:
            True if an active trade exists.
        """
        if self._has_active_trade_check is not None:
            return self._has_active_trade_check()
        return False
