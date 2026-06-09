"""Floor 4 — Psychology Department Head.

**LOCKED ROLE**: Balanced brake head.
Psychology Head is NOT a directional setup machine.
Its role is discipline protection: brake, cool down, block when needed.

Consumes Floor 3 PSYCHOLOGY signals (system-internal, via OutputContract):
- DISCIPLINE_REPORT: trade_allowed, block_reason
- COOLDOWN_STATUS: cooldown_active, cooldown_remaining_s
- MISTAKE_REPORT: mistake_count, same_zone_failures
- TRAP_ALERT: trap_pressure, trap_density
- LOSS_REPORT: loss_count, sequence_length

Internal Thinking:
- Is disciplined action appropriate right now?
- Is cooldown active?
- Are repeated mistakes happening?
- Is trap density unusually high?
- Should trading be blocked entirely?

Primary Setup: **LOCKED — NONE**
Backup Setup: **LOCKED — NONE**

Invalidation (brake sense):
- Cooldown completed
- Repeated mistake risk cleared
- Block condition lifted

Output fields unique to Psychology:
- trade_allowed (bool)
- caution_level (0.0–1.0)
- cooldown_active (bool)
- repeated_mistake_flag (bool)
- trap_pressure (bool)
- block_reason (str)

No context_quality_score (only SMC/ICT require this).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

logger = get_logger("psychology_head")


@dataclass
class PsychologyMemory:
    """Internal state tracking for Psychology Head.

    Tracks behavioral state across refresh cycles.
    """
    trade_allowed: bool = True
    caution_level: float = 0.0
    cooldown_active: bool = False
    cooldown_remaining_s: float = 0.0
    repeated_mistake_flag: bool = False
    mistake_count: int = 0
    same_zone_failures: int = 0
    trap_pressure: bool = False
    trap_density: float = 0.0
    block_reason: str = ""
    loss_count: int = 0
    loss_sequence_length: int = 0


class PsychologyHead(BaseHead):
    """Psychology Head — monitors system discipline and applies brakes when needed.

    This is a balanced brake head. It does NOT produce setups
    (primary_setup and backup_setup are always None).

    Args:
        name: Optional name override (default ``\\"psychology\\"``).
        config: Optional dict with tuning parameters and initial state.
    """

    def __init__(
        self,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or "psychology")
        self._config = config or {}
        self._psych_memory = PsychologyMemory(
            trade_allowed=self._config.get("trade_allowed", True),
            caution_level=self._config.get("caution_level", 0.0),
            cooldown_active=self._config.get("cooldown_active", False),
        )
        # Track last refresh time for cooldown decay
        self._last_refresh: datetime | None = None

    @property
    def head_name(self) -> str:
        return "Psychology Head"

    # ── State Helpers (for tests) ────────────────────────────────────────

    def set_state(
        self,
        trade_allowed: bool | None = None,
        cooldown_active: bool | None = None,
        repeated_mistake_flag: bool | None = None,
        trap_pressure: bool | None = None,
        block_reason: str | None = None,
        caution_level: float | None = None,
        mistake_count: int | None = None,
        same_zone_failures: int | None = None,
        loss_count: int | None = None,
        loss_sequence_length: int | None = None,
    ) -> None:
        """Set internal state directly (useful for testing)."""
        if trade_allowed is not None:
            self._psych_memory.trade_allowed = trade_allowed
        if cooldown_active is not None:
            self._psych_memory.cooldown_active = cooldown_active
        if repeated_mistake_flag is not None:
            self._psych_memory.repeated_mistake_flag = repeated_mistake_flag
        if trap_pressure is not None:
            self._psych_memory.trap_pressure = trap_pressure
        if block_reason is not None:
            self._psych_memory.block_reason = block_reason
        if caution_level is not None:
            self._psych_memory.caution_level = caution_level
        if mistake_count is not None:
            self._psych_memory.mistake_count = mistake_count
        if same_zone_failures is not None:
            self._psych_memory.same_zone_failures = same_zone_failures
        if loss_count is not None:
            self._psych_memory.loss_count = loss_count
        if loss_sequence_length is not None:
            self._psych_memory.loss_sequence_length = loss_sequence_length

    # ── Signal Extraction ───────────────────────────────────────────────

    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[CalculatedSignal]:
        """Extract PSYCHOLOGY-domain signals from the OutputContract.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            Only signals where ``domain == CalculationDomain.PSYCHOLOGY``.
        """
        return [
            s for s in output_contract.signals
            if s.domain == CalculationDomain.PSYCHOLOGY
        ]

    # ── Core Interpretation ─────────────────────────────────────────────

    def _interpret(
        self,
        signals: list[CalculatedSignal],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Interpret PSYCHOLOGY signals and produce Head interpretation.

        Processes discipline, cooldown, mistake, and trap signals to
        determine whether trading should be allowed, braked, or blocked.

        Args:
            signals: PSYCHOLOGY-domain CalculatedSignal list.
            output_contract: Full OutputContract for context.
            current_time: Current timestamp.

        Returns:
            Interpretation dict with trade_allowed, caution_level,
            cooldown_active, repeated_mistake_flag, trap_pressure,
            and block_reason.
        """
        # ── Decay cooldown based on time elapsed ─────────────────────
        self._decay_cooldown(current_time)

        # ── Process signals to update internal state ─────────────────
        self._process_signals(signals)

        # ── Derive trade_allowed from internal state ─────────────────
        trade_allowed = self._derive_trade_allowed()
        block_reason = self._psych_memory.block_reason if not trade_allowed else ""

        # ── Compute caution level ────────────────────────────────────
        caution_level = self._compute_caution_level()

        # ── Build Invalidation ──────────────────────────────────────
        invalidation_rules = self._build_invalidation_rules(
            current_time=current_time,
        )

        # ── Compute Confidence ───────────────────────────────────────
        base_score = self._compute_base_confidence(
            has_recent_signals=len(signals) > 0,
        )
        confidence = compute_confidence(
            base_score=base_score,
            freshness_score=self._compute_approx_freshness(current_time),
            context_quality=0.5,  # No context_quality_score for psychology
            signal_strength=min(1.0, len(signals) / 5),
        )

        # ── Determine light bias (supportive/restrictive) ────────────
        bias = self._derive_bias()

        # ── Build summaries ─────────────────────────────────────────
        witness_lines: list[str] = []
        if not trade_allowed:
            witness_lines.append(f"BLOCKED: {block_reason}")
        if self._psych_memory.cooldown_active:
            remaining = int(self._psych_memory.cooldown_remaining_s)
            witness_lines.append(f"Cooldown active ({remaining}s remaining)")
        if self._psych_memory.repeated_mistake_flag:
            witness_lines.append(
                f"Repeated mistakes: {self._psych_memory.same_zone_failures} zone failures"
            )
        if self._psych_memory.trap_pressure:
            witness_lines.append(f"Trap pressure: {self._psych_memory.trap_density:.2f}")
        if self._psych_memory.loss_sequence_length > 1:
            witness_lines.append(
                f"Loss sequence: {self._psych_memory.loss_sequence_length} in a row"
            )
        if not witness_lines:
            witness_lines.append("Discipline OK — no brakes active")

        bull_case = ""
        bear_case = ""
        if trade_allowed:
            bull_case = "Discipline clear — system may act"
            bear_case = "Risk: discipline degrades with consecutive losses"
        else:
            bull_case = f"Blocked: {block_reason}"
            bear_case = "Waiting for brake condition to clear"

        # ── NO setups — locked ──────────────────────────────────────
        return {
            "bias": bias,
            "confidence": confidence,
            "trade_allowed": trade_allowed,
            "caution_level": caution_level,
            "cooldown_active": self._psych_memory.cooldown_active,
            "repeated_mistake_flag": self._psych_memory.repeated_mistake_flag,
            "trap_pressure": self._psych_memory.trap_pressure,
            "block_reason": block_reason,
            "dominant_tf": "",  # Psychology is session-based, no dominant TF
            "timeframe_view": (
                "Discipline OK" if trade_allowed
                else f"Blocked: {block_reason}"
            ),
            "primary_setup": None,      # LOCKED — no setups
            "backup_setup": None,        # LOCKED — no setups
            "active_zones": [],           # Psychology doesn't maintain zones
            "armed_triggers": [],
            "invalidation": self._make_invalidation_dict(invalidation_rules),
            "bull_case": bull_case,
            "bear_case": bear_case,
            "confluence_note": (
                f"Trade allowed: {trade_allowed}, "
                f"Caution: {caution_level:.2f}, "
                f"Cooldown: {'active' if self._psych_memory.cooldown_active else 'inactive'}, "
                f"Mistakes: {self._psych_memory.mistake_count}"
            ),
            "witness_summary": " | ".join(witness_lines),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _process_signals(self, signals: list[CalculatedSignal]) -> None:
        """Process PSYCHOLOGY signals and update internal state.

        Args:
            signals: PSYCHOLOGY-domain signals to process.
        """
        for sig in signals:
            indicator_type = sig.indicator_type
            value = sig.value or {}

            if indicator_type == "DISCIPLINE_REPORT":
                self._psych_memory.trade_allowed = value.get("trade_allowed", self._psych_memory.trade_allowed)
                if not self._psych_memory.trade_allowed:
                    self._psych_memory.block_reason = value.get("block_reason", "Blocked by discipline report")

            elif indicator_type == "COOLDOWN_STATUS":
                self._psych_memory.cooldown_active = value.get("cooldown_active", self._psych_memory.cooldown_active)
                self._psych_memory.cooldown_remaining_s = value.get("cooldown_remaining_s", 0.0)

            elif indicator_type == "MISTAKE_REPORT":
                self._psych_memory.mistake_count = value.get("mistake_count", self._psych_memory.mistake_count)
                self._psych_memory.same_zone_failures = value.get("same_zone_failures", self._psych_memory.same_zone_failures)
                if self._psych_memory.same_zone_failures >= 2:
                    self._psych_memory.repeated_mistake_flag = True
                elif self._psych_memory.same_zone_failures == 0:
                    self._psych_memory.repeated_mistake_flag = False

            elif indicator_type == "TRAP_ALERT":
                self._psych_memory.trap_pressure = value.get("trap_pressure", self._psych_memory.trap_pressure)
                self._psych_memory.trap_density = value.get("trap_density", self._psych_memory.trap_density)

            elif indicator_type == "LOSS_REPORT":
                self._psych_memory.loss_count = value.get("loss_count", self._psych_memory.loss_count)
                self._psych_memory.loss_sequence_length = value.get("sequence_length", self._psych_memory.loss_sequence_length)

    def _decay_cooldown(self, current_time: datetime) -> None:
        """Decay cooldown based on time elapsed since last refresh.

        Args:
            current_time: Current timestamp.
        """
        if not self._psych_memory.cooldown_active:
            return

        if self._last_refresh is None:
            self._last_refresh = current_time
            return

        elapsed_s = (current_time - self._last_refresh).total_seconds()
        self._last_refresh = current_time

        if elapsed_s <= 0:
            return

        remaining = self._psych_memory.cooldown_remaining_s - elapsed_s
        if remaining <= 0:
            self._psych_memory.cooldown_active = False
            self._psych_memory.cooldown_remaining_s = 0.0
        else:
            self._psych_memory.cooldown_remaining_s = remaining

    def _derive_trade_allowed(self) -> bool:
        """Derive whether trading should be allowed based on internal state.

        Returns:
            True if trading is allowed, False if blocked.
        """
        if not self._psych_memory.trade_allowed:
            return False
        if self._psych_memory.cooldown_active:
            return False
        if self._psych_memory.loss_sequence_length >= 3:
            return False
        if self._psych_memory.trap_pressure and self._psych_memory.trap_density > 0.7:
            return False
        return True

    def _compute_caution_level(self) -> float:
        """Compute overall caution level from internal state.

        Returns:
            Caution level between 0.0 and 1.0.
        """
        factors: list[float] = []

        # Base from existing caution
        factors.append(self._psych_memory.caution_level * 0.3)

        # Cooldown contribution
        if self._psych_memory.cooldown_active:
            factors.append(0.25)

        # Repeated mistakes
        if self._psych_memory.repeated_mistake_flag:
            factors.append(0.20)

        # Trap pressure
        if self._psych_memory.trap_pressure:
            factors.append(0.15 * min(1.0, self._psych_memory.trap_density / 0.5))

        # Loss sequence length
        if self._psych_memory.loss_sequence_length > 0:
            factors.append(min(0.30, self._psych_memory.loss_sequence_length * 0.10))

        # Mistake count
        if self._psych_memory.mistake_count > 0:
            factors.append(min(0.15, self._psych_memory.mistake_count * 0.05))

        if not factors:
            return 0.0

        return max(0.0, min(1.0, sum(factors)))

    def _derive_bias(self) -> BiasType:
        """Derive a light bias based on discipline state.

        Psychology Head does not produce directional bias.
        Returns restrictive vs permissive signal instead.

        Returns:
            NEUTRAL if trade allowed, BEARISH if blocked/restricted.
        """
        if self._derive_trade_allowed() and self._compute_caution_level() < 0.4:
            return BiasType.NEUTRAL
        if not self._derive_trade_allowed():
            return BiasType.BEARISH  # Restricted
        if self._compute_caution_level() >= 0.4:
            return BiasType.NEUTRAL  # Cautious but allowed
        return BiasType.NEUTRAL

    def _build_invalidation_rules(
        self,
        current_time: datetime,
    ) -> list[InvalidationRule]:
        """Build invalidation rules based on current state.

        For Psychology Head, invalidation means the brake condition
        has been resolved — the reason to restrict is no longer valid.

        Args:
            current_time: Current timestamp.

        Returns:
            List of InvalidationRule objects (never empty).
        """
        rules: list[InvalidationRule] = []

        if self._psych_memory.cooldown_active:
            rules.append(InvalidationRule(
                condition="Cooldown period completed — discipline restored",
                price_level=0.0,
                reason="Psychology brake invalidation — cooldown expired",
            ))

        if self._psych_memory.repeated_mistake_flag:
            rules.append(InvalidationRule(
                condition=f"Repeated mistake risk cleared — {self._psych_memory.same_zone_failures} zone failures resolved",
                price_level=0.0,
                reason="Psychology mistake invalidation — pattern broken",
            ))

        if self._psych_memory.trap_pressure:
            rules.append(InvalidationRule(
                condition=f"Trap pressure reduced — density normalised from {self._psych_memory.trap_density:.2f}",
                price_level=0.0,
                reason="Psychology trap invalidation — trap density cleared",
            ))

        if self._psych_memory.loss_sequence_length >= 3:
            rules.append(InvalidationRule(
                condition="Loss sequence broken — discipline reset",
                price_level=0.0,
                reason="Psychology loss sequence invalidation — sequence ended",
            ))

        if not self._psych_memory.trade_allowed:
            rules.append(InvalidationRule(
                condition="Block condition resolved — discipline restored",
                price_level=0.0,
                reason=f"Psychology block lifted — '{self._psych_memory.block_reason}' cleared",
            ))

        # Fallback — always provide at least one rule
        if not rules:
            rules.append(InvalidationRule(
                condition="Psychology state unchanged — no new brake conditions",
                price_level=0.0,
                reason="Psychology invalidation baseline — monitoring for degradation",
            ))

        return rules

    def _compute_base_confidence(
        self,
        has_recent_signals: bool,
    ) -> float:
        """Compute base confidence from available evidence.

        Args:
            has_recent_signals: Whether recent psychology signals exist.

        Returns:
            Base confidence between 0.0 and 1.0.
        """
        score = 0.0

        if has_recent_signals:
            score += 0.4

        # More confidence when discipline is clear
        if self._psych_memory.trade_allowed and not self._psych_memory.cooldown_active:
            score += 0.3

        # State knowledge adds confidence
        if self._psych_memory.mistake_count > 0 or self._psych_memory.loss_count > 0:
            score += 0.2  # We know what's happening

        return min(1.0, score)
