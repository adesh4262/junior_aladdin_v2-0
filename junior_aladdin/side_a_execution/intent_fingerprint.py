"""Side A — Intent Fingerprint: Duplicate execution prevention.

This module provides lightweight execution-safe identity tracking for
ExecutionIntents. It prevents accidental duplicate execution by
generating, registering, and checking fingerprints with TTL-based expiry.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 4 & SIDE_A V1.1):
- Duplicate detection protects against accidental retry submissions
- Different intents = different fingerprints (low false positive rate)
- Short TTL prevents stale fingerprint accumulation
- Fingerprint is NOT market intelligence, NOT conviction, NOT trade decision
- CAUTION severity minimum for duplicate blocks (escalation possible)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from junior_aladdin.shared.types import ExecutionIntent


# =============================================================================
# Constants
# =============================================================================

DEFAULT_FINGERPRINT_TTL_SECONDS: int = 60
"""Default TTL for a registered fingerprint (in seconds)."""

DEFAULT_TIMESTAMP_WINDOW_SECONDS: int = 5
"""Default time window granularity for fingerprint generation (in seconds).

Same trade within this window produces the same fingerprint for
duplicate detection. Larger window = more protection but higher
false positive risk for legitimate same-second intents.
"""


# =============================================================================
# Helper: fingerprint generation
# =============================================================================


def generate_fingerprint(
    trade_id: str,
    action: str,
    strike: str,
    timestamp: datetime,
    window_seconds: int = DEFAULT_TIMESTAMP_WINDOW_SECONDS,
) -> str:
    """Generate a unique fingerprint for an execution intent.

    Based on: trade_id + action + strike + timestamp_window.
    The timestamp_window rounds down to the nearest N-second window
    so that retries within the window produce the same fingerprint.

    Args:
        trade_id: The trade's unique identifier.
        action: BUY or SELL.
        strike: The selected strike price.
        timestamp: The intent's creation timestamp.
        window_seconds: Time window granularity in seconds.

    Returns:
        A 32-character hex digest string serving as the intent fingerprint.
    """
    window_ts = int(timestamp.timestamp() // window_seconds) * window_seconds
    raw = f"{trade_id}|{action}|{strike}|{window_ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def generate_fingerprint_from_intent(
    intent: ExecutionIntent,
    window_seconds: int = DEFAULT_TIMESTAMP_WINDOW_SECONDS,
) -> str:
    """Generate a fingerprint directly from an ExecutionIntent.

    Convenience wrapper that extracts the required fields from the intent.

    Args:
        intent: The ExecutionIntent to fingerprint.
        window_seconds: Time window granularity in seconds.

    Returns:
        A 32-character hex digest string.
    """
    return generate_fingerprint(
        trade_id=intent.trade_id,
        action=intent.action,
        strike=intent.selected_strike,
        timestamp=intent.timestamp,
        window_seconds=window_seconds,
    )


# =============================================================================
# FingerprintStore
# =============================================================================


class IntentFingerprintStore:
    """In-memory registry for intent fingerprints with TTL-based expiry.

    Maintains a dict of fingerprint → registration timestamp.
    Old entries are evicted on access (lazy expiry — checked during
    register and is_duplicate calls, not via background timer).

    Thread-safety note: This is an in-memory store designed for a
    single-threaded async application. For multi-threaded environments,
    a lock would be needed around the _fingerprints dict.
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_FINGERPRINT_TTL_SECONDS,
    ) -> None:
        """Initialize an empty fingerprint store.

        Args:
            ttl_seconds: TTL in seconds for registered fingerprints.
        """
        self._ttl_seconds = ttl_seconds
        self._fingerprints: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_fingerprint(self, fingerprint: str) -> bool:
        """Register a fingerprint for duplicate detection.

        If the fingerprint is already registered and not expired,
        returns False (duplicate — not registered again).
        If expired or new, registers with current timestamp and returns True.

        Args:
            fingerprint: The fingerprint string to register.

        Returns:
            True if newly registered, False if already exists (duplicate).
        """
        self._evict_expired()

        # Check if already registered and not expired
        if fingerprint in self._fingerprints:
            return False

        self._fingerprints[fingerprint] = datetime.utcnow()
        return True

    def is_duplicate(self, fingerprint: str) -> bool:
        """Check whether a fingerprint is already registered as a duplicate.

        Also checks for expired entries and evicts them before checking.

        Args:
            fingerprint: The fingerprint string to check.

        Returns:
            True if the fingerprint is already registered and not expired.
        """
        self._evict_expired()
        return fingerprint in self._fingerprints

    def clear_session(self) -> int:
        """Clear ALL registered fingerprints (reset for new trading day).

        Returns:
            The number of fingerprints that were cleared.
        """
        count = len(self._fingerprints)
        self._fingerprints.clear()
        return count

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def evict_expired(self) -> int:
        """Explicitly evict all expired fingerprints from the store.

        This is an external-facing method that can be called by a
        periodic scheduler (e.g., orchestrator's event loop) to
        proactively clean up expired fingerprints rather than waiting
        for the next ``register_fingerprint`` or ``is_duplicate`` call.

        Returns:
            The number of evicted entries.
        """
        return self._evict_expired()

    def get_active_count(self) -> int:
        """Get the number of currently active (non-expired) fingerprints.

        Returns:
            Active fingerprint count after evicting expired entries.
        """
        evicted = self._evict_expired()
        return len(self._fingerprints)

    def get_fingerprint_timestamp(self, fingerprint: str) -> datetime | None:
        """Get the registration timestamp for a fingerprint.

        Args:
            fingerprint: The fingerprint string to look up.

        Returns:
            The datetime when the fingerprint was registered, or None if not found.
        """
        return self._fingerprints.get(fingerprint)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def ttl_seconds(self) -> int:
        """Get the current TTL in seconds."""
        return self._ttl_seconds

    @ttl_seconds.setter
    def ttl_seconds(self, value: int) -> None:
        """Set the TTL in seconds."""
        if value <= 0:
            raise ValueError(f"TTL must be positive, got {value}")
        self._ttl_seconds = value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_expired(self) -> int:
        """Remove all expired fingerprints from the store.

        A fingerprint is expired if its registration timestamp is older
        than ttl_seconds from now.

        Returns:
            The number of evicted (expired) entries.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self._ttl_seconds)
        expired_keys = [
            key
            for key, reg_ts in self._fingerprints.items()
            if reg_ts < cutoff
        ]
        for key in expired_keys:
            del self._fingerprints[key]
        return len(expired_keys)
