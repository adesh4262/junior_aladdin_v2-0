"""Source adapters for Floor 1.

Provides:
  - AngelOneAdapter: WebSocket + REST connectivity with full lifecycle
  - ManualSourceAdapter: handles manually entered packet data
  - BackupAdapter stub: future-proof slot for alternative data sources

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

import threading
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

# NIFTY 50 index token for Angel One WebSocket subscription
NIFTY_INDEX_TOKEN = "26000"

# Key NIFTY 50 stocks to subscribe to for live tick data
# (token, symbol) — most liquid/important ones first
NIFTY_50_STOCK_TOKENS: list[tuple[str, str]] = [
    ("1594", "RELIANCE"),   # Reliance Industries
    ("11536", "TCS"),       # TCS
    ("3045", "INFY"),       # Infosys
    ("350", "HDFCBANK"),    # HDFC Bank
    ("4963", "ICICIBANK"),  # ICICI Bank
    ("11915", "WIPRO"),     # Wipro
    ("5715", "ITC"),        # ITC
    ("1660", "BAJFINANCE"), # Bajaj Finance
    ("3456", "KOTAKBANK"),  # Kotak Mahindra Bank
    ("11630", "LT"),        # Larsen & Toubro
    ("3787", "SBIN"),       # State Bank of India
    ("8814", "MARUTI"),     # Maruti Suzuki
    ("4494", "HINDUNILVR"), # Hindustan Unilever
    ("685", "BHARTIARTL"),  # Bharti Airtel
    ("8226", "HCLTECH"),    # HCL Technologies
    ("11287", "SUNPHARMA"), # Sun Pharma
    ("5108", "TITAN"),      # Titan
    ("14977", "DMART"),     # Avenue Supermarts (DMart)
    ("2885", "ASIANPAINT"), # Asian Paints
    ("17818", "ADANIENT"),  # Adani Enterprises
    ("17971", "ADANIPORTS"),# Adani Ports
    ("1356", "BAJAJFINSV"), # Bajaj Finserv
    ("4671", "DRREDDY"),    # Dr. Reddy's
    ("1922", "NTPC"),       # NTPC
    ("14872", "POWERGRID"), # Power Grid Corporation
    ("980", "M&M"),        # Mahindra & Mahindra
    ("11667", "ULTRACEMCO"),# UltraTech Cement
    ("2104", "JSWSTEEL"),   # JSW Steel
    ("9904", "ONGC"),       # Oil and Natural Gas Corporation
    ("11491", "TATAMOTORS"),# Tata Motors
    ("11895", "TATASTEEL"), # Tata Steel
    ("3432", "JIOFIN"),     # Jio Financial Services
    ("3433", "SBILIFE"),    # SBI Life Insurance
    ("11511", "TRENT"),     # Trent
    ("1330", "BAJAJHLDNG"), # Bajaj Holdings
    ("14418", "HAL"),       # Hindustan Aeronautics
    ("10666", "COALINDIA"), # Coal India
]

# Deduplicated list of NIFTY 50 stock tokens to subscribe to
NIFTY_50_TOKENS: list[str] = list(dict.fromkeys([tok for tok, sym in NIFTY_50_STOCK_TOKENS]))


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

        # WebSocket instance (SmartWebSocketV2)
        self._ws: Any = None
        self._ws_thread: threading.Thread | None = None

        # Config values needed for WebSocket
        self._api_key: str | None = None
        self._client_code: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish connection to Angel One.

        Performs REST authentication first, then establishes the SmartAPI
        WebSocket for live market data streaming.

        Returns:
            True if connection succeeds.

        Raises:
            ConnectionError: If authentication or Websocket connection fails.
        """
        if self._connected:
            logger.info(
                "Already connected, skipping",
                extra={"connection_id": self._connection_id},
            )
            return True

        try:
            # Step 1: REST Authentication
            self._auth.login()

            # Extract config values for WebSocket
            self._api_key = self._auth._config.get("angel_one.api_key")
            self._client_code = self._auth._config.get("angel_one.client_id")

            logger.info(
                "REST authentication successful — establishing WebSocket",
                extra={"connection_id": self._connection_id},
            )

            # Step 2: Establish SmartAPI WebSocket for live ticks
            self._connect_websocket()

            # Step 3: Mark as connected
            self._connected = True
            self._health.transition_to(LifecycleState.HEALTHY)
            self._health.update_heartbeat()

            logger.info(
                "Angel One connected — WebSocket streaming live data",
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

        Closes the WebSocket connection, marks as disconnected,
        and updates health state.
        Does NOT clear authentication token (can be reused on reconnect).
        """
        # Close WebSocket if active
        if self._ws is not None:
            try:
                self._ws.close_connection()
            except Exception:
                logger.debug("WebSocket close error (non-fatal)")
            self._ws = None

        self._connected = False
        self._health.transition_to(LifecycleState.DISCONNECTED)
        logger.info(
            "Disconnected — WebSocket closed",
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

        Feeds are just registered in the list — actual WebSocket token
        subscription happens automatically in ``_on_open`` when the
        WebSocket connects (via ``_ws_subscribe_nifty_tokens``).

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

    def _connect_websocket(self) -> None:
        """Establish the SmartAPI WebSocket for live market data.

        Creates a SmartWebSocketV2 instance with the authenticated tokens,
        sets up data/error callbacks, connects, and subscribes to NIFTY 50
        tokens for live LTP data.

        If tokens are missing (e.g. test environment or no feed token),
        logs a warning and returns gracefully — REST auth still succeeded.
        """
        token = self._auth.get_token()
        feed_token = self._auth.get_feed_token()

        if not token or not feed_token:
            logger.warning(
                "WebSocket not connected — tokens not available "
                "(has_token=%s, has_feed_token=%s). "
                "Live ticks will not be available.",
                token is not None,
                feed_token is not None,
            )
            return

        if not self._api_key or not self._client_code:
            logger.warning(
                "WebSocket not connected — API key or client code not available"
            )
            return

        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            # Create WebSocket instance
            sws = SmartWebSocketV2(
                auth_token=token,
                api_key=self._api_key,
                client_code=self._client_code,
                feed_token=feed_token,
                max_retry_attempt=3,  # Auto-reconnect up to 3 times
            )

            # ── Callbacks ─────────────────────────────────────

            def _on_open(wsapp) -> None:
                """WebSocket opened — subscribe to tokens.

                SmartWebSocketV2 calls ``on_open`` with a single argument
                (the WebSocket app instance).
                """
                logger.info(
                    "SmartAPI WebSocket connected",
                    extra={"connection_id": self._connection_id},
                )
                # Register spot_tick feed so incoming data flows to callbacks
                if "spot_tick" not in self._subscribed_feeds:
                    self._subscribed_feeds.append("spot_tick")
                self._ws_subscribe_nifty_tokens()

            def _on_data(wsapp, parsed_message) -> None:
                """Received parsed tick data from WebSocket."""
                try:
                    # Log raw message format for first few ticks
                    msg_type = type(parsed_message).__name__
                    if isinstance(parsed_message, dict):
                        logger.info(
                            "RAW TICK: type=%s, keys=%s, sample=%s",
                            msg_type,
                            list(parsed_message.keys())[:10],
                            str(parsed_message)[:200],
                        )
                    else:
                        logger.info("RAW TICK: type=%s, len=%s, sample=%s",
                                     msg_type,
                                     len(str(parsed_message)) if hasattr(parsed_message, '__len__') else '?',
                                     str(parsed_message)[:200])
                    
                    tick_data = self._normalize_tick(parsed_message)
                    if tick_data:
                        self._receive_data("spot_tick", tick_data)
                except Exception:
                    logger.debug("Tick data parse error (non-fatal)", exc_info=True)

            def _on_error(wsapp, error) -> None:
                """WebSocket error occurred."""
                logger.warning(
                    "SmartAPI WebSocket error: %s",
                    error,
                    extra={"connection_id": self._connection_id},
                )
                self._health.transition_to(LifecycleState.DEGRADED)

            def _on_close(wsapp, code, reason) -> None:
                """WebSocket closed."""
                logger.info(
                    "SmartAPI WebSocket closed (code=%s, reason=%s)",
                    code, reason,
                    extra={"connection_id": self._connection_id},
                )
                self._health.transition_to(LifecycleState.DISCONNECTED)

            # Attach callbacks
            sws.on_open = _on_open
            sws.on_data = _on_data
            sws.on_error = _on_error
            sws.on_close = _on_close

            # Store reference before starting thread
            self._ws = sws

            # Connect in a daemon thread — SmartWebSocketV2.connect() is blocking
            # (runs the WebSocket event loop forever)
            ws_thread = threading.Thread(
                target=sws.connect,
                daemon=True,
                name="angel-one-ws",
            )
            ws_thread.start()
            self._ws_thread = ws_thread

            logger.info(
                "SmartAPI WebSocket connecting to %s (daemon thread)",
                SmartWebSocketV2.ROOT_URI,
            )

        except ImportError:
            raise ConnectionError(
                "smartapi-python SDK not installed — cannot establish WebSocket",
            )
        except Exception as e:
            self._ws = None
            raise ConnectionError(
                "Failed to establish SmartAPI WebSocket",
                original_exception=e,
            )

    def _ws_subscribe_nifty_tokens(self) -> None:
        """Subscribe to NIFTY 50 tokens on the active WebSocket.

        Subscribes to:
        - NIFTY 50 index (token 26000) for overall market view
        - Key NIFTY 50 stocks for individual tick data

        Subscribes in LTP mode (mode=1) for minimum bandwidth usage.
        """
        if self._ws is None:
            logger.warning("Cannot subscribe — WebSocket not connected")
            return

        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            # Build token list: NIFTY index + stocks, all on NSE_CM (exchange 1)
            all_tokens = [NIFTY_INDEX_TOKEN] + NIFTY_50_TOKENS

            token_list = [
                {"exchangeType": SmartWebSocketV2.NSE_CM, "tokens": all_tokens}
            ]

            # Subscribe in LTP mode (1) for lightweight updates
            self._ws.subscribe(
                correlation_id="NIFTYSUB01",
                mode=SmartWebSocketV2.LTP_MODE,
                token_list=token_list,
            )

            logger.info(
                "Subscribed to %d tokens on SmartAPI WebSocket (LTP mode)",
                len(all_tokens),
                extra={
                    "connection_id": self._connection_id,
                    "tokens": f"NIFTY index + {len(NIFTY_50_TOKENS)} stocks",
                },
            )

        except Exception as e:
            logger.error(
                "Failed to subscribe to NIFTY tokens",
                extra={"error": str(e), "connection_id": self._connection_id},
            )

    def _resubscribe_feeds(self) -> None:
        """Re-subscribe previously registered feeds after reconnect.

        After reconnection, re-establishes the WebSocket connection and
        re-subscribes to all previously registered feed tokens.
        """
        if self._subscribed_feeds:
            logger.info(
                "Re-subscribing %d feed(s) after reconnect",
                len(self._subscribed_feeds),
                extra={"feeds": self._subscribed_feeds, "connection_id": self._connection_id},
            )
            # Re-establish WebSocket if needed
            if self._connected and self._ws is None:
                try:
                    self._connect_websocket()
                except Exception as e:
                    logger.error("WebSocket reconnection failed: %s", e)

    @staticmethod
    def _normalize_tick(parsed_message: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a raw WebSocket tick into a consistent format.

        The SmartAPI WebSocket returns various formats depending on mode.
        This method normalises them into a standard dict with fields:
            - token: str
            - symbol: str (if available)
            - last_price: float
            - volume: int
            - timestamp: str (ISO format)
            - exchange_type: int

        Args:
            parsed_message: The raw parsed message from SmartWebSocketV2.

        Returns:
            Normalized tick dict, or None if unparseable.
        """
        if not parsed_message or not isinstance(parsed_message, dict):
            return None

        # SmartAPI typically returns keys like:
        # 'tk' (token), 'ltp' (last_traded_price), 'lp' (last_price),
        # 'v' (volume), 'e' (exchange_type)
        token = parsed_message.get("tk") or parsed_message.get("token") or ""

        # LTP could be in 'ltp', 'lp', or 'last_traded_price'
        last_price = (
            parsed_message.get("ltp")
            or parsed_message.get("lp")
            or parsed_message.get("last_price")
            or parsed_message.get("last_traded_price")
            or 0.0
        )

        volume = parsed_message.get("v") or parsed_message.get("volume") or 0
        exchange_type = parsed_message.get("e") or parsed_message.get("exchange") or 1
        symbol = parsed_message.get("symbol") or parsed_message.get("sym") or ""

        # Ensure token is a string for consistent matching
        token_str = str(token)

        return {
            "token": token_str,
            "symbol": symbol,
            "last_price": float(last_price),
            "volume": int(volume),
            "exchange_type": int(exchange_type),
            "feed_type": "spot_tick",
        }

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
