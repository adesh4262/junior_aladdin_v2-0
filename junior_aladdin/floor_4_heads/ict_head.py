"""Floor 4 — ICT Department Head.

Consumes Floor 3 ICT signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- PREMIUM_DISCOUNT: pd_state, equilibrium, premium_zone, discount_zone
- DISPLACEMENT: displacement_type, strength, retraced
- MSS: mss_type, confirmed, break_price
- LIQUIDITY: liquidity_type, price, swept
- DELIVERY_CONTEXT: delivery_score, context_quality

Output (HeadReport):
- bias (BULLISH/BEARISH/NEUTRAL)
- confidence (0.0-1.0)
- context_quality_score (0.0-1.0) — MANDATORY
- primary_setup + backup_setup
- active_zones (PD array levels)
- invalidation rules (mandatory)
- witness_summary (2-3 points)

Architecture rules (LOCKED):
- context_quality_score is mandatory.
- invalidation is mandatory.
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

logger = get_logger("ict_head")

# Setup templates
_PREMIUM_DISCOUNT_REACTION = "Premium/Discount Reaction"
_DISPLACEMENT_RECLAIM = "Displacement Reclaim"
_MSS_CONTINUATION = "MSS Continuation"
_DELIVERY_REVERSAL = "Delivery-Aligned Reversal"


class ICTHead(BaseHead):
    """ICT Head — interprets institutional-style delivery from Floor 3 ICT signals.

    Args:
        name: Optional name override (default ``"ict"``).
        config: Optional dict with tuning parameters.
    """

    def __init__(
        self,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or "ict")
        self._config = config or {}

    @property
    def head_name(self) -> str:
        return "ICT Head"

    # ── Signal Extraction ───────────────────────────────────────────────

    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[CalculatedSignal]:
        return [
            s for s in output_contract.signals
            if s.domain == CalculationDomain.ICT
        ]

    # ── Core Interpretation ─────────────────────────────────────────────

    def _interpret(
        self,
        signals: list[CalculatedSignal],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Interpret ICT signals — premium/discount, displacement, MSS, liquidity."""
        if not signals:
            return self._empty_interpretation()

        # Categorise
        pd_sigs = [s for s in signals if s.indicator_type == "PREMIUM_DISCOUNT"]
        displacement_sigs = [s for s in signals if s.indicator_type == "DISPLACEMENT"]
        mss_sigs = [s for s in signals if s.indicator_type == "MSS"]
        liquidity_sigs = [s for s in signals if s.indicator_type == "LIQUIDITY"]
        delivery_sigs = [s for s in signals if s.indicator_type == "DELIVERY_CONTEXT"]

        # ── Premium/Discount Analysis ───────────────────────────────
        pd_state = ""
        equilibrium = 0.0
        in_discount = False
        in_premium = False
        if pd_sigs:
            pd = pd_sigs[-1].value
            pd_state = pd.get("pd_state", "")
            equilibrium = pd.get("equilibrium", 0.0)
            in_discount = pd_state == "DISCOUNT"
            in_premium = pd_state == "PREMIUM"

        # ── Displacement Analysis ───────────────────────────────────
        displacement_type = ""
        displacement_strength = 0.0
        displaced_bullish = False
        displaced_bearish = False
        if displacement_sigs:
            ds = displacement_sigs[-1].value
            displacement_type = ds.get("displacement_type", "")
            displacement_strength = ds.get("strength", 0.0)
            displaced_bullish = displacement_type == "BULLISH_DISPLACEMENT"
            displaced_bearish = displacement_type == "BEARISH_DISPLACEMENT"

        # ── MSS Analysis ────────────────────────────────────────────
        mss_type = ""
        mss_confirmed = False
        if mss_sigs:
            ms = mss_sigs[-1].value
            mss_type = ms.get("mss_type", "")
            mss_confirmed = ms.get("confirmed", False)

        # ── Liquidity Analysis ──────────────────────────────────────
        buy_side_liquidity = [s for s in liquidity_sigs if s.value.get("liquidity_type") == "BUY_SIDE"]
        sell_side_liquidity = [s for s in liquidity_sigs if s.value.get("liquidity_type") == "SELL_SIDE"]
        unswept_buy = [s for s in buy_side_liquidity if not s.value.get("swept", True)]
        unswept_sell = [s for s in sell_side_liquidity if not s.value.get("swept", True)]

        # ── Delivery Context ────────────────────────────────────────
        delivery_score = 0.5
        if delivery_sigs:
            dc = delivery_sigs[-1].value
            delivery_score = dc.get("delivery_score", 0.5)

        # ── Count directional signals ───────────────────────────────
        bullish_count = 0
        bearish_count = 0

        if in_discount:
            bullish_count += 2  # Discount = cheap = bullish bias
        if in_premium:
            bearish_count += 2  # Premium = expensive = bearish bias
        if displaced_bullish and displacement_strength > 0.5:
            bullish_count += 2
        elif displaced_bullish:
            bullish_count += 1
        if displaced_bearish and displacement_strength > 0.5:
            bearish_count += 2
        elif displaced_bearish:
            bearish_count += 1
        if mss_confirmed and mss_type == "BULLISH_MSS":
            bullish_count += 2
        elif mss_confirmed and mss_type == "BEARISH_MSS":
            bearish_count += 2
        if len(unswept_buy) > 0:
            bearish_count += 1  # Buy-side liquidity above = target for price
        if len(unswept_sell) > 0:
            bullish_count += 1  # Sell-side liquidity below = target for price

        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones ──────────────────────────────────────
        active_zones: list[dict[str, Any]] = []
        if equilibrium > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="EQUILIBRIUM",
                price_level=equilibrium,
                direction="neutral",
                strength=0.7,
            ))
        for sig in pd_sigs:
            val = sig.value
            if val.get("ote_high", 0) > 0:
                active_zones.append(self._make_zone_dict(
                    zone_type="OTE_ZONE",
                    price_level=val.get("ote_high", 0),
                    direction="bullish" if val.get("pd_state") == "DISCOUNT" else "bearish",
                    strength=0.8,
                ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if in_discount:
                primary_setup = _PREMIUM_DISCOUNT_REACTION
                backup_setup = _DISPLACEMENT_RECLAIM if displaced_bullish else None
            elif displaced_bullish:
                primary_setup = _DISPLACEMENT_RECLAIM
                backup_setup = _MSS_CONTINUATION if mss_confirmed else None
            elif mss_confirmed:
                primary_setup = _MSS_CONTINUATION
        elif bias == BiasType.BEARISH:
            if in_premium:
                primary_setup = _PREMIUM_DISCOUNT_REACTION
                backup_setup = _DISPLACEMENT_RECLAIM if displaced_bearish else None
            elif displaced_bearish:
                primary_setup = _DISPLACEMENT_RECLAIM
                backup_setup = _MSS_CONTINUATION if mss_confirmed else None
            elif mss_confirmed:
                primary_setup = _MSS_CONTINUATION
        else:
            if len(unswept_buy) > 0 or len(unswept_sell) > 0:
                primary_setup = _DELIVERY_REVERSAL

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if in_discount:
            invalidation_rules.append(InvalidationRule(
                condition="Discount zone lost — price re-enters premium",
                price_level=equilibrium,
                reason="ICT invalidation — discount no longer holds",
            ))
        if in_premium:
            invalidation_rules.append(InvalidationRule(
                condition="Premium zone reclaimed — price re-enters discount",
                price_level=equilibrium,
                reason="ICT invalidation — premium no longer holds",
            ))
        if mss_confirmed:
            invalidation_rules.append(InvalidationRule(
                condition=f"MSS at {mss_type} fails to hold — structure unchanged",
                price_level=0.0,
                reason="ICT invalidation — MSS failed to confirm",
            ))
        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="ICT delivery context deteriorates — no clear institutional logic",
                price_level=0.0,
                reason="ICT invalidation — delivery context lost",
            ))

        # ── Compute context_quality_score (MANDATORY) ───────────────
        context_quality_score = self._compute_context_quality(
            total_signals=len(signals),
            has_pd=len(pd_sigs) > 0,
            has_displacement=len(displacement_sigs) > 0,
            has_mss=mss_confirmed,
            delivery_score=delivery_score,
        )

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_pd=len(pd_sigs) > 0,
            has_primary=primary_setup is not None,
            mss_confirmed=mss_confirmed,
            delivery_score=delivery_score,
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=context_quality_score,
            signal_strength=min(1.0, len(signals) / 15),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if pd_state:
            witness_lines.append(f"PD Array: {pd_state}")
        if mss_confirmed:
            witness_lines.append(f"MSS confirmed: {mss_type}")
        if primary_setup:
            witness_lines.append(f"Setup: {primary_setup}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Discount zone active ({pd_state}), displacement supports upside"
            bear_case = "Risk: displacement fails, premium rejection continues"
        elif bias == BiasType.BEARISH:
            bear_case = f"Premium zone active ({pd_state}), displacement supports downside"
            bull_case = "Risk: displacement fails, discount bounce occurs"
        else:
            bull_case = "ICT neutral — waiting for displacement or MSS"
            bear_case = "ICT neutral — no clear institutional logic"

        return {
            "bias": bias,
            "confidence": confidence,
            "context_quality_score": context_quality_score,
            "dominant_tf": "1m",
            "timeframe_view": f"PD: {pd_state or 'unknown'}, Displacement: {displacement_type or 'none'}",
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"Delivery score: {delivery_score:.2f}, "
                f"MSS confirmed: {mss_confirmed}, "
                f"Unswept liquidity: {len(unswept_buy) + len(unswept_sell)} levels"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "context_quality_score": 0.0,
            "dominant_tf": "1m",
            "timeframe_view": "No ICT signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No ICT data — cannot assess institutional context",
                    price_level=0.0,
                    reason="No Floor 3 ICT signals received",
                ),
            ]),
            "bull_case": "No ICT data to assess",
            "bear_case": "No ICT data to assess",
            "confluence_note": "Waiting for ICT signals from Floor 3",
            "witness_summary": "No ICT data",
        }

    def _compute_context_quality(
        self,
        total_signals: int,
        has_pd: bool,
        has_displacement: bool,
        has_mss: bool,
        delivery_score: float,
    ) -> float:
        score = 0.0
        if has_pd:
            score += 0.3
        if has_displacement:
            score += 0.2
        if has_mss:
            score += 0.3
        score += delivery_score * 0.1
        score += min(0.1, total_signals * 0.01)
        return min(1.0, score)

    def _compute_base_confidence(
        self,
        has_pd: bool,
        has_primary: bool,
        mss_confirmed: bool,
        delivery_score: float,
    ) -> float:
        score = 0.0
        if has_pd:
            score += 0.2
        if has_primary:
            score += 0.3
        if mss_confirmed:
            score += 0.2
        score += delivery_score * 0.2
        return min(1.0, score)
