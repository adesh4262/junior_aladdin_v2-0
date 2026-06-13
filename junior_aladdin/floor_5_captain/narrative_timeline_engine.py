"""Floor 5 — Narrative Timeline Engine (Step 5.6).

Maintains a timestamped intraday event-chain memory so Captain understands
HOW the market arrived at its current state — not just what it is doing now.

The timeline is updated during the heavy cycle (after market story is built).
It feeds into decision snapshots, active trade supervision, and thesis
integrity tracking.

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 23):
- Timeline is updated AFTER market story engine in the heavy cycle
- Timeline stores significant market events only — NO raw tick logging
- Light cycle reads but does NOT update the timeline
- Timeline excerpts feed into decision snapshots for audit/calibration
- Events are chronological with timestamps for replay compatibility
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    NarrativeTimeline,
    NarrativeTimelineEvent,
)


# ── Standard event type constants ──────────────────────────────────────────
EVENT_GAP_UP = "gap_up"
EVENT_GAP_DOWN = "gap_down"
EVENT_PDH_TOUCH = "pdh_touch"
EVENT_PDL_TOUCH = "pdl_touch"
EVENT_PDH_SWEEP = "pdh_sweep"
EVENT_PDL_SWEEP = "pdl_sweep"
EVENT_LIQUIDITY_SWEEP = "liquidity_sweep"
EVENT_DISPLACEMENT = "displacement"
EVENT_FVG_CREATION = "fvg_creation"
EVENT_CONSOLIDATION = "consolidation"
EVENT_BOS = "bos"                    # Break of Structure
EVENT_CHOCH = "choch"                # Change of Character
EVENT_STRUCTURE_BREAK = "structure_break"
EVENT_REGIME_SHIFT = "regime_shift"
EVENT_OPTIONS_WALL_INTERACTION = "options_wall_interaction"
EVENT_ARMED_PLAN_CREATED = "armed_plan_created"
EVENT_ARMED_PLAN_EXPIRED = "armed_plan_expired"
EVENT_TRADE_EXECUTED = "trade_executed"
EVENT_TRADE_EXITED = "trade_exited"
EVENT_INTERVENTION = "intervention"
EVENT_SESSION_START = "session_start"
EVENT_SESSION_END = "session_end"
EVENT_MILESTONE = "milestone"

# ── Display labels for event types ─────────────────────────────────────────
_EVENT_LABELS: dict[str, str] = {
    EVENT_GAP_UP: "Gap Up",
    EVENT_GAP_DOWN: "Gap Down",
    EVENT_PDH_TOUCH: "PDH Touch",
    EVENT_PDL_TOUCH: "PDL Touch",
    EVENT_PDH_SWEEP: "PDH Sweep",
    EVENT_PDL_SWEEP: "PDL Sweep",
    EVENT_LIQUIDITY_SWEEP: "Liquidity Sweep",
    EVENT_DISPLACEMENT: "Displacement",
    EVENT_FVG_CREATION: "FVG Created",
    EVENT_CONSOLIDATION: "Consolidation",
    EVENT_BOS: "Break of Structure",
    EVENT_CHOCH: "Change of Character",
    EVENT_STRUCTURE_BREAK: "Structure Break",
    EVENT_REGIME_SHIFT: "Regime Shift",
    EVENT_OPTIONS_WALL_INTERACTION: "Options Wall Interaction",
    EVENT_ARMED_PLAN_CREATED: "Armed Plan Created",
    EVENT_ARMED_PLAN_EXPIRED: "Armed Plan Expired",
    EVENT_TRADE_EXECUTED: "Trade Executed",
    EVENT_TRADE_EXITED: "Trade Exited",
    EVENT_INTERVENTION: "Intervention",
    EVENT_SESSION_START: "Session Start",
    EVENT_SESSION_END: "Session End",
    EVENT_MILESTONE: "Milestone",
}

# ── Max events in timeline (bounded to prevent unbounded memory growth) ─────
_DEFAULT_MAX_EVENTS = 200


class NarrativeTimelineEngine:
    """Timestamped intraday event-chain memory for Captain.

    Stores significant market events in chronological order so Captain
    understands how the market evolved through the day.

    Usage::

        engine = NarrativeTimelineEngine()
        engine.add_event(EVENT_GAP_UP, details="Gapped above PDH at open",
                         price_level=19650.0)
        engine.add_event(EVENT_LIQUIDITY_SWEEP, details="PDH sweep at 19650",
                         price_level=19650.0)

        timeline = engine.get_timeline()
        recent = engine.get_recent_events(5)
        excerpt = engine.get_excerpt()
        engine.clear_session()
    """

    def __init__(self, max_events: int = _DEFAULT_MAX_EVENTS) -> None:
        """Initialize the narrative timeline.

        Args:
            max_events: Maximum number of events to retain. When the limit
                is exceeded, the oldest events are pruned automatically.
        """
        self._max_events = max_events
        self._timeline = NarrativeTimeline()

    # ------------------------------------------------------------------
    # Public API — Writing
    # ------------------------------------------------------------------

    def add_event(
        self,
        event_type: str,
        details: str = "",
        price_level: float = 0.0,
        timestamp: datetime | None = None,
    ) -> NarrativeTimelineEvent:
        """Add a significant market event to the timeline.

        Events are appended in chronological order. When the timeline
        exceeds ``max_events``, the oldest events are pruned.

        Args:
            event_type: One of the ``EVENT_*`` constants (e.g., ``EVENT_GAP_UP``).
            details: Human-readable description of the event.
            price_level: Price level at which the event occurred (if relevant).
            timestamp: When the event occurred. If None, uses ``datetime.utcnow()``.

        Returns:
            The newly created ``NarrativeTimelineEvent``.
        """
        dt = timestamp or datetime.utcnow()
        event = NarrativeTimelineEvent(
            event_type=event_type,
            details=details,
            timestamp=dt,
            price_level=price_level,
        )

        self._timeline.events.append(event)
        self._timeline.last_update = dt
        self._timeline.event_count = len(self._timeline.events)

        # Prune oldest events if over the limit
        if len(self._timeline.events) > self._max_events:
            excess = len(self._timeline.events) - self._max_events
            self._timeline.events = self._timeline.events[excess:]
            self._timeline.event_count = len(self._timeline.events)

        return event

    def add_events(
        self,
        events: list[dict[str, Any]],
    ) -> list[NarrativeTimelineEvent]:
        """Add multiple events at once.

        Each dict must have an ``event_type`` key and may optionally
        include ``details``, ``price_level``, and ``timestamp``.

        Args:
            events: List of event dicts.

        Returns:
            List of created ``NarrativeTimelineEvent`` objects.
        """
        created = []
        for evt in events:
            created.append(self.add_event(
                event_type=evt.get("event_type", EVENT_MILESTONE),
                details=evt.get("details", ""),
                price_level=evt.get("price_level", 0.0),
                timestamp=evt.get("timestamp"),
            ))
        return created

    def update_from_market_story(
        self,
        regime: str,
        session_phase: str,
        previous_regime: str | None = None,
    ) -> NarrativeTimelineEvent | None:
        """Optionally record a regime shift event if the regime changed.

        This is called after the market story engine builds a new story.
        If the regime has changed since the last call, a REGIME_SHIFT
        event is recorded.

        Args:
            regime: Current regime string (e.g., ``TREND_UP``).
            session_phase: Current session phase value.
            previous_regime: The previous regime to compare against.

        Returns:
            The created event if a regime shift was detected, else None.
        """
        if previous_regime is not None and previous_regime != regime:
            return self.add_event(
                event_type=EVENT_REGIME_SHIFT,
                details=f"Regime shift: {previous_regime} → {regime} during {session_phase}",
            )
        return None

    # ------------------------------------------------------------------
    # Public API — Reading
    # ------------------------------------------------------------------

    def get_timeline(self) -> NarrativeTimeline:
        """Get the full timeline object.

        Returns:
            The complete ``NarrativeTimeline`` with all events.
        """
        return self._timeline

    def get_all_events(self) -> list[NarrativeTimelineEvent]:
        """Get all events in chronological order.

        Returns:
            List of all ``NarrativeTimelineEvent`` objects.
        """
        return list(self._timeline.events)

    def get_recent_events(self, count: int = 5) -> list[NarrativeTimelineEvent]:
        """Get the most recent N events.

        Args:
            count: Number of recent events to return.

        Returns:
            List of the most recent ``NarrativeTimelineEvent`` objects
            (newest first).
        """
        return list(reversed(self._timeline.events[-count:]))

    def get_events_since(self, since_timestamp: datetime) -> list[NarrativeTimelineEvent]:
        """Get all events that occurred after a given timestamp.

        Args:
            since_timestamp: Only return events after this time.

        Returns:
            List of matching ``NarrativeTimelineEvent`` objects in order.
        """
        return [e for e in self._timeline.events if e.timestamp > since_timestamp]

    def get_events_by_type(self, event_type: str) -> list[NarrativeTimelineEvent]:
        """Get all events of a specific type.

        Args:
            event_type: The event type to filter by.

        Returns:
            List of matching ``NarrativeTimelineEvent`` objects.
        """
        return [e for e in self._timeline.events if e.event_type == event_type]

    def get_event_count(self) -> int:
        """Get the total number of events in the timeline.

        Returns:
            Total event count.
        """
        return self._timeline.event_count

    def get_excerpt(
        self,
        max_events: int = 5,
        include_labels: bool = True,
    ) -> list[str]:
        """Get a compact text excerpt of recent events for decision snapshots.

        Args:
            max_events: Maximum number of events to include in the excerpt.
            include_labels: Whether to prepend human-readable labels.

        Returns:
            List of strings, one per event, newest first.
        """
        recent = self.get_recent_events(max_events)
        if not recent:
            return ["No significant market events yet"]

        excerpt = []
        for evt in recent:
            label = _EVENT_LABELS.get(evt.event_type, evt.event_type) if include_labels else evt.event_type
            time_str = evt.timestamp.strftime("%H:%M:%S") if evt.timestamp else "???"
            price_str = f" @ {evt.price_level:.2f}" if evt.price_level else ""
            detail_str = f" — {evt.details}" if evt.details else ""
            excerpt.append(f"[{time_str}] {label}{price_str}{detail_str}")

        return excerpt

    def get_timeline_summary(self) -> dict[str, Any]:
        """Get a structured summary of the timeline for dashboard (Side B).

        Returns:
            Dict with event_count, last_update, and recent events excerpt.
        """
        return {
            "event_count": self._timeline.event_count,
            "last_update": self._timeline.last_update.isoformat() if self._timeline.last_update else "",
            "recent_excerpt": self.get_excerpt(max_events=3),
        }

    def has_events(self) -> bool:
        """Check if the timeline contains any events.

        Returns:
            True if at least one event exists.
        """
        return self._timeline.event_count > 0

    # ------------------------------------------------------------------
    # Public API — Lifecycle
    # ------------------------------------------------------------------

    def clear_session(self) -> None:
        """Clear all events for a new trading day.

        Resets the timeline to empty state. Called at market open.
        """
        self._timeline = NarrativeTimeline()

    def get_last_event(self) -> NarrativeTimelineEvent | None:
        """Get the most recent event in the timeline.

        Returns:
            The latest event, or None if the timeline is empty.
        """
        if not self._timeline.events:
            return None
        return self._timeline.events[-1]
