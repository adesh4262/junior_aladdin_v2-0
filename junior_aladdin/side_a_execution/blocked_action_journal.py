"""Side A — Blocked Action Journal: Severity-taxonomied block records.

Records every action that Side A blocked for safety/rule reasons.
Every time the risk gate blocks an intent, a BlockedActionRecord is created
and stored here.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.17):
- Records preserve: timestamp, trade_id, block_reason, mode, severity, details
- Severity taxonomy: INFO, CAUTION, SEVERE, CRITICAL
- Every block from risk gate must be recorded
- Queryable by trade_id, severity, and recency

Output contracts:
- To Side C (Memory): BlockedActionRecord → EXECUTION_EVENT / BLOCKED_ACTION
- To Side B (Dashboard): filtered block queries for display
- To execution_logging_layer: block events for Side C ingestion
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import ExecutionMode, Severity
from junior_aladdin.side_a_execution.side_a_types import BlockedActionRecord

logger = get_logger(__name__)


# =============================================================================
# BlockedActionJournal
# =============================================================================


class BlockedActionJournal:
    """Severity-taxonomied journal of all blocked actions.

    Every time Side A blocks an action for safety/rule reasons, a record
    is created and stored here.  Supports query by trade_id, severity,
    and recency.

    Usage::

        journal = BlockedActionJournal(
            on_log_callback=logging_layer.log,
        )

        # Record a blocked action (from risk gate)
        journal.record(BlockedActionRecord(
            trade_id="T001",
            block_reason="Insufficient capital",
            mode=ExecutionMode.REAL,
            severity=Severity.CAUTION,
            details={"available": 10000, "required": 20000},
        ))

        # Query blocks for a trade
        blocks = journal.get_by_trade("T001")

        # Get all CAUTION+ blocks
        warnings = journal.get_by_severity(min_severity=Severity.CAUTION)
    """

    def __init__(
        self,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
        max_records: int = 500,
    ) -> None:
        """Initialize the BlockedActionJournal.

        Args:
            on_log_callback: Called for all journal events.
                Signature: (event_type: str, data: dict) -> None.
            max_records: Maximum number of records to keep (default 500).
                Oldest records are dropped when limit is exceeded.
        """
        self._records: list[BlockedActionRecord] = []
        self._max_records = max_records
        self._on_log_callback = on_log_callback

    # ------------------------------------------------------------------
    # Record Methods
    # ------------------------------------------------------------------

    def record(self, record: BlockedActionRecord) -> BlockedActionRecord:
        """Record a blocked action.

        Args:
            record: The BlockedActionRecord to store.

        Returns:
            The stored record (with timestamp set if not provided).
        """
        if record.timestamp is None:
            record.timestamp = datetime.utcnow()

        self._records.append(record)

        # Enforce max records cap
        if len(self._records) > self._max_records:
            dropped_count = len(self._records) - self._max_records
            self._records = self._records[-self._max_records:]

            logger.warning(
                "Blocked action journal reached max records — oldest entries dropped",
                extra={
                    "max_records": self._max_records,
                    "dropped_count": dropped_count,
                    "current_count": len(self._records),
                },
            )

            # If a CRITICAL record was among those dropped, escalate
            # (This is a safety measure — critical blocks should not be lost)
            self._log("JOURNAL_DROPPED_RECORDS", {
                "max_records": self._max_records,
                "dropped_count": dropped_count,
                "severity": "WARNING",
                "action": "Oldest records dropped — consider increasing max_records",
            })

        self._log("BLOCKED_ACTION_RECORDED", {
            "trade_id": record.trade_id,
            "block_reason": record.block_reason,
            "severity": record.severity.value,
            "mode": record.mode.value,
        })

        logger.info(
            "Blocked action recorded",
            extra={
                "trade_id": record.trade_id,
                "reason": record.block_reason,
                "severity": record.severity.value,
            },
        )

        return record

    def record_block(
        self,
        trade_id: str,
        block_reason: str,
        mode: ExecutionMode = ExecutionMode.ALERT,
        severity: Severity = Severity.CAUTION,
        details: dict[str, Any] | None = None,
    ) -> BlockedActionRecord:
        """Convenience method to create and record a blocked action in one call.

        Args:
            trade_id: Which trade was blocked.
            block_reason: Why the action was blocked.
            mode: Execution mode at time of block.
            severity: Severity classification.
            details: Additional context dict.

        Returns:
            The created BlockedActionRecord.
        """
        record = BlockedActionRecord(
            trade_id=trade_id,
            block_reason=block_reason,
            mode=mode,
            severity=severity,
            details=details or {},
        )
        return self.record(record)

    # ------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------

    def get_by_trade(self, trade_id: str) -> list[BlockedActionRecord]:
        """Get all blocked actions for a specific trade.

        Args:
            trade_id: The trade identifier.

        Returns:
            List of BlockedActionRecord, oldest first.
        """
        return [r for r in self._records if r.trade_id == trade_id]

    def get_by_severity(
        self,
        min_severity: Severity = Severity.CAUTION,
    ) -> list[BlockedActionRecord]:
        """Get all blocked actions at or above a severity level.

        Severity ordering: INFO < CAUTION < SEVERE < CRITICAL

        Args:
            min_severity: Minimum severity threshold.

        Returns:
            List of BlockedActionRecord at or above min_severity, newest first.
        """
        severity_order = {
            Severity.INFO: 0,
            Severity.CAUTION: 1,
            Severity.SEVERE: 2,
            Severity.CRITICAL: 3,
        }
        threshold = severity_order.get(min_severity, 0)
        results = [
            r for r in self._records
            if severity_order.get(r.severity, 0) >= threshold
        ]
        results.reverse()  # newest first
        return results

    def get_recent(self, count: int = 10) -> list[BlockedActionRecord]:
        """Get the most recent blocked actions.

        Args:
            count: Number of records to return (default 10).

        Returns:
            List of BlockedActionRecord, newest first.
        """
        results = list(reversed(self._records))
        return results[:count]

    def get_session_blocks(self) -> list[BlockedActionRecord]:
        """Get all blocked actions for the current session.

        Returns:
            All records, oldest first.
        """
        return list(self._records)

    def count_by_severity(self) -> dict[str, int]:
        """Count blocked actions by severity level.

        Returns:
            Dict of severity value → count.
        """
        counts: dict[str, int] = {}
        for r in self._records:
            sev = r.severity.value
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    def count_by_trade(self) -> dict[str, int]:
        """Count blocked actions by trade ID.

        Returns:
            Dict of trade_id → count.
        """
        counts: dict[str, int] = {}
        for r in self._records:
            counts[r.trade_id] = counts.get(r.trade_id, 0) + 1
        return counts

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary of the blocked action journal.

        Returns:
            Dict with total_blocks, severity_counts, recent_reasons.
        """
        recent = self.get_recent(5)
        return {
            "total_blocks": len(self._records),
            "severity_counts": self.count_by_severity(),
            "recent_reasons": [
                {
                    "trade_id": r.trade_id,
                    "reason": r.block_reason,
                    "severity": r.severity.value,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                }
                for r in recent
            ],
        }

    def clear(self) -> None:
        """Clear all records (testing utility only)."""
        self._records.clear()
        logger.info("Blocked action journal cleared")

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
