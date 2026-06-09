"""Floor 2 Review Engine — event emission, health signals, audits.

Provides the **ReviewEngine** class that manages data health review for the
Floor 2 pipeline.

Responsibilities:
- **Event emission**: Emit ``HealthEvent`` objects when issues are detected.
- **Health signals**: Compute ``ReviewSignal`` from consolidated health state.
- **Audit reports**: Generate ``AuditReport`` for scheduled or event-triggered
  investigations.
- **Review state**: Track review status per source and feed type.

Architecture rules:
- All events are FACTUAL — severities describe data health, not market opinion.
- ``ReviewSignal`` is a lightweight 4-level signal: GOOD → CAUTION → DEGRADED → CRITICAL.
- ``AuditReport.score`` describes pipeline health (0.0–1.0), NOT tradeability.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AuditReport,
    HealthEvent,
    ReviewSignal,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("review_engine")

# Default severity thresholds for computing ReviewSignal
_SEVERITY_WEIGHTS: dict[str, int] = {
    "CAUTION": 1,
    "SEVERE": 2,
    "CRITICAL": 3,
}

# Default thresholds for signal escalation
_SIGNAL_THRESHOLDS: dict[ReviewSignal, int] = {
    ReviewSignal.GOOD: 0,
    ReviewSignal.CAUTION: 1,  # at least 1 active event
    ReviewSignal.DEGRADED: 3,  # 3+ active events or any CRITICAL
    ReviewSignal.CRITICAL: 5,  # 5+ active events or 2+ CRITICAL
}


class ReviewEngine:
    """Manages data health review — events, signals, and audits.

    Typical usage::

        engine = ReviewEngine()
        engine.emit_event("latency_spike", "SEVERE", "angel_one",
                          "Latency exceeded 500ms")
        signal = engine.compute_signal("angel_one")
        report = engine.run_scheduled_audit()
        report = engine.run_investigation(source="angel_one")
    """

    def __init__(
        self,
        signal_thresholds: dict[ReviewSignal, int] | None = None,
        severity_weights: dict[str, int] | None = None,
    ) -> None:
        """Initialise the review engine.

        Args:
            signal_thresholds: Custom thresholds for signal escalation.
                Defaults to ``_SIGNAL_THRESHOLDS``.
            severity_weights: Custom weights for severity levels.
                Defaults to ``_SEVERITY_WEIGHTS``.
        """
        self._lock = Lock()
        # event_id -> HealthEvent
        self._events: dict[str, HealthEvent] = {}
        # source -> [event_id, ...]
        self._source_events: dict[str, list[str]] = {}
        # source -> review_status
        self._review_status: dict[str, str] = {}
        # report_id -> AuditReport
        self._reports: dict[str, AuditReport] = {}

        self._signal_thresholds = signal_thresholds or _SIGNAL_THRESHOLDS
        self._severity_weights = severity_weights or _SEVERITY_WEIGHTS

    # ------------------------------------------------------------------
    # Event Management
    # ------------------------------------------------------------------

    def emit_event(
        self,
        event_type: str,
        severity: str,
        source: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> str:
        """Emit a new health event.

        Args:
            event_type: Type/category of the health event
                (e.g., ``\"latency_spike\"``, ``\"heartbeat_missed\"``).
            severity: ``\"CAUTION\"``, ``\"SEVERE\"``, or ``\"CRITICAL\"``.
            source: The source or component that triggered the event.
            message: Human-readable description.
            details: Optional dict with additional event-specific data.

        Returns:
            The unique event ID.

        Raises:
            ValueError: If severity is not recognised.
        """
        if severity not in self._severity_weights:
            raise ValueError(
                f"Unknown severity: {severity!r}. "
                f"Must be one of {list(self._severity_weights)}",
            )

        event_id = _generate_event_id(event_type, source)
        event = HealthEvent(
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            timestamp=datetime.now(timezone.utc),
            details=details or {},
        )

        with self._lock:
            self._events[event_id] = event
            self._source_events.setdefault(source, []).append(event_id)

        logger.debug(
            "Health event emitted",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "severity": severity,
                "source": source,
            },
        )
        return event_id

    def get_event(self, event_id: str) -> HealthEvent | None:
        """Get a single health event by ID.

        Args:
            event_id: The unique event identifier.

        Returns:
            The ``HealthEvent``, or ``None`` if not found.
        """
        with self._lock:
            return self._events.get(event_id)

    def get_events_by_source(self, source: str) -> list[HealthEvent]:
        """Get all events for a given source.

        Args:
            source: The source name.

        Returns:
            List of ``HealthEvent`` instances (most recent first).
        """
        with self._lock:
            event_ids = self._source_events.get(source, [])
            events = [self._events[eid] for eid in event_ids if eid in self._events]
        return list(reversed(events))

    def get_all_events(self) -> list[HealthEvent]:
        """Get all events across all sources.

        Returns:
            List of all ``HealthEvent`` instances (most recent first).
        """
        with self._lock:
            events = list(self._events.values())
        return list(reversed(events))

    def clear_events(self, source: str | None = None) -> int:
        """Clear events, optionally for a specific source.

        Args:
            source: If provided, only clear events for this source.

        Returns:
            Number of events cleared.
        """
        cleared = 0
        with self._lock:
            if source:
                event_ids = self._source_events.pop(source, [])
                for eid in event_ids:
                    self._events.pop(eid, None)
                cleared = len(event_ids)
            else:
                cleared = len(self._events)
                self._events.clear()
                self._source_events.clear()
        return cleared

    # ------------------------------------------------------------------
    # Review Signal Computation
    # ------------------------------------------------------------------

    def compute_signal(self, source: str | None = None) -> ReviewSignal:
        """Compute the current ``ReviewSignal`` for a source or the whole pipeline.

        The signal is determined by the number and severity of active events.

        Args:
            source: If provided, compute signal for this source only.

        Returns:
            The computed ``ReviewSignal`` (GOOD / CAUTION / DEGRADED / CRITICAL).
        """
        events = self.get_events_by_source(source) if source else self.get_all_events()

        if not events:
            return ReviewSignal.GOOD

        total_events = len(events)
        critical_count = sum(
            1 for e in events if e.severity == "CRITICAL"
        )
        total_weight = sum(
            self._severity_weights.get(e.severity, 0) for e in events
        )

        # Quick escalation for critical events
        if critical_count >= 2:
            return ReviewSignal.CRITICAL
        if critical_count >= 1:
            return ReviewSignal.DEGRADED

        # Use thresholds based on event count
        if total_weight >= self._signal_thresholds.get(ReviewSignal.CRITICAL, 5):
            return ReviewSignal.CRITICAL
        if total_weight >= self._signal_thresholds.get(ReviewSignal.DEGRADED, 3):
            return ReviewSignal.DEGRADED
        if total_weight >= self._signal_thresholds.get(ReviewSignal.CAUTION, 1):
            return ReviewSignal.CAUTION

        return ReviewSignal.GOOD

    # ------------------------------------------------------------------
    # Review Status Tracking
    # ------------------------------------------------------------------

    def set_review_status(self, source: str, status: str) -> None:
        """Set the review status for a source.

        Args:
            source: The source name.
            status: Review status (e.g., ``\"PENDING\"``, ``\"IN_REVIEW\"``,
                ``\"CLEARED\"``).
        """
        with self._lock:
            self._review_status[source] = status
        logger.debug(
            "Review status updated",
            extra={"source": source, "status": status},
        )

    def get_review_status(self, source: str) -> str | None:
        """Get the review status for a source.

        Args:
            source: The source name.

        Returns:
            The review status string, or ``None`` if not set.
        """
        with self._lock:
            return self._review_status.get(source)

    def get_all_review_statuses(self) -> dict[str, str]:
        """Get all review statuses.

        Returns:
            Dict of ``{source: status}``.
        """
        with self._lock:
            return dict(self._review_status)

    # ------------------------------------------------------------------
    # Audit Reports
    # ------------------------------------------------------------------

    def run_scheduled_audit(
        self,
        scope: dict[str, Any] | None = None,
    ) -> AuditReport:
        """Run a scheduled audit of the pipeline or a specific scope.

        Analyses all active events and produces a summary report with an
        overall health score.

        Args:
            scope: Optional dict specifying audit scope
                (e.g., ``{\"source\": \"angel_one\"}``).

        Returns:
            An ``AuditReport`` with findings and a health score (0.0–1.0).
        """
        source = scope.get("source") if scope else None
        events = (
            self.get_events_by_source(source)
            if source
            else self.get_all_events()
        )

        findings = []
        total_severity = 0

        for event in events:
            finding: dict[str, Any] = {
                "event_type": event.event_type,
                "severity": event.severity,
                "source": event.source,
                "message": event.message,
                "timestamp": event.timestamp.isoformat(),
            }
            findings.append(finding)
            total_severity += self._severity_weights.get(event.severity, 0)

        max_possible_severity = len(events) * max(self._severity_weights.values())
        score = max(0.0, 1.0 - (total_severity / max_possible_severity)) if max_possible_severity > 0 else 1.0

        summary_parts = []
        if source:
            summary_parts.append(f"Source: {source}")
        summary_parts.append(
            f"{len(findings)} active event(s), score={score:.2f}"
        )

        report = AuditReport(
            report_id=f"audit_{uuid.uuid4().hex[:8]}",
            report_type="SCHEDULED",
            summary=" | ".join(summary_parts),
            findings=findings,
            score=round(score, 2),
            timestamp=datetime.now(timezone.utc),
        )

        with self._lock:
            self._reports[report.report_id] = report

        logger.info(
            "Scheduled audit completed",
            extra={
                "report_id": report.report_id,
                "findings": len(findings),
                "score": report.score,
            },
        )
        return report

    def run_investigation(
        self,
        source: str | None = None,
        event_type: str | None = None,
    ) -> AuditReport:
        """Run a targeted investigation audit.

        Filters events by source and/or event type to produce a focused
        audit report.

        Args:
            source: Filter events by source.
            event_type: Filter events by event type.

        Returns:
            An ``AuditReport`` focused on the specified criteria.
        """
        events = self.get_all_events()

        # Filter by source
        if source:
            events = [e for e in events if e.source == source]

        # Filter by event type
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        findings = []
        total_severity = 0

        for event in events:
            finding: dict[str, Any] = {
                "event_type": event.event_type,
                "severity": event.severity,
                "source": event.source,
                "message": event.message,
                "timestamp": event.timestamp.isoformat(),
            }
            findings.append(finding)
            total_severity += self._severity_weights.get(event.severity, 0)

        max_possible = len(events) * max(self._severity_weights.values())
        score = max(0.0, 1.0 - (total_severity / max_possible)) if max_possible > 0 else 1.0

        summary_parts = []
        if source:
            summary_parts.append(f"Source: {source}")
        if event_type:
            summary_parts.append(f"Type: {event_type}")
        summary_parts.append(
            f"{len(findings)} event(s), score={score:.2f}"
        )

        report = AuditReport(
            report_id=f"invest_{uuid.uuid4().hex[:8]}",
            report_type="INVESTIGATION",
            summary=" | ".join(summary_parts),
            findings=findings,
            score=round(score, 2),
            timestamp=datetime.now(timezone.utc),
        )

        with self._lock:
            self._reports[report.report_id] = report

        logger.info(
            "Investigation audit completed",
            extra={
                "report_id": report.report_id,
                "findings": len(findings),
                "score": report.score,
            },
        )
        return report

    def get_report(self, report_id: str) -> AuditReport | None:
        """Get a single audit report by ID.

        Args:
            report_id: The unique report identifier.

        Returns:
            The ``AuditReport``, or ``None`` if not found.
        """
        with self._lock:
            return self._reports.get(report_id)

    def get_all_reports(self) -> list[AuditReport]:
        """Get all audit reports.

        Returns:
            List of ``AuditReport`` instances (most recent first).
        """
        with self._lock:
            reports = list(self._reports.values())
        return list(reversed(reports))

    def get_active_event_count(self) -> int:
        """Get the total number of active events.

        Returns:
            Active event count.
        """
        with self._lock:
            return len(self._events)

    def get_event_sources(self) -> set[str]:
        """Get all source names that have active events.

        Returns:
            Set of source names.
        """
        with self._lock:
            return set(self._source_events.keys())

    def get_report_count(self) -> int:
        """Get the total number of audit reports generated.

        Returns:
            Report count.
        """
        with self._lock:
            return len(self._reports)

    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset ALL review engine state — events, reports, and statuses."""
        with self._lock:
            self._events.clear()
            self._source_events.clear()
            self._review_status.clear()
            self._reports.clear()
        logger.info("ReviewEngine state reset")


def _generate_event_id(event_type: str, source: str) -> str:
    """Generate a unique event ID from event type, source, and short UUID."""
    short_id = uuid.uuid4().hex[:6]
    return f"{event_type}_{source}_{short_id}"
