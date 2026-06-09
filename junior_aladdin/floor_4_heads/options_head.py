"""Floor 4 — Options Department Head.

Consumes Floor 3 Options signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- OI_CHANGE: oi_direction (BUYING/UNWINDING), change_pct, strike, option_type (CE/PE)
- PCR: pcr_value, pcr_trend (RISING/FALLING)
- IV: iv_value, iv_percentile, iv_context (HIGH/LOW/NORMAL)
- CALL_WALL / PUT_WALL: wall_strike, wall_strength, distance_pct
- MAX_PAIN: max_pain_strike, distance_pct

Internal Thinking:
- Does options market confirm directional continuation?
- Is price pushing into strong wall resistance/support?
- Is there pressure expansion or pressure exhaustion?
- Is IV condition helpful or dangerous?

Primary Setup examples: OI wall bounce, options pressure continuation
Backup Setup examples: wall-break transition, pressure collapse follow-through

Invalidation examples: wall disappears, supportive pressure collapses,
derivatives bias flips sharply

No context_quality_score needed (only SMC/ICT require this).
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

logger = get_logger("options_head")

# ── Setup templates ─────────────────────────────────────────────────────────

_OI_WALL_BOUNCE = "OI Wall Bounce"
_OPTIONS_PRESSURE_CONTINUATION = "Options Pressure Continuation"
_WALL_BREAK_TRANSITION = "Wall-Break Transition"
_PRESSURE_COLLAPSE = "Pressure Collapse Follow-Through"


class OptionsHead(BaseHead):
    """Options Head — interprets derivatives pressure from Floor 3 options signals.

    Args:
        name: Optional name override (default ``\"options\"``).
        config: Optional dict with tuning parameters.
    """

    def __init__(
        self,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or "options")
        self._config = config or {}

    @property
    def head_name(self) -> str:
        return "Options Head"

    # ── Signal Extraction ───────────────────────────────────────────────

    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[CalculatedSignal]:
        """Extract Options-domain signals from the OutputContract.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            Only signals where ``domain == CalculationDomain.OPTIONS``.
        """
        return [
            s for s in output_contract.signals
            if s.domain == CalculationDomain.OPTIONS
        ]

    # ── Core Interpretation ─────────────────────────────────────────────

    def _interpret(
        self,
        signals: list[CalculatedSignal],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Interpret Options signals and produce Head interpretation.

        Analyzes OI, PCR, IV, walls, and max pain to determine
        bias, confidence, setups, zones, and invalidation.

        Args:
            signals: Options-domain CalculatedSignal list.
            output_contract: Full OutputContract for context.
            current_time: Current timestamp.

        Returns:
            Interpretation dict with all HeadReport fields.
        """
        if not signals:
            return self._empty_interpretation()

        # ── Categorise signals ──────────────────────────────────────
        oi_sigs = [s for s in signals if s.indicator_type == "OI_CHANGE"]
        pcr_sigs = [s for s in signals if s.indicator_type == "PCR"]
        iv_sigs = [s for s in signals if s.indicator_type == "IV"]
        call_wall_sigs = [s for s in signals if s.indicator_type == "CALL_WALL"]
        put_wall_sigs = [s for s in signals if s.indicator_type == "PUT_WALL"]
        max_pain_sigs = [s for s in signals if s.indicator_type == "MAX_PAIN"]

        # ── OI Analysis ─────────────────────────────────────────────
        bullish_oi = [s for s in oi_sigs if s.value.get("oi_direction") == "BUYING"
                      and s.value.get("option_type") == "CE"]
        bearish_oi = [s for s in oi_sigs if s.value.get("oi_direction") == "BUYING"
                      and s.value.get("option_type") == "PE"]
        oi_unwinding = [s for s in oi_sigs if s.value.get("oi_direction") == "UNWINDING"]

        # ── PCR Analysis ────────────────────────────────────────────
        pcr_value = 0.0
        pcr_rising = False
        pcr_falling = False
        if pcr_sigs:
            latest_pcr = pcr_sigs[-1].value
            pcr_value = latest_pcr.get("pcr_value", 0.0)
            pcr_trend = latest_pcr.get("pcr_trend", "")
            pcr_rising = pcr_trend == "RISING"
            pcr_falling = pcr_trend == "FALLING"

        # PCR interpretation:
        # Rising PCR = more puts = bearish sentiment
        # Falling PCR = more calls = bullish sentiment
        # PCR > 1.0 = puts dominating (bearish), < 0.5 = calls dominating (bullish)

        # ── IV Analysis ─────────────────────────────────────────────
        iv_high = False
        iv_low = False
        iv_value = 0.0
        if iv_sigs:
            latest_iv = iv_sigs[-1].value
            iv_value = latest_iv.get("iv_value", 0.0)
            iv_context = latest_iv.get("iv_context", "")
            iv_high = iv_context == "HIGH"
            iv_low = iv_context == "LOW"

        # ── Wall Analysis ──────────────────────────────────────────
        nearest_call_wall = None
        nearest_put_wall = None
        call_wall_distance = 999.0
        put_wall_distance = 999.0

        for s in call_wall_sigs:
            dist = s.value.get("distance_pct", 999.0)
            if dist < call_wall_distance:
                call_wall_distance = dist
                nearest_call_wall = s

        for s in put_wall_sigs:
            dist = s.value.get("distance_pct", 999.0)
            if dist < put_wall_distance:
                put_wall_distance = dist
                nearest_put_wall = s

        # ── Max Pain Analysis ───────────────────────────────────────
        max_pain_strike = 0.0
        max_pain_distance = 999.0
        if max_pain_sigs:
            latest_mp = max_pain_sigs[-1].value
            max_pain_strike = latest_mp.get("max_pain_strike", 0.0)
            max_pain_distance = latest_mp.get("distance_pct", 999.0)

        # ── Count directional signals ───────────────────────────────
        bullish_count = 0
        bearish_count = 0

        # OI: CE buying = bullish, PE buying = bearish
        bullish_count += len(bullish_oi)
        bearish_count += len(bearish_oi)
        bearish_count += len(oi_unwinding)  # Unwinding = exiting positions = cautious

        # PCR
        if pcr_rising:
            bearish_count += 1  # More puts being bought
        elif pcr_falling:
            bullish_count += 1  # More calls being bought

        if pcr_value > 1.0:
            bearish_count += 1  # Heavy put dominance
        elif 0.3 < pcr_value < 0.7:
            bullish_count += 1  # Call dominance

        # IV: High IV = fear = bearish, Low IV = complacency = bullish
        if iv_high:
            bearish_count += 1
        elif iv_low:
            bullish_count += 1

        # Walls: nearest wall proximity
        if call_wall_distance < 1.0:  # Call wall within 1%
            bearish_count += 1  # Resistance nearby
        if put_wall_distance < 1.0:  # Put wall within 1%
            bullish_count += 1  # Support nearby

        # Max pain proximity
        if max_pain_distance < 0.5:  # Price near max pain
            bullish_count += 1  # Max pain often acts as magnet

        # ── Determine Bias ──────────────────────────────────────────
        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones ──────────────────────────────────────
        active_zones: list[dict[str, Any]] = []

        if nearest_call_wall:
            active_zones.append(self._make_zone_dict(
                zone_type="CALL_WALL",
                price_level=nearest_call_wall.value.get("wall_strike", 0.0),
                direction="bearish",
                strength=min(1.0, nearest_call_wall.value.get("wall_strength", 0.5) / 100.0),
                signal_ref=nearest_call_wall.signal_id,
            ))

        if nearest_put_wall:
            active_zones.append(self._make_zone_dict(
                zone_type="PUT_WALL",
                price_level=nearest_put_wall.value.get("wall_strike", 0.0),
                direction="bullish",
                strength=min(1.0, nearest_put_wall.value.get("wall_strength", 0.5) / 100.0),
                signal_ref=nearest_put_wall.signal_id,
            ))

        if max_pain_strike > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="MAX_PAIN",
                price_level=max_pain_strike,
                direction="",
                strength=0.6,
            ))

        # ── Build Triggers ──────────────────────────────────────────
        armed_triggers: list[dict[str, Any]] = []

        if nearest_call_wall and call_wall_distance < 2.0:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="wall_approach",
                condition=f"Price approaching CE wall at {nearest_call_wall.value.get('wall_strike', '?')}",
                price_level=nearest_call_wall.value.get("wall_strike", 0.0),
            ))

        if nearest_put_wall and put_wall_distance < 2.0:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="wall_approach",
                condition=f"Price approaching PE wall at {nearest_put_wall.value.get('wall_strike', '?')}",
                price_level=nearest_put_wall.value.get("wall_strike", 0.0),
            ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if nearest_put_wall:
                primary_setup = _OI_WALL_BOUNCE
                backup_setup = _OPTIONS_PRESSURE_CONTINUATION
            else:
                primary_setup = _OPTIONS_PRESSURE_CONTINUATION
                backup_setup = _WALL_BREAK_TRANSITION

        elif bias == BiasType.BEARISH:
            if nearest_call_wall:
                primary_setup = _OI_WALL_BOUNCE
                backup_setup = _PRESSURE_COLLAPSE
            else:
                primary_setup = _PRESSURE_COLLAPSE
                backup_setup = _WALL_BREAK_TRANSITION

        else:
            if nearest_call_wall or nearest_put_wall:
                primary_setup = _OI_WALL_BOUNCE

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if nearest_call_wall:
            invalidation_rules.append(InvalidationRule(
                condition=f"Call wall at {nearest_call_wall.value.get('wall_strike', 0.0)} decisively broken",
                price_level=nearest_call_wall.value.get("wall_strike", 0.0),
                reason="Call wall resistance broken — bearish thesis invalidated",
            ))
        if nearest_put_wall:
            invalidation_rules.append(InvalidationRule(
                condition=f"Put wall at {nearest_put_wall.value.get('wall_strike', 0.0)} decisively broken",
                price_level=nearest_put_wall.value.get("wall_strike", 0.0),
                reason="Put wall support broken — bullish thesis invalidated",
            ))
        if pcr_value:
            invalidation_rules.append(InvalidationRule(
                condition=f"PCR trend flips — current PCR: {pcr_value:.2f}",
                price_level=0.0,
                reason="Derivatives bias shift — PCR trend reversed",
            ))
        if iv_value:
            invalidation_rules.append(InvalidationRule(
                condition=f"IV regime shifts — IV: {iv_value:.1f}",
                price_level=0.0,
                reason="Volatility context changed — IV regime shift",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Options pressure structure collapses or reverses",
                price_level=0.0,
                reason="General options invalidation",
            ))

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_wall_data=nearest_call_wall is not None or nearest_put_wall is not None,
            has_pcr=len(pcr_sigs) > 0,
            has_iv=len(iv_sigs) > 0,
            has_primary_setup=primary_setup is not None,
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.5,
            signal_strength=min(1.0, len(signals) / 20),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if pcr_value:
            pcr_label = f"PCR: {pcr_value:.2f} ({'rising' if pcr_rising else 'falling' if pcr_falling else 'stable'})"
            witness_lines.append(pcr_label)
        if iv_value:
            iv_label = f"IV: {iv_value:.1f} ({'high' if iv_high else 'low' if iv_low else 'normal'})"
            witness_lines.append(iv_label)
        if nearest_call_wall:
            witness_lines.append(f"CE wall: {nearest_call_wall.value.get('wall_strike', 0.0)}")
        if nearest_put_wall:
            witness_lines.append(f"PE wall: {nearest_put_wall.value.get('wall_strike', 0.0)}")
        if primary_setup:
            witness_lines.append(f"Primary: {primary_setup}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Bullish options — PE wall support, PCR {pcr_value:.2f}"
            bear_case = "Risk: put wall breaks, PCR flips bearish"
        elif bias == BiasType.BEARISH:
            bear_case = f"Bearish options — CE wall resistance, PCR {pcr_value:.2f}"
            bull_case = "Risk: call wall breaks, PCR flips bullish"
        else:
            bull_case = "Neutral options — mixed OI and wall signals"
            bear_case = "Neutral — waiting for clearer directional pressure"

        return {
            "bias": bias,
            "confidence": confidence,
            "dominant_tf": "1m",
            "timeframe_view": (
                f"PCR: {pcr_value:.2f}, "
                f"IV: {iv_value:.1f}, "
                f"CE wall: {nearest_call_wall.value.get('wall_strike', 0.0) if nearest_call_wall else 'none'}, "
                f"PE wall: {nearest_put_wall.value.get('wall_strike', 0.0) if nearest_put_wall else 'none'}"
            ),
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": armed_triggers,
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"Max pain: {max_pain_strike} ({max_pain_distance:.1f}% away), "
                f"OI: {len(bullish_oi)} CE buying / {len(bearish_oi)} PE buying / {len(oi_unwinding)} unwinding"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        """Return a safe empty interpretation when no Options signals exist."""
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "dominant_tf": "1m",
            "timeframe_view": "No Options signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No options data — cannot assess pressure",
                    price_level=0.0,
                    reason="No Floor 3 options signals received",
                ),
            ]),
            "bull_case": "No options data to assess",
            "bear_case": "No options data to assess",
            "confluence_note": "Waiting for options signals from Floor 3",
            "witness_summary": "No options data",
        }

    def _compute_base_confidence(
        self,
        has_wall_data: bool,
        has_pcr: bool,
        has_iv: bool,
        has_primary_setup: bool,
    ) -> float:
        """Compute base confidence from available evidence.

        Args:
            has_wall_data: Whether wall strike data exists.
            has_pcr: Whether PCR data exists.
            has_iv: Whether IV data exists.
            has_primary_setup: Whether a primary setup was identified.

        Returns:
            Base confidence between 0.0 and 1.0.
        """
        score = 0.0

        if has_wall_data:
            score += 0.3
        if has_pcr:
            score += 0.2
        if has_iv:
            score += 0.1
        if has_primary_setup:
            score += 0.4

        return min(1.0, score)
