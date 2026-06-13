"""Floor 5 — Conviction Engine (Step 5.9).

Builds Captain's three internal scores and maps them to conviction bands.

Locked architecture rules (see ROADMAP_FLOOR_05 Section 5, 15 & 24):
- permission_score, conviction_score, and no_trade_score remain SEPARATE
- permission_score: how permissive is the current environment (0-100)
- conviction_score: how confident is Captain in this trade (0-100)
- no_trade_score: how strong is the case for NOT trading (0-100)
- Conviction bands: 0-39→REJECT, 40-59→WEAK, 60-74→TRADABLE, 75-89→STRONG, 90+→ELITE
- Opposite case strength > 0.7 → conviction reduces by >10%
- Session aggression modifier adjusts conviction threshold
- Captain owns CONVICTION — NOT confidence (confidence is Floor 4)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionBand,
    ConvictionScore,
    MarketStory,
    OppositeCase,
    PermissionResult,
    conviction_score_to_band,
    get_aggression_modifier,
    get_permission_strictness,
)
from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.shared.types import HeadReport


# ── Score weights (locked architecture) ─────────────────────────────────────

# Permission score components
_PERMISSION_WEIGHT_ALLOWED = 50.0    # Base if permission gate allows
_PERMISSION_WEIGHT_CONFLUENCE = 20.0  # From confluence quality
_PERMISSION_WEIGHT_SESSION = 15.0     # From session phase
_PERMISSION_WEIGHT_PSYCHOLOGY = 15.0  # From psychology caution

# Conviction score components
_CONVICTION_WEIGHT_CONFLUENCE = 60.0  # Head alignment quality
_CONVICTION_WEIGHT_OPPOSITE = 25.0    # Opposite case (negative impact)
_CONVICTION_WEIGHT_REGIME = 25.0      # Regime clarity
_CONVICTION_WEIGHT_PSYCHOLOGY = 15.0  # Psychology caution/cooldown
_CONVICTION_WEIGHT_SESSION = 10.0     # Session aggression modifier

# No-trade score components
_NOTRADE_WEIGHT_OPPOSITE = 35.0       # Opposite case strength
_NOTRADE_WEIGHT_CONFLICT = 25.0       # Confluence conflict
_NOTRADE_WEIGHT_PSYCHOLOGY = 25.0     # Psychology caution/cooldown
_NOTRADE_WEIGHT_REGIME = 15.0         # Unclear regime

# ── Thresholds ─────────────────────────────────────────────────────────────
_STRONG_OPPOSITION_CUTOFF = 0.7      # Opposite above this = >10% conviction cut
_OPPOSITION_REDUCTION_RATE = 0.15    # 15% reduction for strong opposite
_MAX_CONVICTION_SCORE = 100.0
_MAX_PERMISSION_SCORE = 100.0
_MAX_NOTRADE_SCORE = 100.0

# ── Session modifier impact ────────────────────────────────────────────────
# How much the aggression modifier impacts conviction score
_AGGRESSION_IMPACT_FACTOR = 15.0     # Each 0.1 modifier shifts conviction by 1.5 points


class ConvictionEngine:
    """Computes Captain's three internal scores and conviction band.

    This is the central judgment module — it takes all upstream analysis
    (permission, market story, confluence, opposite case, psychology) and
    produces the final conviction assessment.

    Usage::

        engine = ConvictionEngine()
        scores = engine.compute_scores(
            permission_result=perm_result,
            confluence_result=conf_result,
            opposite_case=opp_case,
            market_story=story,
            psychology_report=psych_report,
            session_policy=session_policy,
            timestamp=datetime.utcnow(),
        )
        logger.info(f"Conviction band: {scores.conviction_band.value}")
    """

    def __init__(self) -> None:
        """Initialize the conviction engine."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_scores(
        self,
        permission_result: PermissionResult | None = None,
        confluence_result: ConfluenceResult | None = None,
        opposite_case: OppositeCase | None = None,
        market_story: MarketStory | None = None,
        psychology_report: HeadReport | None = None,
        session_policy: SessionPolicy | None = None,
        timestamp: datetime | None = None,
    ) -> ConvictionScore:
        """Compute all three conviction scores and the conviction band.

        All parameters are optional — the engine produces sensible defaults
        if any inputs are missing.

        Args:
            permission_result: Result from permission_gate.
            confluence_result: Result from confluence_engine.
            opposite_case: Result from opposite_case_engine.
            market_story: Current market story from market_story_engine.
            psychology_report: Psychology Head report.
            session_policy: SessionPolicy for aggression modifiers.
            timestamp: Current UTC timestamp.

        Returns:
            A fully populated ``ConvictionScore``.
        """
        dt = timestamp or datetime.utcnow()

        # Compute each score independently
        permission_score = self._compute_permission_score(
            permission_result=permission_result,
            confluence_result=confluence_result,
            psychology_report=psychology_report,
            session_policy=session_policy,
            dt=dt,
        )

        conviction_score = self._compute_conviction_score(
            confluence_result=confluence_result,
            opposite_case=opposite_case,
            market_story=market_story,
            psychology_report=psychology_report,
            session_policy=session_policy,
            dt=dt,
        )

        no_trade_score = self._compute_no_trade_score(
            confluence_result=confluence_result,
            opposite_case=opposite_case,
            market_story=market_story,
            psychology_report=psychology_report,
        )

        band = conviction_score_to_band(conviction_score)

        return ConvictionScore(
            permission_score=round(permission_score, 1),
            conviction_score=round(conviction_score, 1),
            no_trade_score=round(no_trade_score, 1),
            conviction_band=band,
            timestamp=dt,
        )

    # ------------------------------------------------------------------
    # Score Computation — Permission Score
    # ------------------------------------------------------------------

    def _compute_permission_score(
        self,
        permission_result: PermissionResult | None,
        confluence_result: ConfluenceResult | None,
        psychology_report: HeadReport | None,
        session_policy: SessionPolicy | None,
        dt: datetime,
    ) -> float:
        """Compute the permission score (0-100).

        How permissive is the current environment for trading?
        Base score from permission gate, modified by confluence,
        session phase, and psychology state.

        Args:
            permission_result: Permission gate result.
            confluence_result: Confluence result.
            psychology_report: Psychology Head report.
            session_policy: Session policy for phase info.
            dt: Current timestamp.

        Returns:
            Permission score (0-100).
        """
        score = 0.0

        # Base: did permission gate pass?
        if permission_result and permission_result.allowed:
            score += _PERMISSION_WEIGHT_ALLOWED
        elif permission_result:
            # Permissions blocked — score is very low
            return max(0.0, 10.0 - len(permission_result.blocked_by) * 5.0)

        # Confluence quality contribution
        if confluence_result:
            score += _PERMISSION_WEIGHT_CONFLUENCE * confluence_result.confluence_quality

        # Session phase contribution
        if session_policy and dt:
            phase = session_policy.get_session_phase(dt)
            strictness = session_policy.get_permission_strictness(phase)
            if strictness == "NORMAL":
                score += _PERMISSION_WEIGHT_SESSION
            elif strictness == "HIGH":
                score += _PERMISSION_WEIGHT_SESSION * 0.5
            elif strictness == "VERY_HIGH":
                score += _PERMISSION_WEIGHT_SESSION * 0.2

        # Psychology caution reduces permission
        if psychology_report:
            if not psychology_report.trade_allowed:
                score *= 0.3  # Drastic reduction if psychology blocks
            elif psychology_report.caution_level > 0.5:
                score *= 1.0 - (psychology_report.caution_level * 0.3)
            if psychology_report.cooldown_active:
                score *= 0.5

        return max(0.0, min(_MAX_PERMISSION_SCORE, score))

    # ------------------------------------------------------------------
    # Score Computation — Conviction Score
    # ------------------------------------------------------------------

    def _compute_conviction_score(
        self,
        confluence_result: ConfluenceResult | None,
        opposite_case: OppositeCase | None,
        market_story: MarketStory | None,
        psychology_report: HeadReport | None,
        session_policy: SessionPolicy | None,
        dt: datetime,
    ) -> float:
        """Compute the conviction score (0-100).

        How confident is Captain in this trade?
        Base from confluence, reduced by opposite case, modified by
        regime clarity, psychology state, and session aggression.

        Args:
            confluence_result: Confluence result.
            opposite_case: Opposite case result.
            market_story: Market story.
            psychology_report: Psychology Head report.
            session_policy: Session policy for aggression modifier.
            dt: Current timestamp.

        Returns:
            Conviction score (0-100).
        """
        score = 0.0

        # Confluence quality — primary driver
        if confluence_result:
            score += _CONVICTION_WEIGHT_CONFLUENCE * confluence_result.confluence_quality

        # Opposite case — reduces conviction
        if opposite_case and opposite_case.exists:
            opposite_impact = opposite_case.strength * _CONVICTION_WEIGHT_OPPOSITE
            score -= opposite_impact

            # Strong opposite case -> extra reduction (>10%)
            if opposite_case.strength >= _STRONG_OPPOSITION_CUTOFF:
                score -= _MAX_CONVICTION_SCORE * _OPPOSITION_REDUCTION_RATE

        # Regime clarity
        if market_story and market_story.regime:
            regime = market_story.regime
            if regime in ("TREND_UP", "TREND_DOWN"):
                score += _CONVICTION_WEIGHT_REGIME
            elif regime in ("WEAK_UP", "WEAK_DOWN"):
                score += _CONVICTION_WEIGHT_REGIME * 0.6
            elif regime == "RANGE":
                score += _CONVICTION_WEIGHT_REGIME * 0.3
            # CHOP and UNCLEAR add nothing

        # Psychology state
        if psychology_report:
            if psychology_report.caution_level > 0.5:
                score -= _CONVICTION_WEIGHT_PSYCHOLOGY * psychology_report.caution_level * 0.5
            if psychology_report.cooldown_active:
                score -= _CONVICTION_WEIGHT_PSYCHOLOGY * 0.5
            if psychology_report.trap_pressure:
                score -= _CONVICTION_WEIGHT_PSYCHOLOGY * 0.3

        # Session aggression modifier
        if session_policy and dt:
            phase = session_policy.get_session_phase(dt)
            modifier = session_policy.get_aggression_modifier(phase)
            score += modifier * _AGGRESSION_IMPACT_FACTOR

        return max(0.0, min(_MAX_CONVICTION_SCORE, score))

    # ------------------------------------------------------------------
    # Score Computation — No-Trade Score
    # ------------------------------------------------------------------

    def _compute_no_trade_score(
        self,
        confluence_result: ConfluenceResult | None,
        opposite_case: OppositeCase | None,
        market_story: MarketStory | None,
        psychology_report: HeadReport | None,
    ) -> float:
        """Compute the no-trade score (0-100).

        How strong is the case for NOT trading right now?
        Driven by opposite case, conflict, psychology concerns,
        and unclear regime.

        Args:
            confluence_result: Confluence result.
            opposite_case: Opposite case result.
            market_story: Market story.
            psychology_report: Psychology Head report.

        Returns:
            No-trade score (0-100).
        """
        score = 0.0

        # Opposite case — strongest no-trade driver
        if opposite_case and opposite_case.exists:
            score += _NOTRADE_WEIGHT_OPPOSITE * opposite_case.strength

        # Confluence conflict
        if confluence_result:
            if confluence_result.conflict_present:
                score += _NOTRADE_WEIGHT_CONFLICT * 0.8
            # Low confluence also contributes
            if confluence_result.confluence_quality < 0.4:
                score += _NOTRADE_WEIGHT_CONFLICT * (1.0 - confluence_result.confluence_quality)

        # Psychology concerns
        if psychology_report:
            if not psychology_report.trade_allowed:
                score += _NOTRADE_WEIGHT_PSYCHOLOGY
            elif psychology_report.caution_level > 0.5:
                score += _NOTRADE_WEIGHT_PSYCHOLOGY * psychology_report.caution_level
            if psychology_report.cooldown_active:
                score += _NOTRADE_WEIGHT_PSYCHOLOGY * 0.5
            if psychology_report.repeated_mistake_flag:
                score += _NOTRADE_WEIGHT_PSYCHOLOGY * 0.4

        # Unclear regime
        if market_story and market_story.regime:
            if market_story.regime in ("CHOP", "UNCLEAR"):
                score += _NOTRADE_WEIGHT_REGIME
            elif market_story.regime == "RANGE":
                score += _NOTRADE_WEIGHT_REGIME * 0.5

        return max(0.0, min(_MAX_NOTRADE_SCORE, score))

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_conviction_summary(
        self,
        scores: ConvictionScore,
    ) -> dict[str, Any]:
        """Get a structured summary of conviction scores for dashboard/logging.

        Args:
            scores: The ConvictionScore from compute_scores().

        Returns:
            Dict with score summary fields.
        """
        band_label = scores.conviction_band.value
        return {
            "permission_score": scores.permission_score,
            "conviction_score": scores.conviction_score,
            "no_trade_score": scores.no_trade_score,
            "conviction_band": band_label,
            "trade_viable": scores.conviction_band
                in (ConvictionBand.TRADABLE, ConvictionBand.STRONG, ConvictionBand.ELITE),
            "needs_confirmation": scores.conviction_band == ConvictionBand.TRADABLE,
            "timestamp": scores.timestamp.isoformat() if scores.timestamp else "",
        }
