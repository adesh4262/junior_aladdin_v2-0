"""Floor 4 — SMC Department Head.

Consumes Floor 3 SMC signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- MARKET_STRUCTURE: structure type, swing counts, trend direction
- FVG: fvg_type, top, bottom, gap_size, mitigated
- ORDER_BLOCK: ob_type, price, strength
- CHOCH: choch_type, break_price, confirmed

Output (HeadReport):
- bias (BULLISH/BEARISH/NEUTRAL)
- confidence (0.0–1.0)
- context_quality_score (0.0–1.0) — MANDATORY for SMC
- primary_setup + backup_setup
- active_zones with status
- armed_triggers
- invalidation rules
- witness_summary (2-3 points)

Architecture rules (LOCKED):
- Interprets Floor 3 signals, never recomputes them.
- context_quality_score is mandatory.
- invalidation is mandatory.
- Setup Exists ≠ Good Setup — context_quality_score reflects this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
)
from junior_aladdin.floor_4_heads.head_base import BaseHead
from junior_aladdin.floor_4_heads.head_types import (
    InvalidationRule,
    compute_bias_from_signals,
    compute_confidence,
)
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import BiasType

logger = get_logger("smc_head")

# ── Setup templates ─────────────────────────────────────────────────────────

_FVG_RETEST = "FVG Retest"
_LIQUIDITY_SWEEP_RECLAIM = "Liquidity Sweep Reclaim"
_ORDER_BLOCK_BOUNCE = "Order Block Bounce"
_CHOCH_CONTINUATION = "Structure Break Continuation"
_BOS_CONTINUATION = "BOS Continuation"


class SMCHead(BaseHead):
    """SMC Head — interprets smart-money structure from Floor 3 SMC signals.

    Args:
        name: Optional name override (default ``\"smc\"``).
        config: Optional dict with tuning parameters (confidence weights, etc.).
    """

    def __init__(
        self,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or "smc")
        self._config = config or {}

    @property
    def head_name(self) -> str:
        return "SMC Head"

    # ── Signal Extraction ───────────────────────────────────────────────

    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[CalculatedSignal]:
        """Extract SMC-domain signals from the OutputContract.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            Only signals where ``domain == CalculationDomain.SMC``.
        """
        return [
            s for s in output_contract.signals
            if s.domain == CalculationDomain.SMC
        ]

    # ── Core Interpretation ─────────────────────────────────────────────

    def _interpret(
        self,
        signals: list[CalculatedSignal],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Interpret SMC signals and produce Head interpretation.

        Analyzes market structure, FVGs, order blocks, and CHOCHs to
        determine bias, confidence, setups, zones, and invalidation.

        Args:
            signals: SMC-domain CalculatedSignal list.
            output_contract: Full OutputContract for context.
            current_time: Current timestamp.

        Returns:
            Interpretation dict with all HeadReport fields.
        """
        if not signals:
            return self._empty_interpretation()

        # ── Categorise signals ──────────────────────────────────────
        structure_sigs = [s for s in signals if s.indicator_type == "MARKET_STRUCTURE"]
        fvg_sigs = [s for s in signals if s.indicator_type == "FVG"]
        ob_sigs = [s for s in signals if s.indicator_type == "ORDER_BLOCK"]
        choch_sigs = [s for s in signals if s.indicator_type == "CHOCH"]

        # ── Structure Analysis ──────────────────────────────────────
        structure_type = ""
        structure_valid = False
        bullish_swing_count = 0
        bearish_swing_count = 0

        if structure_sigs:
            ms = structure_sigs[-1].value  # Latest signal
            structure_type = ms.get("structure_type", "")
            structure_valid = ms.get("structure_valid", False)
            bullish_swing_count = ms.get("swing_high_count", 0)
            bearish_swing_count = ms.get("swing_low_count", 0)

        is_bullish_structure = structure_type in ("BULLISH_HH_HL", "BREAKOUT") and structure_valid
        is_bearish_structure = structure_type == "BEARISH_LH_LL" and structure_valid

        # ── FVG Analysis ────────────────────────────────────────────
        bullish_fvgs = [s for s in fvg_sigs if s.value.get("fvg_type") == "BULLISH_FVG"]
        bearish_fvgs = [s for s in fvg_sigs if s.value.get("fvg_type") == "BEARISH_FVG"]
        active_bullish_fvgs = [s for s in bullish_fvgs if not s.value.get("mitigated", True)]
        active_bearish_fvgs = [s for s in bearish_fvgs if not s.value.get("mitigated", True)]

        # ── Order Block Analysis ────────────────────────────────────
        bullish_obs = [s for s in ob_sigs if s.value.get("ob_type") == "BULLISH_OB"]
        bearish_obs = [s for s in ob_sigs if s.value.get("ob_type") == "BEARISH_OB"]

        # ── CHOCH Analysis ──────────────────────────────────────────
        bullish_chochs = [s for s in choch_sigs if s.value.get("choch_type") == "BULLISH_CHOCH"]
        bearish_chochs = [s for s in choch_sigs if s.value.get("choch_type") == "BEARISH_CHOCH"]
        confirmed_chochs = [s for s in choch_sigs if s.value.get("confirmed", False)]

        # ── Count directional signals ───────────────────────────────
        bullish_count = len(active_bullish_fvgs) + len(bullish_obs) + len(confirmed_chochs)
        bearish_count = len(active_bearish_fvgs) + len(bearish_obs) + len(confirmed_chochs)

        if is_bullish_structure:
            bullish_count += 2  # Structure is a strong signal
        if is_bearish_structure:
            bearish_count += 2

        # ── Determine Bias ──────────────────────────────────────────
        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones ──────────────────────────────────────
        active_zones: list[dict[str, Any]] = []

        for fvg in active_bullish_fvgs + active_bearish_fvgs:
            fvg_type = fvg.value.get("fvg_type", "")
            direction = "bullish" if fvg_type == "BULLISH_FVG" else "bearish"
            price = fvg.value.get("top", 0.0)
            active_zones.append(self._make_zone_dict(
                zone_type="FVG",
                price_level=price,
                direction=direction,
                strength=fvg.value.get("gap_size_pips", 0.5) / 5.0,  # Normalise
                signal_ref=fvg.signal_id,
            ))

        for ob in bullish_obs + bearish_obs:
            ob_type = ob.value.get("ob_type", "")
            direction = "bullish" if ob_type == "BULLISH_OB" else "bearish"
            price = ob.value.get("price", 0.0)
            active_zones.append(self._make_zone_dict(
                zone_type="ORDER_BLOCK",
                price_level=price,
                direction=direction,
                strength=ob.value.get("strength", 0.5),
                signal_ref=ob.signal_id,
            ))

        # ── Build Triggers ──────────────────────────────────────────
        armed_triggers: list[dict[str, Any]] = []

        if active_bullish_fvgs:
            zone = active_zones[0] if active_zones else {}
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="zone_touch",
                condition=f"Price retests bullish FVG at {zone.get('price_level', '?')}",
                price_level=zone.get("price_level", 0.0),
            ))

        if active_bearish_fvgs:
            zone = active_zones[-1] if active_zones else {}
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="zone_touch",
                condition=f"Price retests bearish FVG at {zone.get('price_level', '?')}",
                price_level=zone.get("price_level", 0.0),
            ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if active_bullish_fvgs:
                primary_setup = _FVG_RETEST
                backup_setup = _ORDER_BLOCK_BOUNCE if bullish_obs else None
            elif bullish_obs:
                primary_setup = _ORDER_BLOCK_BOUNCE
                backup_setup = _CHOCH_CONTINUATION if bullish_chochs else None
            elif is_bullish_structure:
                primary_setup = _BOS_CONTINUATION
        elif bias == BiasType.BEARISH:
            if active_bearish_fvgs:
                primary_setup = _FVG_RETEST
                backup_setup = _ORDER_BLOCK_BOUNCE if bearish_obs else None
            elif bearish_obs:
                primary_setup = _ORDER_BLOCK_BOUNCE
                backup_setup = _CHOCH_CONTINUATION if bearish_chochs else None
            elif is_bearish_structure:
                primary_setup = _BOS_CONTINUATION
        else:
            # NEUTRAL — check for sweeps on either side
            if active_bullish_fvgs or bullish_obs:
                primary_setup = _LIQUIDITY_SWEEP_RECLAIM
            elif active_bearish_fvgs or bearish_obs:
                backup_setup = _LIQUIDITY_SWEEP_RECLAIM

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if is_bullish_structure:
            invalidation_rules.append(InvalidationRule(
                condition="Structure breaks below last swing low",
                price_level=_find_lowest_price(active_zones),
                reason="Bullish structure invalidated — trend flip risk",
            ))

        if is_bearish_structure:
            invalidation_rules.append(InvalidationRule(
                condition="Structure breaks above last swing high",
                price_level=_find_highest_price(active_zones),
                reason="Bearish structure invalidated — trend flip risk",
            ))

        if primary_setup == _FVG_RETEST and active_bullish_fvgs:
            invalidation_rules.append(InvalidationRule(
                condition="FVG fully mitigated — gap closed",
                price_level=_find_highest_price(active_zones),
                reason="Setup invalidated — gap no longer exists",
            ))

        if primary_setup == _ORDER_BLOCK_BOUNCE and bullish_obs:
            last_ob = bullish_obs[-1]
            ob_price = last_ob.value.get("price", 0.0)
            invalidation_rules.append(InvalidationRule(
                condition=f"Order block at {ob_price} breaks decisively",
                price_level=ob_price,
                reason="OB structure broken — invalidation level",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Market structure flips against current bias",
                price_level=0.0,
                reason="General structural invalidation",
            ))

        # ── Compute context_quality_score ───────────────────────────
        context_quality_score = self._compute_context_quality(
            structure_valid=structure_valid,
            total_signals=len(signals),
            has_active_fvgs=len(active_bullish_fvgs) + len(active_bearish_fvgs) > 0,
            has_obs=len(ob_sigs) > 0,
            has_chochs=len(confirmed_chochs) > 0,
        )

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            structure_valid, primary_setup is not None,
            len(active_bullish_fvgs) + len(active_bearish_fvgs),
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=context_quality_score,
            signal_strength=min(1.0, len(signals) / 20),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if structure_type:
            witness_lines.append(f"Structure: {structure_type}")
        total_active_zones = len(active_zones)
        if total_active_zones > 0:
            witness_lines.append(f"{total_active_zones} active zones tracked")
        if primary_setup:
            witness_lines.append(f"Primary: {primary_setup}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Bullish structure ({structure_type}) with {len(active_bullish_fvgs)} active FVGs"
            bear_case = "Risk: structure breaks below swing lows"
        elif bias == BiasType.BEARISH:
            bear_case = f"Bearish structure ({structure_type}) with {len(active_bearish_fvgs)} active FVGs"
            bull_case = "Risk: structure reclaims above swing highs"
        else:
            bull_case = "Neutral — watching for directional trigger"
            bear_case = "Neutral — waiting for structure to resolve"

        return {
            "bias": bias,
            "confidence": confidence,
            "context_quality_score": context_quality_score,
            "dominant_tf": "1m",
            "timeframe_view": f"Structure: {structure_type or 'unknown'}, "
                              f"{len(fvg_sigs)} FVGs, {len(ob_sigs)} OBs",
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": armed_triggers,
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"{len(confirmed_chochs)} confirmed CHOCHs "
                f"support {'bullish' if bias == BiasType.BULLISH else 'bearish' if bias == BiasType.BEARISH else 'neutral'} view"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        """Return a safe empty interpretation when no SMC signals exist."""
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "context_quality_score": 0.0,
            "dominant_tf": "1m",
            "timeframe_view": "No SMC signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No SMC data — cannot assess structure",
                    price_level=0.0,
                    reason="No Floor 3 SMC signals received",
                ),
            ]),
            "bull_case": "No SMC data to assess",
            "bear_case": "No SMC data to assess",
            "confluence_note": "Waiting for SMC signals from Floor 3",
            "witness_summary": "No SMC data",
        }

    def _compute_context_quality(
        self,
        structure_valid: bool,
        total_signals: int,
        has_active_fvgs: bool,
        has_obs: bool,
        has_chochs: bool,
    ) -> float:
        """Compute context quality score from signal characteristics.

        Args:
            structure_valid: Whether market structure analysis is valid.
            total_signals: Total SMC signals received.
            has_active_fvgs: Whether active (unmitigated) FVGs exist.
            has_obs: Whether order blocks were detected.
            has_chochs: Whether confirmed CHOCHs exist.

        Returns:
            Quality score between 0.0 and 1.0.
        """
        score = 0.0

        # Structure validity is the foundation
        if structure_valid:
            score += 0.3

        # Active FVGs + OBs show price interaction opportunities
        if has_active_fvgs:
            score += 0.25
        if has_obs:
            score += 0.2

        # CHOCHs show structural confirmation
        if has_chochs:
            score += 0.15

        # Signal volume shows data richness
        score += min(0.1, total_signals * 0.01)

        return min(1.0, score)

    def _compute_base_confidence(
        self,
        structure_valid: bool,
        has_primary_setup: bool,
        active_fvg_count: int,
    ) -> float:
        """Compute base confidence from available evidence.

        Args:
            structure_valid: Whether structure analysis is valid.
            has_primary_setup: Whether a primary setup was identified.
            active_fvg_count: Number of active FVGs.

        Returns:
            Base confidence between 0.0 and 1.0.
        """
        score = 0.0

        if structure_valid:
            score += 0.3
        if has_primary_setup:
            score += 0.4
        if active_fvg_count > 0:
            score += min(0.2, active_fvg_count * 0.1)

        return min(1.0, score)

# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _find_highest_price(zones: list[dict[str, Any]]) -> float:
    """Find the highest price level across a list of zones.

    Args:
        zones: List of zone dicts with ``price_level`` keys.

    Returns:
        The highest price level, or 0.0 if empty.
    """
    prices = [z.get("price_level", 0.0) for z in zones if z.get("price_level")]
    return max(prices) if prices else 0.0


def _find_lowest_price(zones: list[dict[str, Any]]) -> float:
    """Find the lowest price level across a list of zones.

    Args:
        zones: List of zone dicts with ``price_level`` keys.

    Returns:
        The lowest price level, or 0.0 if empty.
    """
    prices = [z.get("price_level", 0.0) for z in zones if z.get("price_level")]
    return min(prices) if prices else 0.0
