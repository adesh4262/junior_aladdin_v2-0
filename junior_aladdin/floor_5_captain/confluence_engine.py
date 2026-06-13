"""Floor 5 — Confluence Engine (Step 5.7).

Combines directional head reports with weighted alignment logic to determine
the strength and direction of expert consensus.

Locked architecture rules (see ROADMAP_FLOOR_05 Section 7):
- Head priority: SMC > ICT > Technical > Options > Macro
- NOT simple democracy — SMC + ICT opposing = stronger veto
- Minimum meaningful alignment: ~60% OR 3 of 5 heads
- Trust weighting depends on: head type, head state, freshness,
  context quality (SMC/ICT), invalidation clarity
- Captain owns CONVICTION, NOT confidence (confidence = Floor 4)
- This module consumes confidence from Floor 4 — it does NOT recalculate it
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ReportTrustTier,
)
from junior_aladdin.shared.types import (
    BiasType,
    FreshnessTag,
    HeadReport,
    HeadState,
)


# ── Head priority weights (LOCKED — ROADMAP_FLOOR_05 Section 7) ────────────
# Base weight reflects each head's importance in structural analysis.
# These are multiplied by state/freshness/quality modifiers.
_HEAD_PRIORITY: dict[str, float] = {
    "SMC Head": 1.0,              # Highest — structural truth
    "ICT Head": 0.9,              # Next — institutional context
    "Technical Head": 0.7,        # Support / confirmation
    "Options Head": 0.6,          # Derivatives confirmation
    "Macro Head": 0.4,            # Light context gate — lowest directional weight
}

# ── Head state modifiers ───────────────────────────────────────────────────
_STATE_MODIFIERS: dict[HeadState, float] = {
    HeadState.READY: 1.0,
    HeadState.UNCERTAIN: 0.6,
    HeadState.STALE: 0.3,
}

# ── Freshness modifiers ────────────────────────────────────────────────────
_FRESHNESS_MODIFIERS: dict[FreshnessTag, float] = {
    FreshnessTag.FRESH: 1.0,
    FreshnessTag.WARM: 0.75,
    FreshnessTag.STALE: 0.4,
}

# ── Context quality modifiers (SMC/ICT only) ───────────────────────────────
_CONTEXT_QUALITY_MODIFIER_HIGH = 1.0
_CONTEXT_QUALITY_MODIFIER_MEDIUM = 0.8
_CONTEXT_QUALITY_MODIFIER_LOW = 0.5

# ── Alignment thresholds ───────────────────────────────────────────────────
_MIN_CONFLUENCE_QUALITY = 0.6     # ~60% minimum for meaningful alignment
_MIN_ALIGNED_HEADS = 3            # At least 3 of 5 heads aligned
_VETO_ALIGNMENT_QUALITY = 0.7     # SMC + ICT opposing at this quality = veto

# ── Direction constants ────────────────────────────────────────────────────
_BULLISH = BiasType.BULLISH.value
_BEARISH = BiasType.BEARISH.value
_NEUTRAL = BiasType.NEUTRAL.value


class ConfluenceEngine:
    """Computes weighted head alignment from Floor 4 directional head reports.

    Produces a ``ConfluenceResult`` that tells Captain how strongly the
    expert heads agree on market direction.

    Usage::

        engine = ConfluenceEngine()
        result = engine.compute_confluence(
            head_reports=head_reports_dict,
            timestamp=datetime.utcnow(),
        )
        if result.confluence_quality >= 0.6 and not result.conflict_present:
            logger.info(f"Strong {result.dominant_direction} confluence")
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_confluence(
        self,
        head_reports: dict[str, HeadReport] | None = None,
        timestamp: datetime | None = None,
    ) -> ConfluenceResult:
        """Compute weighted confluence from directional head reports.

        Args:
            head_reports: Dict mapping head_name → HeadReport.
                Only directional heads (SMC, ICT, Technical, Options, Macro)
                are considered. Psychology Head is skipped.
            timestamp: Current UTC timestamp. If None, uses ``datetime.utcnow()``.

        Returns:
            A fully populated ``ConfluenceResult``.
        """
        dt = timestamp or datetime.utcnow()
        reports = head_reports or {}

        # Get directional heads only (skip Psychology)
        directional = self._get_directional_reports(reports)
        if not directional:
            return ConfluenceResult(
                confluence_quality=0.0,
                conflict_present=False,
                dominant_direction=_NEUTRAL,
                weighting_summary={},
                timestamp=dt,
            )

        # Compute trust-weighted scores per head
        weighted_results: list[dict[str, Any]] = []
        total_weight = 0.0

        for head_name, report in directional.items():
            trust_weight = self._compute_trust_weight(head_name, report)
            weighted_results.append({
                "head_name": head_name,
                "bias": report.bias.value,
                "confidence": report.confidence,
                "trust_weight": trust_weight,
                "state": report.state.value,
                "freshness_tag": report.freshness_tag.value,
            })
            total_weight += trust_weight

        # Compute directional alignment
        bullish_weight = sum(
            r["trust_weight"] * r["confidence"]
            for r in weighted_results
            if r["bias"] == _BULLISH
        )
        bearish_weight = sum(
            r["trust_weight"] * r["confidence"]
            for r in weighted_results
            if r["bias"] == _BEARISH
        )
        neutral_weight = sum(
            r["trust_weight"] * r["confidence"]
            for r in weighted_results
            if r["bias"] == _NEUTRAL
        )

        # Determine dominant direction
        max_direction = max(
            (bullish_weight, _BULLISH),
            (bearish_weight, _BEARISH),
            (neutral_weight, _NEUTRAL),
        )
        dominant_direction = max_direction[1]
        max_score = max_direction[0]

        # Compute confluence quality — ratio of max direction weight to total
        total_directional_weight = bullish_weight + bearish_weight + neutral_weight
        confluence_quality = max_score / total_directional_weight if total_directional_weight > 0 else 0.0

        # Build aligned/opposing lists
        aligned = [
            r["head_name"] for r in weighted_results
            if r["bias"] == dominant_direction
        ]
        opposing = [
            r["head_name"] for r in weighted_results
            if r["bias"] != dominant_direction and r["bias"] != _NEUTRAL
        ]

        # Check for conflict — opposing heads with meaningful weight
        conflict_present = self._detect_conflict(
            weighted_results=weighted_results,
            dominant_direction=dominant_direction,
            confluence_quality=confluence_quality,
        )

        # Build weighting summary for the result
        weighting_summary: dict[str, float] = {
            r["head_name"]: round(r["trust_weight"], 3) for r in weighted_results
        }

        return ConfluenceResult(
            confluence_quality=round(confluence_quality, 4),
            conflict_present=conflict_present,
            aligned_heads=aligned,
            opposing_heads=opposing,
            dominant_direction=dominant_direction,
            weighting_summary=weighting_summary,
            timestamp=dt,
        )

    # ------------------------------------------------------------------
    # Trust Weight Computation
    # ------------------------------------------------------------------

    def _compute_trust_weight(
        self,
        head_name: str,
        report: HeadReport,
    ) -> float:
        """Compute the effective trust weight for a single head report.

        Trust weight = base_priority * state_modifier * freshness_modifier
                      * context_quality_modifier (SMC/ICT only)

        All modifiers are clamped to [0.0, 1.0].

        Args:
            head_name: Name of the head (e.g., ``SMC Head``).
            report: The head's report with state, freshness, and context data.

        Returns:
            Effective trust weight (0.0–1.0).
        """
        base = _HEAD_PRIORITY.get(head_name, 0.5)

        state_mod = _STATE_MODIFIERS.get(report.state, 0.5)
        fresh_mod = _FRESHNESS_MODIFIERS.get(report.freshness_tag, 0.5)

        weight = base * state_mod * fresh_mod

        # Apply context quality modifier for SMC/ICT heads
        if head_name in ("SMC Head", "ICT Head"):
            cq_mod = self._get_context_quality_modifier(report.context_quality_score)
            weight *= cq_mod

        return max(0.0, min(1.0, weight))

    @staticmethod
    def _get_context_quality_modifier(score: float | None) -> float:
        """Convert a context quality score to a modifier.

        Args:
            score: Context quality score (0.0-1.0) or None.

        Returns:
            Modifier between 0.5 and 1.0.
        """
        if score is None:
            return 0.8  # Default to medium if not provided
        if score >= 0.8:
            return _CONTEXT_QUALITY_MODIFIER_HIGH
        elif score >= 0.5:
            return _CONTEXT_QUALITY_MODIFIER_MEDIUM
        return _CONTEXT_QUALITY_MODIFIER_LOW

    # ------------------------------------------------------------------
    # Conflict Detection
    # ------------------------------------------------------------------

    def _detect_conflict(
        self,
        weighted_results: list[dict[str, Any]],
        dominant_direction: str,
        confluence_quality: float,
    ) -> bool:
        """Detect meaningful conflict among heads.

        Conflict is present when:
        1. Heads disagree on direction (both bullish and bearish with non-trivial weight)
        2. SMC + ICT both oppose the dominant direction (veto condition)
        3. Confluence quality is below minimum threshold but opposing weight exists

        Args:
            weighted_results: List of weighted head results.
            dominant_direction: The computed dominant direction.
            confluence_quality: The computed confluence quality.

        Returns:
            True if meaningful conflict is detected.
        """
        if len(weighted_results) < 2:
            return False

        # Check if there are opposing directional biases with meaningful weight
        bullish_heads = [r for r in weighted_results if r["bias"] == _BULLISH]
        bearish_heads = [r for r in weighted_results if r["bias"] == _BEARISH]

        has_both_directions = len(bullish_heads) > 0 and len(bearish_heads) > 0
        if not has_both_directions:
            return False

        # Veto check: do SMC + ICT both oppose the dominant direction?
        smc_opposes = any(
            r["head_name"] == "SMC Head" and r["bias"] != dominant_direction and r["bias"] != _NEUTRAL
            for r in weighted_results
        )
        ict_opposes = any(
            r["head_name"] == "ICT Head" and r["bias"] != dominant_direction and r["bias"] != _NEUTRAL
            for r in weighted_results
        )

        if smc_opposes and ict_opposes and confluence_quality < _VETO_ALIGNMENT_QUALITY:
            return True  # Core heads strongly oppose — veto condition

        # General conflict: both directions present and quality below threshold
        if confluence_quality < _MIN_CONFLUENCE_QUALITY:
            return True

        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_directional_reports(
        head_reports: dict[str, HeadReport],
    ) -> dict[str, HeadReport]:
        """Filter to directional heads only, excluding Psychology Head.

        Args:
            head_reports: All available head reports.

        Returns:
            Dict of directional head reports only.
        """
        return {
            name: report
            for name, report in head_reports.items()
            if name != "Psychology Head"
        }

    @staticmethod
    def get_head_trust_tier(head_name: str, report: HeadReport) -> ReportTrustTier:
        """Determine the trust tier for a head report.

        Utility method usable by other modules (e.g., captain_engine)
        for quick trust assessment.

        Args:
            head_name: Name of the head.
            report: The head's report.

        Returns:
            ``FULL``, ``REDUCED``, or ``MINIMAL`` trust tier.
        """
        if report.state == HeadState.STALE:
            if head_name in ("SMC Head", "ICT Head"):
                return ReportTrustTier.MINIMAL
            return ReportTrustTier.REDUCED

        if report.state == HeadState.UNCERTAIN:
            return ReportTrustTier.REDUCED

        if report.freshness_tag == FreshnessTag.STALE:
            return ReportTrustTier.REDUCED

        return ReportTrustTier.FULL
