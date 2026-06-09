"""Floor 2 Output — review status router.

Provides the **ReviewStatusRouter** class that routes review signals and
status information to the appropriate upper-floor consumers.

Routing destinations:
- **Light signal**: 4-level signal (GOOD/CAUTION/DEGRADED/CRITICAL) sent
  to the Captain summary path. Lightweight — no detailed payload.
- **Side B (Dashboard)**: Detailed review state with event summaries,
  audit findings, and source health overview.
- **Side C (Memory)**: Review event references, audit report references,
  and investigation summaries for long-term storage.

Architecture rules:
- Captain receives ONLY the light signal — no detailed review data.
- Detailed reports go to Side B (dashboard) and Side C (memory).
- ALL review data is factual — no intelligence, no trade judgment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AuditReport,
    HealthEvent,
    ReviewSignal,
)
from junior_aladdin.floor_2_datacenter.review.health_monitor import HealthMonitor
from junior_aladdin.floor_2_datacenter.review.review_engine import ReviewEngine
from junior_aladdin.shared.logging import get_logger

logger = get_logger("review_status_router")


class ReviewStatusRouter:
    """Routes review signals to upper-floor consumers.

    Provides three routing targets:
    - ``route_light_signal``: 4-level signal for Captain (lightweight).
    - ``route_to_side_b``: Detailed review state for the dashboard.
    - ``route_to_side_c``: Event and report references for long-term memory.

    Typical usage::

        router = ReviewStatusRouter(review_engine, health_monitor)

        # For Captain
        signal = router.route_light_signal(\"angel_one\")

        # For Side B (dashboard)
        dashboard_data = router.route_to_side_b()

        # For Side C (memory/journal)
        memory_data = router.route_to_side_c()
    """

    def __init__(
        self,
        review_engine: ReviewEngine,
        health_monitor: HealthMonitor,
    ) -> None:
        """Initialise the review status router.

        Args:
            review_engine: The review engine to read events/signals/reports from.
            health_monitor: The health monitor for source health state data.
        """
        self._review_engine = review_engine
        self._health_monitor = health_monitor

    # ------------------------------------------------------------------
    # Routing Targets
    # ------------------------------------------------------------------

    def route_light_signal(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Route a lightweight review signal intended for the Captain path.

        Captain receives ONLY the 4-level signal and a minimal summary.
        No detailed event data, no raw numbers — just the signal.

        Args:
            source: Optional source scope. If ``None``, aggregate signal.

        Returns:
            A lightweight dict with ``signal``, ``label``, and ``summary``.
        """
        signal = self._review_engine.compute_signal(source)
        label = self._signal_to_label(signal)

        return {
            "type": "review_light_signal",
            "signal": signal.value,
            "label": label,
            "source": source,
            "routed_to": "captain",
            "routed_at": datetime.now(timezone.utc).isoformat(),
        }

    def route_to_side_b(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Route detailed review state for Side B (dashboard).

        Includes event summaries, audit findings, and source health
        overview — suitable for dashboard display.

        Args:
            source: Optional source scope. If ``None``, aggregate data.

        Returns:
            A dict with review state details for dashboard consumption.
        """
        signal = self._review_engine.compute_signal(source)
        events = (
            self._review_engine.get_events_by_source(source)
            if source
            else self._review_engine.get_all_events()
        )

        # Build event summary
        event_summary = self._build_event_summary(events)

        # Build source health overview
        health_states = self._health_monitor.get_all_health_states()

        # Get recent reports
        reports = self._review_engine.get_all_reports()
        recent_reports = [
            {
                "report_id": r.report_id,
                "report_type": r.report_type,
                "score": r.score,
                "summary": r.summary,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in reports[-5:]  # Last 5 reports
        ]

        return {
            "type": "review_side_b",
            "signal": signal.value,
            "source": source,
            "event_summary": event_summary,
            "source_health": health_states,
            "recent_reports": recent_reports,
            "routed_to": "side_b_dashboard",
            "routed_at": datetime.now(timezone.utc).isoformat(),
        }

    def route_to_side_c(
        self,
        source: str | None = None,
        report_limit: int = 10,
    ) -> dict[str, Any]:
        """Route review references for Side C (memory/journal).

        Includes event references, audit report references, and review
        signal history for long-term storage and recall.

        Args:
            source: Optional source scope. If ``None``, aggregate data.
            report_limit: Maximum number of report references to include.

        Returns:
            A dict with review references for memory storage.
        """
        signal = self._review_engine.compute_signal(source)
        events = (
            self._review_engine.get_events_by_source(source)
            if source
            else self._review_engine.get_all_events()
        )

        # Event references (lightweight — no raw payloads)
        event_refs = [
            {
                "event_id": self._get_event_id(e),
                "event_type": e.event_type,
                "severity": e.severity,
                "source": e.source,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ]

        # Report references
        reports = self._review_engine.get_all_reports()
        report_refs = [
            {
                "report_id": r.report_id,
                "report_type": r.report_type,
                "score": r.score,
                "summary": r.summary,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in reports[-report_limit:]
        ]

        return {
            "type": "review_side_c",
            "signal": signal.value,
            "source": source,
            "event_count": len(event_refs),
            "events": event_refs,
            "report_count": len(report_refs),
            "reports": report_refs,
            "routed_to": "side_c_memory",
            "routed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _signal_to_label(signal: ReviewSignal) -> str:
        """Convert a ReviewSignal enum to a human-readable label."""
        labels = {
            ReviewSignal.GOOD: "All systems nominal",
            ReviewSignal.CAUTION: "Minor issues detected — monitoring",
            ReviewSignal.DEGRADED: "Significant degradation — attention required",
            ReviewSignal.CRITICAL: "Critical issues — immediate action needed",
        }
        return labels.get(signal, "Unknown")

    def _get_event_id(self, event: HealthEvent) -> str:
        """Generate a deterministic event ID from event fields.

        Since ``HealthEvent`` does not store an ``event_id`` field,
        this generates a stable fallback ID from the event's type,
        source, and timestamp.

        Args:
            event: The HealthEvent to generate an ID for.

        Returns:
            An event ID string.
        """
        ts = event.timestamp.timestamp() if event.timestamp else 0
        return f"evt_{event.event_type}_{event.source}_{ts:.0f}"

    def _build_event_summary(
        self,
        events: list[HealthEvent],
    ) -> dict[str, Any]:
        """Build a summary of health events.

        Args:
            events: List of HealthEvent instances.

        Returns:
            Dict with event counts by severity and source.
        """
        total = len(events)
        by_severity: dict[str, int] = {}
        by_source: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for event in events:
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
            by_source[event.source] = by_source.get(event.source, 0) + 1
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1

        # Determine highest severity
        severity_order = ["CRITICAL", "SEVERE", "CAUTION"]
        highest = "NONE"
        for s in severity_order:
            if by_severity.get(s, 0) > 0:
                highest = s
                break

        return {
            "total_events": total,
            "by_severity": by_severity,
            "by_source": by_source,
            "by_event_type": by_type,
            "highest_severity": highest,
        }
