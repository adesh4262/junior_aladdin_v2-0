"""Tests for floor_1_connection/shared_utils.py."""

from __future__ import annotations

import json

import pytest

from junior_aladdin.floor_1_connection.shared_utils import (
    generate_connection_id,
    generate_packet_id,
    is_websocket_healthy,
    retry_with_backoff,
    serialize_for_handoff,
)


# ------------------------------------------------------------------
# ID generation tests
# ------------------------------------------------------------------


class TestGenerateConnectionId:
    """Tests for generate_connection_id()."""

    def test_returns_string(self):
        cid = generate_connection_id()
        assert isinstance(cid, str)

    def test_has_conn_prefix(self):
        cid = generate_connection_id()
        assert cid.startswith("conn_")

    def test_unique_ids(self):
        ids = {generate_connection_id() for _ in range(100)}
        assert len(ids) == 100


class TestGeneratePacketId:
    """Tests for generate_packet_id()."""

    def test_returns_string(self):
        pid = generate_packet_id()
        assert isinstance(pid, str)

    def test_has_pkt_prefix(self):
        pid = generate_packet_id()
        assert pid.startswith("pkt_")

    def test_unique_ids(self):
        ids = {generate_packet_id() for _ in range(100)}
        assert len(ids) == 100

    def test_pkt_different_from_conn(self):
        """Packet IDs and connection IDs use different prefixes."""
        pids = {generate_packet_id() for _ in range(10)}
        cids = {generate_connection_id() for _ in range(10)}
        assert pids.isdisjoint(cids)


# ------------------------------------------------------------------
# Retry tests
# ------------------------------------------------------------------


class TestRetryWithBackoff:
    """Tests for retry_with_backoff()."""

    def test_succeeds_on_first_try(self):
        """Returns immediately when func succeeds first time."""
        result = retry_with_backoff(lambda: "success")
        assert result == "success"

    def test_succeeds_after_retry(self):
        """Returns result when func eventually succeeds."""
        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "finally ok"

        result = retry_with_backoff(flaky_func, max_retries=3, base_delay=0.01)
        assert result == "finally ok"
        assert call_count == 3

    def test_raises_after_all_retries(self):
        """Raises the last exception when all retries exhausted."""
        call_count = 0

        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            retry_with_backoff(always_fails, max_retries=2, base_delay=0.01)
        assert call_count == 3  # initial + 2 retries

    def test_respects_max_retries_zero(self):
        """With max_retries=0, runs once and does NOT retry."""
        call_count = 0

        def fails_once():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            retry_with_backoff(fails_once, max_retries=0, base_delay=0.01)
        assert call_count == 1

    def test_default_params(self):
        """Default max_retries=3, base_delay=1.0 are applied."""
        call_count = 0

        def fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            retry_with_backoff(fails)
        assert call_count == 4  # initial + 3 retries (the default)


# ------------------------------------------------------------------
# WebSocket health check tests
# ------------------------------------------------------------------


class TestIsWebsocketHealthy:
    """Tests for is_websocket_healthy()."""

    def test_none_ws_returns_false(self):
        assert is_websocket_healthy(None) is False

    def test_closed_ws_returns_false(self):
        class FakeWS:
            closed = True

        assert is_websocket_healthy(FakeWS()) is False

    def test_open_ws_returns_true(self):
        class FakeWS:
            closed = False

        assert is_websocket_healthy(FakeWS()) is True

    def test_pingable_ws_returns_true(self):
        class FakeWS:
            def ping(self):
                pass

        assert is_websocket_healthy(FakeWS()) is True

    def test_ping_exception_returns_false(self):
        class FakeWS:
            def ping(self):
                raise RuntimeError("ping failed")

        assert is_websocket_healthy(FakeWS()) is False

    def test_no_attributes_returns_true(self):
        """Fallback: if we can't determine state, assume connected."""
        class FakeWS:
            pass

        assert is_websocket_healthy(FakeWS()) is True


# ------------------------------------------------------------------
# Serialization tests
# ------------------------------------------------------------------


class TestSerializeForHandoff:
    """Tests for serialize_for_handoff()."""

    def test_serializes_dict(self):
        data = {"key": "value", "number": 42}
        result = serialize_for_handoff(data)
        assert json.loads(result) == data

    def test_handles_nested_dict(self):
        data = {"outer": {"inner": [1, 2, 3]}}
        result = serialize_for_handoff(data)
        assert json.loads(result) == data

    def test_handles_datetime_with_default_str(self):
        from datetime import datetime
        data = {"now": datetime(2024, 1, 1, 12, 0, 0)}
        result = serialize_for_handoff(data)
        parsed = json.loads(result)
        assert "2024" in parsed["now"]

    def test_handles_custom_object_with_default_str(self):
        """default=str allows serializing objects with __str__."""
        class CustomObj:
            def __str__(self):
                return "custom_repr"

        result = serialize_for_handoff({"obj": CustomObj()})
        parsed = json.loads(result)
        assert parsed["obj"] == "custom_repr"

    def test_handles_empty_dict(self):
        assert serialize_for_handoff({}) == "{}"

    def test_handles_none_values(self):
        data = {"a": None, "b": [None]}
        result = serialize_for_handoff(data)
        parsed = json.loads(result)
        assert parsed["a"] is None
