"""Side A — Data Health Policy: DEGRADED/STALE/CRITICAL → execution behavior.

Maps operational data health signals to execution responses. These are
operational safety facts that influence execution caution behavior —
they are NOT trade intelligence.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.7):
- These states do NOT become trade intelligence
- They are operational safety facts that influence execution caution behavior
- DEGRADED → ALLOW_STRICT (stricter risk checks, higher margins)
- STALE → BLOCK_NEW (existing protected trades continue)
- CRITICAL → ESCALATE_FLATTEN (safety escalation / lock path / flatten policy)
"""

from __future__ import annotations

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import DataHealth
from junior_aladdin.side_a_execution.side_a_types import (
    DataHealthExecutionResponse,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_STRICTNESS_NORMAL: float = 1.0
"""Strictness multiplier for ALLOW_NORMAL (no adjustment)."""

DEFAULT_STRICTNESS_STRICT: float = 1.5
"""Strictness multiplier for ALLOW_STRICT (1.5x tighter thresholds)."""

DEFAULT_STRICTNESS_BLOCKED: float = 0.0
"""Strictness multiplier for BLOCK_NEW (entries blocked, modifier irrelevant)."""

DEFAULT_STRICTNESS_ESCALATE: float = -1.0
"""Strictness multiplier for ESCALATE_FLATTEN (special signal for escalation)."""


# =============================================================================
# Mapping Table
# =============================================================================

_HEALTH_RESPONSE_MAP: dict[DataHealth, DataHealthExecutionResponse] = {
    DataHealth.GOOD: DataHealthExecutionResponse.ALLOW_NORMAL,
    DataHealth.CAUTION: DataHealthExecutionResponse.ALLOW_NORMAL,
    DataHealth.DEGRADED: DataHealthExecutionResponse.ALLOW_STRICT,
    DataHealth.STALE: DataHealthExecutionResponse.BLOCK_NEW,
    DataHealth.CRITICAL: DataHealthExecutionResponse.ESCALATE_FLATTEN,
}

_STRICTNESS_MAP: dict[DataHealthExecutionResponse, float] = {
    DataHealthExecutionResponse.ALLOW_NORMAL: DEFAULT_STRICTNESS_NORMAL,
    DataHealthExecutionResponse.ALLOW_STRICT: DEFAULT_STRICTNESS_STRICT,
    DataHealthExecutionResponse.BLOCK_NEW: DEFAULT_STRICTNESS_BLOCKED,
    DataHealthExecutionResponse.ESCALATE_FLATTEN: DEFAULT_STRICTNESS_ESCALATE,
}

_ENTRY_BLOCKED_MAP: dict[DataHealthExecutionResponse, bool] = {
    DataHealthExecutionResponse.ALLOW_NORMAL: False,
    DataHealthExecutionResponse.ALLOW_STRICT: False,
    DataHealthExecutionResponse.BLOCK_NEW: True,
    DataHealthExecutionResponse.ESCALATE_FLATTEN: True,
}


# =============================================================================
# DataHealthPolicy
# =============================================================================


class DataHealthPolicy:
    """Maps data health signals to execution responses and modifiers.

    Provides a single source of truth for how Side A's execution behavior
    should react to upper-layer operational health facts.

    Usage::

        policy = DataHealthPolicy()
        response = policy.evaluate(DataHealth.DEGRADED)
        # → DataHealthExecutionResponse.ALLOW_STRICT
        strictness = policy.get_execution_strictness(response)
        # → 1.5
        blocked = policy.is_entry_blocked(response)
        # → False
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def evaluate(health_signal: DataHealth) -> DataHealthExecutionResponse:
        """Map a DataHealth signal to an execution response.

        Args:
            health_signal: The current data health state from Floor 2.

        Returns:
            The corresponding DataHealthExecutionResponse.

        Raises:
            ExecutionError: If health_signal is None or unknown.
        """
        if health_signal is None or not isinstance(health_signal, DataHealth):
            raise ExecutionError(
                message="Invalid data health signal — must be a DataHealth enum value",
                details={"signal": str(health_signal)},
            )

        response = _HEALTH_RESPONSE_MAP.get(health_signal)
        if response is None:
            raise ExecutionError(
                message=f"Unmapped data health signal: {health_signal.value}",
                details={"signal": health_signal.value},
            )
        return response

    @staticmethod
    def get_execution_strictness(
        response: DataHealthExecutionResponse,
    ) -> float:
        """Get the strictness modifier for a given execution response.

        The modifier is a multiplier applied to risk gate thresholds:
        - 1.0  = normal thresholds (no adjustment)
        - 1.5  = 1.5x stricter thresholds (e.g., margin buffer increased)
        - 0.0  = entries blocked (modifier irrelevant)
        - -1.0 = escalation required (special signal)

        Args:
            response: The execution response to evaluate.

        Returns:
            A float multiplier for risk gate threshold adjustments.
        """
        return _STRICTNESS_MAP.get(response, DEFAULT_STRICTNESS_NORMAL)

    @staticmethod
    def is_entry_blocked(response: DataHealthExecutionResponse) -> bool:
        """Check whether new entries are blocked under this response.

        Args:
            response: The execution response to evaluate.

        Returns:
            True if new trade entries should be blocked.
        """
        return _ENTRY_BLOCKED_MAP.get(response, True)

    @staticmethod
    def describe(response: DataHealthExecutionResponse) -> str:
        """Get a human-readable description of the execution response.

        Args:
            response: The execution response to describe.

        Returns:
            A human-readable string describing the execution behavior.
        """
        descriptions = {
            DataHealthExecutionResponse.ALLOW_NORMAL: (
                "Normal execution — all risk checks at default thresholds"
            ),
            DataHealthExecutionResponse.ALLOW_STRICT: (
                "Strict execution — risk checks tightened (1.5x). "
                "New entries allowed with higher margins & caution"
            ),
            DataHealthExecutionResponse.BLOCK_NEW: (
                "New entries blocked. Existing protected trades continue "
                "under normal management"
            ),
            DataHealthExecutionResponse.ESCALATE_FLATTEN: (
                "CRITICAL: Safety escalation required. "
                "Lock path / flatten policy activated"
            ),
        }
        return descriptions.get(
            response,
            f"Unknown response: {response.value}",
        )

    # ------------------------------------------------------------------
    # Convenience class methods (no instance needed)
    # ------------------------------------------------------------------

    @classmethod
    def check_health(
        cls,
        health_signal: DataHealth,
    ) -> dict[str, bool | float | str]:
        """Convenience method returning a complete health check result dict.

        Useful for dashboard display and logging.

        Args:
            health_signal: The current data health state from Floor 2.

        Returns:
            Dict with keys: response, strictness, entry_blocked, description.
        """
        response = cls.evaluate(health_signal)
        return {
            "response": response.value,
            "strictness": cls.get_execution_strictness(response),
            "entry_blocked": cls.is_entry_blocked(response),
            "description": cls.describe(response),
        }
