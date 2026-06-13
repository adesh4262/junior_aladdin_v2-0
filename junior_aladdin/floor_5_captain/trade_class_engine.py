"""Floor 5 — Trade Class Engine (Step 5.11).

Authoritatively assigns one of 5 trade classes to an approved trade idea and
provides class-specific metadata (expiry, cooldown, conviction threshold,
management style).

Architecture rules (see ROADMAP_FLOOR_05 Section 11):
- 5 trade classes: SCALP, CONTINUATION, REVERSAL, LIQUIDITY_RECLAIM, OPTIONS_PRESSURE
- Trade class affects: expiry window, cooldown period, management style, conviction threshold
- Captain assigns trade class; Side A executes per class rules
- Trade class engine is called AFTER trade_idea_generator produces a suggestion
- The engine may confirm or override the suggested class based on full context

Trade class characteristics (LOCKED):
- SCALP: 1-2 candle expiry, tight SL, 1:1 target, low conviction threshold
- CONTINUATION: 2-4 candle expiry, trailing SL, trend-following, medium conviction
- REVERSAL: 2-3 candle expiry, counter-trend with confirmation, high conviction
- LIQUIDITY_RECLAIM: until sweep reclaimed or fails, zone-based, medium conviction
- OPTIONS_PRESSURE: until wall tested or pressure collapses, OI-aware, high conviction
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionBand,
    MarketStory,
    SessionPhase,
)
from junior_aladdin.floor_5_captain.trade_idea_generator import TradeIdea
from junior_aladdin.shared.types import TradeClass


# ── TradeClassMetadata dataclass ────────────────────────────────────────────


@dataclass
class TradeClassMetadata:
    """Metadata and rules for a specific trade class.

    Fields:
        trade_class: The TradeClass this metadata describes.
        label: Human-readable label (e.g., "Scalp", "Continuation").
        expiry_candles: Number of 1m candles before setup expires.
        cooldown_candles: Number of 1m candles before re-entry allowed.
        min_conviction_band: Minimum ConvictionBand required for this class.
        management_style: Position management approach description.
        description: Brief explanation of when to use this class.
        requires_confirmation: Whether an extra confirmation tick is required.
        max_spread_bps: Maximum acceptable spread in basis points.
    """
    trade_class: TradeClass
    label: str = ""
    expiry_candles: int = 2
    cooldown_candles: int = 3
    min_conviction_band: ConvictionBand = ConvictionBand.WEAK
    management_style: str = ""
    description: str = ""
    requires_confirmation: bool = False
    max_spread_bps: int = 10


# ── TradeClassAssignment result dataclass ────────────────────────────────────


@dataclass
class TradeClassAssignment:
    """Result of trade class assignment.

    Fields:
        trade_class: The assigned TradeClass.
        metadata: Metadata for the assigned class.
        overridden: Whether the suggested class was overridden.
        override_reason: Reason if overridden.
        confidence_fit: How well the class fits (0.0-1.0).
        assigned_at: When the assignment was made.
    """
    trade_class: TradeClass | None = None
    metadata: TradeClassMetadata | None = None
    overridden: bool = False
    override_reason: str = ""
    confidence_fit: float = 0.0
    assigned_at: datetime = field(default_factory=datetime.utcnow)


# ── Trade class metadata registry (LOCKED) ─────────────────────────────────

_CLASS_METADATA: dict[TradeClass, TradeClassMetadata] = {
    TradeClass.SCALP: TradeClassMetadata(
        trade_class=TradeClass.SCALP,
        label="Scalp",
        expiry_candles=2,
        cooldown_candles=1,
        min_conviction_band=ConvictionBand.WEAK,
        management_style="Quick entry/exit, tight SL, 1:1 target",
        description="Fast trade on short-term imbalance, 1-2 candle hold",
        requires_confirmation=False,
        max_spread_bps=5,
    ),
    TradeClass.CONTINUATION: TradeClassMetadata(
        trade_class=TradeClass.CONTINUATION,
        label="Continuation",
        expiry_candles=4,
        cooldown_candles=3,
        min_conviction_band=ConvictionBand.TRADABLE,
        management_style="Trend-following, trailing SL, 1:2 target preferred",
        description="Follow established trend in strong regime",
        requires_confirmation=True,
        max_spread_bps=8,
    ),
    TradeClass.REVERSAL: TradeClassMetadata(
        trade_class=TradeClass.REVERSAL,
        label="Reversal",
        expiry_candles=3,
        cooldown_candles=5,
        min_conviction_band=ConvictionBand.STRONG,
        management_style="Counter-trend with structure confirmation, wider SL",
        description="Structure break or exhaustion move against prevailing trend",
        requires_confirmation=True,
        max_spread_bps=10,
    ),
    TradeClass.LIQUIDITY_RECLAIM: TradeClassMetadata(
        trade_class=TradeClass.LIQUIDITY_RECLAIM,
        label="Liquidity Reclaim",
        expiry_candles=0,  # Until sweep reclaimed or fails (not candle-bound)
        cooldown_candles=4,
        min_conviction_band=ConvictionBand.TRADABLE,
        management_style="Zone-based: entry on reclaim, SL beyond sweep, target structure",
        description="Sweep of key level followed by reclaim entry",
        requires_confirmation=True,
        max_spread_bps=8,
    ),
    TradeClass.OPTIONS_PRESSURE: TradeClassMetadata(
        trade_class=TradeClass.OPTIONS_PRESSURE,
        label="Options Pressure",
        expiry_candles=0,  # Until wall tested or pressure collapses
        cooldown_candles=3,
        min_conviction_band=ConvictionBand.STRONG,
        management_style="OI wall bounce or pressure continuation, trail on expansion",
        description="Trade based on OI wall interaction or options flow pressure",
        requires_confirmation=True,
        max_spread_bps=12,
    ),
}

# ── Regime-to-trade-class suitability scores (0.0-1.0) ─────────────────────
# Higher = more suitable. Used to override suggestions when context demands it.

_REGIME_CLASS_FIT: dict[str, dict[TradeClass, float]] = {
    "TREND_UP": {
        TradeClass.CONTINUATION: 1.0,
        TradeClass.SCALP: 0.7,
        TradeClass.LIQUIDITY_RECLAIM: 0.6,
        TradeClass.OPTIONS_PRESSURE: 0.4,
        TradeClass.REVERSAL: 0.1,
    },
    "TREND_DOWN": {
        TradeClass.CONTINUATION: 1.0,
        TradeClass.SCALP: 0.7,
        TradeClass.LIQUIDITY_RECLAIM: 0.6,
        TradeClass.OPTIONS_PRESSURE: 0.4,
        TradeClass.REVERSAL: 0.1,
    },
    "WEAK_UP": {
        TradeClass.LIQUIDITY_RECLAIM: 0.9,
        TradeClass.OPTIONS_PRESSURE: 0.7,
        TradeClass.SCALP: 0.6,
        TradeClass.CONTINUATION: 0.4,
        TradeClass.REVERSAL: 0.3,
    },
    "WEAK_DOWN": {
        TradeClass.LIQUIDITY_RECLAIM: 0.9,
        TradeClass.OPTIONS_PRESSURE: 0.7,
        TradeClass.SCALP: 0.6,
        TradeClass.CONTINUATION: 0.4,
        TradeClass.REVERSAL: 0.3,
    },
    "RANGE": {
        TradeClass.OPTIONS_PRESSURE: 1.0,
        TradeClass.SCALP: 0.7,
        TradeClass.LIQUIDITY_RECLAIM: 0.5,
        TradeClass.REVERSAL: 0.4,
        TradeClass.CONTINUATION: 0.1,
    },
    "CHOP": {
        TradeClass.SCALP: 0.9,
        TradeClass.OPTIONS_PRESSURE: 0.4,
        TradeClass.LIQUIDITY_RECLAIM: 0.3,
        TradeClass.REVERSAL: 0.2,
        TradeClass.CONTINUATION: 0.0,
    },
    "UNCLEAR": {
        TradeClass.SCALP: 0.5,
        TradeClass.OPTIONS_PRESSURE: 0.3,
        TradeClass.LIQUIDITY_RECLAIM: 0.2,
        TradeClass.REVERSAL: 0.1,
        TradeClass.CONTINUATION: 0.0,
    },
}

# Session phase modifiers (multiply fit scores)
_SESSION_FIT_MODIFIER: dict[SessionPhase, float] = {
    SessionPhase.GOLDEN_MORNING: 1.0,
    SessionPhase.OPENING: 0.8,
    SessionPhase.LUNCH: 0.6,
    SessionPhase.CLOSING: 0.4,
}


class TradeClassEngine:
    """Authoritatively assigns trade classes with metadata.

    Takes a trade idea's suggested class and validates/refines it against
    the current market context (regime, session, conviction, confluence).

    Usage::

        engine = TradeClassEngine()
        assignment = engine.assign_trade_class(
            trade_idea=idea,
            market_story=story,
            confluence_result=conf_result,
        )
        if assignment.trade_class:
            meta = engine.get_metadata(assignment.trade_class)
            logger.info(f"Assigned {meta.label}: {meta.description}")
    """

    def __init__(self) -> None:
        """Initialize the trade class engine."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign_trade_class(
        self,
        trade_idea: TradeIdea | None = None,
        market_story: MarketStory | None = None,
        confluence_result: ConfluenceResult | None = None,
    ) -> TradeClassAssignment:
        """Assign the final trade class for a trade idea.

        The engine considers:
        1. The suggested class from the trade idea (if any)
        2. Market regime suitability scores
        3. Session phase modifier
        4. Confluence quality adjustment
        5. Conviction band minimum requirements

        Args:
            trade_idea: The TradeIdea from trade_idea_generator.
            market_story: Current MarketStory for context.
            confluence_result: ConfluenceResult for quality context.

        Returns:
            A ``TradeClassAssignment`` with the final class and metadata.
        """
        dt = trade_idea.timestamp if trade_idea else datetime.utcnow()

        # Determine the best class based on full context
        result = self._evaluate_best_class(
            suggested_class=trade_idea.trade_class_suggestion if trade_idea else None,
            market_story=market_story,
            confluence_result=confluence_result,
            conviction_band=trade_idea.conviction_band if trade_idea else None,
        )

        if result is None:
            return TradeClassAssignment(
                trade_class=None,
                metadata=None,
                assigned_at=dt,
            )

        best_class, confidence_fit, overridden, reason = result
        metadata = self.get_metadata(best_class)

        return TradeClassAssignment(
            trade_class=best_class,
            metadata=metadata,
            overridden=overridden,
            override_reason=reason,
            confidence_fit=confidence_fit,
            assigned_at=dt,
        )

    def get_metadata(self, trade_class: TradeClass) -> TradeClassMetadata | None:
        """Get metadata for a trade class.

        Args:
            trade_class: The TradeClass to look up.

        Returns:
            ``TradeClassMetadata`` for the class, or None if unknown.
        """
        return _CLASS_METADATA.get(trade_class)

    def validate_class(
        self,
        trade_class: TradeClass,
        conviction_band: ConvictionBand | None = None,
        market_story: MarketStory | None = None,
    ) -> tuple[bool, str]:
        """Validate whether a trade class is appropriate for current context.

        Args:
            trade_class: The TradeClass to validate.
            conviction_band: Current conviction band.
            market_story: Current market story for regime context.

        Returns:
            Tuple of ``(is_valid, reason_string)``.
        """
        metadata = self.get_metadata(trade_class)
        if metadata is None:
            return False, f"Unknown trade class: {trade_class}"

        # Check conviction band meets minimum
        if conviction_band is not None:
            min_band = metadata.min_conviction_band
            if self._band_value(conviction_band) < self._band_value(min_band):
                return (
                    False,
                    f"Conviction {conviction_band.value} below minimum "
                    f"{min_band.value} required for {metadata.label}",
                )

        # Check regime suitability
        if market_story and market_story.regime:
            regime = market_story.regime.upper()
            if regime in _REGIME_CLASS_FIT:
                fit = _REGIME_CLASS_FIT[regime].get(trade_class, 0.0)
                if fit < 0.2:
                    return (
                        False,
                        f"{metadata.label} unsuitable for {regime} regime (fit: {fit:.1f})",
                    )

        return True, f"{metadata.label} class valid"

    def get_preferred_classes(
        self,
        market_story: MarketStory | None = None,
        conviction_band: ConvictionBand | None = None,
    ) -> list[tuple[TradeClass, float]]:
        """Get preferred trade classes ranked by suitability.

        Args:
            market_story: Current market story for regime/session context.
            conviction_band: Current conviction band for filtering.

        Returns:
            List of ``(TradeClass, suitability_score)`` sorted descending.
        """
        regime = (market_story.regime or "").upper() if market_story else ""
        session = (
            market_story.session_phase
            if market_story and market_story.session_phase
            else SessionPhase.OPENING
        )

        if regime not in _REGIME_CLASS_FIT:
            return []

        session_mod = _SESSION_FIT_MODIFIER.get(session, 0.8)
        fits = _REGIME_CLASS_FIT[regime]

        scored: list[tuple[TradeClass, float]] = []
        for tc, fit in fits.items():
            # Filter by conviction band if provided
            if conviction_band is not None:
                meta = self.get_metadata(tc)
                if meta and self._band_value(conviction_band) < self._band_value(meta.min_conviction_band):
                    continue
            scored.append((tc, fit * session_mod))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Internal Logic
    # ------------------------------------------------------------------

    def _evaluate_best_class(
        self,
        suggested_class: TradeClass | None,
        market_story: MarketStory | None,
        confluence_result: ConfluenceResult | None,
        conviction_band: ConvictionBand | None,
    ) -> tuple[TradeClass, float, bool, str] | None:
        """Evaluate and select the best trade class from all available context.

        Args:
            suggested_class: The suggested class from the trade idea.
            market_story: Current market story.
            confluence_result: Confluence result.
            conviction_band: Current conviction band.

        Returns:
            Tuple of ``(best_class, confidence_fit, was_overridden, reason)``
            or None if no class can be determined.
        """
        regime = (market_story.regime or "").upper() if market_story else ""
        session = (
            market_story.session_phase
            if market_story and market_story.session_phase
            else SessionPhase.OPENING
        )

        if regime not in _REGIME_CLASS_FIT:
            return None

        # Get regime-based fit scores
        fits = _REGIME_CLASS_FIT[regime]
        session_mod = _SESSION_FIT_MODIFIER.get(session, 0.8)
        quality_mod = (
            confluence_result.confluence_quality
            if confluence_result
            else 0.5
        )

        # Score each class
        scored: list[tuple[TradeClass, float]] = []
        for tc, fit in fits.items():
            # Skip if conviction band too low for this class
            if conviction_band is not None:
                meta = self.get_metadata(tc)
                if meta and self._band_value(conviction_band) < self._band_value(meta.min_conviction_band):
                    continue

            adjusted = fit * session_mod * quality_mod
            scored.append((tc, adjusted))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        best_class, best_score = scored[0]

        # Determine if suggested class was overridden
        overridden = False
        reason = ""

        if suggested_class is not None and suggested_class != best_class:
            overridden = True
            suggested_score = next(
                (s for tc, s in scored if tc == suggested_class),
                0.0,
            )
            if best_score > suggested_score * 1.2:  # 20% better
                reason = (
                    f"{best_class.value} preferred over {suggested_class.value} "
                    f"for {regime} regime (fit: {best_score:.2f} vs {suggested_score:.2f})"
                )
            else:
                # Close enough — keep suggestion
                best_class = suggested_class
                best_score = suggested_score
                overridden = False

        return best_class, best_score, overridden, reason

    @staticmethod
    def _band_value(band: ConvictionBand) -> int:
        """Get numeric value of a ConvictionBand for comparison.

        Args:
            band: The ConvictionBand.

        Returns:
            Integer value (REJECT=0, WEAK=1, TRADABLE=2, STRONG=3, ELITE=4).
        """
        values = {
            ConvictionBand.REJECT: 0,
            ConvictionBand.WEAK: 1,
            ConvictionBand.TRADABLE: 2,
            ConvictionBand.STRONG: 3,
            ConvictionBand.ELITE: 4,
        }
        return values.get(band, 0)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_assignment_summary(
        self,
        assignment: TradeClassAssignment,
    ) -> dict[str, Any]:
        """Get a structured summary of trade class assignment.

        Args:
            assignment: The TradeClassAssignment to summarize.

        Returns:
            Dict with key assignment fields.
        """
        return {
            "trade_class": assignment.trade_class.value if assignment.trade_class else "",
            "label": assignment.metadata.label if assignment.metadata else "",
            "expiry_candles": assignment.metadata.expiry_candles if assignment.metadata else 0,
            "cooldown_candles": assignment.metadata.cooldown_candles if assignment.metadata else 0,
            "management_style": assignment.metadata.management_style if assignment.metadata else "",
            "overridden": assignment.overridden,
            "override_reason": assignment.override_reason,
            "confidence_fit": round(assignment.confidence_fit, 2),
            "has_assignment": assignment.trade_class is not None,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else "",
        }
