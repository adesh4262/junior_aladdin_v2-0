"""Floor 4 — Macro Department Head.

**LOCKED ROLE**: Light gate / context head.
Macro Head does NOT generate setups.
Its role is permission, caution, event risk, and background bias.

Consumes Floor 3 MACRO signals (via OutputContract):
- VIX_DATA: vix_value, condition (CALM/HIGH/EXTREME)
- FII_DII_DATA: fiidii_net, fiidii_sentiment (POSITIVE/NEGATIVE/NEUTRAL)
- GLOBAL_CUE: global_cue_state (POSITIVE/NEGATIVE/NEUTRAL)
- EVENT_CALENDAR: events list, next_event, days_until_event, is_event_week
- MACRO_CONTEXT: context_summary, macro_bias

Internal Thinking:
- Is broader environment calm or risky?
- Is event risk nearby?
- Is macro background mildly supportive or cautionary?
- Should Captain become more conservative?

Primary Setup: **LOCKED — NONE**
Backup Setup: **LOCKED — NONE**

Invalidation:
- Event risk passed
- Macro caution removed
- Volatility condition normalized

Output fields unique to Macro:
- caution_level (0.0–1.0)
- event_risk_flag (bool)

No context_quality_score (only SMC/ICT require this).
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

logger = get_logger("macro_head")


class MacroHead(BaseHead):
    """Macro Head — assesses external environment risk and context.

    This is a light gate/context head. It does NOT produce setups
    (primary_setup and backup_setup are always None).

    Args:
        name: Optional name override (default ``\\\"macro\\\"``).
        config: Optional dict with tuning parameters.
    """

    def __init__(
        self,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or "macro")
        self._config = config or {}

    @property
    def head_name(self) -> str:
        return "Macro Head"

    # ── Signal Extraction ───────────────────────────────────────────────

    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[CalculatedSignal]:
        """Extract MACRO-domain signals from the OutputContract.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            Only signals where ``domain == CalculationDomain.MACRO``.
        """
        return [
            s for s in output_contract.signals
            if s.domain == CalculationDomain.MACRO
        ]

    # ── Core Interpretation ─────────────────────────────────────────────

    def _interpret(
        self,
        signals: list[CalculatedSignal],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Interpret MACRO signals and produce Head interpretation.

        Macro Head is a light gate — it does NOT produce setups.
        It reports caution_level, event_risk_flag, and a light bias.

        Args:
            signals: MACRO-domain CalculatedSignal list.
            output_contract: Full OutputContract for context.
            current_time: Current timestamp.

        Returns:
            Interpretation dict with caution_level and event_risk_flag.
        """
        if not signals:
            return self._empty_interpretation()

        # ── Categorise signals ──────────────────────────────────────
        vix_sigs = [s for s in signals if s.indicator_type == "VIX_DATA"]
        fiidii_sigs = [s for s in signals if s.indicator_type == "FII_DII_DATA"]
        global_cue_sigs = [s for s in signals if s.indicator_type == "GLOBAL_CUE"]
        event_sigs = [s for s in signals if s.indicator_type == "EVENT_CALENDAR"]
        macro_ctx_sigs = [s for s in signals if s.indicator_type == "MACRO_CONTEXT"]

        # ── VIX Analysis ────────────────────────────────────────────
        vix_condition = ""
        vix_value = 0.0
        if vix_sigs:
            latest_vix = vix_sigs[-1].value
            vix_value = latest_vix.get("vix_value", 0.0)
            vix_condition = latest_vix.get("condition", "")

        # ── FII/DII Analysis ────────────────────────────────────────
        fiidii_sentiment = ""
        fiidii_net = 0.0
        if fiidii_sigs:
            latest_fiidii = fiidii_sigs[-1].value
            fiidii_net = latest_fiidii.get("fiidii_net", 0.0)
            fiidii_sentiment = latest_fiidii.get("fiidii_sentiment", "")

        # ── Global Cue Analysis ─────────────────────────────────────
        global_cue_state = ""
        if global_cue_sigs:
            latest_cue = global_cue_sigs[-1].value
            global_cue_state = latest_cue.get("global_cue_state", "")

        # ── Event Calendar Analysis ─────────────────────────────────
        is_event_week = False
        days_until_event = 999
        next_event = ""
        if event_sigs:
            latest_event = event_sigs[-1].value
            is_event_week = latest_event.get("is_event_week", False)
            days_until_event = latest_event.get("days_until_event", 999)
            next_event = latest_event.get("next_event", "")

        # ── Macro Context Analysis ──────────────────────────────────
        macro_ctx_bias = ""
        ctx_summary = ""
        if macro_ctx_sigs:
            latest_ctx = macro_ctx_sigs[-1].value
            macro_ctx_bias = latest_ctx.get("macro_bias", "")
            ctx_summary = latest_ctx.get("context_summary", "")

        # ── Compute Caution Level ──────────────────────────────────
        caution_factors: list[float] = []

        # VIX contribution
        if vix_condition == "EXTREME":
            caution_factors.append(0.30)
        elif vix_condition == "HIGH":
            caution_factors.append(0.15)

        # FII/DII contribution
        if fiidii_sentiment == "NEGATIVE":
            caution_factors.append(0.20)
        elif fiidii_sentiment == "POSITIVE":
            caution_factors.append(-0.10)  # Slightly reduces caution

        # Global cue contribution
        if global_cue_state == "NEGATIVE":
            caution_factors.append(0.15)
        elif global_cue_state == "POSITIVE":
            caution_factors.append(-0.05)

        # Event risk contribution
        if is_event_week:
            caution_factors.append(0.20)
        elif days_until_event < 3:
            caution_factors.append(0.10)

        # Macro context bias
        if macro_ctx_bias == "bearish":
            caution_factors.append(0.15)
        elif macro_ctx_bias == "bullish":
            caution_factors.append(-0.05)

        # Aggregate caution level (clamp 0.0–1.0)
        caution_level = max(0.0, min(1.0, sum(caution_factors)))

        # ── Compute Event Risk Flag ─────────────────────────────────
        event_risk_flag = is_event_week or (days_until_event < 2 and days_until_event > 0)

        # ── Count directional signals ──────────────────────────────
        bullish_count = 0
        bearish_count = 0

        # VIX: high/extreme VIX = bearish (fear)
        if vix_condition in ("HIGH", "EXTREME"):
            bearish_count += 1
        elif vix_condition == "CALM":
            bullish_count += 1

        # FII/DII: net selling = bearish, net buying = bullish
        if fiidii_sentiment == "POSITIVE":
            bullish_count += 1
        elif fiidii_sentiment == "NEGATIVE":
            bearish_count += 1

        # Global cue
        if global_cue_state == "POSITIVE":
            bullish_count += 1
        elif global_cue_state == "NEGATIVE":
            bearish_count += 1

        # Event week is slightly bearish (uncertainty)
        if is_event_week:
            bearish_count += 1

        # Macro context
        if macro_ctx_bias == "bullish":
            bullish_count += 1
        elif macro_ctx_bias == "bearish":
            bearish_count += 1

        # ── Determine Bias ──────────────────────────────────────────
        # Macro bias is deliberately "light" — use a higher neutral threshold
        # so macro doesn't overpower core price/structure analysis
        bias = compute_bias_from_signals(bullish_count, bearish_count, neutral_threshold=0.35)

        # ── Build Triggers (event-related) ──────────────────────────
        armed_triggers: list[dict[str, Any]] = []

        if event_risk_flag:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="event_risk",
                condition=f"Event risk: {next_event or 'upcoming event'} — {days_until_event} day(s) away",
            ))

        if caution_level > 0.5:
            armed_triggers.append(self._make_trigger_dict(
                trigger_type="caution_active",
                condition=f"Macro caution level elevated ({caution_level:.2f})",
            ))

        # ── NO setups — Macro is a gate/context head ────────────────
        # LOCKED: primary_setup and backup_setup must be None

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if caution_level > 0.3:
            invalidation_rules.append(InvalidationRule(
                condition="Macro caution condition resolved — environment normalised",
                price_level=0.0,
                reason="Macro caution invalidation — risk factors cleared",
            ))
        if event_risk_flag:
            invalidation_rules.append(InvalidationRule(
                condition=f"Event risk passed — {next_event or 'event'} concluded without disruption",
                price_level=0.0,
                reason="Event risk invalidation — window closed",
            ))
        if vix_condition in ("HIGH", "EXTREME"):
            invalidation_rules.append(InvalidationRule(
                condition=f"VIX normalised from {vix_condition} — volatility contraction",
                price_level=0.0,
                reason="VIX volatility invalidation — fear subsided",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Macro environment state shifts significantly",
                price_level=0.0,
                reason="General macro invalidation",
            ))

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_vix=len(vix_sigs) > 0,
            has_fiidii=len(fiidii_sigs) > 0,
            has_global_cue=len(global_cue_sigs) > 0,
            has_events=len(event_sigs) > 0,
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.5,  # No context_quality_score for macro
            signal_strength=min(1.0, len(signals) / 10),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if vix_value:
            witness_lines.append(f"VIX: {vix_value:.1f} ({vix_condition})")
        if fiidii_sentiment:
            witness_lines.append(f"FII/DII: {fiidii_sentiment} (net: {fiidii_net:+.1f})")
        if global_cue_state:
            witness_lines.append(f"Global: {global_cue_state}")
        if next_event:
            witness_lines.append(f"Event: {next_event} in {days_until_event}d")
        witness_lines.append(f"Caution: {caution_level:.2f}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            if caution_level > 0.4:
                bull_case = "Mildly bullish macro — environment supportive but caution elevated"
            else:
                bull_case = "Bullish macro — VIX calm, FII/DII supportive, global cues positive"
            bear_case = f"Risk: event risk ({next_event}) or VIX spike changes backdrop"
        elif bias == BiasType.BEARISH:
            bear_case = f"Bearish macro — VIX {vix_condition}, FII/DII {fiidii_sentiment}"
            bull_case = "Risk: caution fades, event risk passes without disruption"
        else:
            if caution_level > 0.5:
                bull_case = "Neutral macro — caution elevated, awaiting event clarity"
                bear_case = "Neutral macro — caution elevated, environment uncertain"
            else:
                bull_case = "Neutral macro — no strong directional signal"
                bear_case = "Neutral macro — environment quiet, monitoring for shifts"

        return {
            "bias": bias,
            "confidence": confidence,
            "caution_level": caution_level,
            "event_risk_flag": event_risk_flag,
            "dominant_tf": "1d",  # Macro operates on daily scale
            "timeframe_view": (
                f"VIX: {vix_condition or 'unknown'}, "
                f"FII/DII: {fiidii_sentiment or 'unknown'}, "
                f"Event: {next_event or 'none'}"
            ),
            "primary_setup": None,      # LOCKED — no setups
            "backup_setup": None,        # LOCKED — no setups
            "active_zones": [],           # Macro doesn't maintain price zones
            "armed_triggers": armed_triggers,
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"Caution: {caution_level:.2f}, "
                f"Event risk: {'YES' if event_risk_flag else 'NO'}, "
                f"Context: {ctx_summary or 'no macro context'}"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        """Return a safe empty interpretation when no MACRO signals exist."""
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "caution_level": 0.0,
            "event_risk_flag": False,
            "dominant_tf": "1d",
            "timeframe_view": "No MACRO signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No macro data — cannot assess external environment risk",
                    price_level=0.0,
                    reason="No Floor 3 MACRO signals received",
                ),
            ]),
            "bull_case": "No macro data to assess",
            "bear_case": "No macro data to assess",
            "confluence_note": "Waiting for MACRO signals from Floor 3",
            "witness_summary": "No macro data",
        }

    def _compute_base_confidence(
        self,
        has_vix: bool,
        has_fiidii: bool,
        has_global_cue: bool,
        has_events: bool,
    ) -> float:
        """Compute base confidence from available evidence.

        Args:
            has_vix: Whether VIX data exists.
            has_fiidii: Whether FII/DII data exists.
            has_global_cue: Whether global cue data exists.
            has_events: Whether event calendar data exists.

        Returns:
            Base confidence between 0.0 and 1.0.
        """
        score = 0.0

        if has_vix:
            score += 0.3
        if has_fiidii:
            score += 0.2
        if has_global_cue:
            score += 0.2
        if has_events:
            score += 0.3

        return min(1.0, score)
