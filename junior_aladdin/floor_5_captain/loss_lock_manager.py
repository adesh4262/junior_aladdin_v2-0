"""Floor 5 — Loss Lock Manager (Step 5.3).

Tracks consecutive losing trades in REAL mode and locks mode after a
configurable threshold (default: 3 losses).

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 14):
- 3 losing trades → REAL mode becomes locked/off
- ALERT + PAPER remain active when REAL is locked
- Counter resets next trading day
- A losing trade is any trade where net P&L is negative (not only SL hit)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from junior_aladdin.shared.types import ExecutionMode


class LossLockManager:
    """Tracks consecutive REAL mode losses and enforces the 3-loss lock rule.

    The lock only applies to REAL mode. ALERT and PAPER trades
    are never affected by the loss lock.

    Attributes:
        MAX_LOSSES: Number of consecutive losses before lock (default 3).
        _loss_count: Current consecutive loss count for REAL mode.
        _is_locked: Whether REAL mode is currently locked.
        _locked_date: The date the lock was triggered (for daily reset).
        _current_mode: Current execution mode (determines if loss counts).
        _loss_history: Full history of recorded losses with timestamp.
    """

    MAX_LOSSES: int = 3

    def __init__(self, max_losses: int | None = None) -> None:
        """Initialize the loss lock manager.

        Args:
            max_losses: Override the default max loss threshold.
        """
        self.MAX_LOSSES = max_losses if max_losses is not None else 3
        self._loss_count: int = 0
        self._is_locked: bool = False
        self._locked_date: date | None = None
        self._current_mode: ExecutionMode = ExecutionMode.ALERT
        self._loss_history: list[dict[str, Any]] = []
        self._reset_date: date = self._today()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_loss(self, details: dict[str, Any] | None = None) -> bool:
        """Record a losing trade.

        Only counts toward the lock if the current mode is REAL.
        If the loss pushes the count over MAX_LOSSES, REAL mode is locked.

        Args:
            details: Optional metadata (symbol, P&L, timestamp, etc.).

        Returns:
            True if REAL mode became locked as a result of this loss,
            False otherwise.
        """
        if self._current_mode != ExecutionMode.REAL:
            # Losses in ALERT or PAPER mode don't count toward the lock
            return False

        loss_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self._current_mode.value,
            "loss_count_at_time": self._loss_count + 1,
        }
        if details:
            loss_entry.update(details)

        self._loss_history.append(loss_entry)
        self._loss_count += 1

        if self._loss_count >= self.MAX_LOSSES:
            self._is_locked = True
            self._locked_date = self._today()
            return True  # Lock triggered

        return False  # Under threshold

    def is_locked(self) -> bool:
        """Check if REAL mode is currently locked.

        Returns:
            True if locked (REAL trades blocked), False otherwise.
        """
        return self._is_locked

    def get_loss_count(self) -> int:
        """Get current consecutive loss count.

        Returns:
            Current loss count (0 if no losses since last reset).
        """
        return self._loss_count

    def get_remaining_losses_before_lock(self) -> int:
        """Get how many more losses are allowed before lock.

        Returns:
            Number of losses remaining before lock triggers
            (0 if already locked).
        """
        if self._is_locked:
            return 0
        return max(0, self.MAX_LOSSES - self._loss_count)

    def reset_counter(self, reset_date: date | None = None) -> None:
        """Reset the loss counter. Called at the start of a new trading day.

        Also clears the lock state so REAL mode is available again.

        Args:
            reset_date: The date to use as the new reset reference.
                Defaults to today's date if not provided.
        """
        self._loss_count = 0
        self._is_locked = False
        self._locked_date = None
        self._reset_date = reset_date or self._today()
        self._loss_history = []

    def set_mode(self, mode: ExecutionMode) -> None:
        """Set the current execution mode.

        Args:
            mode: The current execution mode (ALERT, PAPER, or REAL).
        """
        self._current_mode = mode

    def get_mode(self) -> ExecutionMode:
        """Get the current execution mode.

        Returns:
            Current execution mode.
        """
        return self._current_mode

    def get_loss_history(self) -> list[dict[str, Any]]:
        """Get the full loss history.

        Returns:
            List of loss record dicts.
        """
        return list(self._loss_history)

    def get_lock_summary(self) -> dict[str, Any]:
        """Get a structured summary of the current lock state.

        Suitable for dashboard (Side B) and logging (Side C).

        Returns:
            Dict with lock state fields.
        """
        return {
            "loss_count": self._loss_count,
            "max_losses": self.MAX_LOSSES,
            "is_locked": self._is_locked,
            "locked_date": self._locked_date.isoformat() if self._locked_date else None,
            "current_mode": self._current_mode.value,
            "remaining_before_lock": self.get_remaining_losses_before_lock(),
        }

    def check_and_reset_if_new_day(self, current_date: date | None = None) -> bool:
        """Check if a new trading day has started and reset if so.

        Should be called at the start of each heavy cycle.

        Args:
            current_date: The current date (defaults to today).

        Returns:
            True if the counter was reset, False otherwise.
        """
        today = current_date or self._today()
        if today > self._reset_date:
            self.reset_counter(reset_date=today)
            return True
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today() -> date:
        """Get today's date in UTC.

        Returns:
            Current UTC date.
        """
        return datetime.now(timezone.utc).date()
