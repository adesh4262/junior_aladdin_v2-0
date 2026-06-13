"""Floor 4 — Macro Department Head.

**LOCKED ROLE**: Light gate / context head.
Macro Head is NOT a directional setup machine.
Its role is permission and caution: assess whether the broader environment
allows or discourages taking directional risk.

Inputs from Floor 3 (via OutputContract):
- VIX: vix_value, vix_change
- FII_DII: net_state (BUY/SELL/NEUTRAL), magnitude
- EVENT_CALENDAR: event_type, risk_level, time_until
- MACRO_ENVIRONMENT: environment_state (STABLE/CAUTIOUS/STRESSED)

Internal Thinking:
- Is broader environment calm or risky?
- Is event risk nearby?
- Should Captain become more conservative?

Primary Setup: **LOCKED — NONE**
Backup Setup: **LOCKED — NONE**

Invalidation (gate sense):
- Event risk passed
- Macro caution removed
- Volatility condition normalised

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
    compute_confidence,
)
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import BiasType

logger = get_logger("macro_head")


class MacroHead(BaseHead):
    """Macro Head — light gate/context head for macro-environment assessment.

    **LOCKED**: This head does NOT produce primary_setup or backup_setup.
    Its role is permission and caution, not directional trading.

    Args:
        name: Optional name override (default ``"macro"``).
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
        """Interpret macro signals — VIX, FII/DII, event risk, environment.

        Returns a dict with:
        - bias (light leaning)
        - confidence
        - caution_level (0.0-1.0)
        - event_risk_flag
        - primary_setup = None (LOCKED)
        - backup_setup = None (LOCKED)
        - invalidation rules
        """
        if not signals:
            return self._empty_interpretation()

        # Categorise
        vix_sigs = [s for s in signals if s.indicator_type == "VIX"]
        fii_sigs = [s for s in signals if s.indicator_type == "FII_DII"]
        event_sigs = [s for s in signals if s.indicator_type == "EVENT_CALENDAR"]
        env_sigs = [s for s in signals if s.indicator_type == "MACRO_ENVIRONMENT"]

        # ── VIX Analysis ────────────────────────────────────────────
        vix_value = 15.0
        for sig in vix_sigs:
            vix_value = sig.value.get("vix_value", vix_value)

        vix_calm = vix_value < 14
        vix_elevated = 14 <= vix_value <= 20
        vix_stressed = vix_value > 20

        # ── FII/DII Analysis ────────────────────────────────────────
        fii_net = "NEUTRAL"
        fii_magnitude = 0.0
        for sig in fii_sigs:
            fii_net = sig.value.get("net_state", "NEUTRAL")
            fii_magnitude = sig.value.get("magnitude", 0.0)

        # ── Event Calendar Analysis ─────────────────────────────────
        event_risk_flag = False
        event_types: list[str] = []
        highest_event_risk = 0.0
        for sig in event_sigs:
            risk = sig.value.get("risk_level", 0.0)
            if risk > highest_event_risk:
                highest_event_risk = risk
                event_risk_flag = risk > 0.5
            event_type = sig.value.get("event_type", "unknown")
            if risk > 0.3 and event_type not in event_types:
                event_types.append(event_type)

        # ── Environment Analysis ────────────────────────────────────
        env_state = "STABLE"
        for sig in env_sigs:
            env_state = sig.value.get("environment_state", "STABLE")

        # ── Determine caution level ─────────────────────────────────
        caution_level = 0.0

        if vix_stressed:
            caution_level += 0.4
        elif vix_elevated:
            caution_level += 0.2

        if fii_net == "SELL" and fii_magnitude > 500:
            caution_level += 0.3
        elif fii_net == "SELL":
            caution_level += 0.15

        if event_risk_flag:
            caution_level += 0.3 * min(1.0, highest_event_risk)

        if env_state == "STRESSED":
            caution_level += 0.3
        elif env_state == "CAUTIOUS":
            caution_level += 0.15

        caution_level = min(1.0, caution_level)

        # ── Determine light bias ────────────────────────────────────
        # Macro bias is a LIGHT leaning, not a strong directional signal
        bias = BiasType.NEUTRAL
        if caution_level < 0.2 and fii_net == "BUY":
            bias = BiasType.BULLISH  # Mildly supportive
        elif caution_level > 0.6:
            bias = BiasType.BEARISH  # Restrictive
        elif caution_level > 0.3 and fii_net == "SELL":
            bias = BiasType.BEARISH  # Mildly cautious

        # ── Build Invalidation (gate sense) ─────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if vix_stressed or vix_elevated:
            invalidation_rules.append(InvalidationRule(
                condition="VIX normalised below 14 — volatility risk subsided",
                price_level=0.0,
                reason="Macro invalidation — volatility condition normalised",
            ))

        if event_risk_flag:
            invalidation_rules.append(InvalidationRule(
                condition=f"Event risk passed: {', '.join(event_types) if event_types else 'calendar cleared'}",
                price_level=0.0,
                reason="Macro invalidation — event risk no longer active",
            ))

        if caution_level > 0.4:
            invalidation_rules.append(InvalidationRule(
                condition="Macro caution removed — environment improved",
                price_level=0.0,
                reason="Macro invalidation — caution lifted",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Macro environment remains benign — no change",
                price_level=0.0,
                reason="Macro invalidation baseline — monitoring for deterioration",
            ))

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_vix=len(vix_sigs) > 0,
            has_fii=len(fii_sigs) > 0,
            has_events=len(event_sigs) > 0,
            signal_count=len(signals),
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.5,
            signal_strength=min(1.0, len(signals) / 8),
        )

        # ── Build Summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if vix_value > 0:
            witness_lines.append(f"VIX: {vix_value:.1f}")
        if fii_net != "NEUTRAL":
            witness_lines.append(f"FII/DII: {fii_net}")
        if event_risk_flag:
            witness_lines.append(f"Event risk: {', '.join(event_types)}")
        if env_state != "STABLE":
            witness_lines.append(f"Environment: {env_state}")
        if not witness_lines:
            witness_lines.append("Macro environment calm")

        bull_case = ""
        bear_case = ""
        if caution_level < 0.3:
            bull_case = "Macro environment permits normal trading"
            bear_case = "Monitor for VIX spike or event risk"
        elif caution_level < 0.6:
            bull_case = "Macro conditions acceptable with caution"
            bear_case = "Caution advised — elevated risk factors"
        else:
            bull_case = "Macro conditions are restrictive — consider waiting"
            bear_case = "Strong caution — multiple risk factors active"

        return {
            "bias": bias,
            "confidence": confidence,
            "caution_level": caution_level,
            "event_risk_flag": event_risk_flag,
            "dominant_tf": "1d",
            "timeframe_view": (
                f"VIX: {vix_value:.1f}, "
                f"FII: {fii_net}, "
                f"Env: {env_state}"
            ),
            "primary_setup": None,    # LOCKED — no setups
            "backup_setup": None,      # LOCKED — no setups
            "active_zones": [],
            "armed_triggers": self._build_event_triggers(event_types, event_risk_flag, highest_event_risk),
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"VIX: {vix_value:.1f}, "
                f"FII: {fii_net} ({fii_magnitude:.0f}), "
                f"Events: {'active' if event_risk_flag else 'none'}"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "caution_level": 0.0,
            "event_risk_flag": False,
            "dominant_tf": "1d",
            "timeframe_view": "No macro signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No macro data — environment status unknown",
                    price_level=0.0,
                    reason="No Floor 3 macro signals received",
                ),
            ]),
            "bull_case": "Macro environment status unknown",
            "bear_case": "Macro environment status unknown",
            "confluence_note": "Waiting for macro signals from Floor 3",
            "witness_summary": "No macro data",
        }

    def _compute_base_confidence(
        self,
        has_vix: bool,
        has_fii: bool,
        has_events: bool,
        signal_count: int,
    ) -> float:
        score = 0.0
        if has_vix:
            score += 0.3
        if has_fii:
            score += 0.3
        if has_events:
            score += 0.2
        score += min(0.15, signal_count * 0.03)
        return min(1.0, score)

    def _build_event_triggers(
        self,
        event_types: list[str],
        event_risk_flag: bool,
        highest_risk: float,
    ) -> list[dict[str, Any]]:
        """Build armed triggers for macro events when event risk is active.

        Args:
            event_types: List of upcoming event names.
            event_risk_flag: Whether any event has risk > 0.5.
            highest_risk: The highest risk level among active events (0.0-1.0).

        Returns:
            List of trigger dicts, one per event type with risk-adjusted price level.
        """
        if not event_risk_flag or not event_types:
            return []
        risk_pct = round(highest_risk * 100, 0)
        triggers = []
        for evt in event_types:
            triggers.append(self._make_trigger_dict(
                trigger_type="event_risk",
                condition=f"{evt} resolves (risk: {risk_pct:.0f}%) — macro event risk clears",
                zone_ref="",
                status="PENDING",
            ))
        return triggers
