"""Side A — Kill Switch: SOFT (block new) + CRITICAL (flatten & freeze).

Standalone module for hybrid kill-switch governance.  Not all kill events
are equal — a soft safety stop and a full flatten emergency should not be
treated the same.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.15):
- SOFT Kill Switch: Block new entries. Existing trades continue under management.
- CRITICAL Kill Switch: Flatten path (close all positions) + freeze execution.
- Deactivation restores normal operation.
- Every activation/deactivation is logged with reason.
- State is persisted to disk so it survives system restarts.

Output contracts:
- To execution_orchestrator: kill switch state for decision gating
- To risk_gate: is_blocked_for_entry() for check #8 (real lock state)
- To execution_logging_layer: activation/deactivation events
- To dashboard: current kill switch state visibility
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_a_execution.side_a_types import KillSwitchState

logger = get_logger(__name__)


# =============================================================================
# KillSwitch
# =============================================================================


class KillSwitch:
    """Hybrid kill-switch governance — SOFT (block new) + CRITICAL (flatten & freeze).

    Usage::

        kill_switch = KillSwitch(
            on_activate_callback=orchestrator.trigger_emergency,
            on_log_callback=logging_layer.log,
        )

        # SOFT activation — block new entries
        kill_switch.activate_soft("Data degraded — blocking new entries")

        # CRITICAL activation — flatten + freeze
        kill_switch.activate_critical("Unprotected position detected")

        # Deactivate
        kill_switch.deactivate()

        # Query state
        state = kill_switch.get_active_switch()  # KillSwitchState enum
        is_blocked = kill_switch.is_entry_blocked()  # True if SOFT or CRITICAL
    """

    def __init__(
        self,
        on_activate_callback: Callable[[str], bool] | None = None,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
        persistence_path: str | Path | None = None,
    ) -> None:
        """Initialize the KillSwitch.

        Args:
            on_activate_callback: Called when CRITICAL is activated.
                Receives action string ("FLATTEN") and should return bool success.
            on_log_callback: Called for all kill switch events.
                Signature: (event_type: str, data: dict) -> None.
            persistence_path: Path to JSON file for persisting kill switch
                state across system restarts. If None, state is not persisted.
        """
        self._state: KillSwitchState = KillSwitchState.NORMAL
        self._active_reason: str = ""
        self._activated_at: datetime | None = None
        self._deactivated_at: datetime | None = None
        self._on_activate_callback = on_activate_callback
        self._on_log_callback = on_log_callback
        self._activation_history: list[dict[str, Any]] = []
        self._persistence_path: Path | None = (
            Path(persistence_path) if persistence_path else None
        )

        # Restore state from disk on startup
        if self._persistence_path is not None:
            self._load_state()

    # ------------------------------------------------------------------
    # Activation Methods
    # ------------------------------------------------------------------

    def activate_soft(self, reason: str = "Soft kill switch activated") -> bool:
        """Activate the SOFT kill switch.

        Blocks new entries. Existing protected trades continue under management.

        Args:
            reason: Why the kill switch was activated.

        Returns:
            True if activation succeeded.
        """
        if self._state == KillSwitchState.CRITICAL_ACTIVE:
            logger.warning(
                "Cannot activate SOFT — CRITICAL already active",
                extra={"reason": reason},
            )
            return False

        if self._state == KillSwitchState.SOFT_ACTIVE:
            logger.info("Kill switch already SOFT active — updating reason")
            self._active_reason = reason
            return True

        self._state = KillSwitchState.SOFT_ACTIVE
        self._active_reason = reason
        self._activated_at = datetime.utcnow()
        self._deactivated_at = None

        self._record_history("SOFT_ACTIVATED", reason)
        self._log("KILL_SWITCH_SOFT", {"reason": reason})
        self._save_state()

        logger.info("SOFT kill switch activated", extra={"reason": reason})
        return True

    def activate_critical(self, reason: str = "Critical kill switch activated") -> bool:
        """Activate the CRITICAL kill switch.

        Flatten path + freeze execution. Emergency only.
        Triggers the on_activate_callback to flatten positions.

        Args:
            reason: Why the kill switch was activated.

        Returns:
            True if activation succeeded (including if already critical).
        """
        if self._state == KillSwitchState.CRITICAL_ACTIVE:
            logger.info("Kill switch already CRITICAL active — updating reason")
            self._active_reason = reason
            return True

        # Fire flatten callback
        flatten_ok = True
        if self._on_activate_callback is not None:
            try:
                flatten_ok = self._on_activate_callback("FLATTEN")
            except Exception as e:
                logger.error(
                    "CRITICAL kill switch flatten callback failed",
                    extra={"error": str(e)},
                )
                flatten_ok = False

        self._state = KillSwitchState.CRITICAL_ACTIVE
        self._active_reason = reason
        self._activated_at = datetime.utcnow()
        self._deactivated_at = None

        self._record_history("CRITICAL_ACTIVATED", reason)
        self._save_state()
        self._log("KILL_SWITCH_CRITICAL", {
            "reason": reason,
            "flatten_ok": flatten_ok,
        })

        logger.info(
            "CRITICAL kill switch activated",
            extra={"reason": reason, "flatten_ok": flatten_ok},
        )
        return True

    def deactivate(self, reason: str = "Kill switch deactivated") -> bool:
        """Deactivate the kill switch — restore normal operation.

        Args:
            reason: Why the kill switch was deactivated.

        Returns:
            True if deactivation succeeded.
        """
        if self._state == KillSwitchState.NORMAL:
            logger.info("Kill switch already NORMAL — no action needed")
            return True

        previous_state = self._state
        self._state = KillSwitchState.NORMAL
        self._active_reason = ""
        self._deactivated_at = datetime.utcnow()

        self._record_history(
            "DEACTIVATED",
            f"{reason} (was {previous_state.value})",
        )
        self._save_state()
        self._log("KILL_SWITCH_NORMAL", {
            "reason": reason,
            "previous_state": previous_state.value,
        })

        logger.info(
            "Kill switch deactivated",
            extra={"previous_state": previous_state.value, "reason": reason},
        )
        return True

    # ------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------

    def get_active_switch(self) -> KillSwitchState:
        """Get the current kill switch state.

        Returns:
            KillSwitchState.NORMAL, SOFT_ACTIVE, or CRITICAL_ACTIVE.
        """
        return self._state

    def is_entry_blocked(self) -> bool:
        """Check whether new entries are blocked.

        Returns:
            True if SOFT or CRITICAL kill switch is active.
        """
        return self._state in (
            KillSwitchState.SOFT_ACTIVE,
            KillSwitchState.CRITICAL_ACTIVE,
        )

    def is_flatten_active(self) -> bool:
        """Check whether flatten is active (CRITICAL only).

        Returns:
            True if CRITICAL kill switch is active.
        """
        return self._state == KillSwitchState.CRITICAL_ACTIVE

    def get_reason(self) -> str:
        """Get the reason for current activation.

        Returns:
            The reason string, or empty string if NORMAL.
        """
        return self._active_reason

    def get_activated_at(self) -> datetime | None:
        """Get when the kill switch was last activated.

        Returns:
            Datetime of last activation, or None if never activated.
        """
        return self._activated_at

    def get_activation_history(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get kill switch activation/deactivation history.

        Args:
            limit: Maximum number of history entries to return.

        Returns:
            List of history entries, newest first.
        """
        return list(reversed(self._activation_history[-limit:]))

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _record_history(self, event: str, reason: str) -> None:
        """Record an activation/deactivation event in history.

        Args:
            event: The event type (SOFT_ACTIVATED, CRITICAL_ACTIVATED, DEACTIVATED).
            reason: Why the event occurred.
        """
        self._activation_history.append({
            "event": event,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        })

    # ------------------------------------------------------------------
    # Persistence — survive system restarts
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist current kill switch state to disk.

        Saves state, reason, and activation timestamp so that
        if the system restarts, the kill switch state is restored.
        Silently ignores errors (non-fatal — state loss is logged but
        does not crash the system).
        """
        if self._persistence_path is None:
            return

        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "state": self._state.value,
                "reason": self._active_reason,
                "activated_at": self._activated_at.isoformat() if self._activated_at else None,
                "deactivated_at": self._deactivated_at.isoformat() if self._deactivated_at else None,
            }
            with open(self._persistence_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(
                "Failed to persist kill switch state",
                extra={"error": str(e), "path": str(self._persistence_path)},
            )

    def _load_state(self) -> None:
        """Restore kill switch state from disk on startup.

        If a persisted CRITICAL_ACTIVE state is found, logs a warning
        and RE-ACTIVATES critical (triggers flatten callback) since
        the original flatten may not have survived the restart.
        """
        if self._persistence_path is None:
            return

        if not self._persistence_path.exists():
            return

        try:
            with open(self._persistence_path) as f:
                data = json.load(f)

            state_str = data.get("state", "NORMAL")
            self._active_reason = data.get("reason", "")

            if state_str == "CRITICAL_ACTIVE":
                # CRITICAL state found on startup — re-activate to re-flatten
                logger.warning(
                    "Kill switch was CRITICAL before restart — re-activating",
                    extra={"reason": self._active_reason},
                )
                self.activate_critical(
                    reason=(self._active_reason or "Restored from persistence — re-flatten"),
                )
            elif state_str == "SOFT_ACTIVE":
                self._state = KillSwitchState.SOFT_ACTIVE
                self._activated_at = datetime.utcnow()
                logger.info(
                    "Kill switch restored to SOFT_ACTIVE from persistence",
                    extra={"reason": self._active_reason},
                )
        except Exception as e:
            logger.warning(
                "Failed to restore kill switch state",
                extra={"error": str(e), "path": str(self._persistence_path)},
            )

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
