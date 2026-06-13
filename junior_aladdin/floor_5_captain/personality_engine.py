"""Floor 5 — Personality Engine (Step 5.10).

Determines Captain's current decision-making temperament (mood) from
the full context of the current market state, conviction, session phase,
and battlefield conditions.

Captain moods (see shared/types.py — CaptainMood):
- **OBSERVER**: Low confidence, range market, no clear edge.
  Default / fallback when signals are ambiguous.
- **PATIENT**: Moderate confidence (TRADABLE), waiting for a better entry
  or confirmation.  Has direction but is not rushing.
- **AGGRESSIVE**: High confidence (STRONG/ELITE), strong confluence,
  supportive regime, good session window (Golden Morning).
- **DEFENSIVE**: Active trade exists, market choppy, recent loss, or
  unusual caution.  Protect existing position, avoid new risk.
- **SILENT**: No permission, no setups, healthy no-trade.
  Quietly observing, not interested in trading.

Architecture (see ROADMAP_FLOOR_05 Section 5.10):
- Mood is determined AFTER conviction engine and BEFORE trade class engine
- Mood feeds into decision snapshots and Side B dashboard
- Mood does NOT gate trading — it is contextual only
- Mood can be overridden by extreme conditions (e.g., emergency)
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    ConvictionBand,
    MarketStory,
    SessionPhase,
)
from junior_aladdin.shared.types import CaptainMood


# ── Mood determination thresholds ───────────────────────────────────────

# Conviction bands that map to specific moods
_AGGRESSIVE_BANDS = {ConvictionBand.STRONG, ConvictionBand.ELITE}
_PATIENT_BANDS = {ConvictionBand.TRADABLE}
_OBSERVER_BANDS = {ConvictionBand.WEAK}
_SILENT_BANDS = {ConvictionBand.REJECT}

# Regimes that support aggressive mood
_AGGRESSIVE_REGIMES = {"TREND_UP", "TREND_DOWN", "WEAK_UP", "WEAK_DOWN"}

# Regimes that support defensive mood (active trade + choppy)
_DEFENSIVE_REGIMES = {"CHOP", "UNCLEAR", "RANGE"}

# Session phases that boost or reduce aggression
_GOLDEN_MORNING = SessionPhase.GOLDEN_MORNING
_DEFENSIVE_PHASES = {SessionPhase.LUNCH, SessionPhase.CLOSING}


class PersonalityEngine:
    """Determines Captain's mood from current market context.

    Mood is purely contextual — it does NOT gate decisions.  It serves as
    an explainability signal for Side B dashboard and feeds into decision
    snapshots for audit / calibration.

    Usage::

        engine = PersonalityEngine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=market_story,
            active_trade_exists=False,
            permission_allowed=True,
        )
        # mood → AGGRESSIVE
    """

    def __init__(self) -> None:
        """Initialize the personality engine."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def determine_mood(
        self,
        conviction_band: ConvictionBand = ConvictionBand.REJECT,
        session_phase: SessionPhase = SessionPhase.OPENING,
        market_story: MarketStory | None = None,
        active_trade_exists: bool = False,
        permission_allowed: bool = True,
        has_setups: bool = False,
        recent_loss: bool = False,
    ) -> CaptainMood:
        """Determine Captain's current mood from full context.

        The mood is computed by evaluating multiple factors in priority
        order, with extreme conditions (active trade, permission failure,
        recent loss) taking precedence over standard conviction-based
        determination.

        Args:
            conviction_band: Current ConvictionBand from conviction_engine.
            session_phase: Current SessionPhase from session_policy.
            market_story: Current MarketStory (for regime context).
            active_trade_exists: Whether a trade is currently active.
            permission_allowed: Whether the permission gate allowed trading.
            has_setups: Whether active setups / armed plans exist.
            recent_loss: Whether a recent loss was recorded this session.

        Returns:
            The determined ``CaptainMood``.
        """
        regime = (market_story.regime or "").upper() if market_story else ""

        # ── Priority 1: Extreme conditions ──────────────────────────

        # Recent loss + active trade = DEFENSIVE
        if recent_loss and active_trade_exists:
            return CaptainMood.DEFENSIVE

        # Active trade in choppy / unclear regime = DEFENSIVE
        if active_trade_exists and regime in _DEFENSIVE_REGIMES:
            return CaptainMood.DEFENSIVE

        # Active trade = DEFENSIVE (protect existing position)
        if active_trade_exists:
            return CaptainMood.DEFENSIVE

        # Permission failed + no setups = SILENT
        if not permission_allowed and not has_setups:
            return CaptainMood.SILENT

        # Permission failed + recent loss = SILENT
        if not permission_allowed and recent_loss:
            return CaptainMood.SILENT

        # ── Priority 2: Conviction-based mood ───────────────────────

        if conviction_band in _AGGRESSIVE_BANDS:
            return self._determine_aggressive_or_observer(
                session_phase=session_phase,
                regime=regime,
            )

        if conviction_band in _PATIENT_BANDS:
            return self._determine_patient_or_observer(
                session_phase=session_phase,
                regime=regime,
            )

        if conviction_band in _SILENT_BANDS:
            # WEAK conviction — still observing, not interested
            return self._determine_silent_or_observer(
                permission_allowed=permission_allowed,
                has_setups=has_setups,
            )

        # REJECT conviction — SILENT only when permission is blocked
        if not permission_allowed:
            return CaptainMood.SILENT

        return CaptainMood.OBSERVER

    # ------------------------------------------------------------------
    # Mood-specific logic
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_aggressive_or_observer(
        session_phase: SessionPhase,
        regime: str,
    ) -> CaptainMood:
        """Determine if AGGRESSIVE mood is warranted for high conviction.

        AGGRESSIVE requires:
        - Supportive regime (trending)
        - Supportive session phase (Golden Morning preferred)
        - If regime or session is unsupportive → OBSERVER

        Args:
            session_phase: Current session phase.
            regime: Current market regime string.

        Returns:
            ``AGGRESSIVE`` or ``OBSERVER``.
        """
        if regime in _AGGRESSIVE_REGIMES:
            if session_phase == _GOLDEN_MORNING:
                return CaptainMood.AGGRESSIVE
            if session_phase not in _DEFENSIVE_PHASES:
                return CaptainMood.AGGRESSIVE
            # LUNCH or CLOSING — still high conviction but less aggressive
            return CaptainMood.PATIENT

        if regime in _DEFENSIVE_REGIMES:
            # High conviction in choppy market — be careful
            return CaptainMood.PATIENT

        return CaptainMood.OBSERVER

    @staticmethod
    def _determine_patient_or_observer(
        session_phase: SessionPhase,
        regime: str,
    ) -> CaptainMood:
        """Determine if PATIENT mood is warranted for moderate conviction.

        PATIENT requires:
        - Direction exists but needs confirmation
        - Session supports waiting

        Args:
            session_phase: Current session phase.
            regime: Current market regime string.

        Returns:
            ``PATIENT`` or ``OBSERVER``.
        """
        if regime in _AGGRESSIVE_REGIMES:
            if session_phase == _GOLDEN_MORNING:
                return CaptainMood.PATIENT
            if session_phase not in _DEFENSIVE_PHASES:
                return CaptainMood.PATIENT
            # CLOSING — not ideal, but TRADABLE conviction exists
            return CaptainMood.OBSERVER

        if regime in _DEFENSIVE_REGIMES:
            return CaptainMood.OBSERVER

        return CaptainMood.OBSERVER

    @staticmethod
    def _determine_silent_or_observer(
        permission_allowed: bool,
        has_setups: bool,
    ) -> CaptainMood:
        """Determine if SILENT or OBSERVER for low conviction.

        SILENT when permission is blocked (healthy no-trade).
        OBSERVER when permission is allowed but conviction or setups
        are lacking (watching for an edge to appear).

        Args:
            permission_allowed: Whether permission gate allows trading.
            has_setups: Whether setups exist.

        Returns:
            ``SILENT`` or ``OBSERVER``.
        """
        if not permission_allowed:
            return CaptainMood.SILENT
        return CaptainMood.OBSERVER

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def get_mood_label(mood: CaptainMood) -> str:
        """Get a human-readable label for a CaptainMood.

        Args:
            mood: The CaptainMood value.

        Returns:
            Human-readable label string.
        """
        labels = {
            CaptainMood.OBSERVER: "Observing — no clear edge",
            CaptainMood.PATIENT: "Patient — waiting for confirmation",
            CaptainMood.AGGRESSIVE: "Aggressive — high confidence",
            CaptainMood.DEFENSIVE: "Defensive — protecting position",
            CaptainMood.SILENT: "Silent — healthy no-trade",
        }
        return labels.get(mood, "Unknown mood")

    def get_mood_summary(
        self,
        mood: CaptainMood,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get a structured summary of the mood for dashboard (Side B).

        Args:
            mood: The determined CaptainMood.
            context: Optional context dict (conviction, regime, session, etc.).

        Returns:
            Dict with mood summary fields.
        """
        ctx = context or {}
        return {
            "mood": mood.value,
            "label": self.get_mood_label(mood),
            "context": {
                "conviction_band": ctx.get("conviction_band", ""),
                "session_phase": ctx.get("session_phase", ""),
                "regime": ctx.get("regime", ""),
                "active_trade": ctx.get("active_trade", False),
                "permission_allowed": ctx.get("permission_allowed", True),
                "has_setups": ctx.get("has_setups", False),
                "recent_loss": ctx.get("recent_loss", False),
            },
        }
