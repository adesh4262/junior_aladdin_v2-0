"""Angel One authentication manager.

Handles API login, token generation/storage/refresh, and session lifecycle.
Uses SmartApi.SmartConnect for REST API authentication.

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.shared.config import Config
from junior_aladdin.shared.errors import ConnectionError
from junior_aladdin.shared.logging import get_logger

logger = get_logger("auth_manager")


class AuthManager:
    """Manages Angel One API authentication lifecycle.

    Caches tokens in-memory for session duration.
    Detects auth failures and provides refresh capability.
    """

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._feed_token: str | None = None
        self._user_profile: dict[str, Any] | None = None
        self._session_expiry: datetime | None = None
        self._authenticated: bool = False
        self._smart_connect: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self) -> str:
        """Authenticate with Angel One API.

        Uses credentials from Config:
          - angel_one.client_id
          - angel_one.api_key
          - angel_one.pin

        Returns:
            Access token string.

        Raises:
            ConnectionError: If authentication fails (invalid creds,
                network error, or TOTP failure).
        """
        client_id = self._config.get("angel_one.client_id")
        api_key = self._config.get("angel_one.api_key")
        pin = self._config.get("angel_one.pin")

        if not client_id or not api_key or not pin:
            raise ConnectionError(
                "Missing Angel One credentials",
                details={"missing": self._missing_creds(client_id, api_key, pin)},
            )

        try:
            # Lazy-import SmartConnect so the module is importable
            # even when the SDK is not installed (important for tests).
            from SmartApi import SmartConnect  # type: ignore[import-untyped]

            smart_connect = SmartConnect(api_key=api_key)

            # Generate TOTP from config secret
            # PyOTP is optional — falls back to blank string if unavailable.
            totp_secret = self._config.get("angel_one.totp_secret") or ""
            totp = self._generate_totp(secret=totp_secret)
            logger.debug(
                "TOTP generated%s",
                " (from secret)" if totp_secret else " (empty — setup required)",
            )

            data = smart_connect.generateSession(
                clientCode=client_id,
                password=pin,
                totp=totp,
            )

            if not data or not isinstance(data, dict):
                raise ConnectionError(
                    "Invalid response from Angel One login",
                    details={"response_type": type(data).__name__},
                )

            session_data = data.get("data") or data
            self._token = session_data.get("jwtToken") or session_data.get("accessToken")
            self._refresh_token = session_data.get("refreshToken")
            self._feed_token = session_data.get("feedToken")
            self._user_profile = session_data
            self._authenticated = True
            self._smart_connect = smart_connect

            # Set session expiry (~1 day from now, per Angel One convention)
            self._session_expiry = datetime.now(timezone.utc).replace(
                hour=15, minute=30, second=0
            )

            logger.info(
                "Angel One login successful",
                extra={"client_id": client_id[:4] + "****"},
            )
            return str(self._token)

        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(
                "Angel One authentication failed",
                details={"client_id": client_id[:4] + "****"},
                original_exception=e,
            )

    def get_token(self) -> str | None:
        """Return current valid access token, or None if not authenticated."""
        return self._token

    def refresh_token(self) -> str:
        """Refresh the access token using the stored refresh token.

        Returns:
            New access token string.

        Raises:
            ConnectionError: If refresh fails (expired refresh token,
                network error).
        """
        if not self._refresh_token or not self._smart_connect:
            raise ConnectionError(
                "Cannot refresh — no refresh token available",
                details={"has_refresh_token": self._refresh_token is not None},
            )

        try:
            # Use the already-initialized SmartConnect to refresh
            data = self._smart_connect.generateToken(self._refresh_token)

            if not data or not isinstance(data, dict):
                raise ConnectionError("Invalid refresh response from Angel One")

            session_data = data.get("data") or data
            self._token = session_data.get("accessToken", self._token)

            logger.info("Angel One token refreshed successfully")
            return str(self._token)

        except Exception as e:
            raise ConnectionError(
                "Token refresh failed",
                original_exception=e,
            )

    def is_authenticated(self) -> bool:
        """Check if currently authenticated with a valid token."""
        return self._authenticated and self._token is not None

    def logout(self) -> None:
        """Clear authentication state."""
        self._token = None
        self._refresh_token = None
        self._feed_token = None
        self._user_profile = None
        self._session_expiry = None
        self._authenticated = False
        self._smart_connect = None
        logger.info("Angel One logout — authentication state cleared")

    def get_session_expiry(self) -> datetime | None:
        """Return the expected session expiry time, or None."""
        return self._session_expiry

    def get_smart_connect(self) -> Any:
        """Return the SmartConnect instance for downstream consumers.

        Used by RealBroker (Side A) to share the authenticated SDK instance
        for order placement, avoiding a second unauthenticated instance.

        Returns:
            The SmartConnect instance, or None if not authenticated.
        """
        return self._smart_connect

    def get_feed_token(self) -> str | None:
        """Return the feed token for WebSocket connections."""
        return self._feed_token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_totp(secret: str | None = None) -> str:
        """Generate a TOTP code.

        Tries to use pyotp if available. Falls back to empty string.
        """
        try:
            import pyotp  # type: ignore[import-untyped]

            if secret:
                return pyotp.TOTP(secret).now()
            # If no secret configured, return empty — some Angel One
            # setups use pin-only authentication without TOTP.
            return ""
        except ImportError:
            return ""

    @staticmethod
    def _missing_creds(
        client_id: str | None,
        api_key: str | None,
        pin: str | None,
    ) -> list[str]:
        """Return list of missing credential field names."""
        missing = []
        if not client_id:
            missing.append("angel_one.client_id")
        if not api_key:
            missing.append("angel_one.api_key")
        if not pin:
            missing.append("angel_one.pin")
        return missing
