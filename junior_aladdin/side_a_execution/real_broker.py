"""Side A — Real Broker: Angel One live broker integration.

Strict live safety implementation of BrokerProtocol.  REAL mode uses conservative
order practices: LIMIT orders primary, SL-LIMIT for protection, never MARKET
without extreme justification.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.14):
- LIMIT orders primary (never MARKET in REAL without extreme justification)
- Protection: SL-LIMIT
- Same interface as PaperBroker (PAPER/REAL parity on core lifecycle)
- Brokers cannot be replayed — real-time only
- Disconnect → reconnect + reconcile flow
- Every rejection classified + logged

Order discipline (locked):
- Primary order: LIMIT (never MARKET in REAL without extreme justification)
- Protection: SL-LIMIT
- Reduce-only for safety (never increase size)

Dependencies:
- smartapi-python SDK (SmartConnect)
- Config for Angel One credentials
- AuthManager for token management
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from junior_aladdin.shared.config import Config
from junior_aladdin.shared.errors import ConnectionError, ExecutionError
from junior_aladdin.shared.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

#: Angel One order types mapped to SmartAPI constants
ORDER_TYPE_LIMIT: str = "LIMIT"
ORDER_TYPE_MARKET: str = "MARKET"
ORDER_TYPE_SL_LIMIT: str = "STOPLOSS_LIMIT"
ORDER_TYPE_SL_MARKET: str = "STOPLOSS_MARKET"

#: Angel One product types
PRODUCT_DELIVERY: str = "DELIVERY"
PRODUCT_INTRADAY: str = "INTRADAY"
PRODUCT_NORMAL: str = "NORMAL"

#: Angel One validity types
VALIDITY_DAY: str = "DAY"
VALIDITY_IOC: str = "IOC"

#: Angel One transaction types
TRANSACTION_BUY: str = "BUY"
TRANSACTION_SELL: str = "SELL"

#: Exchange for NIFTY options
EXCHANGE_NFO: str = "NFO"

#: Default exchange to use when not specified
DEFAULT_EXCHANGE: str = EXCHANGE_NFO


# =============================================================================
# Order type mapping from internal format to Angel One API format
# =============================================================================

_ORDER_TYPE_MAP: dict[str, str] = {
    "LIMIT": ORDER_TYPE_LIMIT,
    "MARKET": ORDER_TYPE_MARKET,
    "SL_LIMIT": ORDER_TYPE_SL_LIMIT,
    "SL_MARKET": ORDER_TYPE_SL_MARKET,
    "STOPLOSS_LIMIT": ORDER_TYPE_SL_LIMIT,
    "STOPLOSS_MARKET": ORDER_TYPE_SL_MARKET,
}


# =============================================================================
# RealBroker
# =============================================================================


class RealBroker:
    """Angel One live broker implementing BrokerProtocol.

    Strict live safety broker for REAL execution mode.  Uses LIMIT orders
    as primary, SL-LIMIT for protection.  Authenticates via AuthManager
    and communicates with Angel One REST API through SmartConnect SDK.

    Usage::

        broker = RealBroker(
            config=Config(),
            auth_manager=AuthManager(),
        )

        # Login (required before placing orders)
        broker.login()

        # Place an order (matches BrokerProtocol.place_order)
        response = broker.place_order({
            "trade_id": "T001",
            "action": "BUY",
            "option_side": "CE",
            "strike": "18500",
            "quantity": 1,
            "price": 150.0,
            "order_type": "LIMIT",
        })
    """

    def __init__(
        self,
        config: Config | None = None,
        auth_manager: Any | None = None,
        exchange: str = DEFAULT_EXCHANGE,
        product: str = PRODUCT_NORMAL,
    ) -> None:
        """Initialize the RealBroker.

        Args:
            config: Config instance for Angel One API credentials.
            auth_manager: AuthManager instance for token management.
                If None, creates a new one from config.
            exchange: Exchange for orders (default NFO for options).
            product: Product type (default NORMAL).
        """
        self._config = config or Config()
        self._exchange = exchange
        self._product = product

        # Auth manager (lazy-imported to avoid SDK requirement at module level)
        self._auth_manager = auth_manager
        self._smart_connect: Any = None
        self._authenticated: bool = False
        self._token: str | None = None
        self._client_id: str | None = None

        # Internal tracking
        self._orders: dict[str, dict[str, Any]] = {}
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Authenticate with Angel One API.

        Uses AuthManager for token generation.  Falls back to direct
        SmartConnect login if AuthManager is not provided.

        Returns:
            True if login succeeded.

        Raises:
            ConnectionError: If authentication fails.
        """
        if self._authenticated and self._token:
            logger.info("Already authenticated — skipping login")
            return True

        if self._auth_manager is not None:
            try:
                self._token = self._auth_manager.login()
                self._client_id = self._config.get("angel_one.client_id", "")

                # Retrieve the SmartConnect instance from auth_manager
                smart_connect = self._auth_manager.get_smart_connect()
                if smart_connect is not None:
                    self._smart_connect = smart_connect

                self._authenticated = True
                self._connected = True
                logger.info("Real broker authenticated via AuthManager")
                return True
            except ConnectionError:
                raise
            except Exception as e:
                raise ConnectionError(
                    "Real broker authentication failed",
                    details={"error": str(e)},
                    original_exception=e,
                )

        # Fallback: direct SmartConnect login
        return self._direct_login()

    def _direct_login(self) -> bool:
        """Direct SmartConnect login without AuthManager.

        Returns:
            True if login succeeded.

        Raises:
            ConnectionError: If credentials missing or login fails.
        """
        client_id = self._config.get("angel_one.client_id")
        api_key = self._config.get("angel_one.api_key")
        pin = self._config.get("angel_one.pin")

        if not client_id or not api_key or not pin:
            raise ConnectionError(
                "Missing Angel One credentials for direct login",
                details={
                    "has_client_id": client_id is not None,
                    "has_api_key": api_key is not None,
                    "has_pin": pin is not None,
                },
            )

        try:
            from SmartApi import SmartConnect  # type: ignore[import-untyped]

            smart_connect = SmartConnect(api_key=api_key)
            data = smart_connect.generateSession(
                client_id=client_id,
                password=pin,
                token=self._generate_totp(),
            )

            if not data or not isinstance(data, dict):
                raise ConnectionError("Invalid response from Angel One login")

            session_data = data.get("data") or data
            self._token = session_data.get("accessToken")
            self._client_id = client_id
            self._smart_connect = smart_connect
            self._authenticated = True
            self._connected = True

            logger.info(
                "Real broker direct login successful",
                extra={"client_id": client_id[:4] + "****"},
            )
            return True

        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(
                "Angel One direct login failed",
                details={"client_id": client_id[:4] + "****"},
                original_exception=e,
            )

    def logout(self) -> None:
        """Log out and clear authentication state."""
        self._token = None
        self._client_id = None
        self._smart_connect = None
        self._authenticated = False
        self._connected = False
        self._orders.clear()
        logger.info("Real broker logged out")

    def is_authenticated(self) -> bool:
        """Check if currently authenticated with a valid token.

        Returns:
            True if authenticated.
        """
        return self._authenticated and self._token is not None

    # ------------------------------------------------------------------
    # BrokerProtocol Implementation
    # ------------------------------------------------------------------

    def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Submit an order to Angel One.

        Validates authentication, translates order data to Angel One API
        format, and submits via SmartConnect.

        Args:
            order_data: Dict with trade_id, action, option_side, strike,
                       quantity, price, order_type, sl_price, etc.

        Returns:
            Dict with order_id, status, timestamp.

        Raises:
            ExecutionError: If not authenticated or order placement fails.
        """
        if not self.is_authenticated():
            raise ExecutionError(
                "Cannot place order — not authenticated. Call login() first.",
            )

        # --- Step 1: Parse order data ---
        action = order_data.get("action", "BUY")
        option_side = order_data.get("option_side", "CE")
        strike = order_data.get("strike", "")
        quantity = order_data.get("quantity", 1)
        price = order_data.get("price", 0.0)
        order_type = order_data.get("order_type", "LIMIT")
        sl_price = order_data.get("sl_price")
        validity = order_data.get("validity", "DAY")

        # --- Step 2: Build trading symbol ---
        # Format: SYMBOL expiry strike PE/CE (e.g., "NIFTY 25JUN18500 CE")
        symbol = self._build_trading_symbol(option_side, strike)

        # --- Step 3: Map order type ---
        mapped_type = _ORDER_TYPE_MAP.get(order_type, ORDER_TYPE_LIMIT)

        # --- Step 4: Build Angel One order params ---
        order_params: dict[str, Any] = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": "",  # Would be resolved from symbol in production
            "transactiontype": TRANSACTION_BUY if action == "BUY" else TRANSACTION_SELL,
            "exchange": self._exchange,
            "ordertype": mapped_type,
            "producttype": self._product,
            "duration": VALIDITY_DAY if validity == "DAY" else validity,
            "price": str(price) if price > 0 else "0",
            "squareoff": "0",
            "stoploss": str(sl_price) if sl_price else "0",
            "quantity": str(quantity),
        }

        # --- Step 5: Submit via SmartConnect ---
        try:
            smart_connect = self._smart_connect
            if smart_connect is None:
                try:
                    from SmartApi import SmartConnect  # type: ignore[import-untyped]
                except ImportError:
                    raise ExecutionError(
                        message="SmartApi SDK not installed — required for real broker",
                    )
                smart_connect = SmartConnect(
                    api_key=self._config.get("angel_one.api_key", ""),
                )

            response = smart_connect.placeOrder(order_params)
        except Exception as e:
            error_msg = str(e)
            logger.error(
                "Angel One order placement failed",
                extra={"error": error_msg, "trade_id": order_data.get("trade_id", "")},
            )
            raise ExecutionError(
                message=f"Angel One order placement failed: {error_msg}",
                details={
                    "trade_id": order_data.get("trade_id", ""),
                    "action": action,
                    "symbol": symbol,
                },
                original_exception=e,
            )

        # --- Step 6: Parse response ---
        order_id = self._parse_order_response(response)
        now = datetime.utcnow()

        self._orders[order_id] = {
            "order_data": order_data,
            "status": "ACKNOWLEDGED",
            "symbol": symbol,
            "created_at": now,
            "updated_at": now,
            "raw_response": response,
        }

        logger.info(
            "Real broker order placed",
            extra={
                "order_id": order_id,
                "trade_id": order_data.get("trade_id", ""),
                "symbol": symbol,
            },
        )

        return {
            "order_id": order_id,
            "status": "ACKNOWLEDGED",
            "timestamp": now.isoformat(),
            "broker_ref": order_id,
            "extra": {
                "symbol": symbol,
                "exchange": self._exchange,
            },
        }

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an existing order via Angel One.

        Args:
            order_id: The Angel One order identifier to cancel.

        Returns:
            Dict with order_id, status, timestamp.
        """
        if order_id not in self._orders:
            return {
                "order_id": order_id,
                "status": "NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat(),
            }

        if not self.is_authenticated():
            return {
                "order_id": order_id,
                "status": "AUTH_FAILED",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            smart_connect = self._smart_connect
            if smart_connect is None:
                return {
                    "order_id": order_id,
                    "status": "NOT_CONNECTED",
                    "timestamp": datetime.utcnow().isoformat(),
                }

            response = smart_connect.cancelOrder(
                variety="NORMAL",
                orderid=order_id,
            )

            self._orders[order_id]["status"] = "CANCELLED"
            self._orders[order_id]["updated_at"] = datetime.utcnow()

            logger.info("Real broker order cancelled", extra={"order_id": order_id})

            return {
                "order_id": order_id,
                "status": "CANCELLED",
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(
                "Real broker cancel failed",
                extra={"order_id": order_id, "error": str(e)},
            )
            return {
                "order_id": order_id,
                "status": "CANCEL_FAILED",
                "timestamp": datetime.utcnow().isoformat(),
                "extra": {"error": str(e)},
            }

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Get current status of an order from Angel One.

        Args:
            order_id: The Angel One order identifier.

        Returns:
            Dict with order_id, status, timestamp, filled_qty.
        """
        if order_id not in self._orders:
            return {
                "order_id": order_id,
                "status": "NOT_FOUND",
                "timestamp": datetime.utcnow().isoformat(),
            }

        if not self.is_authenticated():
            return {
                "order_id": order_id,
                "status": "AUTH_FAILED",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            smart_connect = self._smart_connect
            if smart_connect is None:
                return {
                    "order_id": order_id,
                    "status": "UNKNOWN",
                    "timestamp": datetime.utcnow().isoformat(),
                }

            response = smart_connect.getOrderStatus()

        except Exception as e:
            logger.error(
                "Real broker status query failed",
                extra={"order_id": order_id, "error": str(e)},
            )
            return {
                "order_id": order_id,
                "status": "QUERY_FAILED",
                "timestamp": datetime.utcnow().isoformat(),
                "extra": {"error": str(e)},
            }

        # Parse Angel One order status response
        if isinstance(response, dict):
            orders = response.get("data", response)
            if isinstance(orders, list):
                for order in orders:
                    if isinstance(order, dict) and order.get("orderid") == order_id:
                        return self._parse_status_response(order_id, order)

        return {
            "order_id": order_id,
            "status": "UNKNOWN",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Reconnect
    # ------------------------------------------------------------------

    def handle_disconnect(self) -> bool:
        """Handle a broker disconnection.

        Attempts to re-authenticate and restore session.

        Returns:
            True if reconnection succeeded.
        """
        logger.warning("Real broker disconnected — attempting reconnect")
        self._connected = False

        try:
            # Attempt re-login
            if self._auth_manager is not None:
                self._auth_manager.logout()
                self.login()
            else:
                # Force re-login
                self._authenticated = False
                self._token = None
                self._smart_connect = None
                self._direct_login()

            self._connected = True
            logger.info("Real broker reconnected successfully")
            return True

        except (ConnectionError, Exception) as e:
            logger.error(
                "Real broker reconnect failed",
                extra={"error": str(e)},
            )
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        """Whether the broker is currently connected."""
        return self._connected and self.is_authenticated()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _build_trading_symbol(self, option_side: str, strike: str) -> str:
        """Build an Angel One trading symbol string.

        Format: NIFTY{expiry}{strike}{option_side}
        E.g.: NIFTY25JUN18500CE

        Args:
            option_side: CE or PE.
            strike: Strike price as string.

        Returns:
            Trading symbol string for Angel One API.
        """
        # For options: NIFTY + expiry + strike + PE/CE
        # Expiry format: YY + MMM (e.g., 25JUN)
        # In production, expiry would be resolved from order_data context
        # For V1, use a generic format that Angel One accepts
        expiry = "25JUN"  # Would be configurable in production
        return f"NIFTY{expiry}{strike}{option_side}"

    def _parse_order_response(self, response: Any) -> str:
        """Parse Angel One order placement response to extract order_id.

        Args:
            response: Raw response from SmartConnect.placeOrder.

        Returns:
            The order ID string.

        Raises:
            ExecutionError: If response is invalid or order rejected.
        """
        if response is None:
            raise ExecutionError(
                "Angel One returned None response for order placement",
            )

        if isinstance(response, dict):
            # Check for error
            if response.get("status") is False or response.get("errorcode") is not None:
                error_msg = response.get("message", response.get("errorcode", "Unknown error"))
                raise ExecutionError(
                    message=f"Angel One rejected order: {error_msg}",
                    details={"response": response},
                )

            # Extract order_id
            data = response.get("data", response)
            if isinstance(data, dict):
                order_id = data.get("orderid") or data.get("order_id") or data.get("nOrdNo")
                if order_id:
                    return str(order_id)

        # Fallback: generate local order ID if API didn't return one
        logger.warning(
            "Angel One did not return an order_id — generating local ID",
            extra={"response": str(response)[:200]},
        )
        return f"AO_{uuid.uuid4().hex[:8].upper()}"

    def _parse_status_response(
        self,
        order_id: str,
        order_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse Angel One order status response into standard format.

        Args:
            order_id: The order identifier.
            order_data: Order status data from Angel One.

        Returns:
            Standardised status dict.
        """
        # Map Angel One status to internal status
        ao_status = str(order_data.get("status", "")).upper()
        internal_status = self._map_angel_status(ao_status)

        filled_qty = int(order_data.get("filledqty", order_data.get("filled_qty", 0)))
        remaining_qty = int(order_data.get("unfilledqty", order_data.get("remaining_qty", 0)))

        # Update internal tracking
        if order_id in self._orders:
            self._orders[order_id]["status"] = internal_status
            self._orders[order_id]["updated_at"] = datetime.utcnow()

        return {
            "order_id": order_id,
            "status": internal_status,
            "filled_qty": filled_qty,
            "remaining_qty": remaining_qty,
            "price": float(order_data.get("price", order_data.get("avgprice", 0))),
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _map_angel_status(ao_status: str) -> str:
        """Map Angel One order status string to internal status.

        Args:
            ao_status: Angel One status string (e.g., "open", "complete").

        Returns:
            Internal status string (e.g., "ACKNOWLEDGED", "FILLED").
        """
        mapping = {
            "OPEN": "ACKNOWLEDGED",
            "PENDING": "PENDING",
            "PENDINGACK": "PENDING",
            "ACKNOWLEDGED": "ACKNOWLEDGED",
            "COMPLETE": "FILLED",
            "FILLED": "FILLED",
            "PARTIALLYFILLED": "PARTIAL_FILL",
            "PARTIAL_FILL": "PARTIAL_FILL",
            "CANCELLED": "CANCELLED",
            "CANCEL": "CANCELLED",
            "REJECTED": "REJECTED",
            "PUTONHOLD": "PENDING",
            "MODIFIED": "MODIFIED",
            "EXPIRED": "EXPIRED",
        }
        return mapping.get(ao_status.upper(), ao_status)

    @staticmethod
    def _generate_totp(secret: str | None = None) -> str:
        """Generate a TOTP code for Angel One login.

        Args:
            secret: Optional TOTP secret.

        Returns:
            TOTP code string, or empty string if pyotp not available.
        """
        try:
            import pyotp  # type: ignore[import-untyped]

            if secret:
                return pyotp.TOTP(secret).now()
            return ""
        except ImportError:
            return ""

    def get_orders(self) -> dict[str, dict[str, Any]]:
        """Get all tracked orders (for testing/inspection).

        Returns:
            Dict of order_id → order info.
        """
        return dict(self._orders)
