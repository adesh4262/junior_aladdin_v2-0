"""Floor 5 — Override Guard (Step 5.3).

Manages the popup confirmation flow when the operator attempts a REAL mode
trade after the loss lock has been triggered.

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 14):
- After REAL mode is locked, attempting a REAL trade requires override
- Operator must explicitly acknowledge/confirm for each next REAL trade
- Every override event is logged for audit and Side C compatibility
- The guard does NOT store override across sessions — each override is
  a one-time grant that must be re-requested for the next trade
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class OverrideRecord:
    """A single override event record for audit/logging.

    Fields:
        override_id: Unique identifier for this override.
        timestamp: When the override was logged.
        granted: Whether the override was granted.
        reason: Operator-provided reason for override.
        details: Additional context (trade details, mode, session, etc.).
    """
    override_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    granted: bool = False
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class OverrideGuard:
    """Manages override confirmation for REAL mode lock breach.

    After REAL mode is locked by LossLockManager, attempting a REAL trade
    requires explicit operator confirmation through this guard.

    The guard ensures:
    1. Override is explicitly requested (require_override).
    2. Override is explicitly granted/denied by operator.
    3. Every override event is logged.
    4. Each override grants only ONE trade — next trade needs new override.

    Attributes:
        _override_required: Whether override is currently needed.
        _override_granted: Whether override has been granted.
        _current_override: The current override record (if any).
        _override_history: Full history of all override events.
    """

    def __init__(self) -> None:
        """Initialize the override guard."""
        self._override_required: bool = False
        self._override_granted: bool = False
        self._current_override: OverrideRecord | None = None
        self._override_history: list[OverrideRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def require_override(self, reason: str = "REAL mode loss lock breach") -> None:
        """Signal that operator override is required.

        This sets the override-required flag. Captain should check
        is_override_required() before proceeding with a REAL trade
        when loss lock is active.

        Args:
            reason: Why the override is required.
        """
        self._override_required = True
        self._override_granted = False
        self._current_override = OverrideRecord(
            reason=reason,
            granted=False,
        )

    def is_override_required(self) -> bool:
        """Check if override must be obtained before proceeding.

        Returns:
            True if override is currently required, False otherwise.
        """
        return self._override_required

    def grant_override(self, operator_reason: str = "", details: dict[str, Any] | None = None) -> bool:
        """Grant the override. Operator explicitly confirms.

        This simulates the operator acknowledging the popup and
        providing a reason for overriding the loss lock.

        Args:
            operator_reason: Operator-provided justification.
            details: Additional context for the override record.

        Returns:
            True if override was successfully granted.
        """
        if not self._override_required:
            return False  # No override needed — nothing to grant

        self._override_granted = True
        self._override_required = False

        # Update current override record
        record_details: dict[str, Any] = {
            "mode": "REAL",
            "action": "override_loss_lock",
        }
        if details:
            record_details.update(details)

        if self._current_override is not None:
            self._current_override.granted = True
            self._current_override.reason = operator_reason
            self._current_override.details = record_details
            self._current_override.timestamp = datetime.now(timezone.utc)
            self._override_history.append(self._current_override)
            self._current_override = None  # Clear so it can't be modified again

        return True

    def deny_override(self, reason: str = "Operator declined") -> None:
        """Deny the override. Trade remains blocked.

        Args:
            reason: Why the override was denied.
        """
        self._override_granted = False
        self._override_required = False

        if self._current_override is not None:
            self._current_override.granted = False
            self._current_override.reason = reason
            self._current_override.timestamp = datetime.now(timezone.utc)
            self._override_history.append(self._current_override)
            self._current_override = None  # Clear so it can't be re-logged

    def is_override_granted(self) -> bool:
        """Check if override has been granted.

        Returns:
            True if override is currently granted (trade can proceed).
        """
        return self._override_granted

    def clear_override(self) -> None:
        """Clear override state after use.

        Called after the overridden trade completes (or is cancelled).
        The next trade will require a fresh override.
        """
        self._override_required = False
        self._override_granted = False
        self._current_override = None

    def log_override(self, details: dict[str, Any] | None = None) -> OverrideRecord | None:
        """Log an override event explicitly (for Side C / audit).

        Can be called manually when needed. If an override is currently
        active, logs its current state. Otherwise creates a new record.

        Args:
            details: Additional context for the log entry.

        Returns:
            The OverrideRecord that was logged, or None.
        """
        if self._current_override is not None:
            if details:
                self._current_override.details.update(details)
            self._override_history.append(self._current_override)
            return self._current_override

        # No active override — log a standalone entry
        record = OverrideRecord(
            granted=False,
            reason="Standalone audit entry (no active override)",
            details=details or {},
        )
        self._override_history.append(record)
        return record

    def get_override_history(self) -> list[OverrideRecord]:
        """Get the full history of all override events.

        Returns:
            List of OverrideRecord objects.
        """
        return list(self._override_history)

    def get_override_count(self) -> int:
        """Get total number of override events recorded.

        Returns:
            Total override event count.
        """
        return len(self._override_history)

    def get_override_summary(self) -> dict[str, Any]:
        """Get a structured summary of override state.

        Suitable for dashboard (Side B) and logging (Side C).

        Returns:
            Dict with override state fields.
        """
        granted = sum(1 for r in self._override_history if r.granted)
        denied = sum(1 for r in self._override_history if not r.granted)
        return {
            "override_required": self._override_required,
            "override_granted": self._override_granted,
            "total_overrides": self.get_override_count(),
            "granted_count": granted,
            "denied_count": denied,
            "has_active_override": self._current_override is not None,
        }

    def get_current_override(self) -> OverrideRecord | None:
        """Get the current active override record.

        Returns:
            Current OverrideRecord, or None if no active override.
        """
        return self._current_override
