"""Tests for floor_1_connection/source_adapters.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from junior_aladdin.floor_1_connection.source_adapters import (
    AngelOneAdapter,
    BackupAdapter,
    ManualSourceAdapter,
)
from junior_aladdin.shared.errors import ConnectionError
from junior_aladdin.shared.types import LifecycleState


# ------------------------------------------------------------------
# AngelOneAdapter tests
# ------------------------------------------------------------------


class TestAngelOneAdapterConnect:
    """Tests for AngelOneAdapter.connect()."""

    def _mock_auth(self, adapter):
        """Helper: mock auth login + token/feed_token for WebSocket support."""
        adapter._api_key = "test_api_key"
        adapter._client_code = "test_client"
        mock_login = patch.object(adapter._auth, "login", return_value="token123")
        mock_get_token = patch.object(adapter._auth, "get_token", return_value="test_jwt")
        mock_get_feed = patch.object(adapter._auth, "get_feed_token", return_value="test_feed")
        mock_login.start()
        mock_get_token.start()
        mock_get_feed.start()
        return mock_login, mock_get_token, mock_get_feed

    def _stop_mocks(self, *mocks):
        for m in mocks:
            m.stop()

    def test_connect_success(self):
        """connect() returns True and sets state to HEALTHY."""
        adapter = AngelOneAdapter()
        mocks = self._mock_auth(adapter)
        try:
            result = adapter.connect()
        finally:
            self._stop_mocks(*mocks)
        assert result is True
        assert adapter.is_connected() is True
        assert adapter.get_lifecycle_state() == LifecycleState.HEALTHY

    def test_connect_already_connected(self):
        """connect() when already connected is a no-op."""
        adapter = AngelOneAdapter()
        mocks = self._mock_auth(adapter)
        try:
            adapter.connect()
        finally:
            self._stop_mocks(*mocks)
        with patch.object(adapter._auth, "login") as mock_login:
            result = adapter.connect()
        assert result is True
        mock_login.assert_not_called()

    def test_connect_raises_on_auth_failure(self):
        """connect() raises ConnectionError when auth fails."""
        adapter = AngelOneAdapter()
        with patch.object(
            adapter._auth, "login", side_effect=ConnectionError("auth failed")
        ):
            with pytest.raises(ConnectionError, match="auth failed"):
                adapter.connect()
        assert adapter.is_connected() is False
        assert adapter.get_lifecycle_state() == LifecycleState.AUTH_FAILED

    def test_connect_sets_connection_id(self):
        """Each adapter gets a unique connection_id."""
        adapter = AngelOneAdapter()
        assert adapter.connection_id.startswith("conn_")


class TestAngelOneAdapterDisconnect:
    """Tests for AngelOneAdapter.disconnect()."""

    def _setup_connected(self, adapter):
        """Helper: set up adapter in connected state with mocked auth."""
        adapter._api_key = "test_api_key"
        adapter._client_code = "test_client"
        with patch.object(adapter._auth, "login", return_value="token123"):
            with patch.object(adapter._auth, "get_token", return_value="test_jwt"):
                with patch.object(adapter._auth, "get_feed_token", return_value="test_feed"):
                    adapter.connect()

    def test_disconnect_sets_disconnected(self):
        adapter = AngelOneAdapter()
        self._setup_connected(adapter)
        adapter.disconnect()
        assert adapter.is_connected() is False
        assert adapter.get_lifecycle_state() == LifecycleState.DISCONNECTED

    def test_disconnect_idempotent(self):
        """Calling disconnect twice should not error."""
        adapter = AngelOneAdapter()
        self._setup_connected(adapter)
        adapter.disconnect()
        adapter.disconnect()  # second call
        assert adapter.is_connected() is False


class TestAngelOneAdapterReconnect:
    """Tests for AngelOneAdapter.reconnect()."""

    def _setup_connected_with_mocks(self, adapter):
        adapter._api_key = "test_api_key"
        adapter._client_code = "test_client"
        return (
            patch.object(adapter._auth, "login", return_value="token123"),
            patch.object(adapter._auth, "get_token", return_value="test_jwt"),
            patch.object(adapter._auth, "get_feed_token", return_value="test_feed"),
        )

    def test_reconnect_after_disconnect(self):
        adapter = AngelOneAdapter()
        mocks = self._setup_connected_with_mocks(adapter)
        for m in mocks:
            m.start()
        try:
            adapter.connect()
            adapter.disconnect()
            result = adapter.reconnect()
        finally:
            for m in mocks:
                m.stop()
        assert result is True
        assert adapter.is_connected() is True
        assert adapter.get_lifecycle_state() == LifecycleState.HEALTHY

    def test_reconnect_when_already_connected(self):
        adapter = AngelOneAdapter()
        mocks = self._setup_connected_with_mocks(adapter)
        for m in mocks:
            m.start()
        try:
            adapter.connect()
            result = adapter.reconnect()
        finally:
            for m in mocks:
                m.stop()
        assert result is True
        assert adapter.is_connected() is True

    def test_reconnect_fails_after_all_retries(self):
        adapter = AngelOneAdapter()
        adapter._connected = False
        with patch.object(
            adapter._auth,
            "login",
            side_effect=ConnectionError("persistent failure"),
        ):
            with pytest.raises(ConnectionError, match="All reconnection attempts failed"):
                adapter.reconnect()
        assert adapter.is_connected() is False

    def test_reconnect_uses_retry_with_backoff(self):
        """reconnect() is wrapped in retry_with_backoff."""
        adapter = AngelOneAdapter()
        mocks = self._setup_connected_with_mocks(adapter)
        for m in mocks:
            m.start()
        try:
            adapter.connect()
            adapter.disconnect()
        finally:
            for m in mocks:
                m.stop()
        with patch(
            "junior_aladdin.floor_1_connection.source_adapters.retry_with_backoff"
        ) as mock_retry:
            mock_retry.return_value = True
            adapter.reconnect()
            mock_retry.assert_called_once()


class TestAngelOneAdapterFeeds:
    """Tests for subscribe_feeds and data callbacks."""

    def test_subscribe_feeds(self):
        adapter = AngelOneAdapter()
        adapter.subscribe_feeds(["spot_tick", "options_snapshot"])
        assert "spot_tick" in adapter.subscribed_feeds
        assert "options_snapshot" in adapter.subscribed_feeds
        assert len(adapter.subscribed_feeds) == 2

    def test_subscribe_feeds_dedup(self):
        """Duplicate feed subscriptions are ignored."""
        adapter = AngelOneAdapter()
        adapter.subscribe_feeds(["spot_tick"])
        adapter.subscribe_feeds(["spot_tick"])
        assert adapter.subscribed_feeds == ["spot_tick"]

    def test_on_data_callback_receives_data(self):
        adapter = AngelOneAdapter()
        adapter.subscribe_feeds(["spot_tick"])
        adapter._api_key = "test_api_key"
        adapter._client_code = "test_client"
        received = []

        def cb(source, feed_type, data):
            received.append((source, feed_type, data))

        adapter.on_data(cb)
        with patch.object(adapter._auth, "login", return_value="token123"):
            with patch.object(adapter._auth, "get_token", return_value="test_jwt"):
                with patch.object(adapter._auth, "get_feed_token", return_value="test_feed"):
                    adapter.connect()

        # Simulate receiving data
        adapter._receive_data("spot_tick", {"ltp": 19500.0})
        assert len(received) == 1
        source, feed_type, data = received[0]
        assert source == "angel_one"
        assert feed_type == "spot_tick"
        assert data["ltp"] == 19500.0

    def test_receive_data_when_disconnected_ignored(self):
        adapter = AngelOneAdapter()
        received = []

        def cb(source, feed_type, data):
            received.append(data)

        adapter.on_data(cb)
        adapter._receive_data("spot_tick", {"ltp": 19500.0})
        assert len(received) == 0  # ignored because not connected

    def test_multiple_callbacks(self):
        adapter = AngelOneAdapter()
        adapter.subscribe_feeds(["spot_tick"])
        adapter._api_key = "test_api_key"
        adapter._client_code = "test_client"
        results = [[], []]

        def cb1(source, ft, data):
            results[0].append(data)

        def cb2(source, ft, data):
            results[1].append(data)

        adapter.on_data(cb1)
        adapter.on_data(cb2)
        with patch.object(adapter._auth, "login", return_value="token123"):
            with patch.object(adapter._auth, "get_token", return_value="test_jwt"):
                with patch.object(adapter._auth, "get_feed_token", return_value="test_feed"):
                    adapter.connect()
        adapter._receive_data("spot_tick", {"ltp": 19500.0})
        assert len(results[0]) == 1
        assert len(results[1]) == 1


class TestAngelOneAdapterLifecycle:
    """Full lifecycle integration test."""

    def test_full_connect_disconnect_reconnect(self):
        adapter = AngelOneAdapter()
        adapter._api_key = "test_api_key"
        adapter._client_code = "test_client"
        with patch.object(adapter._auth, "login", return_value="token123"):
            with patch.object(adapter._auth, "get_token", return_value="test_jwt"):
                with patch.object(adapter._auth, "get_feed_token", return_value="test_feed"):
                    # Connect
                    assert adapter.connect() is True
                    assert adapter.is_connected() is True
                    assert adapter.get_lifecycle_state() == LifecycleState.HEALTHY

                    # Disconnect
                    adapter.disconnect()
                    assert adapter.is_connected() is False
                    assert adapter.get_lifecycle_state() == LifecycleState.DISCONNECTED

                    # Reconnect
                    assert adapter.reconnect() is True
                    assert adapter.is_connected() is True
                    assert adapter.get_lifecycle_state() == LifecycleState.HEALTHY


# ------------------------------------------------------------------
# ManualSourceAdapter tests
# ------------------------------------------------------------------


class TestManualSourceAdapter:
    """Tests for ManualSourceAdapter."""

    def test_submit_manual_calendar(self):
        adapter = ManualSourceAdapter()
        result = adapter.submit_manual("MANUAL_CALENDAR", {"date": "2024-01-26"})
        assert result["source"] == "manual"
        assert result["feed_type"] == "MANUAL_CALENDAR"
        assert result["payload"] == {"date": "2024-01-26"}

    def test_submit_manual_event(self):
        adapter = ManualSourceAdapter()
        result = adapter.submit_manual("MANUAL_EVENT", {"event": "result"})
        assert result["feed_type"] == "MANUAL_EVENT"

    def test_submit_manual_override(self):
        adapter = ManualSourceAdapter()
        result = adapter.submit_manual("MANUAL_OVERRIDE", {"key": "value"})
        assert result["feed_type"] == "MANUAL_OVERRIDE"

    def test_invalid_feed_type_raises(self):
        adapter = ManualSourceAdapter()
        with pytest.raises(ValueError, match="Invalid manual feed type"):
            adapter.submit_manual("INVALID_TYPE", {})

    def test_callback_receives_manual_data(self):
        adapter = ManualSourceAdapter()
        received = []

        def cb(source, feed_type, data):
            received.append((source, feed_type, data))

        adapter.on_data(cb)
        adapter.submit_manual("MANUAL_CALENDAR", {"date": "2024-01-26"})
        assert len(received) == 1
        assert received[0][0] == "manual"
        assert received[0][1] == "MANUAL_CALENDAR"
        assert received[0][2] == {"date": "2024-01-26"}


# ------------------------------------------------------------------
# BackupAdapter stub tests
# ------------------------------------------------------------------


class TestBackupAdapter:
    """Tests for BackupAdapter stub."""

    def test_backup_adapter_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            BackupAdapter()
