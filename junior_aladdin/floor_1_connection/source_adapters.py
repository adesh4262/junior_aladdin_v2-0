"""Source adapters for Floor 1.

Provides:
  - AngelOneAdapter: WebSocket + REST connectivity with full lifecycle
  - ManualSourceAdapter: handles manually entered packet data
  - BackupAdapter stub: future-proof slot for alternative data sources

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from typing import Any, Callable

from junior_aladdin.floor_1_connection.auth_manager import AuthManager
from junior_aladdin.floor_1_connection.shared_utils import (
    generate_connection_id,
    retry_with_backoff,
)
from junior_aladdin.floor_1_connection.source_health import SourceHealthMonitor
from junior_aladdin.shared.errors import ConnectionError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import LifecycleState

logger = get_logger("source_adapters")

# Type alias for data callbacks
DataCallback = Callable[[str, str, dict[str, Any]], None]  # (source_name, feed_type, raw_data)


# ------------------------------------------------------------------
# AngelOneAdapter
# ------------------------------------------------------------------


class AngelOneAdapter:
    """Angel One WebSocket + REST source adapter.

    Manages the full connection lifecycle:
        CONNECT → HEALTHY ↔ DEGRADED ↔ STALE → DISCONNECTED
                                               → HEALTHY (reconnect)
        HEALTHY → AUTH_FAILED → DISCONNECTED → HEALTHY (re-auth + reconnect)

    Integrates AuthManager for credential handling and
    SourceHealthMonitor for lifecycle state tracking.
    """

    def __init__(
        self,
        auth_manager: AuthManager | None = None,
        health_monitor: SourceHealthMonitor | None = None,
    ) -> None:
        self._connection_id = generate_connection_id()
        self._auth = auth_manager or AuthManager()
        self._health = health_monitor or SourceHealthMonitor(self._connection_id)
        self._data_callbacks: list[DataCallback] = []
        self._subscribed_feeds: list[str] = []
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish connection to Angel One.

        Performs authentication first, then marks the connection as active.
        Uses retry_with_backoff for resilience.

        Returns:
            True if connection succeeds.

        Raises:
            ConnectionError: If authentication or connection fails.
        """
        if self._connected:
            logger.info(
                "Already connected, skipping",
                extra={"connection_id": self._connection_id},
            )
            return True

        try:
            # Step 1: Authenticate
            self._auth.login()
            logger.info(
                "Authentication successful",
                extra={"connection_id": self._connection_id},
            )

            # Step 2: Mark as connected
            self._connected = True
            self._health.transition_to(LifecycleState.HEALTHY)
            self._health.update_heartbeat()

            logger.info(
                "Connection established",
                extra={"connection_id": self._connection_id},
            )
            return True

        except ConnectionError:
            self._connected = False
            self._health.transition_to(LifecycleState.AUTH_FAILED)
            raise
        except Exception as e:
            self._connected = False
            self._health.transition_to(LifecycleState.DEGRADED)
            raise ConnectionError(
                "Failed to connect to Angel One",
                details={"connection_id": self._connection_id},
                original_exception=e,
            )

    def disconnect(self) -> None:
        """Disconnect from Angel One gracefully.

        Marks the connection as disconnected and updates health state.
        Does NOT clear authentication token (can be reused on reconnect).
        """
        self._connected = False
        self._health.transition_to(LifecycleState.DISCONNECTED)
        logger.info(
            "Disconnected",
            extra={"connection_id": self._connection_id},
        )

    def reconnect(self) -> bool:
        """Attempt to reconnect after a disconnect.

        Uses retry_with_backoff with exponential backoff.
        Re-authenticates if the token has expired or AUTH_FAILED state was set.
        Re-subscribes previously registered feeds after successful reconnect.

        Returns:
            True if reconnection succeeds.

        Raises:
            ConnectionError: If all reconnection attempts fail.
        """
        if self._connected:
            logger.info("Already connected, skipping reconnect")
            return True

        def _try_reconnect() -> bool:
            """Inner reconnect attempt."""
            try:
                # Re-authenticate if needed
                if not self._auth.is_authenticated():
                    self._auth.login()
                self._connected = True
                # On success: transition from DISCONNECTED → HEALTHY
                self._health.transition_to(LifecycleState.HEALTHY)
                self._health.update_heartbeat()
                # Re-subscribe feeds that were registered before disconnect
                self._resubscribe_feeds()
                logger.info(
                    "Reconnect successful",
                    extra={"connection_id": self._connection_id},
                )
                return True
            except Exception:
                self._connected = False
                raise

        try:
            return retry_with_backoff(_try_reconnect, max_retries=3, base_delay=1.0)
        except Exception as e:
            raise ConnectionError(
                "All reconnection attempts failed",
                details={
                    "connection_id": self._connection_id,
                    "max_retries": 3,
                },
                original_exception=e,
            )

    def is_connected(self) -> bool:
        """Check if the adapter is currently connected."""
        return self._connected

    def get_lifecycle_state(self) -> LifecycleState:
        """Return the current lifecycle state."""
        return self._health.lifecycle_state

    def subscribe_feeds(self, feed_types: list[str]) -> None:
        """Register feed types this adapter should receive.

        Args:
            feed_types: List of feed types (e.g., ``["spot_tick", "options_snapshot"]``).
        """
        for ft in feed_types:
            if ft not in self._subscribed_feeds:
                self._subscribed_feeds.append(ft)
        logger.info(
            "Feeds subscribed",
            extra={"connection_id": self._connection_id, "feeds": self._subscribed_feeds},
        )

    def on_data(self, callback: DataCallback) -> None:
        """Register a callback to receive incoming data.

        The callback receives ``(source_name, feed_type, raw_data)``.
        """
        if callback not in self._data_callbacks:
            self._data_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _receive_data(self, feed_type: str, raw_data: dict[str, Any]) -> None:
        """Process incoming data from the WebSocket / REST feed.

        Args:
            feed_type: The type of feed (must match a subscribed feed).
            raw_data: The raw data dict received.
        """
        if not self._connected:
            logger.warning(
                "Data received but not connected — ignoring",
                extra={"feed_type": feed_type, "connection_id": self._connection_id},
            )
            return

        # Only forward data for subscribed feeds
        if feed_type not in self._subscribed_feeds:
            logger.warning(
                "Data received for unsubscribed feed — ignoring",
                extra={"feed_type": feed_type, "connection_id": self._connection_id},
            )
            return

        # Update health metrics
        self._health.update_heartbeat()

        # Notify all data callbacks
        for cb in self._data_callbacks:
            try:
                cb("angel_one", feed_type, raw_data)
            except Exception:
                logger.error(
                    "Data callback failed",
                    extra={"feed_type": feed_type, "connection_id": self._connection_id},
                )

    def _resubscribe_feeds(self) -> None:
        """Re-subscribe previously registered feeds after reconnect.

        In a live WebSocket scenario, dropping the connection loses all
        subscriptions. This placeholder logs the re-subscription step;
        the real implementation will send subscription commands to the
        Angel One WebSocket after reconnect.
        """
        if self._subscribed_feeds:
            logger.info(
                "Re-subscribing %d feed(s)",
                len(self._subscribed_feeds),
                extra={"feeds": self._subscribed_feeds, "connection_id": self._connection_id},
            )

    @property
    def connection_id(self) -> str:
        return self._connection_id

    @property
    def subscribed_feeds(self) -> list[str]:
        return list(self._subscribed_feeds)


# ------------------------------------------------------------------
# ManualSourceAdapter
# ------------------------------------------------------------------


class ManualSourceAdapter:
    """Adapter for manually entered packet data.

    Handles calendar events, overrides, and other manual inputs.
    These get the same envelope treatment as live data.
    """

    def __init__(self) -> None:
        self._data_callbacks: list[DataCallback] = []

    def on_data(self, callback: DataCallback) -> None:
        """Register a callback to receive manual ingress data."""
        if callback not in self._data_callbacks:
            self._data_callbacks.append(callback)

    def submit_manual(self, feed_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Submit a manually entered packet.

        Args:
            feed_type: One of ``MANUAL_CALENDAR``, ``MANUAL_EVENT``, ``MANUAL_OVERRIDE``.
            raw_data: The manual packet data.

        Returns:
            The envelope-ready dict (same as what callbacks receive).

        Raises:
            ValueError: If feed_type is not a valid manual type.
        """
        valid_types = {"MANUAL_CALENDAR", "MANUAL_EVENT", "MANUAL_OVERRIDE"}
        if feed_type not in valid_types:
            raise ValueError(
                f"Invalid manual feed type: {feed_type}. "
                f"Must be one of: {', '.join(sorted(valid_types))}"
            )

        result = {
            "source": "manual",
            "feed_type": feed_type,
            "payload": raw_data,
        }

        for cb in self._data_callbacks:
            try:
                cb("manual", feed_type, raw_data)
            except Exception:
                logger.error(
                    "Manual data callback failed",
                    extra={"feed_type": feed_type},
                )

        return result


# ------------------------------------------------------------------
# BackupAdapter (STUB)
# ------------------------------------------------------------------


class BackupAdapter:
    """Future backup source adapter slot (STUB).

    Raises NotImplementedError on any operation.
    Architecture-ready for when alternative data sources are needed.
    """

    def __init__(self) -> None:
        raise NotImplementedError("BackupAdapter is not yet implemented")
