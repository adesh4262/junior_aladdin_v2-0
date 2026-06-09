"""Floor 4 — Floor Summary Builder.

Aggregates all 6 Department Head reports into a single FloorSummary
for Captain consumption (summary-first workflow).

Captain reads this FIRST, then drills down into individual reports if needed.

Architecture rules (LOCKED):
- Summary compresses state, never replaces individual reports.
- Conflict detected honestly — no forced consensus.
- Stale/uncertain states propagated transparently.
- No-setup intelligence preserved via setup_absence_context.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import (
    BiasType,
    DataHealth,
    FloorSummary,
    HeadReport,
    HeadState,
)

logger = get_logger("floor_summary_builder")

# ── All recognized head names (ordered for deterministic output) ────────────

_HEAD_ORDER = [
    "SMC Head",
    "ICT Head",
    "Technical Head",
    "Options Head",
    "Macro Head",
    "Psychology Head",
]

# Heads that produce directional bias
_DIRECTIONAL_HEADS = {"SMC Head", "ICT Head", "Technical Head", "Options Head"}

# Heads that produce setups
_SETUP_HEADS = {"SMC Head", "ICT Head", "Technical Head", "Options Head"}

# Heads in core_head_health_snapshot (per Section 29)
_CORE_HEADS = {"SMC Head", "ICT Head", "Technical Head", "Macro Head", "Psychology Head"}


# =============================================================================
# Floor Summary Builder
# =============================================================================


class FloorSummaryBuilder:
    """Aggregates HeadReports into a FloorSummary for Captain.

    Usage::

        builder = FloorSummaryBuilder()
        reports = {
            "SMC Head": smc_report,
            "ICT Head": ict_report,
            ...
        }
        summary = builder.build(reports)
        # Captain reads summary.summary_witness_lines first
    """

    def build(
        self,
        reports: dict[str, HeadReport],
        timestamp: datetime | None = None,
    ) -> FloorSummary:
        """Build a FloorSummary from all head reports.

        Args:
            reports: Dict mapping ``head_name`` → ``HeadReport``.
                Must include all 6 heads for a complete summary.
            timestamp: Summary timestamp. Uses ``datetime.utcnow()`` if None.

        Returns:
            A fully populated ``FloorSummary`` ready for Captain.
        """
        now = timestamp or datetime.utcnow()

        # ── Count states ────────────────────────────────────────────
        ready_count = sum(
            1 for r in reports.values() if r.state == HeadState.READY
        )
        uncertain_count = sum(
            1 for r in reports.values() if r.state == HeadState.UNCERTAIN
        )
        stale_count = sum(
            1 for r in reports.values() if r.state == HeadState.STALE
        )

        # ── Bias snapshot ───────────────────────────────────────────
        bias_snapshot = self._build_bias_snapshot(reports)

        # ── Confidence snapshot ─────────────────────────────────────
        confidence_snapshot = self._build_confidence_snapshot(reports)

        # ── Setups ──────────────────────────────────────────────────
        primary_setups = self._build_primary_setups(reports)
        backup_setups = self._build_backup_setups(reports)
        active_setup_count = sum(1 for s in primary_setups.values() if s is not None)

        # ── Conflict detection ──────────────────────────────────────
        conflict_present = self._detect_conflict(reports)

        # ── Stale warning ───────────────────────────────────────────
        stale_warning_present = stale_count > 0

        # ── Strongest signals ───────────────────────────────────────
        strongest_domain = self._find_strongest_domain_signal(reports)
        strongest_context = self._find_strongest_context_signal(reports)
        strongest_risk = self._find_strongest_risk_warning(reports)

        # ── Data health ─────────────────────────────────────────────
        data_health = self._compute_data_health(reports)

        # ── Health snapshots ────────────────────────────────────────
        head_health = self._build_head_health_snapshot(reports)
        core_health = {
            name: head_health[name]
            for name in _CORE_HEADS
            if name in head_health
        }

        # ── Setup presence / absence context ────────────────────────
        setup_presence, setup_absence_context = self._compute_setup_context(
            reports, active_setup_count,
        )

        # ── Witness lines ───────────────────────────────────────────
        witness_lines = self._build_witness_lines(
            reports=reports,
            ready_count=ready_count,
            uncertain_count=uncertain_count,
            stale_count=stale_count,
            active_setup_count=active_setup_count,
            conflict_present=conflict_present,
            stale_warning_present=stale_warning_present,
        )

        return FloorSummary(
            summary_timestamp=now,
            floor_bias_snapshot=bias_snapshot,
            floor_confidence_snapshot=confidence_snapshot,
            active_setup_count=active_setup_count,
            primary_setups_by_head=primary_setups,
            backup_setups_by_head=backup_setups,
            ready_heads_count=ready_count,
            uncertain_heads_count=uncertain_count,
            stale_heads_count=stale_count,
            conflict_present=conflict_present,
            stale_warning_present=stale_warning_present,
            strongest_domain_signal=strongest_domain,
            strongest_context_signal=strongest_context,
            strongest_risk_warning=strongest_risk,
            data_health_signal=data_health,
            summary_witness_lines=witness_lines,
            core_head_health_snapshot=core_health,
            head_health_snapshot=head_health,
            setup_presence=setup_presence,
            setup_absence_context=setup_absence_context,
        )

    # ── Private Builders ────────────────────────────────────────────────

    def _build_bias_snapshot(
        self,
        reports: dict[str, HeadReport],
    ) -> dict[str, Any]:
        """Build a compact bias overview from all heads.

        Returns a dict with:
        - ``head_biases``: per-head bias map
        - ``bullish_count``: number of heads with BULLISH bias
        - ``bearish_count``: number of heads with BEARISH bias
        - ``neutral_count``: number of heads with NEUTRAL bias
        - ``dominant_floor_bias``: overall floor bias direction
        """
        head_biases: dict[str, str] = {}
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        for name in _HEAD_ORDER:
            report = reports.get(name)
            if report is None:
                continue
            bias_str = report.bias.value if report.bias else "NEUTRAL"
            head_biases[name] = bias_str
            if bias_str == "BULLISH":
                bullish_count += 1
            elif bias_str == "BEARISH":
                bearish_count += 1
            else:
                neutral_count += 1

        dominant = "NEUTRAL"
        if bullish_count > bearish_count and bullish_count > neutral_count:
            dominant = "BULLISH"
        elif bearish_count > bullish_count and bearish_count > neutral_count:
            dominant = "BEARISH"

        return {
            "head_biases": head_biases,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "dominant_floor_bias": dominant,
        }

    def _build_confidence_snapshot(
        self,
        reports: dict[str, HeadReport],
    ) -> dict[str, Any]:
        """Build a compact confidence overview from all heads.

        Returns a dict with:
        - ``head_confidences``: per-head confidence map
        - ``average_confidence``: mean confidence across all heads
        - ``highest_confidence_head``: head with max confidence
        - ``lowest_confidence_head``: head with min confidence
        """
        head_confidences: dict[str, float] = {}
        total = 0.0
        count = 0
        highest: tuple[str, float] = ("", -1.0)
        lowest: tuple[str, float] = ("", 2.0)

        for name in _HEAD_ORDER:
            report = reports.get(name)
            if report is None:
                continue
            conf = report.confidence
            head_confidences[name] = conf
            total += conf
            count += 1

            if conf > highest[1]:
                highest = (name, conf)
            if conf < lowest[1]:
                lowest = (name, conf)

        avg = total / max(count, 1)

        return {
            "head_confidences": head_confidences,
            "average_confidence": round(avg, 3),
            "highest_confidence_head": highest[0] if highest[0] else "",
            "lowest_confidence_head": lowest[0] if lowest[0] else "",
        }

    def _build_primary_setups(
        self,
        reports: dict[str, HeadReport],
    ) -> dict[str, str | None]:
        """Extract primary_setup from each head."""
        result: dict[str, str | None] = {}
        for name in _HEAD_ORDER:
            report = reports.get(name)
            result[name] = report.primary_setup if report else None
        return result

    def _build_backup_setups(
        self,
        reports: dict[str, HeadReport],
    ) -> dict[str, str | None]:
        """Extract backup_setup from each head."""
        result: dict[str, str | None] = {}
        for name in _HEAD_ORDER:
            report = reports.get(name)
            result[name] = report.backup_setup if report else None
        return result

    def _detect_conflict(
        self,
        reports: dict[str, HeadReport],
    ) -> bool:
        """Detect if directional heads disagree (both BULLISH and BEARISH).

        Returns:
            True if at least one head is BULLISH and one is BEARISH
            among directional heads.
        """
        has_bullish = False
        has_bearish = False

        for name in _HEAD_ORDER:
            if name not in _DIRECTIONAL_HEADS:
                continue
            report = reports.get(name)
            if report is None:
                continue
            if report.bias == BiasType.BULLISH:
                has_bullish = True
            elif report.bias == BiasType.BEARISH:
                has_bearish = True

        return has_bullish and has_bearish

    def _find_strongest_domain_signal(
        self,
        reports: dict[str, HeadReport],
    ) -> str:
        """Find the strongest domain (directional) signal.

        Looks at directional heads and picks the one with
        highest confidence, preferring those with setups.
        """
        best_name = ""
        best_score = -1.0

        for name in _HEAD_ORDER:
            if name not in _DIRECTIONAL_HEADS:
                continue
            report = reports.get(name)
            if report is None:
                continue

            # Score = confidence + bonus for having a setup
            score = report.confidence
            if report.primary_setup is not None:
                score += 0.3

            if score > best_score:
                best_score = score
                best_name = name

        if not best_name:
            return "No strong domain signal"

        report = reports.get(best_name)
        setup_str = f" ({report.primary_setup})" if report and report.primary_setup else ""
        return f"{best_name}{setup_str}"

    def _find_strongest_context_signal(
        self,
        reports: dict[str, HeadReport],
    ) -> str:
        """Find the strongest context/background signal.

        Looks at Macro and Psychology heads for context.
        """
        parts: list[str] = []

        macro = reports.get("Macro Head")
        if macro:
            caution = getattr(macro, "caution_level", 0.0)
            event_risk = getattr(macro, "event_risk_flag", False)
            if caution > 0.5:
                parts.append(f"Macro caution: {caution:.2f}")
            if event_risk:
                parts.append("Event risk active")
            elif caution <= 0.3:
                parts.append("Macro environment calm")

        psych = reports.get("Psychology Head")
        if psych:
            trade_allowed = getattr(psych, "trade_allowed", True)
            block_reason = getattr(psych, "block_reason", "")
            if not trade_allowed:
                parts.append(f"Psychology block: {block_reason}")
            elif getattr(psych, "cooldown_active", False):
                parts.append("Cooldown active")
            elif getattr(psych, "repeated_mistake_flag", False):
                parts.append("Repeated mistakes detected")

        return "; ".join(parts) if parts else "No significant context signals"

    def _find_strongest_risk_warning(
        self,
        reports: dict[str, HeadReport],
    ) -> str:
        """Find the strongest risk warning across all heads.

        Considers stale heads, blocked psychology, high macro caution,
        and low context_quality_score in SMC/ICT.
        """
        warnings: list[tuple[float, str]] = []

        for name, report in reports.items():
            if report is None:
                continue

            # Stale heads
            if report.state == HeadState.STALE:
                warnings.append((0.7, f"{name} is STALE"))

            # Psychology block
            if name == "Psychology Head":
                if not getattr(report, "trade_allowed", True):
                    reason = getattr(report, "block_reason", "blocked")
                    warnings.append((0.9, f"Trading blocked: {reason}"))
                elif getattr(report, "cooldown_active", False):
                    warnings.append((0.6, "Cooldown active — trading paused"))

            # Macro caution
            if name == "Macro Head":
                caution = getattr(report, "caution_level", 0.0)
                if caution > 0.7:
                    warnings.append((0.8, f"Macro caution elevated ({caution:.2f})"))
                elif caution > 0.5:
                    warnings.append((0.5, f"Macro caution moderate ({caution:.2f})"))

            # Low context quality in SMC/ICT
            if name in ("SMC Head", "ICT Head"):
                cqs = getattr(report, "context_quality_score", None)
                if cqs is not None and cqs < 0.3:
                    warnings.append((0.6, f"{name} context quality low ({cqs:.2f})"))

        # Return the highest severity warning
        warnings.sort(key=lambda w: w[0], reverse=True)
        return warnings[0][1] if warnings else "No significant warnings"

    def _compute_data_health(
        self,
        reports: dict[str, HeadReport],
    ) -> DataHealth:
        """Compute aggregate data health from all head reports.

        Returns:
            DataHealth.GOOD if no issues.
            DataHealth.CAUTION if any head is STALE or uncertain.
            DataHealth.DEGRADED if multiple heads are STALE.
            DataHealth.CRITICAL if most heads are STALE or unavailable.
        """
        total = len(reports)
        if total == 0:
            return DataHealth.CRITICAL

        stale_count = sum(1 for r in reports.values() if r.state == HeadState.STALE)
        uncertain_count = sum(1 for r in reports.values() if r.state == HeadState.UNCERTAIN)

        if stale_count >= total * 0.5:
            return DataHealth.CRITICAL
        if stale_count >= total * 0.3:
            return DataHealth.DEGRADED
        if stale_count > 0 or uncertain_count > 1:
            return DataHealth.CAUTION
        return DataHealth.GOOD

    def _build_head_health_snapshot(
        self,
        reports: dict[str, HeadReport],
    ) -> dict[str, dict[str, str]]:
        """Build per-head health snapshot with state and freshness.

        Returns a dict: ``head_name → {"state": ..., "freshness_tag": ...}``
        """
        snapshot: dict[str, dict[str, str]] = {}

        for name in _HEAD_ORDER:
            report = reports.get(name)
            if report is None:
                snapshot[name] = {"state": "STALE", "freshness_tag": "STALE"}
            else:
                snapshot[name] = {
                    "state": report.state.value if report.state else "STALE",
                    "freshness_tag": report.freshness_tag.value if report.freshness_tag else "STALE",
                }

        return snapshot

    def _compute_setup_context(
        self,
        reports: dict[str, HeadReport],
        active_setup_count: int,
    ) -> tuple[str | None, str | None]:
        """Compute setup presence/absence context.

        Returns:
            Tuple of (setup_presence, setup_absence_context).
            - setup_presence: "HAS_SETUP" if any setup active, "NO_SETUP" otherwise
            - setup_absence_context: NO_SETUP quality ("READY_NO_SETUP" / etc.)
        """
        if active_setup_count > 0:
            return "HAS_SETUP", None

        # NO_SETUP — determine context quality
        # Check if any setup-capable head is in degraded state
        worst_state = HeadState.READY
        for name in _SETUP_HEADS:
            report = reports.get(name)
            if report is None:
                continue
            if report.state == HeadState.STALE:
                worst_state = HeadState.STALE
            elif report.state == HeadState.UNCERTAIN and worst_state != HeadState.STALE:
                worst_state = HeadState.UNCERTAIN

        if worst_state == HeadState.STALE:
            return "NO_SETUP", "STALE_NO_SETUP"
        elif worst_state == HeadState.UNCERTAIN:
            return "NO_SETUP", "UNCERTAIN_NO_SETUP"
        return "NO_SETUP", "READY_NO_SETUP"

    def _build_witness_lines(
        self,
        reports: dict[str, HeadReport],
        ready_count: int,
        uncertain_count: int,
        stale_count: int,
        active_setup_count: int,
        conflict_present: bool,
        stale_warning_present: bool,
    ) -> list[str]:
        """Build compact witness-style summary lines.

        Returns:
            A short list of human-readable summary points.
        """
        lines: list[str] = []

        # Total heads tracked
        total = len(reports)
        lines.append(
            f"Floor state: {ready_count}/{total} ready, "
            f"{uncertain_count} uncertain, {stale_count} stale"
        )

        # Setups
        if active_setup_count > 0:
            lines.append(f"{active_setup_count} active setup(s) across directional heads")

        # Bias snapshot
        bias_info = self._build_bias_snapshot(reports)
        dominant = bias_info.get("dominant_floor_bias", "NEUTRAL")
        lines.append(
            f"Floor bias: {dominant} "
            f"({bias_info['bullish_count']}B/{bias_info['bearish_count']}S/"
            f"{bias_info['neutral_count']}N)"
        )

        # Conflict
        if conflict_present:
            lines.append("⚠ Conflict detected — directional heads disagree")

        # Stale warning
        if stale_warning_present:
            stale_names = [
                name for name, r in reports.items()
                if r and r.state == HeadState.STALE
            ]
            lines.append(f"⚠ Stale heads: {', '.join(stale_names)}")

        # Psychology block
        psych = reports.get("Psychology Head")
        if psych and not getattr(psych, "trade_allowed", True):
            reason = getattr(psych, "block_reason", "blocked")
            lines.append(f"🛑 Psychology block active: {reason}")

        # Highest confidence directional head
        conf_snapshot = self._build_confidence_snapshot(reports)
        if conf_snapshot["highest_confidence_head"]:
            best = conf_snapshot["highest_confidence_head"]
            best_report = reports.get(best)
            if best_report:
                lines.append(
                    f"Strongest: {best} "
                    f"(confidence: {best_report.confidence:.2f})"
                )

        return lines
