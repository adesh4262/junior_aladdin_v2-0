"""Side A — Captain Interface: DecisionOutput → ExecutionIntent translation.

This module is the contract boundary between Floor 5 (Captain) and Side A (Execution).
It receives Captain's approved DecisionOutput, validates all mandatory fields,
translates to ExecutionIntent, generates intent fingerprint, and checks freshness.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 4):
- Side A NEVER creates trades — it only receives approved intent
- Side A does NOT interpret market meaning
- Side A may reject stale intents
- ALERT notification must fire before PAPER/REAL routing (handled by mode_router)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import (
    CaptainDecision,
    DecisionType,
    ExecutionIntent,
    ExecutionMode,
    TradeClass,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_AGE_SECONDS: int = 60
"""Default maximum age for an intent to be considered fresh (in seconds)."""


# =============================================================================
# Helper Functions
# =============================================================================


def _generate_trade_id(decision: CaptainDecision) -> str:
    """Generate a unique trade ID from a CaptainDecision.

    Uses snapshot_id if available, otherwise generates a timestamp-based ID.

    Args:
        decision: The CaptainDecision to generate a trade ID for.

    Returns:
        A unique trade ID string.
    """
    if decision.snapshot_id:
        return f"trade_{decision.snapshot_id}"
    return f"trade_cap_{int(decision.timestamp.timestamp() * 1000)}"


def _generate_intent_fingerprint(
    trade_id: str,
    action: str,
    strike: str,
    timestamp: datetime,
    window_seconds: int = 5,
) -> str:
    """Generate a unique intent fingerprint for duplicate detection.

    Based on: trade_id + action + strike + timestamp_window.
    The timestamp_window rounds down to the nearest N-second window
    so that retries within the window produce the same fingerprint.

    Args:
        trade_id: Unique trade identifier.
        action: BUY or SELL.
        strike: Selected strike price.
        timestamp: Intent creation timestamp.
        window_seconds: Time window granularity in seconds.

    Returns:
        A hex digest string serving as the intent fingerprint.
    """
    window_ts = int(timestamp.timestamp() // window_seconds) * window_seconds
    raw = f"{trade_id}|{action}|{strike}|{window_ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _validate_trade_decision_fields(decision: CaptainDecision) -> None:
    """Validate that all mandatory trade fields are present in a DecisionOutput.

    Only called when decision.decision == DecisionType.TRADE.
    Raises ExecutionError with details of all missing fields.

    Args:
        decision: The CaptainDecision to validate.

    Raises:
        ExecutionError: If any mandatory field is missing or invalid.
    """
    missing: list[str] = []

    # String fields that must be non-empty
    if not decision.action or decision.action not in ("BUY", "SELL"):
        missing.append(f"action (must be BUY/SELL, got {decision.action!r})")
    if not decision.option_side or decision.option_side not in ("CE", "PE"):
        missing.append(f"option_side (must be CE/PE, got {decision.option_side!r})")
    if not decision.selected_strike:
        missing.append("selected_strike (must not be empty)")

    # Trade class must be a valid TradeClass enum
    if not isinstance(decision.trade_class, TradeClass):
        missing.append(f"trade_class (must be a TradeClass enum, got {type(decision.trade_class).__name__})")

    # Entry plan must have trigger/zone/confirmation
    if not decision.entry_plan:
        missing.append("entry_plan (must not be empty for TRADE)")
    else:
        for key in ("trigger", "zone", "confirmation"):
            if key not in decision.entry_plan:
                missing.append(f"entry_plan.{key} (mandatory in entry_plan)")

    # Invalidation level must be positive
    if decision.invalidation_level <= 0:
        missing.append("invalidation_level (must be > 0)")

    # SL plan must have price/type
    if not decision.stop_loss_plan:
        missing.append("stop_loss_plan (must not be empty)")
    else:
        for key in ("price", "type"):
            if key not in decision.stop_loss_plan:
                missing.append(f"stop_loss_plan.{key} (mandatory in stop_loss_plan)")

    # Target plan must have targets list or trailing config
    if not decision.target_plan:
        missing.append("target_plan (must not be empty)")

    if missing:
        raise ExecutionError(
            message="CaptainDecision missing mandatory fields for TRADE intent",
            details={
                "missing_fields": missing,
                "snapshot_id": decision.snapshot_id,
            },
        )


def _build_system_context(
    system_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a validated system context dict, filling defaults for missing keys.

    The system context provides runtime execution environment info that
    is NOT part of Captain's decision but is needed for execution.

    Args:
        system_context: Optional dict with mode, capital, intervention settings.

    Returns:
        A dict with guaranteed keys: mode, available_capital, max_risk_per_trade,
        intervention_allowed.
    """
    context = system_context or {}
    return {
        "mode": context.get("mode", ExecutionMode.ALERT),
        "available_capital": context.get("available_capital", 0.0),
        "max_risk_per_trade": context.get("max_risk_per_trade", 0.0),
        "intervention_allowed": context.get("intervention_allowed", False),
    }


# =============================================================================
# CaptainInterface
# =============================================================================


class CaptainInterface:
    """Receives Captain's DecisionOutput, validates, and translates to ExecutionIntent.

    This is the primary contract boundary between Floor 5 and Side A.
    All Captain intents must pass through this interface before execution.

    Responsibilities:
    - Validate all mandatory fields in DecisionOutput
    - Translate DecisionOutput → ExecutionIntent
    - Generate intent fingerprint for duplicate detection
    - Check intent freshness (reject stale intents)
    - Extract execution context for downstream use

    The system_context dict provides runtime execution environment info:
    - mode (ExecutionMode): Current execution mode (ALERT/PAPER/REAL)
    - available_capital (float): Available capital for this trade
    - max_risk_per_trade (float): Maximum risk per trade
    - intervention_allowed (bool): Whether override is currently allowed
    """

    def __init__(
        self,
        max_age_seconds: int | None = None,
        config: Any | None = None,
    ) -> None:
        """Initialize the CaptainInterface.

        Args:
            max_age_seconds: Maximum age for an intent to be considered fresh.
                If None, uses the config value or default (60s).
            config: Optional Config instance. If provided and
                ``max_age_seconds`` is None, reads from
                ``thresholds.freshness_max_age_seconds``.
        """
        if max_age_seconds is not None:
            self._max_age_seconds = max_age_seconds
        elif config is not None:
            self._max_age_seconds = config.get(
                "thresholds.freshness_max_age_seconds",
                DEFAULT_MAX_AGE_SECONDS,
            )
        else:
            self._max_age_seconds = DEFAULT_MAX_AGE_SECONDS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def receive_intent(
        self,
        decision_output: CaptainDecision,
        system_context: dict[str, Any] | None = None,
    ) -> ExecutionIntent:
        """Receive a CaptainDecision and translate to ExecutionIntent.

        Args:
            decision_output: The CaptainDecision from Floor 5.
            system_context: Optional runtime execution context dict.
                Can contain: mode, available_capital, max_risk_per_trade,
                intervention_allowed.

        Returns:
            A validated ExecutionIntent ready for routing.

        Raises:
            ExecutionError: If decision is not TRADE or mandatory fields missing.
        """
        # Step 1: Validate decision type — only TRADE produces intents
        if decision_output.decision != DecisionType.TRADE:
            raise ExecutionError(
                message="Cannot build ExecutionIntent from non-TRADE decision",
                details={
                    "decision": decision_output.decision.value,
                    "snapshot_id": decision_output.snapshot_id,
                },
            )

        # Step 2: Validate all mandatory trade fields
        _validate_trade_decision_fields(decision_output)

        # Step 3: Build runtime context
        ctx = _build_system_context(system_context)

        # Step 4: Generate trade_id
        trade_id = _generate_trade_id(decision_output)

        # Step 5: Generate intent fingerprint
        intent_fingerprint = _generate_intent_fingerprint(
            trade_id=trade_id,
            action=decision_output.action,
            strike=decision_output.selected_strike,
            timestamp=decision_output.timestamp,
        )

        # Step 6: Build and return ExecutionIntent
        return ExecutionIntent(
            trade_id=trade_id,
            action=decision_output.action,
            option_side=decision_output.option_side,
            selected_strike=decision_output.selected_strike,
            trade_class=decision_output.trade_class,
            entry_plan=dict(decision_output.entry_plan),
            invalidation_level=decision_output.invalidation_level,
            stop_loss_plan=dict(decision_output.stop_loss_plan),
            target_plan=dict(decision_output.target_plan),
            capital_context={
                "available_capital": ctx["available_capital"],
                "max_risk_per_trade": ctx["max_risk_per_trade"],
            },
            mode=ctx["mode"],
            intervention_allowed=ctx["intervention_allowed"],
            intent_fingerprint=intent_fingerprint,
            timestamp=decision_output.timestamp,
        )

    def validate_intent_freshness(
        self,
        intent: ExecutionIntent,
        max_age_seconds: int | None = None,
    ) -> bool:
        """Check whether an ExecutionIntent is still fresh enough to execute.

        An intent is considered stale if its timestamp is older than
        max_age_seconds from the current time.

        Args:
            intent: The ExecutionIntent to check.
            max_age_seconds: Maximum age in seconds. Defaults to instance value.

        Returns:
            True if the intent is fresh, False if stale.
        """
        age_limit = max_age_seconds if max_age_seconds is not None else self._max_age_seconds
        age = (datetime.utcnow() - intent.timestamp).total_seconds()
        return age <= age_limit

    def extract_execution_context(self, intent: ExecutionIntent) -> dict[str, Any]:
        """Extract a lightweight execution context dict from an ExecutionIntent.

        This context dict is suitable for dashboard display, Side C logging,
        and downstream module consumption.

        Args:
            intent: The ExecutionIntent to extract context from.

        Returns:
            A dict with key execution context fields.
        """
        return {
            "trade_id": intent.trade_id,
            "action": intent.action,
            "option_side": intent.option_side,
            "strike": intent.selected_strike,
            "trade_class": intent.trade_class.value,
            "mode": intent.mode.value,
            "conviction_basis": {
                "entry_trigger": intent.entry_plan.get("trigger", ""),
                "entry_zone": intent.entry_plan.get("zone", ""),
                "invalidation_level": intent.invalidation_level,
                "sl_price": intent.stop_loss_plan.get("price", 0.0),
            },
            "capital": {
                "available": intent.capital_context.get("available_capital", 0.0),
                "max_risk": intent.capital_context.get("max_risk_per_trade", 0.0),
            },
            "intervention_allowed": intent.intervention_allowed,
            "intent_fingerprint": intent.intent_fingerprint,
            "created_at": intent.timestamp.isoformat(),
        }

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def max_age_seconds(self) -> int:
        """Get the current maximum intent age in seconds."""
        return self._max_age_seconds

    @max_age_seconds.setter
    def max_age_seconds(self, value: int) -> None:
        """Set the maximum intent age in seconds.

        Args:
            value: New maximum age in seconds. Must be positive.
        """
        if value <= 0:
            raise ExecutionError(
                message="max_age_seconds must be positive",
                details={"value": value},
            )
        self._max_age_seconds = value
