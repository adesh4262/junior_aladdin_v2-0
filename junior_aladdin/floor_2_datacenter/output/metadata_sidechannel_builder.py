"""Floor 2 Output — metadata side-channel builder.

Provides the **MetadataSidechannelBuilder** class that packages factual
metadata — quality facts, traceability, transform stage, review signal,
and source health — into a lightweight side-channel for transport to
upper floors alongside the main data stream.

Architecture rules:
- Side-channel contains FACTUAL metadata only — no raw market data.
- All fields are descriptive (packet_completeness=96%), never prescriptive.
- ReviewSignal is a 4-level light signal (GOOD/CAUTION/DEGRADED/CRITICAL).
- Detailed review reports go to Side B (dashboard) and Side C (memory),
  NOT through the side-channel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    QualityFacts,
    ReviewSignal,
)
from junior_aladdin.floor_2_datacenter.metadata.transform_stage_tracker import (
    TransformStageTracker,
)
from junior_aladdin.floor_2_datacenter.review.health_monitor import HealthMonitor
from junior_aladdin.floor_2_datacenter.review.review_engine import ReviewEngine
from junior_aladdin.shared.logging import get_logger

logger = get_logger("metadata_sidechannel_builder")


class MetadataSidechannelBuilder:
    """Builds the metadata side-channel for the Floor 3 handoff.

    Packages quality facts, traceability, transform stage history, review
    signal, and source health state into a single dict.

    Typical usage::

        builder = MetadataSidechannelBuilder(review_engine, health_monitor, tracker)
        sidechannel = builder.build_sidechannel()
    """

    def __init__(
        self,
        review_engine: ReviewEngine,
        health_monitor: HealthMonitor,
        transform_tracker: TransformStageTracker,
    ) -> None:
        """Initialise the side-channel builder.

        Args:
            review_engine: The review engine (for events, signals, reports).
            health_monitor: The health monitor (for source health states).
            transform_tracker: The transform stage tracker (for stage history).
        """
        self._review_engine = review_engine
        self._health_monitor = health_monitor
        self._transform_tracker = transform_tracker

    # ------------------------------------------------------------------
    # Main Build API
    # ------------------------------------------------------------------

    def build_sidechannel(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Build the complete metadata side-channel dict.

        Args:
            source: Optional source name to scope the side-channel to.
                If ``None``, includes aggregate data across all sources.

        Returns:
            A dict with the following top-level keys:
            - ``quality_facts``: Dict of factual quality metrics.
            - ``review_signal``: 4-level light signal string.
            - ``source_health``: Dict of source health states.
            - ``transform_stage``: Dict of transform stage summaries.
            - ``event_summary``: Count of active health events.
            - ``report_summary``: Count of available audit reports.
            - ``built_at``: ISO timestamp of when this was built.
        """
        # Build quality facts
        quality_facts = self._build_quality_facts(source)

        # Compute review signal
        signal = self._review_engine.compute_signal(source)
        review_signal_str = signal.value

        # Build source health summary
        if source:
            source_health = self._health_monitor.get_all_health_states()
            if source in source_health:
                source_health = {source: source_health[source]}
            else:
                source_health = {}
        else:
            source_health = self._health_monitor.get_all_health_states()

        # Build transform stage summary
        transform_stage = self._build_transform_summary(source)

        # Event and report counts
        event_count = self._review_engine.get_active_event_count()
        report_count = self._review_engine.get_report_count()

        # Event sources
        event_sources = list(self._review_engine.get_event_sources())

        sidechannel: dict[str, Any] = {
            "quality_facts": quality_facts,
            "review_signal": review_signal_str,
            "source_health": source_health,
            "transform_stage": transform_stage,
            "event_summary": {
                "active_events": event_count,
                "event_sources": event_sources,
            },
            "report_summary": {
                "total_reports": report_count,
            },
            "built_at": datetime.now(timezone.utc).isoformat(),
        }

        return sidechannel

    # ------------------------------------------------------------------
    # Specific Side-Channel Sections
    # ------------------------------------------------------------------

    def build_quality_facts_section(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Build only the quality facts section.

        Args:
            source: Optional source to scope facts to.

        Returns:
            A dict of factual quality metrics.
        """
        return self._build_quality_facts(source)

    def build_review_signal_section(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Build only the review signal section.

        Args:
            source: Optional source to scope signal to.

        Returns:
            A dict with ``signal`` (str) and ``source`` (str | None).
        """
        signal = self._review_engine.compute_signal(source)
        return {
            "signal": signal.value,
            "source": source,
        }

    def build_source_health_section(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Build only the source health section.

        Args:
            source: Optional source to scope health to.

        Returns:
            A dict mapping source names to their health state info.
        """
        if source:
            health = self._health_monitor.get_all_health_states()
            if source in health:
                return {source: health[source]}
            return {}
        return self._health_monitor.get_all_health_states()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _build_quality_facts(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Build factual quality metrics for the side-channel.

        Quality facts are descriptive (packet_completeness=96%), NOT
        prescriptive (\"this feed is good for trading\").
        """
        # Compute per-source health scores
        if source:
            score = self._health_monitor.get_health_score(source)
            state = self._health_monitor.get_health_state(source)
            return {
                "overall_health_score": score,
                "overall_health_state": state,
                "source": source,
            }

        # Aggregate across all sources
        all_health = self._health_monitor.get_all_health_states()
        if not all_health:
            return {
                "overall_health_score": 1.0,
                "overall_health_state": "HEALTHY",
                "source_count": 0,
                "active_events": 0,
            }

        avg_score = sum(
            h.get("score", 1.0) for h in all_health.values()
        ) / len(all_health)

        # Determine aggregate state — worst state wins
        states = [h.get("state", "HEALTHY") for h in all_health.values()]
        if "CRITICAL" in states:
            agg_state = "CRITICAL"
        elif "DEGRADED" in states:
            agg_state = "DEGRADED"
        else:
            agg_state = "HEALTHY"

        return {
            "overall_health_score": round(avg_score, 2),
            "overall_health_state": agg_state,
            "source_count": len(all_health),
            "active_events": self._review_engine.get_active_event_count(),
        }

    def _build_transform_summary(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Build a summary of transform stage tracking.

        Args:
            source: Optional source to scope summary (not directly used
                since transform tracker is packet-based, not source-based).

        Returns:
            Dict with pipeline stage information.
        """
        tracker = self._transform_tracker

        # Get overall stats from the transform tracker
        stuck_packets = tracker.find_stuck_packets()

        return {
            "stuck_packets": len(stuck_packets),
            "stuck_details": stuck_packets[:10],  # Limit to first 10
            "available": True,
        }
