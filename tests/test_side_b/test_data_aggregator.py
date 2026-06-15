"""Pytest tests for Side B DataAggregator.

Tests the central polling engine:
  - Initialisation (cache, last_state)
  - poll_all() — all 7 data sources with correct CacheTier
  - poll_hot() — HOT-tier data (execution, market)
  - poll_warm() — WARM-tier data (heads, captain)
  - get_aggregated_state() and get_state_snapshot()
  - Error handling — source failure doesn't crash entire poll
  - Internal builder methods (_build_market_snapshot, _build_captain_state, etc.)

Reference: ROADMAP_SIDE_B Step 8.3
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from junior_aladdin.side_b_api.data_aggregator import DataAggregator, get_default_aggregator
from junior_aladdin.side_b_api.data_contracts import (
    CaptainDisplayState,
    ComponentHealthDetail,
    DashboardState,
    ExecutionDisplayState,
    FloorSummaryDisplay,
    MarketDataSnapshot,
    SystemHealthSnapshot,
)
from junior_aladdin.side_b_api.session_cache import CacheTier, SessionCache
from junior_aladdin.shared.types import CaptainMood, ExecutionMode


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the module-level singleton cache with a fresh one per test.

    DataAggregator uses ``get_default_cache()`` which returns a module-level
    singleton.  Without this fixture, poll_all() calls from earlier tests
    leak cached entries into later tests.
    """
    fresh = SessionCache(max_entries=100)
    monkeypatch.setattr(
        "junior_aladdin.side_b_api.data_aggregator.get_default_cache",
        lambda: fresh,
    )
    monkeypatch.setattr(
        "junior_aladdin.side_b_api.session_cache.get_default_cache",
        lambda: fresh,
    )


@pytest.fixture
def agg() -> DataAggregator:
    """Provide a fresh DataAggregator for each test."""
    return DataAggregator()


@pytest.fixture
def mock_source_data() -> dict:
    """Standard mock data returned by each source adapter."""
    return {
        "floor_1": {
            "connection_status": "CONNECTED",
            "source_health": {"lifecycle_state": "HEALTHY", "latency_ms": 12.5, "ltp": 19500.0},
            "last_poll": "2026-06-13T10:00:00",
        },
        "floor_2": {
            "data_health": "GOOD",
            "validation_stats": {"total": 100, "passed": 95, "failed": 3, "warned": 2},
            "replay_active": False,
            "replay_session_id": None,
        },
        "floor_3": {
            "cmsp": {
                "price_state": {"trend": "BULLISH"},
                "key_levels": [19450, 19500, 19550],
            },
            "domain_summaries": {"smc": {"state": "BULLISH"}},
        },
        "floor_4": {
            "floor_summary": {
                "floor_bias_snapshot": {"dominant_floor_bias": "BULLISH"},
                "floor_confidence_snapshot": {"average_confidence": 0.75},
                "active_setup_count": 3,
                "ready_heads_count": 4,
                "uncertain_heads_count": 1,
                "stale_heads_count": 1,
            },
            "head_reports": [
                {"head_name": "Technical", "state": "READY", "bias": "BULLISH", "confidence": 0.8,
                 "freshness_tag": "FRESH", "context_quality_score": None, "primary_setup": None,
                 "backup_setup": None, "no_setup_flag": True},
            ],
            "head_states": {"Technical": "READY"},
        },
        "floor_5": {
            "captain_state": {
                "mood": "PATIENT",
                "decision_state": "WAIT",
                "conviction_band": "WEAK",
                "market_story_summary": "Bullish structure",
                "silence_reason": None,
            },
            "armed_plans": [{"plan_id": "plan_001", "direction": "BUY", "readiness": "WATCHING"}],
        },
        "side_a": {
            "execution_state": {
                "mode": "PAPER",
                "state": "MONITORING",
                "escalation_level": "NORMAL",
                "kill_switch_state": "NORMAL",
                "position": {"trade_id": "t_001", "direction": "BUY", "filled_qty": 50},
            },
            "blocked_actions": [],
        },
        "side_c": {
            "trade_history": [{"trade_id": "t_001"}],
            "decision_history": [],
            "health_events": [],
        },
    }


# ══════════════════════════════════════════════════════════════
#  1. Initialisation Tests
# ══════════════════════════════════════════════════════════════


class TestInitialisation:
    """Verify DataAggregator is correctly initialised."""

    def test_init_creates_cache(self, agg: DataAggregator) -> None:
        """Aggregator has a SessionCache instance."""
        assert agg._cache is not None
        assert isinstance(agg._cache, SessionCache)

    def test_init_last_state_is_none(self, agg: DataAggregator) -> None:
        """Initially, last_state is None (no polls yet)."""
        assert agg._last_state is None

    def test_get_aggregated_state_before_poll(self, agg: DataAggregator) -> None:
        """get_aggregated_state() returns None before any poll."""
        assert agg.get_aggregated_state() is None

    def test_get_default_aggregator_singleton(self) -> None:
        """get_default_aggregator() returns the same instance."""
        a1 = get_default_aggregator()
        a2 = get_default_aggregator()
        assert a1 is a2
        assert isinstance(a1, DataAggregator)


# ══════════════════════════════════════════════════════════════
#  2. poll_all() Tests — full poll, all 7 sources
# ══════════════════════════════════════════════════════════════


class TestPollAll:
    """Verify poll_all() calls all 7 sources and assembles DashboardState."""

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_poll_all_calls_all_sources(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """All 7 source poll functions are called exactly once each."""
        mock_f1.return_value = mock_source_data["floor_1"]
        mock_f2.return_value = mock_source_data["floor_2"]
        mock_f3.return_value = mock_source_data["floor_3"]
        mock_f4.return_value = mock_source_data["floor_4"]
        mock_f5.return_value = mock_source_data["floor_5"]
        mock_sa.return_value = mock_source_data["side_a"]
        mock_sc.return_value = mock_source_data["side_c"]

        state = agg.poll_all()

        assert isinstance(state, DashboardState)
        mock_f1.assert_called_once()
        mock_f2.assert_called_once()
        mock_f3.assert_called_once()
        mock_f4.assert_called_once()
        mock_f5.assert_called_once()
        mock_sa.assert_called_once()
        mock_sc.assert_called_once()

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_poll_all_returns_dashboard_state(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """poll_all() returns a fully populated DashboardState."""
        for mock_fn, key in [(mock_f1, "floor_1"), (mock_f2, "floor_2"), (mock_f3, "floor_3"),
                              (mock_f4, "floor_4"), (mock_f5, "floor_5"), (mock_sa, "side_a"),
                              (mock_sc, "side_c")]:
            mock_fn.return_value = mock_source_data[key]

        state = agg.poll_all()

        assert state.market.symbol == "NIFTY 50"
        assert state.market.ltp == 19500.0
        assert state.floor_summary.floor_bias == "BULLISH"
        assert state.captain.mood == "PATIENT"
        assert state.execution.mode == "PAPER"
        assert state.health.floors["floor_1"].state == "CONNECTED"
        assert state.health.sides["side_a"].state == "HEALTHY"

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_poll_all_cache_tiers_correct(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """poll_all() stores data under correct CacheTier per source."""
        for mock_fn, key in [(mock_f1, "floor_1"), (mock_f2, "floor_2"), (mock_f3, "floor_3"),
                              (mock_f4, "floor_4"), (mock_f5, "floor_5"), (mock_sa, "side_a"),
                              (mock_sc, "side_c")]:
            mock_fn.return_value = mock_source_data[key]

        agg.poll_all()
        cache = agg._cache

        # HOT
        assert cache.get("side_a", CacheTier.HOT) is not None
        # WARM
        assert cache.get("floor_1", CacheTier.WARM) is not None
        assert cache.get("floor_4", CacheTier.WARM) is not None
        assert cache.get("floor_5", CacheTier.WARM) is not None
        # COLD
        assert cache.get("floor_2", CacheTier.COLD) is not None
        assert cache.get("floor_3", CacheTier.COLD) is not None
        assert cache.get("side_c", CacheTier.COLD) is not None

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_poll_all_updates_last_state(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """After poll_all(), get_aggregated_state() returns the new state."""
        for mock_fn, key in [(mock_f1, "floor_1"), (mock_f2, "floor_2"), (mock_f3, "floor_3"),
                              (mock_f4, "floor_4"), (mock_f5, "floor_5"), (mock_sa, "side_a"),
                              (mock_sc, "side_c")]:
            mock_fn.return_value = mock_source_data[key]

        state = agg.poll_all()
        assert agg.get_aggregated_state() is state
        assert agg.get_aggregated_state().timestamp is not None

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_poll_all_has_timestamp(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f1: MagicMock,
        agg: DataAggregator,
    ) -> None:
        """DashboardState has a valid timestamp after poll."""
        mock_f1.return_value = {"connection_status": "CONNECTED", "source_health": {}}
        mock_sa.return_value = {"execution_state": {}}
        mock_sc.return_value = {}
        state = agg.poll_all()
        assert isinstance(state.timestamp, datetime)

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_poll_all_health_snapshot_computed(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """Health snapshot is recomputed after full poll."""
        for mock_fn, key in [(mock_f1, "floor_1"), (mock_f2, "floor_2"), (mock_f3, "floor_3"),
                              (mock_f4, "floor_4"), (mock_f5, "floor_5"), (mock_sa, "side_a"),
                              (mock_sc, "side_c")]:
            mock_fn.return_value = mock_source_data[key]

        state = agg.poll_all()
        assert isinstance(state.health, SystemHealthSnapshot)
        assert state.health.overall_status is not None
        assert "floor_1" in state.health.floors
        assert "side_a" in state.health.sides
        assert len(state.health.floors) == 4  # floors 1, 2, 3, 5 (floor_4 doesn't add to health.floors)


# ══════════════════════════════════════════════════════════════
#  3. poll_hot() Tests
# ══════════════════════════════════════════════════════════════


class TestPollHot:
    """Verify poll_hot() only polls HOT-tier sources."""

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    def test_poll_hot_returns_partial_dict(
        self, mock_f1: MagicMock, mock_sa: MagicMock, agg: DataAggregator,
    ) -> None:
        """poll_hot() returns a partial dict with 'execution' and 'market' keys."""
        mock_sa.return_value = {"execution_state": {"mode": "ALERT"}}
        mock_f1.return_value = {"source_health": {"ltp": 19500.0}, "connection_status": "CONNECTED"}

        partial = agg.poll_hot()

        assert isinstance(partial, dict)
        assert "execution" in partial
        assert "market" in partial

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    def test_poll_hot_execution_display_state(
        self, mock_f1: MagicMock, mock_sa: MagicMock, agg: DataAggregator,
    ) -> None:
        """Execution state from poll_hot() is an ExecutionDisplayState."""
        mock_sa.return_value = {"execution_state": {"mode": "PAPER", "state": "MONITORING"}}
        mock_f1.return_value = {"source_health": {"ltp": 19500.0}, "connection_status": "CONNECTED"}

        partial = agg.poll_hot()
        assert isinstance(partial["execution"], ExecutionDisplayState)
        assert partial["execution"].mode == "PAPER"

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    def test_poll_hot_market_snapshot(
        self, mock_f1: MagicMock, mock_sa: MagicMock, agg: DataAggregator,
    ) -> None:
        """Market data from poll_hot() is a MarketDataSnapshot."""
        mock_sa.return_value = {"execution_state": {"mode": "ALERT"}}
        mock_f1.return_value = {"source_health": {"ltp": 19600.0}, "connection_status": "CONNECTED"}

        partial = agg.poll_hot()
        assert isinstance(partial["market"], MarketDataSnapshot)
        assert partial["market"].ltp == 19600.0

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    def test_poll_hot_cache_side_a_hot(
        self, mock_f1: MagicMock, mock_sa: MagicMock, agg: DataAggregator,
    ) -> None:
        """Side A data is cached under HOT tier."""
        mock_sa.return_value = {"execution_state": {"mode": "ALERT"}}
        mock_f1.return_value = {"source_health": {"ltp": 19500.0}, "connection_status": "CONNECTED"}

        agg.poll_hot()
        assert agg._cache.get("side_a", CacheTier.HOT) is not None

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    def test_poll_hot_only_polls_hot_sources(
        self, mock_f1: MagicMock, mock_sa: MagicMock, agg: DataAggregator,
    ) -> None:
        """poll_hot() does NOT poll WARM or COLD sources."""
        mock_sa.return_value = {"execution_state": {}}
        mock_f1.return_value = {"source_health": {}, "connection_status": "UNKNOWN"}

        agg.poll_hot()

        # Only floor_1 and side_a were called (poll_hot only polls these)
        mock_sa.assert_called_once()
        mock_f1.assert_called_once()


# ══════════════════════════════════════════════════════════════
#  4. poll_warm() Tests
# ══════════════════════════════════════════════════════════════


class TestPollWarm:
    """Verify poll_warm() only polls WARM-tier sources."""

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    def test_poll_warm_returns_partial_dict(
        self, mock_f5: MagicMock, mock_f4: MagicMock, agg: DataAggregator,
    ) -> None:
        """poll_warm() returns a partial dict with 'captain' and 'floor_summary'."""
        mock_f4.return_value = {
            "floor_summary": {"floor_bias_snapshot": {"bias": "NEUTRAL"}},
            "head_reports": [],
        }
        mock_f5.return_value = {
            "captain_state": {"mood": "OBSERVER"},
            "armed_plans": [],
        }

        partial = agg.poll_warm()
        assert isinstance(partial, dict)
        assert "captain" in partial
        assert "floor_summary" in partial
        assert "head_reports" in partial

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    def test_poll_warm_captain_display_state(
        self, mock_f5: MagicMock, mock_f4: MagicMock, agg: DataAggregator,
    ) -> None:
        """Captain state from poll_warm() is a CaptainDisplayState."""
        mock_f4.return_value = {"floor_summary": {}, "head_reports": []}
        mock_f5.return_value = {"captain_state": {"mood": "OBSERVER"}, "armed_plans": []}

        partial = agg.poll_warm()
        assert isinstance(partial["captain"], CaptainDisplayState)
        assert partial["captain"].mood == "OBSERVER"

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    def test_poll_warm_floor_summary_display(
        self, mock_f5: MagicMock, mock_f4: MagicMock, agg: DataAggregator,
    ) -> None:
        """Floor summary from poll_warm() is a FloorSummaryDisplay."""
        mock_f4.return_value = {
            "floor_summary": {"floor_bias_snapshot": {"dominant_floor_bias": "BULLISH"}, "floor_confidence_snapshot": {"average_confidence": 0.8}},
            "head_reports": [],
        }
        mock_f5.return_value = {"captain_state": {"mood": "OBSERVER"}, "armed_plans": []}

        partial = agg.poll_warm()
        assert isinstance(partial["floor_summary"], FloorSummaryDisplay)
        assert partial["floor_summary"].floor_bias == "BULLISH"
        assert partial["floor_summary"].floor_confidence == 0.8

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    def test_poll_warm_cache_tiers(
        self, mock_f5: MagicMock, mock_f4: MagicMock, agg: DataAggregator,
    ) -> None:
        """WARM poll caches floor_4 and floor_5 under WARM tier."""
        mock_f4.return_value = {"floor_summary": {}, "head_reports": []}
        mock_f5.return_value = {"captain_state": {"mood": "OBSERVER"}, "armed_plans": []}

        agg.poll_warm()
        assert agg._cache.get("floor_4", CacheTier.WARM) is not None
        assert agg._cache.get("floor_5", CacheTier.WARM) is not None


# ══════════════════════════════════════════════════════════════
#  5. Error Handling Tests
# ══════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Verify aggregator handles source failures gracefully."""

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_source_failure_does_not_crash_poll(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """If one source raises, poll_all() continues with other sources."""
        mock_f1.side_effect = RuntimeError("Connection lost")
        mock_f2.return_value = mock_source_data["floor_2"]
        mock_f3.return_value = mock_source_data["floor_3"]
        mock_f4.return_value = mock_source_data["floor_4"]
        mock_f5.return_value = mock_source_data["floor_5"]
        mock_sa.return_value = mock_source_data["side_a"]
        mock_sc.return_value = mock_source_data["side_c"]

        state = agg.poll_all()
        assert isinstance(state, DashboardState)
        # Floor 2 data should still be applied
        assert state.health.data_health_signal.value == "GOOD"

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_all_sources_fail_returns_partial_state(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
    ) -> None:
        """If ALL sources fail, poll_all() still returns a valid DashboardState with defaults."""
        for mock_fn in [mock_f1, mock_f2, mock_f3, mock_f4, mock_f5, mock_sa, mock_sc]:
            mock_fn.side_effect = RuntimeError("All down")

        state = agg.poll_all()
        assert isinstance(state, DashboardState)
        # Default values preserved
        assert state.market.ltp == 0.0
        assert state.floor_summary.floor_bias == "NEUTRAL"
        assert state.captain.mood == CaptainMood.OBSERVER
        assert state.execution.mode == ExecutionMode.ALERT

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    def test_poll_hot_source_failure_graceful(
        self, mock_f1: MagicMock, mock_sa: MagicMock, agg: DataAggregator,
    ) -> None:
        """poll_hot() handles source failure without crashing."""
        mock_sa.side_effect = RuntimeError("Side A down")
        mock_f1.return_value = {"source_health": {"ltp": 19500.0}, "connection_status": "CONNECTED"}

        partial = agg.poll_hot()
        # Market should still work even if Side A fails
        assert "market" in partial
        assert partial["market"].ltp == 19500.0

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    def test_poll_warm_source_failure_graceful(
        self, mock_f5: MagicMock, mock_f4: MagicMock, agg: DataAggregator,
    ) -> None:
        """poll_warm() handles source failure without crashing."""
        mock_f4.side_effect = RuntimeError("Floor 4 down")
        mock_f5.return_value = {"captain_state": {"mood": "OBSERVER"}, "armed_plans": []}

        partial = agg.poll_warm()
        # Captain should still work even if Floor 4 fails
        assert "captain" in partial
        assert partial["captain"].mood == "OBSERVER"


# ══════════════════════════════════════════════════════════════
#  6. get_state_snapshot() Tests
# ══════════════════════════════════════════════════════════════


class TestGetStateSnapshot:
    """Verify get_state_snapshot() returns correct data."""

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_get_snapshot_all_components(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """get_state_snapshot() returns all 7 components after poll."""
        for mock_fn, key in [(mock_f1, "floor_1"), (mock_f2, "floor_2"), (mock_f3, "floor_3"),
                              (mock_f4, "floor_4"), (mock_f5, "floor_5"), (mock_sa, "side_a"),
                              (mock_sc, "side_c")]:
            mock_fn.return_value = mock_source_data[key]

        agg.poll_all()
        snapshot = agg.get_state_snapshot()

        assert "floor_1" in snapshot
        assert "floor_2" in snapshot
        assert "floor_3" in snapshot
        assert "floor_4" in snapshot
        assert "floor_5" in snapshot
        assert "side_a" in snapshot
        assert "side_c" in snapshot

    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_1")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_2")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_3")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_4")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_floor_5")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_a")
    @patch("junior_aladdin.side_b_api.data_aggregator.poll_side_c")
    def test_get_snapshot_filtered_components(
        self,
        mock_sc: MagicMock, mock_sa: MagicMock, mock_f5: MagicMock,
        mock_f4: MagicMock, mock_f3: MagicMock, mock_f2: MagicMock,
        mock_f1: MagicMock,
        agg: DataAggregator,
        mock_source_data: dict,
    ) -> None:
        """get_state_snapshot() with components filter returns only requested keys."""
        for mock_fn, key in [(mock_f1, "floor_1"), (mock_f2, "floor_2"), (mock_f3, "floor_3"),
                              (mock_f4, "floor_4"), (mock_f5, "floor_5"), (mock_sa, "side_a"),
                              (mock_sc, "side_c")]:
            mock_fn.return_value = mock_source_data[key]

        agg.poll_all()
        snapshot = agg.get_state_snapshot(components=["floor_1", "side_a", "side_c"])

        assert "floor_1" in snapshot
        assert "side_a" in snapshot
        assert "side_c" in snapshot
        assert "floor_2" not in snapshot
        assert "floor_3" not in snapshot

    def test_get_snapshot_before_poll(self, agg: DataAggregator) -> None:
        """get_state_snapshot() before any poll returns empty component dicts."""
        snapshot = agg.get_state_snapshot()
        for key in ("floor_1", "floor_2", "floor_3", "floor_4", "floor_5", "side_a", "side_c"):
            assert snapshot.get(key) is None


# ══════════════════════════════════════════════════════════════
#  7. Builder Method Tests
# ══════════════════════════════════════════════════════════════


class TestBuilderMethods:
    """Verify internal builder methods produce correct output structures."""

    def test_build_market_snapshot(self, agg: DataAggregator) -> None:
        """_build_market_snapshot creates MarketDataSnapshot from Floor 1 data."""
        f1_data = {"source_health": {"ltp": 19550.5}}
        market = agg._build_market_snapshot(f1_data)
        assert isinstance(market, MarketDataSnapshot)
        assert market.symbol == "NIFTY 50"
        assert market.ltp == 19550.5

    def test_build_market_snapshot_default_ltp(self, agg: DataAggregator) -> None:
        """_build_market_snapshot defaults to 0.0 when ltp missing."""
        market = agg._build_market_snapshot({})
        assert market.ltp == 0.0

    def test_build_captain_state_full(self, agg: DataAggregator) -> None:
        """_build_captain_state creates CaptainDisplayState with all fields."""
        f5_data = {
            "captain_state": {
                "mood": "AGGRESSIVE",
                "decision": "TRADE",
                "conviction_score": 85.0,
                "conviction_band": "STRONG",
                "market_story_summary": "Strong momentum",
                "silence_reason": None,
            },
            "armed_plans": [{"plan_id": "p1"}, {"plan_id": "p2"}],
        }
        captain = agg._build_captain_state(f5_data)
        assert captain.mood == "AGGRESSIVE"
        assert captain.decision == "TRADE"
        assert captain.conviction_score == 85.0
        assert captain.conviction_band == "STRONG"
        assert captain.active_plan_count == 2
        assert captain.silence_reason is None

    def test_build_captain_state_empty(self, agg: DataAggregator) -> None:
        """_build_captain_state returns defaults when data is empty."""
        captain = agg._build_captain_state({})
        assert captain.mood == "OBSERVER"
        assert captain.decision == "WAIT"
        assert captain.conviction_score == 0.0
        assert captain.active_plan_count == 0

    def test_build_execution_state_from_es(self, agg: DataAggregator) -> None:
        """_build_execution_state parses execution_state dict."""
        sa_data = {
            "execution_state": {
                "mode": "PAPER",
                "state": "ACTIVE",
                "escalation_level": "NORMAL",
                "kill_switch_state": "NORMAL",
            },
        }
        exec_state = agg._build_execution_state(sa_data)
        assert exec_state.mode == "PAPER"
        assert exec_state.state == "ACTIVE"
        assert exec_state.escalation_level == "NORMAL"

    def test_build_execution_state_empty(self, agg: DataAggregator) -> None:
        """_build_execution_state returns defaults when data is empty."""
        exec_state = agg._build_execution_state({})
        assert exec_state.mode == "ALERT"
        assert exec_state.state == "IDLE"
        assert exec_state.kill_switch_state == "NORMAL"

    def test_build_floor_summary_full(self, agg: DataAggregator) -> None:
        """_build_floor_summary creates FloorSummaryDisplay with head reports."""
        f4_data = {
            "floor_summary": {
                "floor_bias_snapshot": {"dominant_floor_bias": "BULLISH"},
                "floor_confidence_snapshot": {"average_confidence": 0.8},
                "active_setup_count": 3,
                "ready_heads_count": 4,
                "uncertain_heads_count": 1,
                "stale_heads_count": 0,
            },
            "head_reports": [
                {"head_name": "Technical", "state": "READY", "bias": "BULLISH",
                 "confidence": 0.9, "freshness_tag": "FRESH"},
                {"head_name": "ICT", "state": "READY", "bias": "BULLISH",
                 "confidence": 0.7, "freshness_tag": "FRESH",
                 "context_quality_score": 0.85, "primary_setup": "fvg_retest"},
            ],
        }
        fs = agg._build_floor_summary(f4_data)
        assert fs.floor_bias == "BULLISH"
        assert fs.floor_confidence == 0.8
        assert fs.active_setup_count == 3
        assert fs.ready_heads == 4
        assert len(fs.heads) == 2
        assert fs.heads[0].head_name == "Technical"
        assert fs.heads[1].head_name == "ICT"

    def test_build_floor_summary_empty(self, agg: DataAggregator) -> None:
        """_build_floor_summary returns defaults when data is empty."""
        fs = agg._build_floor_summary({})
        assert fs.floor_bias == "NEUTRAL"
        assert fs.floor_confidence == 0.0
        assert fs.active_setup_count == 0
        assert fs.heads == []

    def test_apply_floor_1_fills_health(self, agg: DataAggregator) -> None:
        """_apply_floor_1 sets floor_1 health and market data."""
        state = DashboardState()
        f1_data = {"connection_status": "CONNECTED", "source_health": {"lifecycle_state": "HEALTHY", "ltp": 19500.0}}
        result = agg._apply_floor_1(state, f1_data)
        assert result.health.floors["floor_1"].state == "CONNECTED"
        assert result.market.ltp == 19500.0

    def test_apply_floor_2_sets_data_health(self, agg: DataAggregator) -> None:
        """_apply_floor_2 sets data_health_signal from Floor 2 data."""
        state = DashboardState()
        f2_data = {"data_health": "GOOD"}
        result = agg._apply_floor_2(state, f2_data)
        from junior_aladdin.shared.types import DataHealth
        assert result.health.data_health_signal == DataHealth.GOOD
        assert result.health.floors["floor_2"].state == "GOOD"

    def test_apply_floor_3_sets_cmsp_health(self, agg: DataAggregator) -> None:
        """_apply_floor_3 sets floor_3 health based on CMSP presence."""
        state = DashboardState()
        f3_data = {"cmsp": {"price_state": {"trend": "BULLISH"}, "key_levels": [19450, 19500]}}
        result = agg._apply_floor_3(state, f3_data)
        assert result.health.floors["floor_3"].state == "HEALTHY"

    def test_apply_floor_3_empty_sets_degraded(self, agg: DataAggregator) -> None:
        """_apply_floor_3 sets DEGRADED when CMSP is empty."""
        state = DashboardState()
        result = agg._apply_floor_3(state, {})
        assert result.health.floors["floor_3"].state == "DEGRADED"

    def test_apply_side_a_sets_execution_and_health(self, agg: DataAggregator) -> None:
        """_apply_side_a sets execution state and side_a health."""
        state = DashboardState()
        sa_data = {"execution_state": {"mode": "PAPER", "escalation_level": "NORMAL"}}
        result = agg._apply_side_a(state, sa_data)
        assert result.execution.mode == "PAPER"
        assert result.health.sides["side_a"].state == "HEALTHY"

    def test_apply_side_a_escalation_maps_to_health(self, agg: DataAggregator) -> None:
        """Escalation SEVERE maps to DEGRADED health."""
        state = DashboardState()
        sa_data = {"execution_state": {"escalation_level": "SEVERE"}}
        result = agg._apply_side_a(state, sa_data)
        assert result.health.sides["side_a"].state == "DEGRADED"

    def test_apply_side_a_emergency_maps_to_unavailable(self, agg: DataAggregator) -> None:
        """Escalation EMERGENCY maps to UNAVAILABLE health."""
        state = DashboardState()
        sa_data = {"execution_state": {"escalation_level": "EMERGENCY"}}
        result = agg._apply_side_a(state, sa_data)
        assert result.health.sides["side_a"].state == "UNAVAILABLE"

    def test_build_health_snapshot_all_good(self, agg: DataAggregator) -> None:
        """_build_health_snapshot returns GOOD when all components healthy."""
        state = DashboardState()
        state.health.floors["floor_1"] = ComponentHealthDetail(name="floor_1", state="CONNECTED")
        state.health.floors["floor_2"] = ComponentHealthDetail(name="floor_2", state="GOOD")
        state.health.sides["side_a"] = ComponentHealthDetail(name="side_a", state="HEALTHY")
        health = agg._build_health_snapshot(state)
        from junior_aladdin.shared.types import DataHealth
        assert health.overall_status == DataHealth.GOOD

    def test_build_health_snapshot_degraded(self, agg: DataAggregator) -> None:
        """_build_health_snapshot returns DEGRADED when any component is DEGRADED."""
        state = DashboardState()
        state.health.floors["floor_1"] = ComponentHealthDetail(name="floor_1", state="CONNECTED")
        state.health.floors["floor_2"] = ComponentHealthDetail(name="floor_2", state="DEGRADED")
        health = agg._build_health_snapshot(state)
        from junior_aladdin.shared.types import DataHealth
        assert health.overall_status == DataHealth.DEGRADED

    def test_build_health_snapshot_critical_on_unavailable(self, agg: DataAggregator) -> None:
        """_build_health_snapshot returns CRITICAL when any component is UNAVAILABLE."""
        state = DashboardState()
        state.health.sides["side_a"] = ComponentHealthDetail(name="side_a", state="UNAVAILABLE")
        health = agg._build_health_snapshot(state)
        from junior_aladdin.shared.types import DataHealth
        assert health.overall_status == DataHealth.CRITICAL
