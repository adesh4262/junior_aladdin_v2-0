"""Floor 5 — Decision Snapshot Writer (Step 5.18).

Freezes a structured snapshot of every major Captain decision for audit,
review, shadow logging, confidence calibration, and Side C memory.

Architecture (see ROADMAP_FLOOR_05 Section 5.18):
- Every major decision freezes a DecisionSnapshot
- Snapshot contains: market story, timeline excerpt, heads summary,
  armed plan reference, conviction, invalidation, reason, context
- Snapshots are session-scoped, retrievable by ID
- Snapshots support replay compatibility and dashboard explainability
- The writer can build a SnapContext from a CaptainDecision + engine outputs
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import CaptainMood
from junior_aladdin.shared.types import CaptainDecision, DecisionSnapshot


# ── SnapContext (input bag for write_snapshot) ─────────────────────────────


@dataclass
class SnapContext:
    """Input context for creating a DecisionSnapshot.

    Factory method ``from_captain_decision()`` builds this from a
    ``CaptainDecision`` plus optional engine outputs.

    Fields:
        market_story_summary: Current market story summary string.
        narrative_timeline_excerpt: Last N events from timeline.
        heads_summary: Dict mapping head_name → bias/confidence/state.
        armed_plan_reference: Plan ID if an armed plan was created.
        conviction_score: The conviction score from conviction_engine.
        invalidation: Dict with invalidation details.
        decision_reason: Human-readable reason for this decision.
        silence_reason: If no trade, the primary silence reason string.
        session_context: Dict with session phase, regime, mood.
        capital_context: Dict with capital limit, mode.
        mood: Current CaptainMood.
    """
    market_story_summary: str = ""
    narrative_timeline_excerpt: list[str] = field(default_factory=list)
    heads_summary: dict[str, Any] = field(default_factory=dict)
    armed_plan_reference: str | None = None
    conviction_score: float = 0.0
    invalidation: dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""
    silence_reason: str = ""
    session_context: dict[str, Any] = field(default_factory=dict)
    capital_context: dict[str, Any] = field(default_factory=dict)
    mood: CaptainMood = CaptainMood.OBSERVER

    @classmethod
    def from_captain_decision(
        cls,
        captain_decision: CaptainDecision,
        market_story_summary: str = "",
        narrative_timeline_excerpt: list[str] | None = None,
        heads_summary: dict[str, Any] | None = None,
        mood: CaptainMood | None = None,
    ) -> SnapContext:
        """Build a SnapContext from a CaptainDecision plus optional extras.

        Args:
            captain_decision: The CaptainDecision produced by trade_constructor.
            market_story_summary: Optional market story string.
            narrative_timeline_excerpt: Optional timeline excerpt.
            heads_summary: Optional heads summary dict.
            mood: Optional CaptainMood (overrides decision default).

        Returns:
            A fully populated ``SnapContext``.
        """
        return cls(
            market_story_summary=market_story_summary,
            narrative_timeline_excerpt=narrative_timeline_excerpt or [],
            heads_summary=heads_summary or {},
            armed_plan_reference=captain_decision.snapshot_id or None,
            conviction_score=captain_decision.conviction_score,
            invalidation={
                "level": captain_decision.invalidation_level,
                "stop_loss": captain_decision.stop_loss_plan,
            },
            decision_reason=captain_decision.reason_summary,
            silence_reason=captain_decision.silence_reason or "",
            session_context={
                "decision": captain_decision.decision.value,
                "action": captain_decision.action,
                "option_side": captain_decision.option_side,
                "strike": captain_decision.selected_strike,
                "trade_class": captain_decision.trade_class.value,
            },
            capital_context={
                "permission_score": captain_decision.permission_score,
                "no_trade_score": captain_decision.no_trade_score,
            },
            mood=mood or CaptainMood.OBSERVER,
        )


# ── DecisionSnapshotWriter ────────────────────────────────────────────────


class DecisionSnapshotWriter:
    """Writes, stores, and retrieves decision snapshots.

    Every major Captain decision should produce a snapshot for audit trail,
    confidence calibration, and Side C memory emission.

    Usage::

        writer = DecisionSnapshotWriter()

        # Create a snapshot from context
        snap = writer.write_snapshot(context)

        # Retrieve
        snap = writer.get_snapshot(snap.snapshot_id)

        # All snapshots for the session
        for s in writer.get_session_snapshots():
            print(s.snapshot_id, s.decision_reason)

        # Reset for new day
        writer.clear_session()
    """

    def __init__(self) -> None:
        """Initialize the decision snapshot writer."""
        self._snapshots: dict[str, DecisionSnapshot] = {}
        self._order: list[str] = []  # insertion order tracking

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_snapshot(self, context: SnapContext) -> DecisionSnapshot:
        """Write a new decision snapshot.

        Generates a unique snapshot ID and stores the frozen snapshot
        for later retrieval.

        Args:
            context: The ``SnapContext`` with all relevant decision data.

        Returns:
            The newly created ``DecisionSnapshot``.
        """
        snapshot_id = str(uuid.uuid4())
        now = datetime.utcnow()

        snap = DecisionSnapshot(
            snapshot_id=snapshot_id,
            timestamp=now,
            market_story_summary=context.market_story_summary,
            narrative_timeline_excerpt=context.narrative_timeline_excerpt,
            heads_summary=context.heads_summary,
            armed_plan_reference=context.armed_plan_reference,
            conviction_score=context.conviction_score,
            invalidation=context.invalidation,
            decision_reason=context.decision_reason,
            session_context=context.session_context,
            capital_context=context.capital_context,
            mood=context.mood,
        )

        self._snapshots[snapshot_id] = snap
        self._order.append(snapshot_id)
        return snap

    def get_snapshot(self, snapshot_id: str) -> DecisionSnapshot | None:
        """Retrieve a snapshot by ID.

        Args:
            snapshot_id: The UUID string of the snapshot.

        Returns:
            ``DecisionSnapshot`` if found, else None.
        """
        return self._snapshots.get(snapshot_id)

    def get_session_snapshots(self) -> list[DecisionSnapshot]:
        """Get all snapshots created this session, in insertion order.

        Returns:
            List of all ``DecisionSnapshot`` entries, ordered by creation.
        """
        return [self._snapshots[sid] for sid in self._order]

    def get_snapshot_count(self) -> int:
        """Get total number of snapshots taken.

        Returns:
            Integer count of all snapshots.
        """
        return len(self._snapshots)

    def get_latest_snapshot(self) -> DecisionSnapshot | None:
        """Get the most recently created snapshot.

        Uses insertion order rather than timestamp to avoid precision issues
        when multiple snapshots are created in the same microsecond.

        Returns:
            The most recently created ``DecisionSnapshot``, or None.
        """
        if not self._order:
            return None
        return self._snapshots[self._order[-1]]

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def clear_session(self) -> None:
        """Clear all snapshots for a new trading day."""
        self._snapshots.clear()
        self._order.clear()

    def has_snapshots(self) -> bool:
        """Check if any snapshots exist.

        Returns:
            True if at least one snapshot exists.
        """
        return len(self._snapshots) > 0
