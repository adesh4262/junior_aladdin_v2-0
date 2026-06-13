"""Floor 4 — Options Department Head.

Consumes Floor 3 OPTIONS signals and produces a HeadReport for Captain.

Inputs from Floor 3 (via OutputContract):
- PCR: pcr_value, pcr_change
- OI_CHANGE: oi_change_pct, strike, option_type
- WALL: wall_type (CALL_WALL/PUT_WALL), strike, oi_concentration
- IV: iv_value, iv_percentile, iv_state
- OPTIONS_PRESSURE: pressure_type, strength, direction

Output (HeadReport):
- bias (BULLISH/BEARISH/NEUTRAL)
- confidence (0.0-1.0)
- primary_setup + backup_setup
- active_zones (wall levels)
- invalidation rules (mandatory)
- witness_summary (2-3 points)

Architecture rules (LOCKED):
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

logger = get_logger("options_head")

# Setup templates
_OI_WALL_BOUNCE = "OI Wall Bounce"
_PRESSURE_CONTINUATION = "Options Pressure Continuation"
_WALL_BREAK = "Wall-Break Transition"
_PRESSURE_COLLAPSE = "Pressure Collapse Follow-Through"


class OptionsHead(BaseHead):
    """Options Head — interprets options market pressure from Floor 3 signals.

    Args:
        name: Optional name override (default ``"options"``).
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
        if not signals:
            return self._empty_interpretation()

        # Categorise
        pcr_sigs = [s for s in signals if s.indicator_type == "PCR"]
        oi_change_sigs = [s for s in signals if s.indicator_type == "OI_CHANGE"]
        wall_sigs = [s for s in signals if s.indicator_type == "WALL"]
        iv_sigs = [s for s in signals if s.indicator_type == "IV"]
        pressure_sigs = [s for s in signals if s.indicator_type == "OPTIONS_PRESSURE"]

        # ── PCR Analysis ────────────────────────────────────────────
        pcr_value = 1.0
        if pcr_sigs:
            pcr_value = pcr_sigs[-1].value.get("pcr_value", 1.0)

        # ── OI Change Analysis ──────────────────────────────────────
        ce_oi_building = [s for s in oi_change_sigs
                          if s.value.get("option_type") == "CE"
                          and s.value.get("oi_change_pct", 0) > 10]
        pe_oi_building = [s for s in oi_change_sigs
                          if s.value.get("option_type") == "PE"
                          and s.value.get("oi_change_pct", 0) > 10]

        # ── Wall Analysis ───────────────────────────────────────────
        call_walls = [s for s in wall_sigs if s.value.get("wall_type") == "CALL_WALL"]
        put_walls = [s for s in wall_sigs if s.value.get("wall_type") == "PUT_WALL"]
        active_call_wall = call_walls[-1] if call_walls else None
        active_put_wall = put_walls[-1] if put_walls else None

        # ── IV Analysis ─────────────────────────────────────────────
        iv_state = ""
        if iv_sigs:
            iv_state = iv_sigs[-1].value.get("iv_state", "")

        # ── Pressure Analysis ───────────────────────────────────────
        bullish_pressure = 0
        bearish_pressure = 0
        for sig in pressure_sigs:
            direction = sig.value.get("direction", "")
            strength = sig.value.get("strength", 0.5)
            if direction == "BULLISH":
                bullish_pressure += strength
            elif direction == "BEARISH":
                bearish_pressure += strength

        # ── Count directional signals ───────────────────────────────
        bullish_count = 0
        bearish_count = 0

        # PCR: < 0.8 = bearish (low PCR, call-heavy → potential exhaustion), > 1.2 = bullish (high PCR, put-heavy → potential fear)
        if pcr_value < 0.8:
            bearish_count += 1
        elif pcr_value > 1.2:
            bullish_count += 1

        # OI building
        bullish_count += len(pe_oi_building)
        bearish_count += len(ce_oi_building)

        # Walls
        if active_call_wall:
            bearish_count += 2  # Call wall = resistance
        if active_put_wall:
            bullish_count += 2  # Put wall = support

        # Pressure signals
        bullish_count += int(bullish_pressure)
        bearish_count += int(bearish_pressure)

        bias = compute_bias_from_signals(bullish_count, bearish_count)

        # ── Build Active Zones (walls) ──────────────────────────────
        active_zones: list[dict[str, Any]] = []

        if active_call_wall:
            active_zones.append(self._make_zone_dict(
                zone_type="CALL_WALL",
                price_level=active_call_wall.value.get("strike", 0.0),
                direction="bearish",
                strength=active_call_wall.value.get("oi_concentration", 0.5),
            ))
        if active_put_wall:
            active_zones.append(self._make_zone_dict(
                zone_type="PUT_WALL",
                price_level=active_put_wall.value.get("strike", 0.0),
                direction="bullish",
                strength=active_put_wall.value.get("oi_concentration", 0.5),
            ))

        # ── Determine Setups ────────────────────────────────────────
        primary_setup: str | None = None
        backup_setup: str | None = None

        if bias == BiasType.BULLISH:
            if active_put_wall:
                primary_setup = _OI_WALL_BOUNCE
                backup_setup = _PRESSURE_CONTINUATION if bullish_pressure > 0 else None
            elif bullish_pressure > 0:
                primary_setup = _PRESSURE_CONTINUATION
        elif bias == BiasType.BEARISH:
            if active_call_wall:
                primary_setup = _OI_WALL_BOUNCE
                backup_setup = _PRESSURE_CONTINUATION if bearish_pressure > 0 else None
            elif bearish_pressure > 0:
                primary_setup = _PRESSURE_CONTINUATION
        else:
            # NEUTRAL — check for wall break potential
            if active_call_wall:
                backup_setup = _WALL_BREAK
            elif active_put_wall:
                backup_setup = _WALL_BREAK

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules: list[InvalidationRule] = []

        if active_call_wall:
            invalidation_rules.append(InvalidationRule(
                condition="Call wall at {:.0f} breaks — resistance disappears".format(
                    active_call_wall.value.get("strike", 0.0)),
                price_level=active_call_wall.value.get("strike", 0.0),
                reason="Options invalidation — wall support/resistance removed",
            ))
        if active_put_wall:
            invalidation_rules.append(InvalidationRule(
                condition="Put wall at {:.0f} breaks — support disappears".format(
                    active_put_wall.value.get("strike", 0.0)),
                price_level=active_put_wall.value.get("strike", 0.0),
                reason="Options invalidation — wall support/resistance removed",
            ))
        if bullish_pressure > 0:
            invalidation_rules.append(InvalidationRule(
                condition="Bullish options pressure collapses",
                price_level=0.0,
                reason="Options invalidation — pressure faded",
            ))
        if bearish_pressure > 0:
            invalidation_rules.append(InvalidationRule(
                condition="Bearish options pressure collapses",
                price_level=0.0,
                reason="Options invalidation — pressure faded",
            ))

        if not invalidation_rules:
            invalidation_rules.append(InvalidationRule(
                condition="Options data flips — PCR/OI/Wall structure changes",
                price_level=0.0,
                reason="Options invalidation — structure no longer supportive",
            ))

        # ── Compute Confidence ──────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_walls=len(active_zones) > 0,
            has_primary=primary_setup is not None,
            oi_building_signals=len(ce_oi_building) + len(pe_oi_building),
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.5,
            signal_strength=min(1.0, len(signals) / 10),
        )

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if pcr_value > 0:
            witness_lines.append(f"PCR: {pcr_value:.2f}")
        if active_call_wall:
            witness_lines.append(f"CE wall: {active_call_wall.value.get('strike', 0):.0f}")
        if active_put_wall:
            witness_lines.append(f"PE wall: {active_put_wall.value.get('strike', 0):.0f}")
        if primary_setup:
            witness_lines.append(f"Setup: {primary_setup}")

        bull_case = ""
        bear_case = ""
        if bias == BiasType.BULLISH:
            bull_case = f"Put wall support at {active_put_wall.value.get('strike', 0):.0f}" if active_put_wall else "Options bullish"
            bear_case = "Risk: call wall resistance or OI flip"
        elif bias == BiasType.BEARISH:
            bear_case = f"Call wall resistance at {active_call_wall.value.get('strike', 0):.0f}" if active_call_wall else "Options bearish"
            bull_case = "Risk: put wall support or OI flip"
        else:
            bull_case = "Options neutral — no dominant pressure"
            bear_case = "Options neutral — watching for wall interactions"

        return {
            "bias": bias,
            "confidence": confidence,
            "dominant_tf": "",
            "timeframe_view": f"PCR: {pcr_value:.2f}, IV: {iv_state or 'neutral'}",
            "primary_setup": primary_setup,
            "backup_setup": backup_setup,
            "active_zones": active_zones,
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"PCR: {pcr_value:.2f}, "
                f"CE OI build: {len(ce_oi_building)}, "
                f"PE OI build: {len(pe_oi_building)}"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _empty_interpretation(self) -> dict[str, Any]:
        return {
            "bias": BiasType.NEUTRAL,
            "confidence": 0.0,
            "dominant_tf": "",
            "timeframe_view": "No options signals available",
            "primary_setup": None,
            "backup_setup": None,
            "active_zones": [],
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict([
                InvalidationRule(
                    condition="No options data — cannot assess derivatives pressure",
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
        has_walls: bool,
        has_primary: bool,
        oi_building_signals: int,
    ) -> float:
        score = 0.0
        if has_walls:
            score += 0.3
        if has_primary:
            score += 0.3
        score += min(0.3, oi_building_signals * 0.1)
        return min(1.0, score)
