"""Floor 4 — Technical Department Head.

Consumes Floor 3 TECHNICAL signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- TREND: trend_state, mtf_alignment, supertrend
- MOMENTUM: momentum_state, adx_value
- RSI: rsi_value, oversold, overbought
- MA_FAST / MA_SLOW: ma_value, ma_type, period
- VWAP: vwap_value, vwap_distance_pct
- ATR: atr_value
- VOLUME_PROFILE: poc, vah, val

Output (HeadReport):
- bias (BULLISH/BEARISH/NEUTRAL)
- confidence (0.0–1.0)
- primary_setup + backup_setup
- active_zones (key technical levels)
- invalidation rules (mandatory)
- witness_summary (2-3 points)

Architecture rules (LOCKED):
- Basic candle pattern logic belongs here, not in SMC/ICT.
- No context_quality_score (only SMC/ICT require this).
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

logger = get_logger("technical_head")

# Setup templates
_VWAP_PULLBACK = "VWAP Pullback Continuation"
_TREND_CONTINUATION = "Trend Continuation Reclaim"
_MTF_BREAKOUT = "MTF Breakout Continuation"
_SUPPORT_RESISTANCE = "Support/Resistance Rebound"


class TechnicalHead(BaseHead):
    """Technical Head — interprets market technical health from Floor 3 signals.

    Args:
        name: Optional name override (default ``"technical"``).
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
        """Extract TECHNICAL-domain signals from the OutputContract."""
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
        """Interpret technical signals and produce Head interpretation."""
        if not signals:
            return self._empty_interpretation()

        # ── Categorise signals ──────────────────────────────────────
        trend_sigs = [s for s in signals if s.indicator_type == "TREND"]
        momentum_sigs = [s for s in signals if s.indicator_type == "MOMENTUM"]
        rsi_sigs = [s for s in signals if s.indicator_type == "RSI"]
        vwap_sigs = [s for s in signals if s.indicator_type == "VWAP"]
        ma_sigs = [s for s in signals if s.indicator_type.startswith("MA_")]
        atr_sigs = [s for s in signals if s.indicator_type == "ATR"]
        profile_sigs = [s for s in signals if s.indicator_type == "VOLUME_PROFILE"]

        # ── Trend Analysis ──────────────────────────────────────────
        trend_state = ""
        mtf_alignment = ""
        trend_aligned = False

        if trend_sigs:
            ts = trend_sigs[-1].value
            trend_state = ts.get("trend_state", "")
            mtf_alignment = ts.get("mtf_alignment", "")
            trend_aligned = mtf_alignment == "ALIGNED"

        # ── Momentum Analysis ───────────────────────────────────────
        momentum_state = ""
        adx_value = 0.0
        if momentum_sigs:
            ms = momentum_sigs[-1].value
            momentum_state = ms.get("momentum_state", "")
            adx_value = ms.get("adx_value", 0.0)

        # ── RSI Analysis ────────────────────────────────────────────
        rsi_value = 50.0
        oversold = False
        overbought = False
        if rsi_sigs:
            rs = rsi_sigs[-1].value
            rsi_value = rs.get("rsi_value", 50.0)
            oversold = rs.get("oversold", False)
            overbought = rs.get("overbought", False)

        # ── VWAP Analysis ───────────────────────────────────────────
        vwap_value = 0.0
        vwap_distance_pct = 0.0
        above_vwap = False
        if vwap_sigs:
            vs = vwap_sigs[-1].value
            vwap_value = vs.get("vwap_value", 0.0)
            vwap_distance_pct = vs.get("vwap_distance_pct", 0.0)
            above_vwap = vwap_distance_pct > 0

        # ── Moving Average Analysis ─────────────────────────────────
        fast_ma = 0.0
        slow_ma = 0.0
        for sig in ma_sigs:
            if sig.indicator_type == "MA_FAST":
                fast_ma = sig.value.get("ma_value", 0.0)
            elif sig.indicator_type == "MA_SLOW":
                slow_ma = sig.value.get("ma_value", 0.0)

        # ── Build directional counts ────────────────────────────────
        bullish_count = 0
        bearish_count = 0

        if trend_state in ("STRONG_UP", "WEAK_UP"):
            bullish_count += 2 if trend_aligned else 1
        elif trend_state in ("STRONG_DOWN", "WEAK_DOWN"):
            bearish_count += 2 if trend_aligned else 1

        if momentum_state == "STRONG":
            bullish_count += 1 if trend_state in ("STRONG_UP", "WEAK_UP") else 0
            bearish_count += 1 if trend_state in ("STRONG_DOWN", "WEAK_DOWN") else 0

        if not oversold and not overbought and 40 <= rsi_value <= 60:
            pass  # Neutral RSI — no directional signal
        elif oversold:
            bullish_count += 1  # Oversold → potential bounce
        elif overbought:
            bearish_count += 1  # Overbought → potential pullback

        if vwap_value > 0:
            if above_vwap:
                bullish_count += 1
            else:
                bearish_count += 1

        if fast_ma > slow_ma > 0:
            bullish_count += 1
        elif slow_ma > fast_ma > 0:
            bearish_count += 1

        # ── Determine Bias ──────────────────────────────────────────
        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones (technical levels) ───────────────────
        active_zones: list[dict[str, Any]] = []

        if vwap_value > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="VWAP",
                price_level=vwap_value,
                direction="bullish" if above_vwap else "bearish",
                strength=0.6,
            ))
        if fast_ma > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="MA_FAST",
                price_level=fast_ma,
                direction="bullish" if fast_ma > slow_ma else "bearish",
                strength=0.5,
            ))
        if slow_ma > 0:
            active_zones.append(self._make_zone_dict(
                zone_type="MA_SLOW",
                price_level=slow_ma,
                direction="bullish" if fast_ma > slow_ma else "bearish",
                strength=0.7,
            ))

        # Volume profile levels
        if profile_sigs:
            vp = profile_sigs[-1].value
            poc = vp.get("poc", 0.0)
            vah = vp.get("vah", 0.0)
            val = vp.get("val", 0.0)
            if poc > 0:
                active_zones.append(self._make_zone_dict(
                    zone_type="POC",
                    price_level=poc,
                    direction="neutral",
                    strength=0.8,
                ))
            if vah > 0:
                active_zones.append(self._make_zone_dict(
                    zone_type="VAH",
                    price_level=vah,
                    direction="bearish",
                    strength=0.6,
                ))
            if val > 0:
                active_zones.append(self._make_zone_dict(
                    zone_type="VAL",
                    price_level=val,
                    direction="bullish",
                    strength=0.6,
                ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if vwap_value > 0:
                primary_setup = _VWAP_PULLBACK
                backup_setup = _TREND_CONTINUATION if trend_aligned else None
            elif trend_aligned:
                primary_setup = _TREND_CONTINUATION
                backup_setup = _MTF_BREAKOUT
            else:
                primary_setup = _SUPPORT_RESISTANCE
        elif bias == BiasType.BEARISH:
            if vwap_value > 0:
                primary_setup = _VWAP_PULLBACK
                backup_setup = _TREND_CONTINUATION if trend_aligned else None
            elif trend_aligned:
                primary_setup = _TREND_CONTINUATION
                backup_setup = _MTF_BREAKOUT
            else:
                primary_setup = _SUPPORT_RESISTANCE
        else:
            # NEUTRAL — check for oversold/overbought mean reversion
            if oversold:
                primary_setup = _SUPPORT_RESISTANCE
            elif overbought:
                backup_setup = _SUPPORT_RESISTANCE
            elif vwap_value > 0 and abs(vwap_distance_pct) > 0.5:
                primary_setup = _VWAP_PULLBACK

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if trend_aligned:
            invalidation_rules.append(InvalidationRule(
                condition="MTF alignment collapses — trend structure broken",
                price_level=self._find_key_level(active_zones, "MA_SLOW"),
                reason="Technical invalidation — MTF alignment lost",
            ))

        if vwap_value > 0:
            invalidation_rules.append(InvalidationRule(
                condition=f"VWAP relation lost decisively (distance > 1%)",
                price_level=vwap_value,
                reason="Technical invalidation — VWAP deviation too large",
            ))

        if fast_ma > 0 and slow_ma > 0:
            invalidation_rules.append(InvalidationRule(
                condition="MA crossover reverses direction",
                price_level=(fast_ma + slow_ma) / 2,
                reason="Technical invalidation — MA structure reversed",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Technical structure breaks against current bias",
                price_level=0.0,
                reason="Technical invalidation — structure no longer supportive",
            ))

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            trend_aligned=trend_aligned,
            has_primary=primary_setup is not None,
            signal_count=len(signals),
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.6 if trend_aligned else 0.3,
            signal_strength=min(1.0, len(signals) / 15),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if trend_state:
            witness_lines.append(f"Trend: {trend_state}")
        if mtf_alignment:
            witness_lines.append(f"MTF: {mtf_alignment}")
        if primary_setup:
            witness_lines.append(f"Setup: {primary_setup}")

        view_parts = []
        if trend_state:
            view_parts.append(f"Trend {trend_state}")
        if mtf_alignment:
            view_parts.append(f"MTF {mtf_alignment}")
        if rsi_value:
            view_parts.append(f"RSI {rsi_value:.0f}")
        timeframe_view = " | ".join(view_parts) if view_parts else "No technical data"

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Trend {trend_state} aligned ({mtf_alignment}), RSI {rsi_value:.0f}"
            bear_case = "Risk: VWAP rejection or trend breakdown"
        elif bias == BiasType.BEARISH:
            bear_case = f"Trend {trend_state} aligned ({mtf_alignment}), RSI {rsi_value:.0f}"
            bull_case = "Risk: VWAP reclaim or trend reversal"
        else:
            bull_case = "Technical neutral — range conditions"
            bear_case = "Waiting for MTF alignment"

        return {
            "bias": bias,
            "confidence": confidence,
            "dominant_tf": "1m",
            "timeframe_view": timeframe_view,
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"RSI {rsi_value:.0f} | "
                f"ADX {adx_value:.1f} | "
                f"VWAP dist {vwap_distance_pct:+.2f}%"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "dominant_tf": "1m",
            "timeframe_view": "No technical signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No technical data — cannot assess structure",
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
        trend_aligned: bool,
        has_primary: bool,
        signal_count: int,
    ) -> float:
        score = 0.0
        if trend_aligned:
            score += 0.4
        if has_primary:
            score += 0.3
        score += min(0.2, signal_count * 0.02)
        return min(1.0, score)

    def _find_key_level(
        self,
        zones: list[dict[str, Any]],
        zone_type: str,
    ) -> float:
        for z in zones:
            if z.get("zone_type") == zone_type:
                return z.get("price_level", 0.0)
        return 0.0
