"""Tests for floor_1_connection/auth_manager.py.

Uses mock SmartConnect to test without real Angel One credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from junior_aladdin.floor_1_connection.auth_manager import AuthManager
from junior_aladdin.shared.errors import ConnectionError


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mock_smart_connect():
    """Create a mock SmartConnect that returns a valid session."""
    mock = MagicMock()
    mock.generateSession.return_value = {
        "data": {
            "accessToken": "test_access_token_12345",
            "refreshToken": "test_refresh_token_67890",
            "feedToken": "test_feed_token_abcde",
            "userProfile": {"clientId": "TEST001", "name": "Test User"},
        }
    }
    mock.generateToken.return_value = {
        "data": {
            "accessToken": "refreshed_access_token_99999",
        }
    }
    return mock


@pytest.fixture
def auth_manager(test_config) -> AuthManager:
    """Create AuthManager with test config (no .env loading)."""
    # Set mock credentials in the config data so login() passes the
    # credential check before reaching the SmartConnect mock.
    test_config._data["angel_one"] = {
        "client_id": "TEST001",
        "api_key": "test_api_key_123",
        "pin": "1234",
    }
    return AuthManager(config=test_config)


# ------------------------------------------------------------------
# Login tests
# ------------------------------------------------------------------


class TestLogin:
    """Tests for AuthManager.login()."""

    def test_login_success(self, auth_manager, mock_smart_connect):
        """login() returns token with valid credentials."""
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            token = auth_manager.login()

        assert token == "test_access_token_12345"
        assert auth_manager.is_authenticated() is True
        assert auth_manager.get_token() == "test_access_token_12345"
        assert auth_manager.get_feed_token() == "test_feed_token_abcde"

    def test_login_raises_on_missing_creds(self, auth_manager):
        """login() raises ConnectionError when credentials missing."""
        auth_manager._config._data["angel_one"] = {
            "client_id": "",
            "api_key": "",
            "pin": "",
        }
        with pytest.raises(ConnectionError, match="Missing Angel One credentials"):
            auth_manager.login()

    def test_login_raises_on_api_failure(self, auth_manager, mock_smart_connect):
        """login() raises ConnectionError when SmartConnect fails."""
        mock_smart_connect.generateSession.side_effect = Exception("API timeout")
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            with pytest.raises(ConnectionError, match="Angel One authentication failed"):
                auth_manager.login()

    def test_login_raises_on_empty_response(self, auth_manager, mock_smart_connect):
        """login() raises ConnectionError when API returns empty response."""
        mock_smart_connect.generateSession.return_value = {}
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            with pytest.raises(ConnectionError, match="Invalid response"):
                auth_manager.login()

    def test_login_logs_success(self, auth_manager, mock_smart_connect):
        """login() logs a success message."""
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            with patch(
                "junior_aladdin.floor_1_connection.auth_manager.logger"
            ) as mock_logger:
                auth_manager.login()
                mock_logger.info.assert_called_once()


# ------------------------------------------------------------------
# Token management tests
# ------------------------------------------------------------------


class TestTokenManagement:
    """Tests for get_token, refresh_token, get_feed_token."""

    def test_get_token_returns_none_before_login(self, auth_manager):
        assert auth_manager.get_token() is None

    def test_get_token_after_login(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
        assert auth_manager.get_token() == "test_access_token_12345"

    def test_refresh_token_returns_new_token(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
            new_token = auth_manager.refresh_token()
        assert new_token == "refreshed_access_token_99999"
        assert auth_manager.get_token() == "refreshed_access_token_99999"

    def test_refresh_token_raises_without_login(self, auth_manager):
        with pytest.raises(ConnectionError, match="Cannot refresh"):
            auth_manager.refresh_token()

    def test_get_feed_token_before_login(self, auth_manager):
        assert auth_manager.get_feed_token() is None

    def test_get_feed_token_after_login(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
        assert auth_manager.get_feed_token() == "test_feed_token_abcde"


# ------------------------------------------------------------------
# Authentication state tests
# ------------------------------------------------------------------


class TestAuthState:
    """Tests for is_authenticated, logout, get_session_expiry."""

    def test_not_authenticated_initially(self, auth_manager):
        assert auth_manager.is_authenticated() is False

    def test_authenticated_after_login(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
        assert auth_manager.is_authenticated() is True

    def test_not_authenticated_after_logout(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
        auth_manager.logout()
        assert auth_manager.is_authenticated() is False

    def test_logout_clears_state(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
        auth_manager.logout()
        assert auth_manager.get_token() is None
        assert auth_manager.get_feed_token() is None
        assert auth_manager.get_session_expiry() is None

    def test_get_session_expiry_returns_datetime(self, auth_manager, mock_smart_connect):
        with patch("SmartApi.SmartConnect", return_value=mock_smart_connect):
            auth_manager.login()
        expiry = auth_manager.get_session_expiry()
        assert expiry is not None
        assert hasattr(expiry, "hour")


# ------------------------------------------------------------------
# Config loading tests
# ------------------------------------------------------------------


class TestConfigLoading:
    """Tests that AuthManager reads config correctly."""

    def test_uses_test_config(self, auth_manager, test_config):
        assert auth_manager._config is test_config

    def test_missing_creds_detection(self, auth_manager):
        missing = auth_manager._missing_creds(None, "key", None)
        assert "angel_one.client_id" in missing
        assert "angel_one.pin" in missing
        assert "angel_one.api_key" not in missing

    def test_login_with_blank_config_raises(self, auth_manager):
        auth_manager._config._data["angel_one"] = {
            "client_id": "",
            "api_key": "",
            "pin": "",
        }
        with pytest.raises(ConnectionError, match="Missing Angel One credentials"):
            auth_manager.login()
