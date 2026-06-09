"""Floor 4 — Head State Manager.

Manages Head state lifecycle: READY / UNCERTAIN / STALE.

State transition rules:
- ``READY``: last_deep_update within freshness window, no internal conflict.
- ``UNCERTAIN``: conflicting signals, borderline freshness, partial data.
- ``STALE``: last_deep_update beyond stale threshold, degraded data.

Freshness computation:
- ``freshness_score``: 0.0 (stale) to 1.0 (fresh).
- ``freshness_tag``: FRESH (score > 0.7), WARM (0.3–0.7), STALE (< 0.3).
- ``last_deep_update``: timestamp of last meaningful refresh.

State + Freshness interaction:
- READY + FRESH/WARM → normal trust.
- UNCERTAIN + any → reduced interpretive weight.
- STALE + STALE → caution, reduced trust, possible block per head type.

Usage::

    from junior_aladdin.floor_4_heads.head_state_manager import HeadStateManager
    from junior_aladdin.floor_4_heads.head_refresh_policy import REFRESH_POLICY_SMC

    manager = HeadStateManager(policy=REFRESH_POLICY_SMC)
    state, freshness = manager.update(last_deep_update, confidence=0.75)
    # state = HeadState.READY, freshness.freshness_tag = FreshnessTag.FRESH

    if manager.is_stale():
        # Head needs attention before Captain can trust it
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from junior_aladdin.floor_4_heads.head_refresh_policy import (
    RefreshPolicy,
    is_stale as _check_stale,
)
from junior_aladdin.floor_4_heads.head_types import compute_freshness
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import FreshnessTag, HeadState

logger = get_logger("head_state_manager")

# Confidence thresholds for state determination
_UNCERTAIN_CONFIDENCE_MAX = 0.3   # confidence < 0.3 → UNCERTAIN
_READY_CONFIDENCE_MIN = 0.3       # confidence >= 0.3 → READY (subject to freshness)


# =============================================================================
# FreshnessState
# =============================================================================


@dataclass
class FreshnessState:
    """Complete freshness snapshot for a Head at a point in time.

    Fields:
        freshness_score: Float from 0.0 (stale) to 1.0 (fresh).
        freshness_tag: ``FreshnessTag`` enum — FRESH / WARM / STALE.
        seconds_since_update: Raw seconds since the last update.
        state: The HeadState derived from freshness + confidence.
            ``READY``, ``UNCERTAIN``, or ``STALE``.
    """
    freshness_score: float = 0.0
    freshness_tag: FreshnessTag = FreshnessTag.STALE
    seconds_since_update: int = 0
    state: HeadState = HeadState.STALE


# Pure functions — compute_freshness imported from head_types.py


def compute_state(
    freshness_tag: FreshnessTag,
    confidence: float,
    has_internal_conflict: bool = False,
) -> HeadState:
    """Determine Head state from freshness and confidence.

    State transition rules:
    - STALE freshness_tag → STALE state regardless of confidence.
    - FRESH/WARM + confidence >= 0.3 + no conflict → READY.
    - FRESH/WARM + confidence < 0.3 → UNCERTAIN.
    - FRESH/WARM + conflict → UNCERTAIN.

    Args:
        freshness_tag: The computed ``FreshnessTag``.
        confidence: Head's confidence score (0.0–1.0).
        has_internal_conflict: Whether the Head has conflicting signals.

    Returns:
        ``HeadState.READY``, ``HeadState.UNCERTAIN``, or ``HeadState.STALE``.
    """
    # STALE freshness always means STALE state
    if freshness_tag == FreshnessTag.STALE:
        return HeadState.STALE

    # Conflict makes the head uncertain regardless of confidence
    if has_internal_conflict:
        return HeadState.UNCERTAIN

    # Low confidence → uncertain
    if confidence < _UNCERTAIN_CONFIDENCE_MAX:
        return HeadState.UNCERTAIN

    # All conditions met → ready
    return HeadState.READY


def transition(
    current_state: HeadState,
    new_state: HeadState,
) -> HeadState:
    """Determine the new state after applying a transition.

    The transition from current → proposed follows these rules:
    - STALE can only transition to READY or UNCERTAIN if a fresh update arrives.
    - UNCERTAIN can transition to READY if confidence improves.
    - READY can transition to UNCERTAIN or STALE as freshness decays.

    Args:
        current_state: The Head's current ``HeadState``.
        new_state: The proposed new ``HeadState`` based on current data.

    Returns:
        The resulting ``HeadState`` after applying transition logic.
    """
    # No transition needed if same
    if current_state == new_state:
        return current_state

    # Allow all forward transitions (they reflect the data)
    # STALE → READY/UNCERTAIN is allowed (fresh update arrived)
    # READY → STALE/UNCERTAIN is allowed (freshness decayed)
    # UNCERTAIN → READY/STALE is allowed
    return new_state


# =============================================================================
# HeadStateManager
# =============================================================================


class HeadStateManager:
    """Manages the operational state lifecycle of a single Department Head.

    Combines freshness computation with state transitions,
    using the Head's ``RefreshPolicy`` for staleness thresholds.

    Args:
        policy: The Head's ``RefreshPolicy`` (used for stale threshold).
        initial_state: Starting head state. Default ``HeadState.STALE``
            (never updated yet).

    Example::

        manager = HeadStateManager(policy=REFRESH_POLICY_SMC)

        # After first update
        fs = manager.update(last_deep_update=datetime.utcnow(), confidence=0.8)
        print(fs.state)          # HeadState.READY
        print(fs.freshness_tag)  # FreshnessTag.FRESH

        # Check if stale
        if manager.is_stale():
            logger.warning("SMC Head is stale")

        # Get snapshot for report
        snapshot = manager.get_freshness_snapshot()
        report_state = snapshot["state"]
        report_freshness = snapshot["freshness_tag"]
    """

    def __init__(
        self,
        policy: RefreshPolicy,
        initial_state: HeadState = HeadState.STALE,
    ) -> None:
        self._policy = policy
        self._current_state: HeadState = initial_state
        self._last_state_change: datetime | None = None
        self._last_freshness: FreshnessState = FreshnessState()

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def current_state(self) -> HeadState:
        """The Head's current operational state."""
        return self._current_state

    @property
    def last_freshness(self) -> FreshnessState:
        """The most recently computed freshness snapshot."""
        return self._last_freshness

    # ── Core API ────────────────────────────────────────────────────────

    def update(
        self,
        last_deep_update: datetime | None,
        confidence: float = 0.0,
        has_internal_conflict: bool = False,
        now: datetime | None = None,
    ) -> FreshnessState:
        """Update the Head's state based on freshness and confidence.

        This is the main entry point called after a refresh cycle.

        Args:
            last_deep_update: When the Head last performed a deep update (UTC).
            confidence: The Head's current confidence (0.0–1.0).
            has_internal_conflict: Whether the Head has conflicting signals.
            now: Current time (UTC). Uses ``datetime.utcnow()`` if None.

        Returns:
            A ``FreshnessState`` with the computed freshness and state.
        """
        # Compute freshness from update time (uses head_types.compute_freshness)
        freshness_score, freshness_tag, seconds = compute_freshness(
            last_deep_update, now,
        )

        # Determine the proposed new state
        proposed_state = compute_state(
            freshness_tag=freshness_tag,
            confidence=confidence,
            has_internal_conflict=has_internal_conflict,
        )

        # Apply transition
        old_state = self._current_state
        new_state = transition(old_state, proposed_state)

        # Track state changes
        if new_state != old_state:
            self._last_state_change = now or datetime.utcnow()
            logger.info(
                "Head state transition",
                extra={
                    "from": old_state.value,
                    "to": new_state.value,
                    "freshness_tag": freshness_tag.value,
                    "confidence": round(confidence, 2),
                },
            )

        # Update internal state
        self._current_state = new_state
        self._last_freshness = FreshnessState(
            freshness_score=freshness_score,
            freshness_tag=freshness_tag,
            seconds_since_update=seconds,
            state=new_state,
        )

        return self._last_freshness

    def is_stale(self, last_update: datetime | None = None) -> bool:
        """Check whether the Head has become stale.

        Uses the configured ``RefreshPolicy.stale_after_seconds`` threshold.

        Args:
            last_update: Optional override timestamp. Uses the stored
                ``last_deep_update`` from the last ``update()`` call if None.

        Returns:
            ``True`` if the Head is past the stale threshold.
        """
        return _check_stale(self._policy, last_update)

    def get_freshness_snapshot(self) -> dict[str, Any]:
        """Get a compact freshness snapshot for report generation.

        Returns:
            Dict with ``state``, ``freshness_score``, ``freshness_tag``,
            and ``seconds_since_update`` keys.
        """
        return {
            "state": self._current_state.value,
            "freshness_score": self._last_freshness.freshness_score,
            "freshness_tag": self._last_freshness.freshness_tag.value,
            "seconds_since_update": self._last_freshness.seconds_since_update,
        }

    def reset(self, state: HeadState = HeadState.STALE) -> None:
        """Reset the manager to its initial state.

        Args:
            state: The state to reset to. Default ``HeadState.STALE``.
        """
        self._current_state = state
        self._last_state_change = None
        self._last_freshness = FreshnessState()
        logger.debug("Head state manager reset", extra={"to": state.value})
