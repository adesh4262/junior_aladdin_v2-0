"""Tests for floor_1_connection/feed_adapters.py."""

from __future__ import annotations

import pytest

from junior_aladdin.floor_1_connection.feed_adapters import (
    CalendarFeedAdapter,
    MacroFeedAdapter,
    OptionsFeedAdapter,
    SpotFeedAdapter,
    VixFeedAdapter,
)


# ------------------------------------------------------------------
# SpotFeedAdapter tests
# ------------------------------------------------------------------


class TestSpotFeedAdapter:
    """Tests for SpotFeedAdapter."""

    def test_feed_type_is_spot_tick(self):
        adapter = SpotFeedAdapter()
        assert adapter.feed_type == "spot_tick"

    def test_on_tick_returns_envelope_ready_dict(self):
        adapter = SpotFeedAdapter()
        result = adapter.on_tick({"ltp": 19500.0, "volume": 1000})
        assert result["feed_type"] == "spot_tick"
        assert result["ltp"] == 19500.0
        assert result["volume"] == 1000

    def test_on_tick_preserves_all_fields(self):
        adapter = SpotFeedAdapter()
        raw = {"ltp": 19500.5, "volume": 25000, "symbol": "NIFTY", "bid": 19499.0, "ask": 19501.0}
        result = adapter.on_tick(raw)
        for k, v in raw.items():
            assert result[k] == v

    def test_subscribe_callback_receives_data(self):
        adapter = SpotFeedAdapter()
        received = []

        def cb(data):
            received.append(data)

        adapter.subscribe(cb)
        adapter.on_tick({"ltp": 19500.0, "volume": 1000})
        assert len(received) == 1
        assert received[0]["feed_type"] == "spot_tick"
        assert received[0]["ltp"] == 19500.0

    def test_multiple_callbacks(self):
        adapter = SpotFeedAdapter()
        results = [[], []]

        def cb1(data):
            results[0].append(data)

        def cb2(data):
            results[1].append(data)

        adapter.subscribe(cb1)
        adapter.subscribe(cb2)
        adapter.on_tick({"ltp": 19500.0, "volume": 1000})
        assert len(results[0]) == 1
        assert len(results[1]) == 1

    def test_handle_data_returns_correct_dict(self):
        adapter = SpotFeedAdapter()
        result = adapter.handle_data({"ltp": 19500.0})
        assert result["feed_type"] == "spot_tick"
        assert result["ltp"] == 19500.0


# ------------------------------------------------------------------
# OptionsFeedAdapter tests
# ------------------------------------------------------------------


class TestOptionsFeedAdapter:
    """Tests for OptionsFeedAdapter."""

    def test_feed_type_is_options_snapshot(self):
        adapter = OptionsFeedAdapter()
        assert adapter.feed_type == "options_snapshot"

    def test_on_snapshot_returns_envelope_ready_dict(self):
        adapter = OptionsFeedAdapter()
        result = adapter.on_snapshot({"oi": 100000, "strike": 19500, "premium": 150.0})
        assert result["feed_type"] == "options_snapshot"
        assert result["oi"] == 100000
        assert result["strike"] == 19500

    def test_subscribe_callback_receives_snapshot(self):
        adapter = OptionsFeedAdapter()
        received = []

        def cb(data):
            received.append(data)

        adapter.subscribe(cb)
        adapter.on_snapshot({"oi": 100000, "strike": 19500})
        assert len(received) == 1


# ------------------------------------------------------------------
# VixFeedAdapter tests
# ------------------------------------------------------------------


class TestVixFeedAdapter:
    """Tests for VixFeedAdapter."""

    def test_feed_type_is_vix_tick(self):
        adapter = VixFeedAdapter()
        assert adapter.feed_type == "vix_tick"

    def test_on_tick_returns_envelope_ready_dict(self):
        adapter = VixFeedAdapter()
        result = adapter.on_tick({"vix": 14.5, "change": -0.3})
        assert result["feed_type"] == "vix_tick"
        assert result["vix"] == 14.5

    def test_subscribe_callback(self):
        adapter = VixFeedAdapter()
        received = []

        def cb(data):
            received.append(data)

        adapter.subscribe(cb)
        adapter.on_tick({"vix": 14.5})
        assert len(received) == 1


# ------------------------------------------------------------------
# MacroFeedAdapter stub tests
# ------------------------------------------------------------------


class TestMacroFeedAdapter:
    """Tests for MacroFeedAdapter (stub)."""

    def test_feed_type_is_macro_data(self):
        adapter = MacroFeedAdapter()
        assert adapter.feed_type == "macro_data"

    def test_on_macro_update_with_data(self):
        adapter = MacroFeedAdapter()
        result = adapter.on_macro_update({"fii_net": 500, "dii_net": -200})
        assert result["feed_type"] == "macro_data"
        assert result["fii_net"] == 500
        assert result["stub"] is True

    def test_on_macro_update_without_data(self):
        adapter = MacroFeedAdapter()
        result = adapter.on_macro_update()
        assert result["feed_type"] == "macro_data"
        assert result["stub"] is True
        # Should not raise on empty call

    def test_on_macro_update_with_none(self):
        adapter = MacroFeedAdapter()
        result = adapter.on_macro_update(None)
        assert result["feed_type"] == "macro_data"
        assert result["stub"] is True

    def test_subscribe_callback(self):
        adapter = MacroFeedAdapter()
        received = []

        def cb(data):
            received.append(data)

        adapter.subscribe(cb)
        adapter.on_macro_update({"fii_net": 500})
        assert len(received) == 1
        assert received[0]["fii_net"] == 500


# ------------------------------------------------------------------
# CalendarFeedAdapter stub tests
# ------------------------------------------------------------------


class TestCalendarFeedAdapter:
    """Tests for CalendarFeedAdapter (stub)."""

    def test_feed_type_is_calendar_event(self):
        adapter = CalendarFeedAdapter()
        assert adapter.feed_type == "calendar_event"

    def test_on_calendar_event_with_data(self):
        adapter = CalendarFeedAdapter()
        result = adapter.on_calendar_event({"event_type": "holiday", "date": "2024-01-26"})
        assert result["feed_type"] == "calendar_event"
        assert result["event_type"] == "holiday"
        assert result["stub"] is True

    def test_on_calendar_event_without_data(self):
        adapter = CalendarFeedAdapter()
        result = adapter.on_calendar_event()
        assert result["feed_type"] == "calendar_event"
        assert result["stub"] is True

    def test_on_calendar_event_with_expiry(self):
        adapter = CalendarFeedAdapter()
        result = adapter.on_calendar_event({"event_type": "expiry", "date": "2024-02-01"})
        assert result["event_type"] == "expiry"
        assert result["date"] == "2024-02-01"

    def test_subscribe_callback(self):
        adapter = CalendarFeedAdapter()
        received = []

        def cb(data):
            received.append(data)

        adapter.subscribe(cb)
        adapter.on_calendar_event({"event_type": "holiday"})
        assert len(received) == 1


# ------------------------------------------------------------------
# Cross-adapter tests
# ------------------------------------------------------------------


class TestFeedAdapterConsistency:
    """Tests that all adapters follow same patterns."""

    def test_all_adapters_have_feed_type(self):
        adapters = [
            SpotFeedAdapter(),
            OptionsFeedAdapter(),
            VixFeedAdapter(),
            MacroFeedAdapter(),
            CalendarFeedAdapter(),
        ]
        feed_types = {a.feed_type for a in adapters}
        assert len(feed_types) == 5  # all unique
        assert "spot_tick" in feed_types
        assert "options_snapshot" in feed_types
        assert "vix_tick" in feed_types
        assert "macro_data" in feed_types
        assert "calendar_event" in feed_types

    def test_all_adapters_support_subscribe(self):
        adapters = [
            SpotFeedAdapter(),
            OptionsFeedAdapter(),
            VixFeedAdapter(),
            MacroFeedAdapter(),
            CalendarFeedAdapter(),
        ]
        for adapter in adapters:
            calls = []

            def cb(data):
                calls.append(data)

            adapter.subscribe(cb)
            # Each adapter has its own specific public method
            if hasattr(adapter, "on_tick"):
                adapter.on_tick({"test": True})  # type: ignore[union-attr]
            elif hasattr(adapter, "on_snapshot"):
                adapter.on_snapshot({"test": True})  # type: ignore[union-attr]
            elif hasattr(adapter, "on_macro_update"):
                adapter.on_macro_update({"test": True})
            elif hasattr(adapter, "on_calendar_event"):
                adapter.on_calendar_event({"test": True})
            assert len(calls) == 1, f"{type(adapter).__name__} callback not fired"

    def test_no_market_interpretation(self):
        """Verify no intelligence fields in adapter output."""
        adapters = [
            SpotFeedAdapter(),
            OptionsFeedAdapter(),
            VixFeedAdapter(),
        ]
        forbidden = {"bias", "signal", "setup", "confidence", "conviction", "trend"}
        for adapter in adapters:
            result = adapter.handle_data({"test": 1})
            for key in result:
                assert key not in forbidden, (
                    f"{type(adapter).__name__} must not add '{key}' (intelligence field)"
                )
