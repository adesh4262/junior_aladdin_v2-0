"""Floor 5 — Active Trade Supervisor (Step 5.19).

Thesis integrity tracking while a trade is active. Runs in both heavy cycle
(candle close) and light cycle (tick) to monitor the health of an active trade's
original thesis.

Questions tracked:
- Is original OB/FVG/zone still valid?
- Is options support still alive?
- Did macro context shift?
- Does market story still support thesis?
- Has opposite case strengthened?

Architecture rules (see ROADMAP_FLOOR_05 Section 5.19):
- Active trade supervisor is called AFTER trade_constructor
- Runs in both heavy and light cycles
- Does NOT make intervention decisions — only reports thesis health
- intervention_engine consumes this output for rare override decisions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    MarketStory,
)
from junior_aladdin.shared.types import CaptainDecision, TradeClass


# ── ThesisReview dataclass ────────────────────────────────────────────────


@dataclass
class ThesisReview:
    """Result of reviewing an active trade's thesis integrity.

    Fields:
        thesis_intact: Whether the original trading thesis is still valid.
        concerns: List of specific concerns found during review.
        zone_valid: Whether the original entry zone (OB/FVG) is still valid.
        options_support_alive: Whether options support is still present.
        macro_shift_detected: Whether macro context has shifted significantly.
        market_story_supports: Whether current market story still supports thesis.
        opposite_case_strengthened: Whether the opposite case has gotten stronger.
        recommendation: One of ``THESIS_INTACT``, ``MONITOR_CLOSELY``,
                       ``PREPARE_EXIT``, ``INTERVENTION_REQUIRED``.
        recommendation_label: Human-readable label for the recommendation.
        reviewed_at: When the review was performed.
    """
    thesis_intact: bool = True
    concerns: list[str] = field(default_factory=list)
    zone_valid: bool = True
    options_support_alive: bool = True
    macro_shift_detected: bool = False
    market_story_supports: bool = True
    opposite_case_strengthened: bool = False
    recommendation: str = "THESIS_INTACT"
    recommendation_label: str = "Thesis intact"
    reviewed_at: datetime = field(default_factory=datetime.utcnow)


# ── Recommendation levels ─────────────────────────────────────────────────

# Maps recommendation codes to human-readable labels and severity
_RECOMMENDATIONS: dict[str, tuple[str, int]] = {
    "THESIS_INTACT": ("Thesis intact", 0),
    "MONITOR_CLOSELY": ("Minor concerns, monitor closely", 1),
    "PREPARE_EXIT": ("Thesis weakening, prepare exit", 2),
    "INTERVENTION_REQUIRED": ("Thesis significantly broken, intervention needed", 3),
}


# ── ActiveTradeSupervisor ─────────────────────────────────────────────────


class ActiveTradeSupervisor:
    """Tracks thesis integrity of active trades.

    Provides structured reviews of whether the original trading thesis remains
    valid based on current market conditions. Used by both heavy and light cycles.

    Usage::

        supervisor = ActiveTradeSupervisor()

        # Heavy cycle review (full context)
        review = supervisor.review_thesis(
            active_trade=decision,
            current_market_story=story,
            current_price=19550.0,
            zone_price=19500.0,
        )

        if not review.thesis_intact:
            logger.warning(f\"Thesis concerns: {review.concerns}\")

        # Check if intervention should be considered
        if supervisor.should_intervene():
            logger.info(\"Strong opposite confluence — considering intervention\")
    """

    def __init__(self) -> None:
        """Initialize the active trade supervisor."""
        self._active_trade: CaptainDecision | None = None
        self._reviews: list[ThesisReview] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review_thesis(
        self,
        active_trade: CaptainDecision | None = None,
        current_market_story: MarketStory | None = None,
        current_price: float = 0.0,
        zone_price: float = 0.0,
        zone_label: str = "",
        current_confluence: ConfluenceResult | None = None,
        original_confluence_direction: str = "",
    ) -> ThesisReview:
        """Review the integrity of an active trade's thesis.

        Checks multiple dimensions of thesis health and produces a
        structured assessment with recommendation.

        Args:
            active_trade: The CaptainDecision for the active trade.
            current_market_story: Current market story from market_story_engine.
            current_price: Current market price.
            zone_price: The original zone price (OB, FVG, etc.).
            zone_label: The original zone label for context.
            current_confluence: Current confluence result for opposite case check.
            original_confluence_direction: The dominant direction when trade was opened
                                          (BULLISH/BEARISH).

        Returns:
            A ``ThesisReview`` with integrity assessment and concerns.
        """
        self._active_trade = active_trade or self._active_trade
        concerns: list[str] = []
        zone_valid = True
        options_alive = True
        macro_shift = False
        story_supports = True
        opposite_stronger = False

        at = self._active_trade

        # Check 1: Zone validity — price hasn't moved far from zone
        if zone_price > 0 and current_price > 0 and at:
            zone_valid = self._check_zone_validity(
                direction=at.action,
                zone_price=zone_price,
                current_price=current_price,
                trade_class=at.trade_class,
            )
            if not zone_valid:
                concerns.append(f"Zone {zone_label or zone_price} no longer valid "
                                f"(price at {current_price:.1f})")

        # Check 2: Market story support
        if current_market_story and at:
            story_supports = self._check_market_story_support(
                trade_direction=at.action,
                market_story=current_market_story,
            )
            if not story_supports:
                concerns.append(f"Market story no longer supports {at.action} thesis "
                                f"(regime: {current_market_story.regime})")

        # Check 3: Macro context shift
        if current_market_story and at:
            macro_shift = self._check_macro_shift(market_story=current_market_story)
            if macro_shift:
                concerns.append(f"Macro context shifted (regime: {current_market_story.regime})")

        # Check 4: Options support
        if at and at.trade_class == TradeClass.OPTIONS_PRESSURE:
            # Simplified: for non-OPTIONS trades, support is considered alive
            options_alive = self._check_options_support(current_price)
            if not options_alive:
                concerns.append("Options support appears weakened")

        # Check 5: Opposite case strength
        if current_confluence:
            opposite_stronger = self._check_opposite_case(
                current_confluence=current_confluence,
                original_direction=original_confluence_direction or (at.action if at else ""),
            )
            if opposite_stronger:
                concerns.append("Opposite case has strengthened significantly")

        # Determine recommendation
        recommendation, rec_label = self._determine_recommendation(
            concerns=concerns,
            zone_valid=zone_valid,
            opposite_stronger=opposite_stronger,
            macro_shift=macro_shift,
        )

        review = ThesisReview(
            thesis_intact=recommendation == "THESIS_INTACT",
            concerns=concerns,
            zone_valid=zone_valid,
            options_support_alive=options_alive,
            macro_shift_detected=macro_shift,
            market_story_supports=story_supports,
            opposite_case_strengthened=opposite_stronger,
            recommendation=recommendation,
            recommendation_label=rec_label,
            reviewed_at=datetime.utcnow(),
        )

        self._reviews.append(review)
        return review

    # ------------------------------------------------------------------
    # Check Methods
    # ------------------------------------------------------------------

    @staticmethod
    def _check_zone_validity(
        direction: str,
        zone_price: float,
        current_price: float,
        trade_class: TradeClass | None = None,
        threshold_pct: float = 0.005,
    ) -> bool:
        """Check if the original entry zone is still valid.

        Zone validity means price hasn't moved too far from the zone
        in the opposite direction of the trade.

        Args:
            direction: Trade direction (BUY/SELL).
            zone_price: The original zone price.
            current_price: Current market price.
            trade_class: Trade class for context.
            threshold_pct: Maximum allowed deviation (default 0.5%).

        Returns:
            True if the zone is still valid.
        """
        if current_price <= 0 or zone_price <= 0:
            return True

        deviation = abs(current_price - zone_price) / zone_price

        # SCALP has tighter zone tolerance
        if trade_class == TradeClass.SCALP:
            threshold_pct = 0.003  # 0.3%
        elif trade_class == TradeClass.REVERSAL:
            threshold_pct = 0.008  # 0.8% (wider for reversals)

        return deviation <= threshold_pct

    @staticmethod
    def _check_market_story_support(
        trade_direction: str,
        market_story: MarketStory,
    ) -> bool:
        """Check if the current market story still supports the trade.

        Args:
            trade_direction: Trade direction (BUY/SELL).
            market_story: Current market story.

        Returns:
            True if market story still supports the trade.
        """
        if not market_story.regime:
            return True

        regime = market_story.regime.upper()
        bias = market_story.bias.upper() if market_story.bias else ""

        # Regimes that generally don't support any trade
        if regime in ("CHOP", "UNCLEAR"):
            return False

        # Check directional alignment
        if trade_direction == "BUY" and bias == "BEARISH":
            return False
        if trade_direction == "SELL" and bias == "BULLISH":
            return False

        return True

    @staticmethod
    def _check_macro_shift(
        market_story: MarketStory,
    ) -> bool:
        """Check if macro context has shifted significantly.

        A regime of CHOP or UNCLEAR is always concerning for active trades.
        Full regime-flip tracking (original vs current) requires the
        caller to store the opening regime and pass it separately.

        Args:
            market_story: Current market story.

        Returns:
            True if a concerning macro shift is detected.
        """
        if not market_story or not market_story.regime:
            return False

        regime = market_story.regime.upper()

        # A regime of CHOP or UNCLEAR is always concerning for active trades
        if regime in ("CHOP", "UNCLEAR"):
            return True

        return False

    @staticmethod
    def _check_options_support(current_price: float) -> bool:
        """Check if options support is still alive.

        Simplified check. In production this would use live OI data.

        Args:
            current_price: Current market price (proxy for OI health).

        Returns:
            True if options support appears intact.
        """
        # Simplified: any positive price means support exists
        # In production, this checks OI wall proximity
        return current_price > 0

    @staticmethod
    def _check_opposite_case(
        current_confluence: ConfluenceResult,
        original_direction: str,
    ) -> bool:
        """Check if the opposite case has strengthened significantly.

        Args:
            current_confluence: Current confluence result.
            original_direction: The original trade direction (BUY/SELL)
                               mapped to BULLISH/BEARISH.

        Returns:
            True if opposite case is now stronger than when trade opened.
        """
        if current_confluence is None:
            return False

        # Map trade direction to confluence direction
        if original_direction == "BUY":
            original_dir = "BULLISH"
        elif original_direction == "SELL":
            original_dir = "BEARISH"
        else:
            original_dir = original_direction

        # Check if dominant direction has flipped
        current_direction = current_confluence.dominant_direction
        if current_direction == "NEUTRAL":
            return False

        # Direction flip = opposite case strengthened
        if original_dir == "BULLISH" and current_direction == "BEARISH":
            return True
        if original_dir == "BEARISH" and current_direction == "BULLISH":
            return True

        # Low confluence quality also suggests opposite case gaining strength
        if current_confluence.confluence_quality < 0.3:
            return True

        return False

    # ------------------------------------------------------------------
    # Recommendation Logic
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_recommendation(
        concerns: list[str],
        zone_valid: bool,
        opposite_stronger: bool,
        macro_shift: bool,
    ) -> tuple[str, str]:
        """Determine the recommendation based on review findings.

        Args:
            concerns: List of concerns found.
            zone_valid: Whether the zone is still valid.
            opposite_stronger: Whether opposite case strengthened.
            macro_shift: Whether macro context shifted.

        Returns:
            Tuple of ``(recommendation_code, recommendation_label)``.
        """
        if not concerns:
            return "THESIS_INTACT", "Thesis intact"

        # Intervention required if multiple critical factors fail
        critical_count = sum([not zone_valid, opposite_stronger, macro_shift])
        if critical_count >= 2:
            return "INTERVENTION_REQUIRED", "Thesis significantly broken, intervention needed"

        # Prepare exit if zone is invalid or opposite is stronger
        if not zone_valid or opposite_stronger:
            return "PREPARE_EXIT", "Thesis weakening, prepare exit"

        # Monitor closely for 1-2 concerns
        if len(concerns) >= 1:
            return "MONITOR_CLOSELY", "Minor concerns, monitor closely"

        return "THESIS_INTACT", "Thesis intact"

    # ------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------

    def get_supervision_state(self) -> dict[str, Any]:
        """Get the current supervision state summary.

        Returns:
            Dict with supervision state fields.
        """
        latest = self.get_latest_review()
        return {
            "has_active_trade": self._active_trade is not None,
            "total_reviews": len(self._reviews),
            "latest_recommendation": latest.recommendation if latest else "",
            "latest_recommendation_label": latest.recommendation_label if latest else "",
            "thesis_intact": latest.thesis_intact if latest else True,
            "concern_count": len(latest.concerns) if latest else 0,
            "concerns": latest.concerns if latest else [],
        }

    def should_intervene(self) -> bool:
        """Check if intervention should be considered.

        Only returns True if the latest review recommends intervention.
        The intervention_engine makes the final decision.

        Returns:
            True if the latest review recommends intervention.
        """
        latest = self.get_latest_review()
        if latest is None:
            return False
        return latest.recommendation == "INTERVENTION_REQUIRED"

    def get_latest_review(self) -> ThesisReview | None:
        """Get the most recent thesis review.

        Returns:
            The latest ``ThesisReview``, or None if no reviews exist.
        """
        if not self._reviews:
            return None
        return self._reviews[-1]

    def get_review_history(self) -> list[ThesisReview]:
        """Get all thesis reviews performed this session.

        Returns:
            List of ``ThesisReview`` entries in chronological order.
        """
        return list(self._reviews)

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def clear_active_trade(self) -> None:
        """Clear the active trade reference (when trade closes)."""
        self._active_trade = None

    def clear_session(self) -> None:
        """Clear all supervision state for a new trading day."""
        self._active_trade = None
        self._reviews.clear()
