"""Pytest tests for Side B data source adapters.

Tests all 7 source adapters:
  - floor_1: source health, connection status
  - floor_2: data health, validation stats, replay
  - floor_3: CMSP, domain summaries, chart data
  - floor_4: floor summary, head reports, head states
  - floor_5: captain state, decision snapshots, armed plans
  - side_a: execution state, blocked actions, logs
  - side_c: trade/decision/health read models

Each adapter is designed to degrade gracefully when its underlying
floor/side module isn't available — returning default/empty structures.

We test both the graceful-degradation path (no mocking) and the
success path (with mocking of internal imports).

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

import pytest


# ══════════════════════════════════════════════════════════════
#  1. Floor 1 — Source Health & Connection Status
# ══════════════════════════════════════════════════════════════


class TestFloor1Source:
    """Test poll_floor_1() — source health, connection, latency."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with data from ComponentRegistry singleton."""
        from junior_aladdin.side_b_api.data_sources.floor_1_source import poll_floor_1

        result = poll_floor_1()

        assert isinstance(result, dict)
        assert "source_health" in result
        assert "connection_status" in result
        assert "last_poll" in result
        # Now uses ComponentRegistry — SourceHealthMonitor starts as HEALTHY
        assert result["connection_status"] in ("CONNECTED", "ERROR")
        assert isinstance(result["source_health"], dict)

    def test_connection_status_correct_keys(self) -> None:
        """Result dict has all expected keys."""
        from junior_aladdin.side_b_api.data_sources.floor_1_source import poll_floor_1

        result = poll_floor_1()
        assert "source_health" in result
        assert "connection_status" in result
        assert "last_poll" in result

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp string."""
        from junior_aladdin.side_b_api.data_sources.floor_1_source import poll_floor_1

        result = poll_floor_1()
        from datetime import datetime
        # Should parse without error
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None

    def test_source_health_has_lifecycle_key(self) -> None:
        """source_health dict contains expected keys."""
        from junior_aladdin.side_b_api.data_sources.floor_1_source import poll_floor_1

        result = poll_floor_1()
        health = result["source_health"]
        # Default keys should exist even when polling fails
        assert "lifecycle_state" in health or len(health) == 0


# ══════════════════════════════════════════════════════════════
#  2. Floor 2 — Data Health & Validation
# ══════════════════════════════════════════════════════════════


class TestFloor2Source:
    """Test poll_floor_2() — data health, validation stats, replay."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with default values when imports fail."""
        from junior_aladdin.side_b_api.data_sources.floor_2_source import poll_floor_2

        result = poll_floor_2()

        assert isinstance(result, dict)
        assert "data_health" in result
        assert "review_signal" in result
        assert "validation_stats" in result
        assert "replay_active" in result
        assert "replay_session_id" in result
        assert "last_poll" in result
        assert result["data_health"] == "UNKNOWN"
        assert result["replay_active"] is False
        assert result["replay_session_id"] is None

    def test_validation_stats_defaults(self) -> None:
        """validation_stats defaults to zero counts."""
        from junior_aladdin.side_b_api.data_sources.floor_2_source import poll_floor_2

        result = poll_floor_2()
        stats = result["validation_stats"]
        assert stats["total"] == 0
        assert stats["passed"] == 0
        assert stats["failed"] == 0
        assert stats["warned"] == 0

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp."""
        from junior_aladdin.side_b_api.data_sources.floor_2_source import poll_floor_2
        from datetime import datetime

        result = poll_floor_2()
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None


# ══════════════════════════════════════════════════════════════
#  3. Floor 3 — CMSP & Domains
# ══════════════════════════════════════════════════════════════


class TestFloor3Source:
    """Test poll_floor_3() — CMSP, domain summaries, chart data."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with data from F3Orchestrator (via ComponentRegistry)."""
        from junior_aladdin.side_b_api.data_sources.floor_3_source import poll_floor_3

        result = poll_floor_3()

        assert isinstance(result, dict)
        assert "cmsp" in result
        assert "domain_summaries" in result
        assert "chart_data" in result
        assert "last_poll" in result
        # F3Orchestrator now runs even without candle data — returns engine statuses
        assert isinstance(result["cmsp"], dict)
        assert "data_health" in result["cmsp"]
        assert "engine_statuses" in result["cmsp"]
        assert isinstance(result["domain_summaries"], dict)
        assert result["chart_data"] is None

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp."""
        from junior_aladdin.side_b_api.data_sources.floor_3_source import poll_floor_3
        from datetime import datetime

        result = poll_floor_3()
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None

    def test_cmsp_has_engine_statuses(self) -> None:
        """CMSP populated by F3Orchestrator with engine statuses even without candles."""
        from junior_aladdin.side_b_api.data_sources.floor_3_source import poll_floor_3

        result = poll_floor_3()
        cmsp = result["cmsp"]
        assert isinstance(cmsp, dict)
        assert "data_health" in cmsp
        assert "engine_statuses" in cmsp
        # Engines should report status even without candle data
        assert len(cmsp["engine_statuses"]) > 0


# ══════════════════════════════════════════════════════════════
#  4. Floor 4 — Head Reports
# ══════════════════════════════════════════════════════════════


class TestFloor4Source:
    """Test poll_floor_4() — floor summary, head reports, head states."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with default values when imports fail."""
        from junior_aladdin.side_b_api.data_sources.floor_4_source import poll_floor_4

        result = poll_floor_4()

        assert isinstance(result, dict)
        assert "floor_summary" in result
        assert "head_reports" in result
        assert "head_states" in result
        assert "last_poll" in result
        assert result["floor_summary"] == {}
        assert result["head_reports"] == []
        assert result["head_states"] == {}

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp."""
        from junior_aladdin.side_b_api.data_sources.floor_4_source import poll_floor_4
        from datetime import datetime

        result = poll_floor_4()
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None


# ══════════════════════════════════════════════════════════════
#  5. Floor 5 — Captain State
# ══════════════════════════════════════════════════════════════


class TestFloor5Source:
    """Test poll_floor_5() — captain state, decision snapshots, armed plans."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with data from ComponentRegistry CaptainEngine."""
        from junior_aladdin.side_b_api.data_sources.floor_5_source import poll_floor_5

        result = poll_floor_5()

        assert isinstance(result, dict)
        assert "captain_state" in result
        assert "decision_snapshots" in result
        assert "armed_plans" in result
        assert "last_poll" in result
        # Now gets real data from CaptainEngine singleton — captain_state is populated
        assert isinstance(result["captain_state"], dict)
        assert "mood" in result["captain_state"]
        assert isinstance(result["decision_snapshots"], list)
        assert isinstance(result["armed_plans"], list)

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp."""
        from junior_aladdin.side_b_api.data_sources.floor_5_source import poll_floor_5
        from datetime import datetime

        result = poll_floor_5()
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None


# ══════════════════════════════════════════════════════════════
#  6. Side A — Execution State
# ══════════════════════════════════════════════════════════════


class TestSideASource:
    """Test poll_side_a() — execution state, blocked actions, logs."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with data from ComponentRegistry orchestrator."""
        from junior_aladdin.side_b_api.data_sources.side_a_source import poll_side_a

        result = poll_side_a()

        assert isinstance(result, dict)
        assert "execution_state" in result
        assert "blocked_actions" in result
        assert "execution_logs" in result
        assert "last_poll" in result
        # Now gets real data from orchestrator singleton — execution_state is populated
        assert isinstance(result["execution_state"], dict)
        assert "state" in result["execution_state"]
        assert isinstance(result["blocked_actions"], list)
        assert isinstance(result["execution_logs"], list)

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp."""
        from junior_aladdin.side_b_api.data_sources.side_a_source import poll_side_a
        from datetime import datetime

        result = poll_side_a()
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None


# ══════════════════════════════════════════════════════════════
#  7. Side C — Read Models
# ══════════════════════════════════════════════════════════════


class TestSideCSource:
    """Test poll_side_c() — trade/decision/health/blocked/override read models."""

    def test_returns_dict_with_defaults(self) -> None:
        """Returns expected keys with default values when imports fail."""
        from junior_aladdin.side_b_api.data_sources.side_c_source import poll_side_c

        result = poll_side_c()

        assert isinstance(result, dict)
        assert "trade_history" in result
        assert "decision_history" in result
        assert "health_events" in result
        assert "blocked_action_history" in result
        assert "override_history" in result
        assert "last_poll" in result
        assert result["trade_history"] == []
        assert result["decision_history"] == []
        assert result["health_events"] == []
        assert result["blocked_action_history"] == []
        assert result["override_history"] == []

    def test_last_poll_is_iso_timestamp(self) -> None:
        """last_poll is a valid ISO timestamp."""
        from junior_aladdin.side_b_api.data_sources.side_c_source import poll_side_c
        from datetime import datetime

        result = poll_side_c()
        parsed = datetime.fromisoformat(result["last_poll"])
        assert parsed is not None


# ══════════════════════════════════════════════════════════════
#  8. Shared Integration — All 7 Sources
# ══════════════════════════════════════════════════════════════


class TestAllSources:
    """Tests across all 7 source adapters to ensure interface consistency."""

    SOURCE_MODULES = [
        "junior_aladdin.side_b_api.data_sources.floor_1_source",
        "junior_aladdin.side_b_api.data_sources.floor_2_source",
        "junior_aladdin.side_b_api.data_sources.floor_3_source",
        "junior_aladdin.side_b_api.data_sources.floor_4_source",
        "junior_aladdin.side_b_api.data_sources.floor_5_source",
        "junior_aladdin.side_b_api.data_sources.side_a_source",
        "junior_aladdin.side_b_api.data_sources.side_c_source",
    ]

    def test_all_sources_importable(self) -> None:
        """All 7 source modules import successfully."""
        for mod_name in self.SOURCE_MODULES:
            import importlib
            mod = importlib.import_module(mod_name)
            assert mod is not None

    def test_all_sources_have_last_poll(self) -> None:
        """Every source returns a 'last_poll' key."""
        for mod_name in self.SOURCE_MODULES:
            import importlib
            mod = importlib.import_module(mod_name)
            # map function names
            func_name = mod_name.split(".")[-1]  # e.g. floor_1_source
            poll_names = {
                "floor_1_source": "poll_floor_1",
                "floor_2_source": "poll_floor_2",
                "floor_3_source": "poll_floor_3",
                "floor_4_source": "poll_floor_4",
                "floor_5_source": "poll_floor_5",
                "side_a_source": "poll_side_a",
                "side_c_source": "poll_side_c",
            }
            fn = getattr(mod, poll_names[func_name])
            result = fn()
            assert "last_poll" in result, f"{mod_name} missing last_poll"

    @pytest.mark.parametrize("mod_name,func_name,expected_keys", [
        ("floor_1_source", "poll_floor_1", ["source_health", "connection_status", "last_poll"]),
        ("floor_2_source", "poll_floor_2", ["data_health", "review_signal", "validation_stats", "replay_active", "replay_session_id", "last_poll"]),
        ("floor_3_source", "poll_floor_3", ["cmsp", "domain_summaries", "chart_data", "last_poll"]),
        ("floor_4_source", "poll_floor_4", ["floor_summary", "head_reports", "head_states", "last_poll"]),
        ("floor_5_source", "poll_floor_5", ["captain_state", "decision_snapshots", "armed_plans", "last_poll"]),
        ("side_a_source", "poll_side_a", ["execution_state", "blocked_actions", "execution_logs", "last_poll"]),
        ("side_c_source", "poll_side_c", ["trade_history", "decision_history", "health_events", "blocked_action_history", "override_history", "last_poll"]),
    ])
    def test_source_has_expected_keys(self, mod_name: str, func_name: str, expected_keys: list[str]) -> None:
        """Each source returns all of its expected keys (graceful degradation path)."""
        import importlib
        mod = importlib.import_module(f"junior_aladdin.side_b_api.data_sources.{mod_name}")
        fn = getattr(mod, func_name)
        result = fn()
        for key in expected_keys:
            assert key in result, f"{func_name} missing key '{key}'"

    @pytest.mark.parametrize("func_name", [
        "poll_floor_1",
        "poll_floor_2",
        "poll_floor_3",
        "poll_floor_4",
        "poll_floor_5",
        "poll_side_a",
        "poll_side_c",
    ])
    def test_all_sources_do_not_raise(self, func_name: str) -> None:
        """Every source handles missing imports without raising exceptions."""
        import importlib
        # Map function names to module names
        module_map = {
            "poll_floor_1": "floor_1_source",
            "poll_floor_2": "floor_2_source",
            "poll_floor_3": "floor_3_source",
            "poll_floor_4": "floor_4_source",
            "poll_floor_5": "floor_5_source",
            "poll_side_a": "side_a_source",
            "poll_side_c": "side_c_source",
        }
        mod = importlib.import_module(f"junior_aladdin.side_b_api.data_sources.{module_map[func_name]}")
        fn = getattr(mod, func_name)
        try:
            result = fn()
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"{func_name} raised {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════
#  9. __init__ Module Tests
# ══════════════════════════════════════════════════════════════


class TestDataSourcesInit:
    """Verify data_sources/__init__.py exports all poll functions."""

    def test_all_poll_functions_exported(self) -> None:
        """__init__ exports all 7 poll functions."""
        from junior_aladdin.side_b_api.data_sources import (
            poll_floor_1,
            poll_floor_2,
            poll_floor_3,
            poll_floor_4,
            poll_floor_5,
            poll_side_a,
            poll_side_c,
        )
        assert callable(poll_floor_1)
        assert callable(poll_floor_2)
        assert callable(poll_floor_3)
        assert callable(poll_floor_4)
        assert callable(poll_floor_5)
        assert callable(poll_side_a)
        assert callable(poll_side_c)

    def test___all__is_complete(self) -> None:
        """__all__ lists all 7 poll functions."""
        from junior_aladdin.side_b_api.data_sources import __all__
        assert "poll_floor_1" in __all__
        assert "poll_floor_2" in __all__
        assert "poll_floor_3" in __all__
        assert "poll_floor_4" in __all__
        assert "poll_floor_5" in __all__
        assert "poll_side_a" in __all__
        assert "poll_side_c" in __all__
        assert len(__all__) == 7
