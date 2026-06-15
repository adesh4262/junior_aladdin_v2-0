"""Junior Aladdin — Shared SystemConfig singleton.

PERSISTENT runtime configuration that is NOT subject to cache TTL expiry.

The Side B session cache (CacheTier.COLD = 30s TTL) was being used to store
mode/capital/kill_switch — causing operator commands to revert after 30 seconds.

SystemConfig solves this by providing persistent in-memory storage that:
- Never expires (no TTL)
- Is a module-level singleton (same instance everywhere)
- Reads .env + config/*.yaml on init
- Accepts runtime overrides (operator commands from dashboard)
- Is importable from any floor/side without circular imports
- Thread-safe for background poller + dashboard API access

Usage:
    from junior_aladdin.shared.system_config import get_system_config

    config = get_system_config()
    
    # Read
    mode = config.get_mode()
    capital = config.get_capital_limit()
    
    # Write (from dashboard control routes)
    config.set_mode(ExecutionMode.PAPER, reason="Paper trading session")
    config.set_capital_limit(50000.0, reason="Daily limit")
    config.set_kill_switch("SOFT", reason="High volatility")
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.types import ExecutionMode


# =============================================================================
# SystemConfig
# =============================================================================


@dataclass
class _ControlState:
    """Inner mutable state for SystemConfig — wrapped for thread safety.

    All mutations go through SystemConfig methods which acquire the lock.
    """
    mode: ExecutionMode = ExecutionMode.ALERT
    capital_limit: float | None = None
    kill_switch_state: str = "NORMAL"  # NORMAL / SOFT / CRITICAL
    capital_reason: str = ""
    mode_reason: str = ""
    kill_switch_reason: str = ""
    mode_updated_at: datetime = field(default_factory=datetime.utcnow)
    capital_updated_at: datetime | None = None
    kill_switch_updated_at: datetime | None = None

    # Environment overrides from .env / config
    env_name: str = "development"
    angel_one_client_id: str = ""
    angel_one_api_key: str = ""
    angel_one_pin: str = ""
    angel_one_totp_secret: str = ""


class SystemConfig:
    """Persistent runtime configuration — NOT subject to cache TTL.

    Thread-safe singleton. All public methods acquire a reentrant lock
    so background poller and dashboard API can safely coexist.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = _ControlState()
        self._load_env()

    # ── Mode ──────────────────────────────────────────────────────────

    def get_mode(self) -> ExecutionMode:
        """Get current execution mode."""
        with self._lock:
            return self._state.mode

    def set_mode(self, mode: ExecutionMode | str, reason: str = "") -> None:
        """Set execution mode.

        Args:
            mode: ExecutionMode enum or string (ALERT / PAPER / REAL).
            reason: Optional operator rationale.

        Raises:
            ValidationError: If mode string is invalid.
        """
        with self._lock:
            if isinstance(mode, str):
                try:
                    mode = ExecutionMode(mode.upper())
                except ValueError:
                    raise ValidationError(
                        f"Invalid execution mode: {mode}. Must be ALERT, PAPER, or REAL.",
                    )
            self._state.mode = mode
            self._state.mode_reason = reason
            self._state.mode_updated_at = datetime.utcnow()

    # ── Capital ───────────────────────────────────────────────────────

    def get_capital_limit(self) -> float | None:
        """Get current capital limit, or None if not set."""
        with self._lock:
            return self._state.capital_limit

    def set_capital_limit(self, limit: float, reason: str = "") -> None:
        """Set capital limit.

        Args:
            limit: Capital limit in INR (must be positive or 0 to clear).
            reason: Optional operator rationale.
        """
        with self._lock:
            if limit < 0:
                raise ValidationError(f"Capital limit cannot be negative: {limit}")
            self._state.capital_limit = limit if limit > 0 else None
            self._state.capital_reason = reason
            self._state.capital_updated_at = datetime.utcnow()

    # ── Kill Switch ───────────────────────────────────────────────────

    def get_kill_switch_state(self) -> str:
        """Get current kill switch state (NORMAL / SOFT / CRITICAL)."""
        with self._lock:
            return self._state.kill_switch_state

    def set_kill_switch(self, state: str, reason: str = "") -> None:
        """Set kill switch state.

        Args:
            state: NORMAL, SOFT, or CRITICAL.
            reason: Required for SOFT and CRITICAL activations.

        Raises:
            ValidationError: If state is invalid or reason missing for activation.
        """
        with self._lock:
            state = state.upper()
            if state not in ("NORMAL", "SOFT", "CRITICAL"):
                raise ValidationError(
                    f"Invalid kill switch state: {state}. Must be NORMAL, SOFT, or CRITICAL.",
                )
            if state in ("SOFT", "CRITICAL") and not reason:
                raise ValidationError(
                    f"Kill switch {state} activation requires a reason.",
                )
            self._state.kill_switch_state = state
            self._state.kill_switch_reason = reason
            self._state.kill_switch_updated_at = datetime.utcnow()

    # ── Bulk snapshot ────────────────────────────────────────────────

    def get_snapshot(self) -> dict[str, Any]:
        """Get a snapshot of all runtime config for dashboard display."""
        with self._lock:
            return {
                "mode": self._state.mode.value,
                "capital_limit": self._state.capital_limit,
                "kill_switch_state": self._state.kill_switch_state,
                "mode_reason": self._state.mode_reason,
                "capital_reason": self._state.capital_reason,
                "kill_switch_reason": self._state.kill_switch_reason,
                "mode_updated_at": self._state.mode_updated_at.isoformat(),
                "capital_updated_at": (
                    self._state.capital_updated_at.isoformat()
                    if self._state.capital_updated_at else None
                ),
                "kill_switch_updated_at": (
                    self._state.kill_switch_updated_at.isoformat()
                    if self._state.kill_switch_updated_at else None
                ),
                "env": self._state.env_name,
            }

    # ── Angel One credentials ────────────────────────────────────────

    def get_angel_one_credentials(self) -> dict[str, str]:
        """Get Angel One API credentials from config."""
        with self._lock:
            return {
                "client_id": self._state.angel_one_client_id,
                "api_key": self._state.angel_one_api_key,
                "pin": self._state.angel_one_pin,
                "totp_secret": self._state.angel_one_totp_secret,
            }

    # ── Internal ──────────────────────────────────────────────────────

    def _load_env(self) -> None:
        """Load environment variables and config yaml values."""
        # Environment
        self._state.env_name = os.getenv("ENV", "development")

        # Angel One from .env
        self._state.angel_one_client_id = os.getenv("ANGEL_ONE_CLIENT_ID", "")
        self._state.angel_one_api_key = os.getenv("ANGEL_ONE_API_KEY", "")
        self._state.angel_one_pin = os.getenv("ANGEL_ONE_PIN", "")
        self._state.angel_one_totp_secret = os.getenv("ANGEL_ONE_TOTP_SECRET", "")

        # If .env didn't have values, try the config yaml via existing Config class
        if not self._state.angel_one_client_id:
            try:
                from junior_aladdin.shared.config import Config
                cfg = Config()
                self._state.angel_one_client_id = cfg.get("angel_one.client_id") or ""
                self._state.angel_one_api_key = cfg.get("angel_one.api_key") or ""
                self._state.angel_one_pin = cfg.get("angel_one.pin") or ""
                self._state.angel_one_totp_secret = cfg.get("angel_one.totp_secret") or ""
            except Exception:
                pass  # Config not available — will fail at login time


# Module-level singleton
_system_config: SystemConfig | None = None
_system_config_lock = threading.Lock()


def get_system_config() -> SystemConfig:
    """Return the module-level singleton SystemConfig.

    Thread-safe — uses a dedicated lock for first-time initialisation.
    """
    global _system_config  # noqa: PLW0603
    if _system_config is None:
        with _system_config_lock:
            if _system_config is None:
                _system_config = SystemConfig()
    return _system_config
