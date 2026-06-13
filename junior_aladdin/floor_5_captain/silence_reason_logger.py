"""Floor 5 — Silence Reason Logger (Step 5.17).

Structured reasons for WAIT / BLOCKED / REJECT decisions.
Every no-trade decision MUST carry at least one SilenceReason.

Architecture (see ROADMAP_FLOOR_05 Section 5.17):
- 11 silence reasons covering all no-trade scenarios
- Primary reason identifies the most significant block
- Session-scoped memory — resets at end of trading day
- Consumed by captain_engine for decision output + Side B dashboard
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import SilenceReason


# ── Severity ranking for silence reasons ───────────────────────────────────
# Higher number = more significant. Used for primary reason selection.
# Psychology block is non-overridable → highest rank.

_REASON_SEVERITY: dict[SilenceReason, int] = {
    SilenceReason.PSYCHOLOGY_BLOCK: 100,       # Non-overridable
    SilenceReason.REAL_MODE_LOCK: 90,           # Hard lock
    SilenceReason.ACTIVE_TRADE_EXISTS: 80,      # One-trade rule
    SilenceReason.DEAD_MARKET: 70,              # No trading environment
    SilenceReason.NARRATIVE_SHIFT: 60,          # Structural change
    SilenceReason.CAPITAL_MISMATCH: 50,         # Capital constraint
    SilenceReason.WEAK_CONVICTION: 40,          # Low confidence
    SilenceReason.INSUFFICIENT_CONFLUENCE: 30,  # Weak alignment
    SilenceReason.TRAP_RISK_HIGH: 25,           # Zone trap concern
    SilenceReason.STALE_SETUP: 20,              # Setup no longer fresh
    SilenceReason.PLAN_EXPIRED: 10,             # Plan timed out
}


def _get_severity(reason: SilenceReason) -> int:
    """Get severity rank for a silence reason.

    Args:
        reason: The SilenceReason to rank.

    Returns:
        Integer severity (higher = more significant).
    """
    return _REASON_SEVERITY.get(reason, 0)


# ── SilenceRecord dataclass ────────────────────────────────────────────────


@dataclass
class SilenceRecord:
    """A single silence reason record.

    Fields:
        decision: The Captain decision type (WAIT, BLOCKED, REJECT).
        reason: The SilenceReason enum value.
        reason_label: Human-readable label (e.g., "Psychology Block").
        details: Optional detailed context about why this reason applies.
        source: Which module/check triggered this reason.
        timestamp: When this reason was logged.
    """
    decision: str = ""
    reason: SilenceReason = SilenceReason.WEAK_CONVICTION
    reason_label: str = ""
    details: str = ""
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ── Human-readable labels for each reason ──────────────────────────────────

_REASON_LABELS: dict[SilenceReason, str] = {
    SilenceReason.INSUFFICIENT_CONFLUENCE: "Insufficient Confluence",
    SilenceReason.PSYCHOLOGY_BLOCK: "Psychology Block",
    SilenceReason.ACTIVE_TRADE_EXISTS: "Active Trade Exists",
    SilenceReason.DEAD_MARKET: "Dead Market",
    SilenceReason.TRAP_RISK_HIGH: "Trap Risk High",
    SilenceReason.STALE_SETUP: "Stale Setup",
    SilenceReason.PLAN_EXPIRED: "Plan Expired",
    SilenceReason.NARRATIVE_SHIFT: "Narrative Shift",
    SilenceReason.CAPITAL_MISMATCH: "Capital Mismatch",
    SilenceReason.REAL_MODE_LOCK: "Real Mode Locked",
    SilenceReason.WEAK_CONVICTION: "Weak Conviction",
}


# ── SilenceReasonLogger ───────────────────────────────────────────────────


class SilenceReasonLogger:
    """Logs and manages structured silence reasons for WAIT/BLOCKED/REJECT.

    Every no-trade decision should be logged with at least one reason.
    The logger maintains a session-scoped history for dashboard and audit.

    Usage::

        logger = SilenceReasonLogger()

        # Log a single reason
        rec = logger.log_reason(
            decision="BLOCKED",
            reason=SilenceReason.PSYCHOLOGY_BLOCK,
            details="Psychology head trade_allowed = False",
            source="permission_gate",
        )

        # Get the most significant reason
        primary = logger.get_primary_reason()
        print(primary.reason_label)  # "Psychology Block"

        # Get all reasons for the session
        for rec in logger.get_session_reasons():
            print(f"[{rec.decision}] {rec.reason_label}")
    """

    def __init__(self) -> None:
        """Initialize the silence reason logger."""
        self._records: list[SilenceRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_reason(
        self,
        decision: str,
        reason: SilenceReason,
        details: str = "",
        source: str = "",
    ) -> SilenceRecord:
        """Log a silence reason.

        Args:
            decision: The Captain decision type (WAIT, BLOCKED, REJECT).
            reason: The SilenceReason enum value.
            details: Optional detailed explanation.
            source: Which module/check triggered this reason.

        Returns:
            The newly created ``SilenceRecord``.
        """
        record = SilenceRecord(
            decision=decision,
            reason=reason,
            reason_label=_REASON_LABELS.get(reason, reason.value),
            details=details,
            source=source,
            timestamp=datetime.utcnow(),
        )
        self._records.append(record)
        return record

    def get_primary_reason(self) -> SilenceRecord | None:
        """Get the most significant silence reason logged this session.

        Uses severity ranking: PSYCHOLOGY_BLOCK > REAL_MODE_LOCK > etc.
        If multiple reasons tied, returns the most recent one.

        Returns:
            The highest-severity ``SilenceRecord``, or None if no records.
        """
        if not self._records:
            return None

        return max(self._records, key=lambda r: (_get_severity(r.reason), r.timestamp))

    def get_session_reasons(self) -> list[SilenceRecord]:
        """Get all silence reasons logged this session.

        Returns:
            List of all ``SilenceRecord`` entries, ordered by log time.
        """
        return list(self._records)

    def get_reasons_by_decision(self, decision: str) -> list[SilenceRecord]:
        """Get all silence reasons for a specific decision type.

        Args:
            decision: Decision type filter (e.g., "WAIT", "BLOCKED", "REJECT").

        Returns:
            List of ``SilenceRecord`` entries matching the decision type.
        """
        return [r for r in self._records if r.decision == decision]

    def get_reason_count(self) -> int:
        """Get total number of silence reasons logged.

        Returns:
            Integer count of all records.
        """
        return len(self._records)

    def get_reason_count_by_type(self) -> dict[str, int]:
        """Get count of each silence reason type.

        Returns:
            Dict mapping reason labels to occurrence counts.
        """
        counts: dict[str, int] = {}
        for record in self._records:
            label = record.reason_label
            counts[label] = counts.get(label, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def clear_session(self) -> None:
        """Clear all silence reason records for a new trading day.

        Called at the start of each new trading session.
        """
        self._records.clear()

    def has_reasons(self) -> bool:
        """Check if any silence reasons have been logged.

        Returns:
            True if at least one record exists.
        """
        return len(self._records) > 0

    # ------------------------------------------------------------------
    # Summary / Utility
    # ------------------------------------------------------------------

    def get_logger_summary(self) -> dict[str, Any]:
        """Get a structured summary of the logger state.

        Returns:
            Dict with logger summary fields.
        """
        primary = self.get_primary_reason()
        return {
            "total_reasons": self.get_reason_count(),
            "primary_reason": primary.reason_label if primary else "",
            "primary_decision": primary.decision if primary else "",
            "reason_breakdown": self.get_reason_count_by_type(),
            "has_reasons": self.has_reasons(),
        }
