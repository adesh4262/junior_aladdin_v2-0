"""Floor 4 — Base Head class.

All Department Heads inherit from ``BaseHead`` which provides:
- Common freshness/state management
- Standard report building (HeadReport creation)
- Setup tracking (primary + backup)
- Invalidation management
- Trigger zone management

Architecture rules (LOCKED):
- Heads interpret Floor 3 signals, never recompute them.
- Every Head must define invalidation (mandatory).
- SMC/ICT Heads must provide context_quality_score.
- Macro/Psychology Heads must NOT produce primary_setup or backup_setup.
- Heads reduce complexity for Captain, never increase it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import (
    BiasType,
    FreshnessTag,
    HeadReport,
    HeadState,
)
from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_4_heads.head_types import (
    InvalidationRule,
    TriggerInfo,
    ZoneInfo,
    compute_freshness,
)

logger = get_logger("head_base")


@dataclass
class HeadMemory:
    """Minimal shared memory for a Head.

    Each Head stores its last decision context here.
    Memory depth is Head-specific — subclasses may extend this.

    Fields:
        last_refresh_time: When the Head last performed a deep refresh.
        last_primary_setup: Previous cycle's primary setup string.
        last_bias: Previous cycle's bias.
        last_confidence: Previous cycle's confidence score.
    """
    last_refresh_time: datetime | None = None
    last_primary_setup: str = ""
    last_bias: BiasType = BiasType.NEUTRAL
    last_confidence: float = 0.0


class BaseHead(ABC):
    """Abstract base class for all Department Heads.

    Subclasses must implement:
    - ``head_name`` (class attribute)
    - ``_interpret()`` — core interpretation logic

    Args:
        name: The Head's name (e.g., ``\"smc\"``, ``\"ict\"``).
            Used to set ``head_name`` in the generated HeadReport.
    """

    def __init__(self, name: str = "") -> None:
        self._name = name or self.__class__.__name__.replace("Head", "").lower()
        self._memory = HeadMemory()
        self._last_deep_update: datetime | None = None
        logger.info(
            "Head initialised",
            extra={"head": self._name, "class": self.__class__.__name__},
        )

    # ── Properties ──────────────────────────────────────────────────────

    @property
    @abstractmethod
    def head_name(self) -> str:
        """Human-readable head name (e.g., ``\"SMC Head\"``)."""
        ...

    # ── Public API ──────────────────────────────────────────────────────

    def refresh(
        self,
        output_contract: OutputContract,
        current_time: datetime | None = None,
    ) -> HeadReport:
        """Perform a full refresh cycle for this Head.

        1. Extracts relevant signals from the OutputContract.
        2. Runs core interpretation logic (subclass-specific).
        3. Builds the HeadReport with freshness/state.
        4. Updates Head memory.

        Args:
            output_contract: The validated OutputContract from Floor 3.
            current_time: Current time (UTC). Uses ``datetime.utcnow()`` if None.

        Returns:
            A fully populated HeadReport ready for Captain consumption.
        """
        now = current_time or datetime.utcnow()
        signals = self._extract_signals(output_contract)

        # Run subclass interpretation
        interpretation = self._interpret(signals, output_contract, now)

        # Compute freshness
        freshness_score, freshness_tag, _ = compute_freshness(
            self._last_deep_update, now,
        )

        # Build state from freshness
        state = self._compute_state(freshness_tag, interpretation)

        # Build report
        report = self._build_report(
            interpretation=interpretation,
            state=state,
            freshness_score=freshness_score,
            freshness_tag=freshness_tag,
            now=now,
        )

        # Update memory
        self._memory.last_refresh_time = now
        self._memory.last_primary_setup = interpretation.get("primary_setup", "")
        self._memory.last_bias = interpretation.get("bias", BiasType.NEUTRAL)
        self._memory.last_confidence = interpretation.get("confidence", 0.0)
        self._last_deep_update = now

        logger.debug(
            "Head refresh complete",
            extra={
                "head": self._name,
                "state": state.value,
                "bias": interpretation.get("bias", BiasType.NEUTRAL).value,
                "confidence": round(interpretation.get("confidence", 0.0), 2),
            },
        )

        return report

    # ── Subclass Interface ──────────────────────────────────────────────

    @abstractmethod
    def _extract_signals(
        self,
        output_contract: OutputContract,
    ) -> list[Any]:
        """Extract relevant signals from the OutputContract.

        Each Head filters for its own domain's signals.

        Args:
            output_contract: The validated Floor 3 output.

        Returns:
            List of relevant signals (CalculatedSignal objects).
        """
        ...

    @abstractmethod
    def _interpret(
        self,
        signals: list[Any],
        output_contract: OutputContract,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Core interpretation logic — domain-specific.

        Args:
            signals: Relevant signals extracted from Floor 3.
            output_contract: Full OutputContract (for summary/context).
            current_time: Current time for timestamping.

        Returns:
            A dict with at minimum:
            - ``bias`` (BiasType)
            - ``confidence`` (float 0.0–1.0)
            - ``primary_setup`` (str or None)
            - ``backup_setup`` (str or None)
            - ``invalidation`` (dict)
            - ``bull_case`` (str)
            - ``bear_case`` (str)
            - ``witness_summary`` (str)
            - ``active_zones`` (list[dict])
            - ``armed_triggers`` (list[dict])
            - ``confluence_note`` (str)
            - ``dominant_tf`` (str)
            - ``timeframe_view`` (str)
        """
        ...

    # ── Internal ────────────────────────────────────────────────────────

    def _compute_state(
        self,
        freshness_tag: FreshnessTag,
        interpretation: dict[str, Any],
    ) -> HeadState:
        """Compute Head state from freshness and interpretation.

        Args:
            freshness_tag: Current freshness of the Head's data.
            interpretation: The interpretation result dict.

        Returns:
            HeadState.READY, HeadState.UNCERTAIN, or HeadState.STALE.
        """
        if freshness_tag == FreshnessTag.STALE:
            return HeadState.STALE

        confidence = interpretation.get("confidence", 0.0)
        if confidence < 0.3:
            return HeadState.UNCERTAIN

        return HeadState.READY

    def _build_report(
        self,
        interpretation: dict[str, Any],
        state: HeadState,
        freshness_score: float,
        freshness_tag: FreshnessTag,
        now: datetime,
    ) -> HeadReport:
        """Build a HeadReport from interpretation results.

        Args:
            interpretation: The interpretation result dict.
            state: Computed Head state.
            freshness_score: Freshness score (0.0–1.0).
            freshness_tag: Freshness tag.
            now: Current timestamp.

        Returns:
            A fully formed HeadReport.
        """
        return HeadReport(
            head_name=self.head_name,
            state=state,
            freshness_score=freshness_score,
            freshness_tag=freshness_tag,
            last_deep_update=self._last_deep_update or now,
            bias=interpretation.get("bias", BiasType.NEUTRAL),
            confidence=interpretation.get("confidence", 0.0),
            dominant_tf=interpretation.get("dominant_tf", "1m"),
            timeframe_view=interpretation.get("timeframe_view", ""),
            primary_setup=interpretation.get("primary_setup"),
            backup_setup=interpretation.get("backup_setup"),
            active_zones=interpretation.get("active_zones", []),
            armed_triggers=interpretation.get("armed_triggers", []),
            invalidation=interpretation.get("invalidation", {}),
            bull_case=interpretation.get("bull_case", ""),
            bear_case=interpretation.get("bear_case", ""),
            confluence_note=interpretation.get("confluence_note", ""),
            witness_summary=interpretation.get("witness_summary", ""),
            context_quality_score=interpretation.get("context_quality_score"),

            # Macro head specific fields
            event_risk_flag=interpretation.get("event_risk_flag", False),

            # Psychology head specific fields
            caution_level=interpretation.get("caution_level", 0.0),
            trade_allowed=interpretation.get("trade_allowed", True),
            cooldown_active=interpretation.get("cooldown_active", False),
            repeated_mistake_flag=interpretation.get("repeated_mistake_flag", False),
            trap_pressure=interpretation.get("trap_pressure", False),
            block_reason=interpretation.get("block_reason", ""),
        )

    def _compute_approx_freshness(self, current_time: datetime) -> float:
        """Compute an approximate freshness score from last update time.

        Shared by all heads — uses the same decay thresholds:
        - < 2 min: 1.0 (very fresh)
        - 2-10 min: 0.7 (moderate)
        - 10-30 min: 0.4 (stale-ish)
        - > 30 min: 0.1 (very stale)

        Args:
            current_time: Current time for comparison.

        Returns:
            Freshness score between 0.0 and 1.0.
        """
        if self._last_deep_update is None:
            return 0.5

        elapsed = (current_time - self._last_deep_update).total_seconds()
        if elapsed < 120:
            return 1.0
        elif elapsed < 600:
            return 0.7
        elif elapsed < 1800:
            return 0.4
        return 0.1

    def _make_zone_dict(
        self,
        zone_type: str,
        price_level: float,
        direction: str,
        status: str = "ACTIVE",
        strength: float = 0.5,
        signal_ref: str = "",
    ) -> dict[str, Any]:
        """Create a standardised zone dict for HeadReport.active_zones.

        Args:
            zone_type: Type (e.g., ``\"FVG\"``).
            price_level: Key price level.
            direction: ``\"bullish\"`` or ``\"bearish\"``.
            status: Zone status.
            strength: Relative strength (0.0–1.0).
            signal_ref: Originating Floor 3 signal_id.

        Returns:
            A zone dict.
        """
        return {
            "zone_type": zone_type,
            "price_level": price_level,
            "direction": direction,
            "status": status,
            "strength": strength,
            "signal_ref": signal_ref,
        }

    def _make_trigger_dict(
        self,
        trigger_type: str,
        condition: str,
        zone_ref: str = "",
        status: str = "PENDING",
        price_level: float = 0.0,
    ) -> dict[str, Any]:
        """Create a standardised trigger dict for HeadReport.armed_triggers.

        Args:
            trigger_type: Type (e.g., ``\"zone_touch\"``).
            condition: Human-readable condition.
            zone_ref: Related zone reference.
            status: Trigger status.
            price_level: Activation price level.

        Returns:
            A trigger dict.
        """
        return {
            "trigger_type": trigger_type,
            "condition": condition,
            "zone_ref": zone_ref,
            "status": status,
            "price_level": price_level,
        }

    def _make_invalidation_dict(
        self,
        rules: list[InvalidationRule],
    ) -> dict[str, Any]:
        """Create a standardised invalidation dict for HeadReport.

        Args:
            rules: List of InvalidationRule objects.

        Returns:
            An invalidation dict with ``\"rules\"`` and ``\"summary\"``.
        """
        return {
            "rules": [
                {
                    "condition": r.condition,
                    "price_level": r.price_level,
                    "reason": r.reason,
                }
                for r in rules
            ],
            "summary": "; ".join(r.condition for r in rules[:3]),
        }
