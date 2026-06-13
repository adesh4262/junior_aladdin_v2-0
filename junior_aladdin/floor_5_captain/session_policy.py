"""Floor 5 — Session Policy Engine.

Defines session-dependent behaviour rules for Captain's permission gate,
conviction threshold, and aggression modifiers.

Session phases with aggression modifiers (LOCKED — ROADMAP_FLOOR_05 Section 9):
- OPENING (9:15-9:45 IST): observe/cautious, context building
  → permission_strictness: HIGH, aggression_modifier: -0.2
- GOLDEN_MORNING (9:45-11:00 IST): strongest permission window
  → permission_strictness: NORMAL, aggression_modifier: +0.1
- LUNCH (11:00-13:00 IST): defensive/selective, lower volume
  → permission_strictness: HIGH, aggression_modifier: -0.1
- CLOSING (13:00-15:30 IST): cautious/risk-aware, avoid overnight risk
  → permission_strictness: VERY_HIGH, aggression_modifier: -0.2

Architecture rules (LOCKED):
- Session phase overrides base permission strictness.
- Opening window is NOT full attack mode — observe/context-build first.
- Closing window is risk-aware — avoid overnight exposure.
- Golden morning is the strongest permission window of the day.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    SessionPhase,
    get_aggression_modifier,
    get_permission_strictness,
    get_session_phase_from_time,
)

# ── IST timezone offset (UTC + 5:30) ────────────────────────────────────────
_IST_OFFSET = timezone.utc  # We handle conversion via hour/minute extraction

# ── Preferred trade classes by session phase ────────────────────────────────
_PREFERRED_TRADE_CLASSES: dict[SessionPhase, list[str]] = {
    SessionPhase.OPENING: [
        "LIQUIDITY_RECLAIM",      # Sweep + reclaim common in opening
    ],
    SessionPhase.GOLDEN_MORNING: [
        "CONTINUATION",           # Trend continuation after direction established
        "SCALP",                  # Quick entry/exit in high volume
        "LIQUIDITY_RECLAIM",      # Still valid for morning sweeps
        "OPTIONS_PRESSURE",       # OI wall interactions in high volume
    ],
    SessionPhase.LUNCH: [
        "REVERSAL",               # Structure breaks / exhaustion moves
        "OPTIONS_PRESSURE",       # Options moves in lower volume
    ],
    SessionPhase.CLOSING: [
        "SCALP",                  # Quick, defined-risk trades only
        "OPTIONS_PRESSURE",       # If options support is clear
    ],
}

# ── Session boundary constants (IST minutes from midnight) ──────────────────
_MARKET_OPEN = 9 * 60 + 15         # 9:15 IST
_OPENING_END = 9 * 60 + 45         # 9:45 IST
_GOLDEN_MORNING_END = 11 * 60 + 0  # 11:00 IST
_LUNCH_END = 13 * 60 + 0           # 13:00 IST
_MARKET_CLOSE = 15 * 60 + 30       # 15:30 IST


# =============================================================================
# SessionPolicy
# =============================================================================


class SessionPolicy:
    """Session-dependent behaviour rules for Captain.

    Provides methods for determining session phase, permission strictness,
    aggression modifiers, preferred trade classes, and window detection.

    Usage::

        policy = SessionPolicy()
        phase = policy.get_session_phase(datetime.utcnow())
        strictness = policy.get_permission_strictness(phase)
        modifier = policy.get_aggression_modifier(phase)
        classes = policy.get_preferred_trade_classes(phase)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_session_phase(self, timestamp: datetime | None = None) -> SessionPhase:
        """Determine the current session phase from a timestamp.

        Args:
            timestamp: A datetime (assumed UTC). If None, uses ``datetime.utcnow()``.
                The timestamp is converted to IST for phase determination.

        Returns:
            The corresponding ``SessionPhase``.
        """
        dt = timestamp or datetime.utcnow()
        # Convert UTC to IST (UTC + 5:30)
        ist_hour, ist_minute = self._utc_to_ist(dt)
        return get_session_phase_from_time(ist_hour, ist_minute)

    def get_permission_strictness(self, phase: SessionPhase) -> str:
        """Get the permission strictness level for a session phase.

        Args:
            phase: The session phase.

        Returns:
            ``\"NORMAL\"``, ``\"HIGH\"``, or ``\"VERY_HIGH\"``.
        """
        return get_permission_strictness(phase)

    def get_aggression_modifier(self, phase: SessionPhase) -> float:
        """Get the aggression modifier for a session phase.

        Modifier is applied to the conviction threshold:
        - Positive = more aggressive (lower threshold).
        - Negative = less aggressive (higher threshold).

        Args:
            phase: The session phase.

        Returns:
            Float modifier (e.g., ``-0.2``, ``+0.1``).
        """
        return get_aggression_modifier(phase)

    def get_preferred_trade_classes(self, phase: SessionPhase) -> list[str]:
        """Get recommended trade classes for a session phase.

        Args:
            phase: The session phase.

        Returns:
            List of preferred trade class strings for this phase.
        """
        return _PREFERRED_TRADE_CLASSES.get(phase, list(_PREFERRED_TRADE_CLASSES[SessionPhase.OPENING]))

    def is_opening_window(self, timestamp: datetime | None = None) -> bool:
        """Check if the market is in the opening window (9:15-9:45 IST).

        Args:
            timestamp: A datetime (assumed UTC). If None, uses now.

        Returns:
            ``True`` if current time is in the opening window.
        """
        dt = timestamp or datetime.utcnow()
        ist_hour, ist_minute = self._utc_to_ist(dt)
        total = ist_hour * 60 + ist_minute
        return _MARKET_OPEN <= total < _OPENING_END

    def is_closing_window(self, timestamp: datetime | None = None) -> bool:
        """Check if the market is in the closing window (13:00-15:30 IST).

        Args:
            timestamp: A datetime (assumed UTC). If None, uses now.

        Returns:
            ``True`` if current time is in the closing window.
        """
        dt = timestamp or datetime.utcnow()
        ist_hour, ist_minute = self._utc_to_ist(dt)
        total = ist_hour * 60 + ist_minute
        return _LUNCH_END <= total < _MARKET_CLOSE

    def is_market_open(self, timestamp: datetime | None = None) -> bool:
        """Check if the market is currently open for trading.

        Market hours: 9:15-15:30 IST (Monday-Friday).

        Args:
            timestamp: A datetime (assumed UTC). If None, uses now.

        Returns:
            ``True`` if market is open.
        """
        dt = timestamp or datetime.utcnow()
        ist_hour, ist_minute = self._utc_to_ist(dt)
        total = ist_hour * 60 + ist_minute

        # Check weekday (Monday=0, Sunday=6)
        weekday = dt.weekday()
        if weekday >= 5:  # Saturday or Sunday
            return False

        return _MARKET_OPEN <= total < _MARKET_CLOSE

    def is_market_closed(self, timestamp: datetime | None = None) -> bool:
        """Check if the market is currently closed.

        Args:
            timestamp: A datetime (assumed UTC). If None, uses now.

        Returns:
            ``True`` if market is closed.
        """
        return not self.is_market_open(timestamp)

    def get_session_summary(self, timestamp: datetime | None = None) -> dict[str, Any]:
        """Get a complete summary of session state for the given time.

        Args:
            timestamp: A datetime (assumed UTC). If None, uses now.

        Returns:
            Dict with session phase, strictness, modifier, preferred trade
            classes, and market open/close status.
        """
        dt = timestamp or datetime.utcnow()
        phase = self.get_session_phase(dt)
        return {
            "phase": phase.value,
            "permission_strictness": self.get_permission_strictness(phase),
            "aggression_modifier": self.get_aggression_modifier(phase),
            "preferred_trade_classes": self.get_preferred_trade_classes(phase),
            "is_market_open": self.is_market_open(dt),
            "is_opening_window": self.is_opening_window(dt),
            "is_closing_window": self.is_closing_window(dt),
            "timestamp": dt.isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _utc_to_ist(dt: datetime) -> tuple[int, int]:
        """Convert a UTC datetime to IST hour and minute.

        IST is UTC + 5:30.

        Args:
            dt: UTC datetime.

        Returns:
            Tuple of ``(ist_hour, ist_minute)``.
        """
        # Add 5 hours 30 minutes
        total_minutes = dt.hour * 60 + dt.minute + 330  # 5*60 + 30
        # Handle day wrap
        total_minutes = total_minutes % (24 * 60)
        return divmod(total_minutes, 60)
