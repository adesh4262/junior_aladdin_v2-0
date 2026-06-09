"""Source Health Monitor for Floor 1 connection lifecycle.

Tracks connection lifecycle state (HEALTHY → DEGRADED → STALE → etc.),
emits factual health metrics for Floor 2 handoff and observability.

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import LifecycleState, SourceHealth

logger = get_logger("source_health")

# Valid state transitions as a map: current_state -> set(allowed_next_states)
VALID_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.HEALTHY: {
        LifecycleState.DEGRADED,
        LifecycleState.AUTH_FAILED,
        LifecycleState.DISCONNECTED,  # explicit disconnect allowed from healthy
    },
    LifecycleState.DEGRADED: {
        LifecycleState.HEALTHY,
        LifecycleState.STALE,
    },
    LifecycleState.STALE: {
        LifecycleState.DEGRADED,
        LifecycleState.DISCONNECTED,
    },
    LifecycleState.AUTH_FAILED: {
        LifecycleState.DISCONNECTED,
        LifecycleState.HEALTHY,  # after re-auth
    },
    LifecycleState.DISCONNECTED: {
        LifecycleState.HEALTHY,  # after reconnect
    },
}


class SourceHealthMonitor:
    """Tracks the health lifecycle of a single connection source.

    Maintains a state machine with validated transitions.
    Emits factual health metrics for Floor 2 metadata side-channel.

    Usage:
        monitor = SourceHealthMonitor(connection_id="conn_abc")
        monitor.update_latency(12.5)
        monitor.transition_to(LifecycleState.DEGRADED)
        facts = monitor.get_health_facts()
    """

    def __init__(self, connection_id: str) -> None:
        self._connection_id = connection_id
        self._state = SourceHealth(
            lifecycle_state=LifecycleState.HEALTHY,
            latency_ms=0.0,
            heartbeat_age_s=0.0,
            reconnect_count=0,
        )
        self._last_heartbeat: datetime = datetime.now(timezone.utc)
        self._last_latency_update: datetime = datetime.now(timezone.utc)
        logger.info(
            "SourceHealthMonitor initialized",
            extra={"connection_id": connection_id, "initial_state": "HEALTHY"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self) -> SourceHealth:
        """Return the current health snapshot."""
        return self._state

    def update_latency(self, latency_ms: float) -> None:
        """Update the measured connection latency.

        Args:
            latency_ms: Round-trip latency in milliseconds (must be >= 0).

        Raises:
            ValidationError: If latency_ms is negative.
        """
        if latency_ms < 0:
            raise ValidationError(
                "Latency cannot be negative",
                details={"latency_ms": latency_ms},
            )
        self._state.latency_ms = round(latency_ms, 2)
        self._last_latency_update = datetime.now(timezone.utc)

    def update_heartbeat(self) -> None:
        """Record a heartbeat, resetting the heartbeat age to 0."""
        self._last_heartbeat = datetime.now(timezone.utc)
        self._state.heartbeat_age_s = 0.0

    def tick_heartbeat_age(self) -> None:
        """Increment the heartbeat age by the elapsed time since the last tick.

        Should be called periodically (e.g., every second) so the heartbeat age
        accurately reflects how long since the last actual heartbeat was received.
        """
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_heartbeat).total_seconds()
        self._state.heartbeat_age_s = round(max(0.0, elapsed), 1)

    def transition_to(self, new_state: LifecycleState) -> None:
        """Transition to a new lifecycle state.

        Args:
            new_state: The target LifecycleState.

        Raises:
            ValidationError: If the transition is not allowed.
        """
        current = self._state.lifecycle_state
        if current == new_state:
            return  # same state, no-op

        allowed = VALID_TRANSITIONS.get(current, set())
        if new_state not in allowed:
            raise ValidationError(
                f"Invalid state transition: {current.value} → {new_state.value}",
                details={
                    "from": current.value,
                    "to": new_state.value,
                    "allowed": [s.value for s in sorted(allowed, key=lambda x: x.value)],
                },
            )

        # Special handling for specific transitions
        old_state = current
        self._state.lifecycle_state = new_state

        if new_state == LifecycleState.DISCONNECTED:
            if old_state != LifecycleState.AUTH_FAILED:
                # Only count as a reconnect-worthy disconnect if it wasn't
                # already in AUTH_FAILED state
                self._state.reconnect_count += 1
        elif new_state == LifecycleState.HEALTHY:
            # Reset heartbeat on successful connect/reconnect
            self.update_heartbeat()

        logger.info(
            "State transition: %s → %s",
            old_state.value,
            new_state.value,
            extra={
                "connection_id": self._connection_id,
                "from": old_state.value,
                "to": new_state.value,
                "reconnect_count": self._state.reconnect_count,
            },
        )

    def get_health_facts(self) -> dict[str, Any]:
        """Return health facts for Floor 2 handoff metadata side-channel.

        Returns:
            Dict with: lifecycle_state, latency_ms, heartbeat_age_s,
            reconnect_count.
        """
        return {
            "lifecycle_state": self._state.lifecycle_state.value,
            "latency_ms": self._state.latency_ms,
            "heartbeat_age_s": self._state.heartbeat_age_s,
            "reconnect_count": self._state.reconnect_count,
        }

    @property
    def connection_id(self) -> str:
        return self._connection_id

    @property
    def lifecycle_state(self) -> LifecycleState:
        return self._state.lifecycle_state
