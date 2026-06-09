"""Floor 4 — ICT Department Head.

Consumes Floor 3 ICT signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- PD_ARRAY: zone_type (PREMIUM/DISCOUNT), price_level, strength
- KILL_ZONE: zone_type (kill zone), start/end time, active
- NEXT_KILL_ZONE: upcoming kill zone, time_remaining
- LIQUIDITY: liquidity_type (BUY/SELL), price_level, strength
- LIQUIDITY_CONTEXT: context_summary, bias

Internal Thinking:
- Is price in premium or discount location?
- Was there real displacement or weak move?
- Is MSS meaningful or noisy?
- Is market showing controlled delivery in one direction?
- Is setup context strong enough to be trusted?

Primary Setup examples: premium/discount reaction, displacement reclaim
Backup Setup examples: MSS continuation, delivery-aligned reversal attempt

Invalidation examples: discount lost, premium invalidated, displacement erased,
MSS fails to hold meaning

EXTRA MANDATORY FIELD: context_quality_score (SMC/ICT only)
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

# ── Setup templates ─────────────────────────────────────────────────────────

_PREMIUM_DISCOUNT_REACTION = "Premium/Discount Reaction"
_DISPLACEMENT_RECLAIM = "Displacement Reclaim"
_MSS_CONTINUATION = "MSS Continuation"
_DELIVERY_REVERSAL = "Delivery-Aligned Reversal Attempt"


class ICTHead(BaseHead):
    """ICT Head — interprets institutional delivery logic from Floor 3 ICT signals.

    Args:
        name: Optional name override (default ``\"ict\"``).
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
        """Extract ICT-domain signals from the OutputContract.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            Only signals where ``domain == CalculationDomain.ICT``.
        """
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
        """Interpret ICT signals and produce Head interpretation.

        Analyzes PD arrays, kill zones, and liquidity to determine
        bias, confidence, setups, zones, and invalidation.

        Args:
            signals: ICT-domain CalculatedSignal list.
            output_contract: Full OutputContract for context.
            current_time: Current timestamp.

        Returns:
            Interpretation dict with ``context_quality_score`` (MANDATORY).
        """
        if not signals:
            return self._empty_interpretation()

        # ── Categorise signals ──────────────────────────────────────
        pd_sigs = [s for s in signals if s.indicator_type == "PD_ARRAY"]
        kz_sigs = [s for s in signals if s.indicator_type == "KILL_ZONE"]
        nkz_sigs = [s for s in signals if s.indicator_type == "NEXT_KILL_ZONE"]
        liq_sigs = [s for s in signals if s.indicator_type == "LIQUIDITY"]
        liq_ctx_sigs = [s for s in signals if s.indicator_type == "LIQUIDITY_CONTEXT"]

        # ── Next Kill Zone Analysis ───────────────────────────────
        nkz_upcoming = [
            s for s in nkz_sigs
            if s.value.get("time_remaining", 9999) < 600  # Within 10 minutes
        ]
        has_upcoming_kz = len(nkz_upcoming) > 0
        closest_nkz = min(nkz_sigs, key=lambda s: s.value.get("time_remaining", 9999)) if nkz_sigs else None

        # ── PD Array Analysis ───────────────────────────────────────
        premium_zones = [s for s in pd_sigs if s.value.get("zone_type") == "PREMIUM"]
        discount_zones = [s for s in pd_sigs if s.value.get("zone_type") == "DISCOUNT"]
        price_in_premium = any(s.value.get("active", False) for s in premium_zones)
        price_in_discount = any(s.value.get("active", False) for s in discount_zones)

        # ── Kill Zone Analysis ───────────────────────────────────────
        active_kill_zones = [s for s in kz_sigs if s.value.get("active", False)]
        has_active_kz = len(active_kill_zones) > 0

        # ── Liquidity Analysis ───────────────────────────────────────
        buy_liquidity = [s for s in liq_sigs if s.value.get("liquidity_type") == "BUY"]
        sell_liquidity = [s for s in liq_sigs if s.value.get("liquidity_type") == "SELL"]
        buy_liq_strength = sum(s.value.get("strength", 0.5) for s in buy_liquidity) / max(len(buy_liquidity), 1)
        sell_liq_strength = sum(s.value.get("strength", 0.5) for s in sell_liquidity) / max(len(sell_liquidity), 1)

        # ── Liquidity Context Analysis ───────────────────────────────
        liq_ctx_bias = ""
        if liq_ctx_sigs:
            liq_ctx_bias = liq_ctx_sigs[-1].value.get("bias", "")

        # ── Count directional signals ───────────────────────────────
        bullish_count = 0
        bearish_count = 0

        # PD Array: premium = bearish zone, discount = bullish zone
        if price_in_premium:
            bearish_count += 2  # Price in premium → expected to drop
        if price_in_discount:
            bullish_count += 2  # Price in discount → expected to rise

        # PD Zones count
        bullish_count += len(discount_zones)
        bearish_count += len(premium_zones)

        # Kill zone context
        if has_active_kz:
            bullish_count += 1  # Kill zone = potential directional move

        # Next kill zone: approaching kill zones add anticipation
        # (direction-neutral but signals imminent institutional activity)
        if has_upcoming_kz:
            bullish_count += 1  # Anticipation of directional move
            bearish_count += 1

        # Liquidity: buy liquidity above = target for shorts, sell liq below = target for longs
        bullish_count += len(buy_liquidity)  # Buy liquidity = bullish target
        bearish_count += len(sell_liquidity)  # Sell liquidity = bearish target

        # Liquidity context bias
        if liq_ctx_bias == "bullish":
            bullish_count += 1
        elif liq_ctx_bias == "bearish":
            bearish_count += 1

        # ── Determine Bias ──────────────────────────────────────────
        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones ──────────────────────────────────────
        active_zones: list[dict[str, Any]] = []

        for pd in premium_zones:
            active_zones.append(self._make_zone_dict(
                zone_type="PREMIUM",
                price_level=pd.value.get("price_level", 0.0),
                direction="bearish",
                strength=pd.value.get("strength", 0.5),
                signal_ref=pd.signal_id,
            ))

        for pd in discount_zones:
            active_zones.append(self._make_zone_dict(
                zone_type="DISCOUNT",
                price_level=pd.value.get("price_level", 0.0),
                direction="bullish",
                strength=pd.value.get("strength", 0.5),
                signal_ref=pd.signal_id,
            ))

        for liq in buy_liquidity + sell_liquidity:
            direction = "bullish" if liq.value.get("liquidity_type") == "BUY" else "bearish"
            active_zones.append(self._make_zone_dict(
                zone_type="LIQUIDITY",
                price_level=liq.value.get("price_level", 0.0),
                direction=direction,
                strength=liq.value.get("strength", 0.5),
                signal_ref=liq.signal_id,
            ))

        # ── Build Triggers ──────────────────────────────────────────
        armed_triggers: list[dict[str, Any]] = []

        for kz in active_kill_zones:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="kill_zone_active",
                condition=f"Kill zone active — {kz.value.get('zone_type', 'unknown')}",
            )            )

        if closest_nkz and closest_nkz.value.get("time_remaining", 9999) < 300:
            remaining = closest_nkz.value.get("time_remaining", 0)
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="upcoming_kill_zone",
                condition=(
                    f"Kill zone approaching — "
                    f"{closest_nkz.value.get('zone_type', 'unknown')} in {int(remaining)}s"
                ),
            ))

        if price_in_premium:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="zone_touch",
                condition="Price in premium — watching for discount reaction",
            ))
        elif price_in_discount:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="zone_touch",
                condition="Price in discount — watching for premium reaction",
            ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if price_in_discount:
                primary_setup = _PREMIUM_DISCOUNT_REACTION
                backup_setup = _DELIVERY_REVERSAL if has_active_kz else _MSS_CONTINUATION
            elif buy_liquidity:
                primary_setup = _DISPLACEMENT_RECLAIM
                backup_setup = _MSS_CONTINUATION
            else:
                primary_setup = _MSS_CONTINUATION
        elif bias == BiasType.BEARISH:
            if price_in_premium:
                primary_setup = _PREMIUM_DISCOUNT_REACTION
                backup_setup = _DELIVERY_REVERSAL if has_active_kz else _MSS_CONTINUATION
            elif sell_liquidity:
                primary_setup = _DISPLACEMENT_RECLAIM
                backup_setup = _MSS_CONTINUATION
            else:
                primary_setup = _PREMIUM_DISCOUNT_REACTION
        else:
            if price_in_premium:
                primary_setup = _PREMIUM_DISCOUNT_REACTION
            elif price_in_discount:
                backup_setup = _PREMIUM_DISCOUNT_REACTION
            elif buy_liquidity or sell_liquidity:
                backup_setup = _DISPLACEMENT_RECLAIM

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if price_in_premium:
            invalidation_rules.append(InvalidationRule(
                condition="Premium structure invalidated — price continues higher",
                price_level=0.0,
                reason="ICT premium invalidation — expected drop failed",
            ))
        if price_in_discount:
            invalidation_rules.append(InvalidationRule(
                condition="Discount structure invalidated — price continues lower",
                price_level=0.0,
                reason="ICT discount invalidation — expected rise failed",
            ))
        if has_active_kz:
            invalidation_rules.append(InvalidationRule(
                condition="Kill zone window expired without directional response",
                price_level=0.0,
                reason="Kill zone invalidation — window closed",
            ))
        if liq_ctx_bias:
            invalidation_rules.append(InvalidationRule(
                condition=f"Liquidity context flipped — bias changed from {liq_ctx_bias}",
                price_level=0.0,
                reason="ICT liquidity context invalidated",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="ICT delivery context degrades — premium/discount zones unclear",
                price_level=0.0,
                reason="General ICT invalidation",
            ))

        # ── Compute context_quality_score ───────────────────────────
        context_quality_score = self._compute_context_quality(
            has_pd_zones=len(pd_sigs) > 0,
            has_active_kill_zone=has_active_kz,
            has_upcoming_kill_zone=has_upcoming_kz,
            has_liquidity_data=len(liq_sigs) > 0,
            has_liquidity_context=len(liq_ctx_sigs) > 0,
            total_signals=len(signals),
        )

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_pd_array=len(pd_sigs) > 0,
            has_active_kill_zone=has_active_kz,
            has_upcoming_kill_zone=has_upcoming_kz,
            has_primary_setup=primary_setup is not None,
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=context_quality_score,
            signal_strength=min(1.0, len(signals) / 20),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if price_in_premium:
            witness_lines.append("Price in PREMIUM zone")
        if price_in_discount:
            witness_lines.append("Price in DISCOUNT zone")
        if has_active_kz:
            witness_lines.append(f"{len(active_kill_zones)} kill zone(s) active")
        if has_upcoming_kz:
            witness_lines.append(f"{len(nkz_upcoming)} upcoming kill zone(s) imminent")
        if buy_liquidity:
            witness_lines.append(f"{len(buy_liquidity)} buy liquidity zone(s)")
        if sell_liquidity:
            witness_lines.append(f"{len(sell_liquidity)} sell liquidity zone(s)")
        if primary_setup:
            witness_lines.append(f"Primary: {primary_setup}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Bullish ICT — price in discount, {len(buy_liquidity)} buy liquidity targets"
            bear_case = "Risk: discount invalidated, delivery fails"
        elif bias == BiasType.BEARISH:
            bear_case = f"Bearish ICT — price in premium, {len(sell_liquidity)} sell liquidity targets"
            bull_case = "Risk: premium invalidated, delivery flips"
        else:
            bull_case = "Neutral — mixed PD array, watching for directional trigger"
            bear_case = "Neutral — waiting for kill zone or displacement"

        return {
            "bias": bias,
            "confidence": confidence,
            "context_quality_score": context_quality_score,
            "dominant_tf": "1m",
            "timeframe_view": (
                f"{'Premium' if price_in_premium else 'Discount' if price_in_discount else 'Neutral'} PD, "
                f"{len(kz_sigs)} kill zones, {len(liq_sigs)} liquidity zones"
            ),
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": armed_triggers,
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"PD: {len(premium_zones)} premium / {len(discount_zones)} discount zones, "
                f"liquidity bias: {liq_ctx_bias or 'none'}"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        """Return a safe empty interpretation when no ICT signals exist."""
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
                    condition="No ICT data — cannot assess PD/delivery",
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
        has_pd_zones: bool,
        has_active_kill_zone: bool,
        has_upcoming_kill_zone: bool,
        has_liquidity_data: bool,
        has_liquidity_context: bool,
        total_signals: int,
    ) -> float:
        """Compute context quality score from signal characteristics.

        Args:
            has_pd_zones: Whether premium/discount zone data exists.
            has_active_kill_zone: Whether an active kill zone is present.
            has_upcoming_kill_zone: Whether a next-day kill zone is approaching.
            has_liquidity_data: Whether liquidity zone data exists.
            has_liquidity_context: Whether liquidity context/interpretation exists.
            total_signals: Total ICT signals received.

        Returns:
            Quality score between 0.0 and 1.0.
        """
        score = 0.0

        # PD Array is the foundation of ICT analysis
        if has_pd_zones:
            score += 0.35
        if has_active_kill_zone:
            score += 0.25  # Timing context from active zones
        if has_upcoming_kill_zone:
            score += 0.05  # Bonus: upcoming timing context
        if has_liquidity_data:
            score += 0.2  # Liquidity targets
        if has_liquidity_context:
            score += 0.1  # Interpretive layer
        score += min(0.1, total_signals * 0.01)

        return min(1.0, score)

    def _compute_base_confidence(
        self,
        has_pd_array: bool,
        has_active_kill_zone: bool,
        has_upcoming_kill_zone: bool,
        has_primary_setup: bool,
    ) -> float:
        """Compute base confidence from available evidence.

        Args:
            has_pd_array: Whether PD array data exists.
            has_active_kill_zone: Whether an active kill zone exists.
            has_upcoming_kill_zone: Whether a next-day kill zone is approaching.
            has_primary_setup: Whether a primary setup was identified.

        Returns:
            Base confidence between 0.0 and 1.0.
        """
        score = 0.0

        if has_pd_array:
            score += 0.3
        if has_active_kill_zone:
            score += 0.2
        if has_upcoming_kill_zone:
            score += 0.05
        if has_primary_setup:
            score += 0.4

        return min(1.0, score)


