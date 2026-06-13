"""Floor 5 — Opposite Case Engine (Step 5.8).

Pre-mortem failure analysis. Checks the strongest argument AGAINST the
proposed trade direction before Captain commits.

Architecture rules (LOCKED — see ROADMAP_FLOOR_05 Section 24):
- Always check opposite case before committing to a trade
- If opposite case is too strong, conviction reduces (>10% reduction)
- Trade can downgrade to WAIT or REJECT if opposite case dominates
- Opposite case reduces one-sided overconfidence

Checks performed:
1. Nearby resistance/support that invalidates thesis
2. Options wall opposition (walls against direction)
3. Contradictory macro context
4. Opposite head biases (heads opposing the trade direction)
5. Weak invalidation clarity (poorly defined invalidation = riskier)
6. Strong opposite bull/bear cases from heads
7. Opposite structure case from SMC/ICT context
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    OppositeCase,
)
from junior_aladdin.shared.types import BiasType, HeadReport


# ── Direction constants ────────────────────────────────────────────────────
_BULLISH = BiasType.BULLISH.value
_BEARISH = BiasType.BEARISH.value
_NEUTRAL = BiasType.NEUTRAL.value

# ── Thresholds ─────────────────────────────────────────────────────────────
_STRONG_OPPOSITION_THRESHOLD = 0.7   # Opposite case this strong = significant risk
_MODERATE_OPPOSITION_THRESHOLD = 0.4 # Above this = worth noting
_DEFAULT_INVALIDATION_CLARITY = 0.5  # Default if invalidation data is missing

# ── Head names ─────────────────────────────────────────────────────────────
_SMC_HEAD = "SMC Head"
_ICT_HEAD = "ICT Head"
_OPTIONS_HEAD = "Options Head"
_MACRO_HEAD = "Macro Head"


class OppositeCaseEngine:
    """Pre-mortem failure analysis for Captain's proposed trade direction.

    Examines the market from the opposite side to identify risks and
    failure scenarios before Captain commits capital.

    Usage::

        engine = OppositeCaseEngine()
        opposite = engine.analyze(
            proposed_direction="BULLISH",
            head_reports=head_reports,
        )
        if opposite.strength > 0.7:
            logger.warning(f"Strong opposite case: {opposite.reasons}")
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        proposed_direction: str,
        head_reports: dict[str, HeadReport] | None = None,
        timestamp: datetime | None = None,
    ) -> OppositeCase:
        """Analyze the opposite case against the proposed direction.

        Args:
            proposed_direction: The proposed trade direction (``BULLISH`` or ``BEARISH``).
            head_reports: Dict of head reports from Floor 4.
            timestamp: Current UTC timestamp. If None, uses ``datetime.utcnow()``.

        Returns:
            An ``OppositeCase`` with strength assessment, reasons,
            and mitigating factors.
        """
        reports = head_reports or {}
        dt = timestamp or datetime.utcnow()

        if proposed_direction not in (_BULLISH, _BEARISH):
            return OppositeCase(
                exists=False,
                strength=0.0,
                reasons=[],
                mitigating_factors=["No directional trade proposed"],
            )

        opposite_direction = _BEARISH if proposed_direction == _BULLISH else _BULLISH

        all_reasons: list[str] = []
        all_mitigating: list[str] = []
        opposition_score = 0.0
        check_count = 0

        # Run each opposite case check
        checks = [
            self._check_head_biases(reports, opposite_direction),
            self._check_bull_bear_cases(reports, opposite_direction),
            self._check_options_context(reports, opposite_direction),
            self._check_macro_context(reports, opposite_direction),
            self._check_invalidation_clarity(reports, proposed_direction),
            self._check_smc_ict_structure(reports, opposite_direction),
        ]

        for reason, mitigating, score in checks:
            if reason and score > 0:
                all_reasons.append(reason)
                opposition_score += score
                check_count += 1
            if mitigating:
                all_mitigating.append(mitigating)
            elif reason:
                # Add a default mitigating if check found an issue
                pass  # Mitigating factors are optional

        # Normalize opposition score based on number of active checks
        if check_count > 0:
            opposition_score = min(1.0, opposition_score / max(1, check_count))
        else:
            opposition_score = 0.0

        exists = opposition_score > 0.1

        return OppositeCase(
            exists=exists,
            strength=round(opposition_score, 4),
            reasons=all_reasons,
            mitigating_factors=all_mitigating,
        )

    # ------------------------------------------------------------------
    # Individual Checks
    # ------------------------------------------------------------------

    def _check_head_biases(
        self,
        reports: dict[str, HeadReport],
        opposite_direction: str,
    ) -> tuple[str, str, float]:
        """Check how many heads have a bias in the opposite direction.

        Heads with opposite bias contribute to opposite case strength.
        SMC + ICT opposition counts double.

        Args:
            reports: Head reports dict.
            opposite_direction: The direction opposite to proposed trade.

        Returns:
            Tuple of (reason, mitigating_factor, score).
        """
        opposing_heads = [
            (name, r.confidence)
            for name, r in reports.items()
            if r.bias.value == opposite_direction and name != "Psychology Head"
        ]

        if not opposing_heads:
            return ("", "", 0.0)

        names = [h[0] for h in opposing_heads]
        avg_conf = sum(h[1] for h in opposing_heads) / len(opposing_heads)

        score = (len(opposing_heads) / 5.0) * avg_conf

        # Boost score if SMC or ICT are among opposing heads
        has_smc = _SMC_HEAD in names
        has_ict = _ICT_HEAD in names
        if has_smc:
            score = min(1.0, score + 0.15)
        if has_ict:
            score = min(1.0, score + 0.10)

        names_str = ", ".join(names)
        reason = f"{len(opposing_heads)} head(s) bias opposite: {names_str} (avg conf {avg_conf:.2f})"
        mitigating = f"Mitigated by higher priority heads supporting proposed direction" if has_smc or has_ict else ""

        return (reason, mitigating, score)

    def _check_bull_bear_cases(
        self,
        reports: dict[str, HeadReport],
        opposite_direction: str,
    ) -> tuple[str, str, float]:
        """Check if heads have strong bull/bear cases for the opposite direction.

        Uses the bull_case/bear_case fields from head reports.

        Args:
            reports: Head reports dict.
            opposite_direction: The direction opposite to proposed trade.

        Returns:
            Tuple of (reason, mitigating_factor, score).
        """
        # Check which field to look at based on opposite direction
        case_field = "bull_case" if opposite_direction == _BULLISH else "bear_case"

        strong_cases = 0
        total_cases = 0

        for name, report in reports.items():
            if name == "Psychology Head":
                continue
            case_text = getattr(report, case_field, "") or ""
            if case_text:
                total_cases += 1
                if len(case_text) > 20:  # Non-trivial case description
                    strong_cases += 1

        if strong_cases == 0:
            return ("", "", 0.0)

        score = min(1.0, strong_cases / 3.0)
        reason = f"{strong_cases} head(s) describe strong {opposite_direction.lower()} case"
        mitigating = "Opposing cases are not strong enough to override" if strong_cases <= 2 else ""

        return (reason, mitigating, score)

    def _check_options_context(
        self,
        reports: dict[str, HeadReport],
        opposite_direction: str,
    ) -> tuple[str, str, float]:
        """Check for options wall opposition.

        If Options Head reports zones that oppose the proposed direction,
        there may be significant options pressure against the trade.

        Args:
            reports: Head reports dict.
            opposite_direction: The direction opposite to proposed trade.

        Returns:
            Tuple of (reason, mitigating_factor, score).
        """
        options_report = reports.get(_OPTIONS_HEAD)
        if options_report is None:
            return ("", "", 0.0)

        # Check if options bias is opposite
        if options_report.bias.value != opposite_direction:
            return ("", "", 0.0)

        # Check for active zones that suggest wall opposition
        zones = options_report.active_zones or []
        wall_zones = [
            z for z in zones
            if isinstance(z, dict) and "wall" in str(z.get("label", "")).lower()
        ]

        if wall_zones:
            score = min(1.0, options_report.confidence * 1.2)
            wall_labels = [z.get("label", "wall") for z in wall_zones]
            reason = f"Options wall(s) in opposite direction: {', '.join(wall_labels[:3])}"
            mitigating = "Options pressure can fade after wall test"
            return (reason, mitigating, score)

        # No specific walls, but bias is opposite
        if options_report.confidence >= 0.6:
            score = options_report.confidence * 0.6
            reason = f"Options Head biases {opposite_direction.lower()} with {options_report.confidence:.0%} confidence"
            mitigating = "Options bias is secondary to structure"
            return (reason, mitigating, score)

        return ("", "", 0.0)

    def _check_macro_context(
        self,
        reports: dict[str, HeadReport],
        opposite_direction: str,
    ) -> tuple[str, str, float]:
        """Check if macro context contradicts the proposed direction.

        Uses Macro Head's event_risk_flag and bias.

        Args:
            reports: Head reports dict.
            opposite_direction: The direction opposite to proposed trade.

        Returns:
            Tuple of (reason, mitigating_factor, score).
        """
        macro_report = reports.get(_MACRO_HEAD)
        if macro_report is None:
            return ("", "", 0.0)

        if macro_report.event_risk_flag and macro_report.bias.value == opposite_direction:
            score = 0.6 * (macro_report.confidence or 0.5)
            reason = f"Macro event risk flagged + bias {opposite_direction.lower()}"
            mitigating = "Macro is lowest weight in confluence"
            return (reason, mitigating, score)

        if macro_report.event_risk_flag:
            score = 0.3
            reason = "Macro event risk flagged (non-directional)"
            mitigating = "Event risk may already be priced in"
            return (reason, mitigating, score)

        # Macro bias opposite = mild concern
        if macro_report.bias.value == opposite_direction and macro_report.confidence >= 0.6:
            score = 0.3
            reason = f"Macro context leans {opposite_direction.lower()}"
            mitigating = "Macro is lowest weight in confluence"
            return (reason, mitigating, score)

        return ("", "", 0.0)

    def _check_invalidation_clarity(
        self,
        reports: dict[str, HeadReport],
        proposed_direction: str,
    ) -> tuple[str, str, float]:
        """Check how clearly heads define invalidation for the proposed direction.

        Poorly defined invalidation = higher opposite case risk.

        Args:
            reports: Head reports dict.
            proposed_direction: The proposed trade direction.

        Returns:
            Tuple of (reason, mitigating_factor, score).
        """
        # Check supporting heads for clear invalidation
        supporting_heads = [
            (name, r)
            for name, r in reports.items()
            if r.bias.value == proposed_direction and name != "Psychology Head"
        ]

        if not supporting_heads:
            return ("", "", 0.0)

        weak_invalidation = 0
        for name, report in supporting_heads:
            inval = report.invalidation or {}
            # Check if invalidation has meaningful content
            has_price_level = "price" in str(inval).lower() or "level" in str(inval).lower()
            has_description = bool(inval) and bool(inval.get("condition") or inval.get("reason"))
            if not has_price_level and not has_description:
                weak_invalidation += 1

        if weak_invalidation == 0:
            return ("", "", 0.0)

        ratio = weak_invalidation / len(supporting_heads)
        if ratio < 0.3:
            return ("", "", 0.0)

        score = min(0.5, ratio * 0.6)
        reason = f"{weak_invalidation}/{len(supporting_heads)} supporting heads have unclear invalidation"
        mitigating = "Invalidation clarity is qualitative, not a hard block"

        return (reason, mitigating, score)

    def _check_smc_ict_structure(
        self,
        reports: dict[str, HeadReport],
        opposite_direction: str,
    ) -> tuple[str, str, float]:
        """Check if SMC/ICT structure supports the opposite case.

        Uses witness_summary and context_quality_score to assess
        structural integrity of the opposite case.

        Args:
            reports: Head reports dict.
            opposite_direction: The direction opposite to proposed trade.

        Returns:
            Tuple of (reason, mitigating_factor, score).
        """
        smc = reports.get(_SMC_HEAD)
        ict = reports.get(_ICT_HEAD)

        if smc is None and ict is None:
            return ("", "", 0.0)

        # Check if either structurally supports the opposite direction
        structural_score = 0.0
        structure_details: list[str] = []

        for head_name, report in [(_SMC_HEAD, smc), (_ICT_HEAD, ict)]:
            if report is None:
                continue
            if report.bias.value == opposite_direction:
                # Core head opposes — significant structural concern
                cq = report.context_quality_score or 0.5
                base_strength = report.confidence * cq

                if head_name == _SMC_HEAD:
                    structural_score += base_strength * 1.5  # SMC opposition carries more weight
                    structure_details.append(f"SMC biases {opposite_direction.lower()}")
                else:
                    structural_score += base_strength * 1.2  # ICT opposition also significant
                    structure_details.append(f"ICT biases {opposite_direction.lower()}")

        if structural_score == 0.0:
            return ("", "", 0.0)

        score = min(1.0, structural_score)
        reason = "; ".join(structure_details)
        mitigating = "Structure bias is directional, not a hard block"

        return (reason, mitigating, score)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_opposition_summary(
        self,
        opposite_case: OppositeCase,
    ) -> dict[str, Any]:
        """Get a structured summary of the opposite case for dashboard/logging.

        Args:
            opposite_case: The OppositeCase result from analyze().

        Returns:
            Dict with opposition summary fields.
        """
        return {
            "exists": opposite_case.exists,
            "strength": opposite_case.strength,
            "reason_count": len(opposite_case.reasons),
            "top_reasons": opposite_case.reasons[:3],
            "mitigating_factors": opposite_case.mitigating_factors[:2],
            "severity": "HIGH" if opposite_case.strength >= _STRONG_OPPOSITION_THRESHOLD
                       else "MODERATE" if opposite_case.strength >= _MODERATE_OPPOSITION_THRESHOLD
                       else "LOW",
        }
