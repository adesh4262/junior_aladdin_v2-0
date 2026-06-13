"""Floor 5 — Market Story Engine (Step 5.5).

Builds Captain's understanding of today's market context from Floor 4 inputs.

The market story answers the question: "What is happening in the market right
now, and how did it get here?" It is NOT a trade signal — it is context for
all subsequent Captain layers (confluence, conviction, trade construction).

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 5):
- Market Story Engine is called AFTER permission gate passes
- Market Story Engine is called BEFORE narrative timeline update
- Market Story Engine consumes ONLY Floor 4 data (Floor Summary + Head Reports)
- Captain does NOT consume Floor 3 packets directly
- Regime is derived from Floor 4, NOT recalculated by Captain
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    MarketStory,
    SessionPhase,
)
from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.shared.types import BiasType, FloorSummary, HeadReport


# ── Regime mapping helpers ─────────────────────────────────────────────────

# Bias-direction strings used in regime detection
_BULLISH_STR = BiasType.BULLISH.value
_BEARISH_STR = BiasType.BEARISH.value
_NEUTRAL_STR = BiasType.NEUTRAL.value

# Confidence thresholds for regime strength
_HIGH_CONFIDENCE_THRESHOLD = 0.7
_LOW_CONFIDENCE_THRESHOLD = 0.4


class MarketStoryEngine:
    """Builds Captain's current market context story from Floor 4 inputs.

    The engine produces a structured ``MarketStory`` dataclass that captures:
    - Market regime (trend/range/chop/volatile)
    - Current session phase
    - Premium/discount location relative to PD array
    - Key level interactions
    - Directional bias derived from floor consensus
    - A human-readable summary

    Usage::

        engine = MarketStoryEngine(session_policy)
        story = engine.build_story(
            floor_summary=floor_summary,
            head_reports=head_reports,
            timestamp=datetime.utcnow(),
        )
    """

    def __init__(self, session_policy: SessionPolicy) -> None:
        """Initialize the market story engine.

        Args:
            session_policy: SessionPolicy instance for session phase detection.
        """
        self._session_policy = session_policy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_story(
        self,
        floor_summary: FloorSummary | None = None,
        head_reports: dict[str, HeadReport] | None = None,
        timestamp: datetime | None = None,
    ) -> MarketStory:
        """Build the current market story from available Floor 4 data.

        All parameters are optional — the engine produces a sensible default
        story even with minimal input. This ensures it never crashes during
        Captain's heavy cycle.

        Args:
            floor_summary: Current Floor Summary from Floor 4.
            head_reports: Dict mapping head_name → HeadReport (all 6 heads).
            timestamp: Current UTC timestamp. If None, uses ``datetime.utcnow()``.

        Returns:
            A fully populated ``MarketStory`` dataclass.
        """
        dt = timestamp or datetime.utcnow()
        reports = head_reports or {}
        summary = floor_summary

        # Build each component of the story
        regime = self._detect_regime(summary, reports)
        session_phase = self._get_session_phase(dt)
        premium_discount = self._get_premium_discount_location(reports)
        key_levels = self._get_key_levels_interaction(reports)
        bias = self._get_directional_bias(summary, reports)
        summary_text = self._build_summary_text(
            regime=regime,
            session_phase=session_phase,
            premium_discount=premium_discount,
            key_levels=key_levels,
            bias=bias,
            summary=summary,
        )

        return MarketStory(
            regime=regime,
            session_phase=session_phase,
            premium_discount_location=premium_discount,
            key_levels_interaction=key_levels,
            bias=bias,
            summary=summary_text,
            timestamp=dt,
        )

    # ------------------------------------------------------------------
    # Component Builders
    # ------------------------------------------------------------------

    def _detect_regime(
        self,
        floor_summary: FloorSummary | None,
        head_reports: dict[str, HeadReport],
    ) -> str:
        """Detect the current market regime from Floor 4 data.

        Regime is determined by:
        - Floor Summary floor_bias_snapshot (overall direction)
        - Floor Summary floor_confidence_snapshot (strength of conviction)
        - Head-level confidence scores (for validation)

        Returns one of: ``TREND_UP``, ``TREND_DOWN``, ``RANGE``, ``CHOP``,
        ``VOLATILE``, or ``UNCLEAR`` as fallback.

        Args:
            floor_summary: Current Floor Summary.
            head_reports: Dict of head reports.

        Returns:
            Regime description string.
        """
        if floor_summary is None:
            return self._detect_regime_from_reports(head_reports)

        # Extract floor-level bias and confidence
        bias_snapshot = floor_summary.floor_bias_snapshot or {}
        confidence_snapshot = floor_summary.floor_confidence_snapshot or {}

        floor_bias = bias_snapshot.get("dominant_bias", _NEUTRAL_STR)
        floor_confidence = confidence_snapshot.get("average_confidence", 0.0)

        # Check for volatility signals
        conflict = floor_summary.conflict_present
        stale_heads = floor_summary.stale_heads_count
        total_heads = (
            floor_summary.ready_heads_count
            + floor_summary.uncertain_heads_count
            + stale_heads
        )

        if total_heads > 0 and stale_heads / total_heads > 0.5:
            return "UNCLEAR"  # Too many stale heads to trust regime

        if conflict and floor_confidence < _LOW_CONFIDENCE_THRESHOLD:
            return "CHOP"  # Conflicting views + low confidence = choppy

        # Determine regime from bias + confidence
        if floor_bias == _BULLISH_STR:
            if floor_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
                return "TREND_UP"
            elif floor_confidence >= _LOW_CONFIDENCE_THRESHOLD:
                return "WEAK_UP"
            return "RANGE"

        if floor_bias == _BEARISH_STR:
            if floor_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
                return "TREND_DOWN"
            elif floor_confidence >= _LOW_CONFIDENCE_THRESHOLD:
                return "WEAK_DOWN"
            return "RANGE"

        # NEUTRAL bias
        if conflict:
            return "CHOP"
        return "RANGE"

    def _detect_regime_from_reports(
        self,
        head_reports: dict[str, HeadReport],
    ) -> str:
        """Fallback regime detection using head reports when Floor Summary is unavailable.

        Args:
            head_reports: Dict of head reports.

        Returns:
            Regime description string.
        """
        if not head_reports:
            return "UNCLEAR"

        directional_reports = [
            r for r in head_reports.values()
            if r.head_name not in ("Psychology Head",)
        ]
        if not directional_reports:
            return "UNCLEAR"

        avg_confidence = sum(r.confidence for r in directional_reports) / len(directional_reports)
        biases = [r.bias.value for r in directional_reports]
        bullish_count = biases.count(_BULLISH_STR)
        bearish_count = biases.count(_BEARISH_STR)

        if avg_confidence < _LOW_CONFIDENCE_THRESHOLD:
            return "CHOP"

        if bullish_count > bearish_count:
            if avg_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
                return "TREND_UP"
            return "WEAK_UP"
        elif bearish_count > bullish_count:
            if avg_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
                return "TREND_DOWN"
            return "WEAK_DOWN"

        return "RANGE"

    def _get_session_phase(self, timestamp: datetime) -> SessionPhase:
        """Determine the current session phase.

        Args:
            timestamp: UTC timestamp.

        Returns:
            Current SessionPhase.
        """
        return self._session_policy.get_session_phase(timestamp)

    def _get_premium_discount_location(
        self,
        head_reports: dict[str, HeadReport],
    ) -> str:
        """Determine premium/discount location from SMC/ICT reports.

        Checks if price is in premium (above PDH/VWAP) or discount
        (below PDL/VWAP) zone based on head report summaries.

        Args:
            head_reports: Dict of head reports.

        Returns:
            Description string: ``Premium``, ``Discount``, or ``Around Equilibrium``.
        """
        # Check SMC head for structure context
        smc_report = head_reports.get("SMC Head")
        if smc_report and smc_report.bias in (BiasType.BULLISH, BiasType.BEARISH):
            return self._infer_pd_from_bias_and_context(smc_report)

        # Check ICT head as fallback
        ict_report = head_reports.get("ICT Head")
        if ict_report and ict_report.bias in (BiasType.BULLISH, BiasType.BEARISH):
            return self._infer_pd_from_bias_and_context(ict_report)

        # Check Technical head for VWAP reference
        tech_report = head_reports.get("Technical Head")
        if tech_report:
            return self._infer_pd_from_bias_and_context(tech_report)

        return "Around Equilibrium"

    def _infer_pd_from_bias_and_context(self, report: HeadReport) -> str:
        """Infer premium/discount from a head report's bias and context quality.

        Args:
            report: A directional head report.

        Returns:
            Premium/discount description string.
        """
        if report.bias == BiasType.BULLISH:
            return "Discount (bullish structure suggests discount buying)"
        elif report.bias == BiasType.BEARISH:
            return "Premium (bearish structure suggests premium selling)"
        return "Around Equilibrium"

    def _get_key_levels_interaction(
        self,
        head_reports: dict[str, HeadReport],
    ) -> str:
        """Describe how price is interacting with key levels.

        Aggregates active_zones from all directional head reports to
        understand which levels are being tested, respected, or broken.

        Args:
            head_reports: Dict of head reports.

        Returns:
            Description of key level interaction.
        """
        level_mentions: list[str] = []

        for name, report in head_reports.items():
            if name == "Psychology Head":
                continue  # Psychology has no structural levels

            # Extract active zones
            zones = getattr(report, "active_zones", None) or []
            zone_labels = [z.get("label", z.get("type", "zone")) for z in zones if isinstance(z, dict)]
            if zone_labels:
                level_mentions.append(f"{name}: {', '.join(zone_labels[:3])}")

            # Check witness_summary for implicit level context
            witness = getattr(report, "witness_summary", "") or ""
            if witness and "level" in witness.lower():
                level_mentions.append(f"{name}: {witness[:60]}")

        if not level_mentions:
            return "No active key levels reported by heads"

        if len(level_mentions) <= 3:
            return "; ".join(level_mentions)

        return "; ".join(level_mentions[:3]) + f" (+{len(level_mentions) - 3} more)"

    def _get_directional_bias(
        self,
        floor_summary: FloorSummary | None,
        head_reports: dict[str, HeadReport],
    ) -> str:
        """Determine the overall directional bias from Floor Summary.

        Floor Summary's floor_bias_snapshot is the primary source.
        Falls back to head report consensus if summary is unavailable.

        Args:
            floor_summary: Current Floor Summary.
            head_reports: Dict of head reports.

        Returns:
            ``BULLISH``, ``BEARISH``, or ``NEUTRAL``.
        """
        if floor_summary and floor_summary.floor_bias_snapshot:
            bias = floor_summary.floor_bias_snapshot.get("dominant_bias")
            if bias in (_BULLISH_STR, _BEARISH_STR, _NEUTRAL_STR):
                return bias

        # Fallback: count head biases
        if not head_reports:
            return _NEUTRAL_STR

        directional = [
            r for r in head_reports.values()
            if r.head_name not in ("Psychology Head",)
        ]
        if not directional:
            return _NEUTRAL_STR

        bullish = sum(1 for r in directional if r.bias == BiasType.BULLISH)
        bearish = sum(1 for r in directional if r.bias == BiasType.BEARISH)

        if bullish > bearish:
            return _BULLISH_STR
        elif bearish > bullish:
            return _BEARISH_STR
        return _NEUTRAL_STR

    def _build_summary_text(
        self,
        regime: str,
        session_phase: SessionPhase,
        premium_discount: str,
        key_levels: str,
        bias: str,
        summary: FloorSummary | None,
    ) -> str:
        """Build a human-readable market story summary.

        Combines all components into a coherent narrative sentence
        that explains the current market context.

        Args:
            regime: Detected market regime.
            session_phase: Current session phase.
            premium_discount: Premium/discount location.
            key_levels: Key level interaction description.
            bias: Directional bias.
            summary: Floor Summary (for witness lines if available).

        Returns:
            Human-readable market story summary.
        """
        phase_label = session_phase.value.replace("_", " ").title()
        bias_label = bias.title()

        parts = [
            f"{phase_label} session — {bias_label} bias",
            f"Regime: {regime}",
        ]

        if premium_discount:
            parts.append(f"Location: {premium_discount}")

        if key_levels and "No active" not in key_levels:
            parts.append(f"Levels: {key_levels}")

        # Add witness/context from Floor Summary
        if summary and summary.summary_witness_lines:
            top_witnesses = summary.summary_witness_lines[:2]
            parts.extend(f"Context: {w}" for w in top_witnesses)

        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_market_context(
        self,
        floor_summary: FloorSummary | None = None,
        head_reports: dict[str, HeadReport] | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        """Get a lightweight market context dict suitable for dashboard/logging.

        Unlike ``build_story()`` which returns a full ``MarketStory`` dataclass,
        this returns a plain dict for quick consumption by Side B (dashboard)
        or Side C (memory/audit).

        Note: This is a utility/public API method for external consumers.
        It is NOT called during the captain_engine heavy cycle — the
        engine uses ``build_story()`` directly for its internal flow.

        Args:
            floor_summary: Current Floor Summary.
            head_reports: Dict of head reports.
            timestamp: Current UTC timestamp.

        Returns:
            Dict with key market context fields.
        """
        story = self.build_story(
            floor_summary=floor_summary,
            head_reports=head_reports,
            timestamp=timestamp,
        )
        return {
            "regime": story.regime,
            "session_phase": story.session_phase.value,
            "bias": story.bias,
            "premium_discount": story.premium_discount_location,
            "summary": story.summary,
            "timestamp": story.timestamp.isoformat() if story.timestamp else "",
        }
