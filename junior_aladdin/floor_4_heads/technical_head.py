"""Floor 4 — Technical Department Head.

Consumes Floor 3 Technical signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- RSI: rsi_value, overbought, oversold
- MA_FAST / MA_SLOW: ma_value, ma_type
- MA_CROSS: cross_type (GOLDEN/DEATH), confirmed
- ATR: atr_value, volatility_context
- VOLUME_PROFILE: poc, vah, val, volume_ratio

Internal Thinking:
- Is trend aligned or fragmented?
- Is current move impulsive, healthy, weak, or overextended?
- Is price above/below key technical references with quality?
- Is the setup continuation-friendly or fade-prone?

Primary Setup examples: VWAP pullback continuation, trend continuation reclaim
Backup Setup examples: technical breakout continuation, support/resistance rebound

Invalidation examples: VWAP relation lost decisively, continuation structure broken,
MTF alignment collapses below threshold

Architecture rules (LOCKED):
- Interprets Floor 3 signals, never recomputes them.
- invalidation is mandatory.
- No context_quality_score needed (only SMC/ICT require this).
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

logger = get_logger("technical_head")

# ── Setup templates ─────────────────────────────────────────────────────────

_VWAP_PULLBACK = "VWAP Pullback Continuation"
_TREND_CONTINUATION = "Trend Continuation Reclaim"
_BREAKOUT_CONTINUATION = "Technical Breakout Continuation"
_SR_BOUNCE = "Support/Resistance Rebound"


class TechnicalHead(BaseHead):
    """Technical Head — interprets technical indicators from Floor 3 signals.

    Args:
        name: Optional name override (default ``\"technical\"``).
        config: Optional dict with tuning parameters.
    """

    def __init__(
        self,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or "technical")
        self._config = config or {}

    @property
    def head_name(self) -> str:
        return "Technical Head"

    # ── Signal Extraction ───────────────────────────────────────────────

    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[CalculatedSignal]:
        """Extract Technical-domain signals from the OutputContract.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            Only signals where ``domain == CalculationDomain.TECHNICAL``.
        """
        return [
            s for s in output_contract.signals
            if s.domain == CalculationDomain.TECHNICAL
        ]

    # ── Core Interpretation ─────────────────────────────────────────────

    def _interpret(
        self,
        signals: list[CalculatedSignal],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Interpret Technical signals and produce Head interpretation.

        Analyzes RSI, MA cross, ATR, and Volume Profile to determine
        bias, confidence, setups, zones, and invalidation.

        Args:
            signals: Technical-domain CalculatedSignal list.
            output_contract: Full OutputContract for context.
            current_time: Current timestamp.

        Returns:
            Interpretation dict with all HeadReport fields.
        """
        if not signals:
            return self._empty_interpretation()

        # ── Categorise signals ──────────────────────────────────────
        rsi_sigs = [s for s in signals if s.indicator_type == "RSI"]
        ma_fast_sigs = [s for s in signals if s.indicator_type == "MA_FAST"]
        ma_slow_sigs = [s for s in signals if s.indicator_type == "MA_SLOW"]
        ma_cross_sigs = [s for s in signals if s.indicator_type == "MA_CROSS"]
        atr_sigs = [s for s in signals if s.indicator_type == "ATR"]
        vol_sigs = [s for s in signals if s.indicator_type == "VOLUME_PROFILE"]

        # ── RSI Analysis ────────────────────────────────────────────
        rsi_value = 50.0
        rsi_overbought = False
        rsi_oversold = False
        if rsi_sigs:
            latest_rsi = rsi_sigs[-1].value
            rsi_value = latest_rsi.get("rsi_value", 50.0)
            rsi_overbought = latest_rsi.get("overbought", False)
            rsi_oversold = latest_rsi.get("oversold", False)

        # ── MA Analysis ─────────────────────────────────────────────
        ma_fast_value = 0.0
        ma_slow_value = 0.0
        if ma_fast_sigs:
            ma_fast_value = ma_fast_sigs[-1].value.get("ma_value", 0.0)
        if ma_slow_sigs:
            ma_slow_value = ma_slow_sigs[-1].value.get("ma_value", 0.0)

        fast_above_slow = (ma_fast_value > ma_slow_value) if (ma_fast_value and ma_slow_value) else None

        # ── MA Cross Analysis ───────────────────────────────────────
        golden_cross = False
        death_cross = False
        cross_confirmed = False
        if ma_cross_sigs:
            latest_cross = ma_cross_sigs[-1].value
            cross_type = latest_cross.get("cross_type", "")
            cross_confirmed = latest_cross.get("confirmed", False)
            golden_cross = cross_type == "GOLDEN" and cross_confirmed
            death_cross = cross_type == "DEATH" and cross_confirmed

        # ── ATR Analysis ────────────────────────────────────────────
        atr_value = 0.0
        volatility_high = False
        volatility_low = False
        if atr_sigs:
            latest_atr = atr_sigs[-1].value
            atr_value = latest_atr.get("atr_value", 0.0)
            vol_context = latest_atr.get("volatility_context", "")
            volatility_high = vol_context == "HIGH"
            volatility_low = vol_context == "LOW"

        # ── Volume Profile Analysis ─────────────────────────────────
        poc = 0.0
        vah = 0.0
        val = 0.0
        volume_ratio = 0.0
        if vol_sigs:
            latest_vol = vol_sigs[-1].value
            poc = latest_vol.get("poc", 0.0)
            vah = latest_vol.get("vah", 0.0)
            val = latest_vol.get("val", 0.0)
            volume_ratio = latest_vol.get("volume_ratio", 0.0)

        # ── Count bullish / bearish signals ─────────────────────────
        bullish_count = 0
        bearish_count = 0

        # RSI signals
        if rsi_oversold:
            bullish_count += 1  # Oversold → potential bounce
        elif rsi_overbought:
            bearish_count += 1  # Overbought → potential drop

        if rsi_value > 50:
            bullish_count += 1
        elif rsi_value < 50:
            bearish_count += 1

        # MA cross signals
        if golden_cross:
            bullish_count += 2  # Strong structure signal
        elif death_cross:
            bearish_count += 2

        if fast_above_slow is True:
            bullish_count += 1
        elif fast_above_slow is False:
            bearish_count += 1

        # Volume signals
        if volume_ratio > 1.5:
            bullish_count += 1  # High volume supports trend
        elif volume_ratio < 0.5:
            bearish_count += 1  # Low volume suggests weakness

        # ── Determine Bias ──────────────────────────────────────────
        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones ──────────────────────────────────────
        active_zones: list[dict[str, Any]] = []

        if vah > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="VOLUME_PROFILE_VAH",
                price_level=vah,
                direction="bearish" if bias == BiasType.BEARISH else "bullish",
                strength=min(1.0, volume_ratio),
            ))
        if val > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="VOLUME_PROFILE_VAL",
                price_level=val,
                direction="bullish" if bias == BiasType.BULLISH else "bearish",
                strength=min(1.0, volume_ratio),
            ))
        if poc > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="POC",
                price_level=poc,
                direction="",
                strength=0.7,
            ))

        # ── Build Triggers ──────────────────────────────────────────
        armed_triggers: list[dict[str, Any]] = []

        if golden_cross:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="trend_aligned",
                condition="Golden cross confirmed — trend support active",
            ))
        if death_cross:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="trend_aligned",
                condition="Death cross confirmed — trend resistance active",
            ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if golden_cross:
                primary_setup = _TREND_CONTINUATION
                backup_setup = _VWAP_PULLBACK if vah > 0 else _BREAKOUT_CONTINUATION
            elif golden_cross or rsi_oversold:
                primary_setup = _SR_BOUNCE
                backup_setup = _VWAP_PULLBACK
            else:
                primary_setup = _VWAP_PULLBACK
        elif bias == BiasType.BEARISH:
            if death_cross:
                primary_setup = _TREND_CONTINUATION
                backup_setup = _BREAKOUT_CONTINUATION
            elif rsi_overbought:
                primary_setup = _SR_BOUNCE
                backup_setup = _BREAKOUT_CONTINUATION
            else:
                primary_setup = _BREAKOUT_CONTINUATION

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if bias == BiasType.BULLISH:
            invalidation_rules.append(InvalidationRule(
                condition="VWAP relation lost — price breaks below VWAP decisively",
                price_level=0.0,
                reason="Bullish technical structure invalidated — VWAP lost",
            ))
        if bias == BiasType.BEARISH:
            invalidation_rules.append(InvalidationRule(
                condition="VWAP relation lost — price breaks above VWAP decisively",
                price_level=0.0,
                reason="Bearish technical structure invalidated — VWAP reclaimed",
            ))

        if golden_cross or death_cross:
            invalidation_rules.append(InvalidationRule(
                condition=f"MA cross invalidated — {'death' if golden_cross else 'golden'} cross appeared",
                price_level=0.0,
                reason="Primary MA signal invalidated by opposing cross",
            ))

        if atr_value > 0:
            invalidation_rules.append(InvalidationRule(
                condition="Volatility contraction — ATR drops below significance threshold",
                price_level=atr_value * 0.5,
                reason="Setup context weakened by low volatility",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Technical structure degrades — MTF alignment collapses",
                price_level=0.0,
                reason="General technical invalidation",
            ))

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            rsi_value=rsi_value,
            has_ma_cross=golden_cross or death_cross,
            volume_ratio=volume_ratio,
            has_primary_setup=primary_setup is not None,
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.5,  # Technical head uses neutral context quality
            signal_strength=min(1.0, len(signals) / 20),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if rsi_value:
            rsi_label = "overbought" if rsi_overbought else "oversold" if rsi_oversold else f"{rsi_value:.1f}"
            witness_lines.append(f"RSI: {rsi_label}")
        if golden_cross:
            witness_lines.append("Golden cross confirmed")
        if death_cross:
            witness_lines.append("Death cross confirmed")
        if atr_value:
            witness_lines.append(f"ATR: {atr_value:.2f} ({'high' if volatility_high else 'low' if volatility_low else 'normal'} vol)")
        if primary_setup:
            witness_lines.append(f"Primary: {primary_setup}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Bullish tech bias — RSI {rsi_value:.1f}, MA aligned"
            bear_case = "Risk: VWAP lost, MA cross invalidated"
        elif bias == BiasType.BEARISH:
            bear_case = f"Bearish tech bias — RSI {rsi_value:.1f}, MA aligned"
            bull_case = "Risk: VWAP reclaimed, structure flips bullish"
        else:
            bull_case = "Neutral — mixed technical signals"
            bear_case = "Neutral — waiting for clearer technical alignment"

        return {
            "bias": bias,
            "confidence": confidence,
            "dominant_tf": "1m",
            "timeframe_view": (
                f"RSI: {rsi_value:.1f}, "
                f"MA: {'golden' if golden_cross else 'death' if death_cross else 'mixed'}, "
                f"ATR: {atr_value:.2f}"
            ),
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": armed_triggers,
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"Volume ratio: {volume_ratio:.2f}, "
                f"{'confirmed cross' if cross_confirmed else 'no cross signal'}"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        """Return a safe empty interpretation when no Technical signals exist."""
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "dominant_tf": "1m",
            "timeframe_view": "No Technical signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No technical data — cannot assess",
                    price_level=0.0,
                    reason="No Floor 3 technical signals received",
                ),
            ]),
            "bull_case": "No technical data to assess",
            "bear_case": "No technical data to assess",
            "confluence_note": "Waiting for technical signals from Floor 3",
            "witness_summary": "No technical data",
        }

    def _compute_base_confidence(
        self,
        rsi_value: float,
        has_ma_cross: bool,
        volume_ratio: float,
        has_primary_setup: bool,
    ) -> float:
        """Compute base confidence from available evidence.

        Args:
            rsi_value: Current RSI value.
            has_ma_cross: Whether a significant MA cross exists.
            volume_ratio: Current volume ratio.
            has_primary_setup: Whether a primary setup was identified.

        Returns:
            Base confidence between 0.0 and 1.0.
        """
        score = 0.0

        if abs(rsi_value - 50) > 10:  # RSI shows clear direction
            score += 0.2
        if has_ma_cross:
            score += 0.3
        if volume_ratio > 1.2:
            score += 0.2
        if has_primary_setup:
            score += 0.3

        return min(1.0, score)


