"""Side B data aggregator.

Central polling engine that calls all 7 data source adapters on their
configured HOT / WARM / COLD intervals and assembles the results into
a single ``DashboardState`` for the API server.

Reference: ROADMAP_SIDE_B Step 8.3, SIDE_B_DASHBOARD_V1_2_FINAL Section 21
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from junior_aladdin.side_b_api.api_config import DEFAULT_CONFIG
from junior_aladdin.side_b_api.data_contracts import (
    CaptainDisplayState,
    ComponentHealthDetail,
    DashboardState,
    ExecutionDisplayState,
    FloorSummaryDisplay,
    HeadReportDisplay,
    MarketDataSnapshot,
    SystemHealthSnapshot,
)
from junior_aladdin.side_b_api.session_cache import CacheTier, get_default_cache

log = logging.getLogger(__name__)

# Single import point for all data sources
from junior_aladdin.side_b_api.data_sources import (
    poll_floor_1,
    poll_floor_2,
    poll_floor_3,
    poll_floor_4,
    poll_floor_5,
    poll_side_a,
    poll_side_c,
)


# ──────────────────────────────────────────────
#  Aggregator
# ──────────────────────────────────────────────


class DataAggregator:
    """Aggregates data from all 7 floor/side sources into a single DashboardState.

    Usage::

        agg = DataAggregator()
        state = agg.poll_all()          # Full poll — all 7 sources
        hot = agg.poll_hot()            # Critical data only (exec, market, alerts)
        warm = agg.poll_warm()          # Important data (heads, captain)
        cached = agg.get_aggregated_state()
    """

    def __init__(self) -> None:
        self._cache = get_default_cache()
        self._last_state: DashboardState | None = None

    # ── Public API ──

    def poll_all(self) -> DashboardState:
        """Poll ALL 7 data sources and return a fully assembled DashboardState.

        This is the primary poll method used on startup and full-refresh.
        Individual tier polls (hot / warm) are preferred during normal operation.
        """
        result = DashboardState(timestamp=datetime.utcnow())

        try:
            f1 = poll_floor_1()
            result = self._apply_floor_1(result, f1)
            self._cache.set("floor_1", f1, CacheTier.WARM)
        except Exception:
            log.warning("Floor 1 poll failed", exc_info=True)

        try:
            f2 = poll_floor_2()
            result = self._apply_floor_2(result, f2)
            self._cache.set("floor_2", f2, CacheTier.COLD)
        except Exception:
            log.warning("Floor 2 poll failed", exc_info=True)

        try:
            f3 = poll_floor_3()
            result = self._apply_floor_3(result, f3)
            self._cache.set("floor_3", f3, CacheTier.COLD)
        except Exception:
            log.warning("Floor 3 poll failed", exc_info=True)

        try:
            f4 = poll_floor_4()
            result = self._apply_floor_4(result, f4)
            self._cache.set("floor_4", f4, CacheTier.WARM)
        except Exception:
            log.warning("Floor 4 poll failed", exc_info=True)

        try:
            f5 = poll_floor_5()
            result = self._apply_floor_5(result, f5)
            self._cache.set("floor_5", f5, CacheTier.WARM)
        except Exception:
            log.warning("Floor 5 poll failed", exc_info=True)

        try:
            sa = poll_side_a()
            result = self._apply_side_a(result, sa)
            self._cache.set("side_a", sa, CacheTier.HOT)
        except Exception:
            log.warning("Side A poll failed", exc_info=True)

        try:
            sc = poll_side_c()
            self._cache.set("side_c", sc, CacheTier.COLD)
            # Side C read models are queryable via get_state_snapshot()
            # but do NOT directly mutate DashboardState fields.
            # Dashboard consumes Side C through read models on-demand.
        except Exception:
            log.warning("Side C poll failed", exc_info=True)

        # Recompute overall health status from all component states
        self._build_health_snapshot(result)

        self._last_state = result
        return result

    def poll_hot(self) -> dict[str, Any]:
        """Poll HOT-tier data only: execution state, market data, alerts.

        Called every ~500ms during normal operation.

        Returns:
            Partial dict with 'execution', 'market', 'chart_data', and 'alerts' keys.
        """
        partial: dict[str, Any] = {}

        try:
            sa = poll_side_a()
            partial["execution"] = self._build_execution_state(sa)
            self._cache.set("side_a", sa, CacheTier.HOT)
        except Exception:
            log.warning("Side A hot poll failed", exc_info=True)

        # Market data polled on HOT tier
        try:
            f1 = poll_floor_1()
            partial["market"] = self._build_market_snapshot(f1)
            self._cache.set("market_data", partial["market"], CacheTier.HOT)
        except Exception:
            pass

        return partial

    def poll_warm(self) -> dict[str, Any]:
        """Poll WARM-tier data only: head reports, captain state, floor summary.

        Called every ~3s during normal operation.

        Returns:
            Partial dict with 'captain', 'floor_summary', and 'head_reports' keys.
        """
        partial: dict[str, Any] = {}

        try:
            f4 = poll_floor_4()
            partial["floor_summary"] = self._build_floor_summary(f4)
            partial["head_reports"] = f4.get("head_reports", [])
            self._cache.set("floor_4", f4, CacheTier.WARM)
        except Exception:
            log.warning("Floor 4 warm poll failed", exc_info=True)

        try:
            f5 = poll_floor_5()
            partial["captain"] = self._build_captain_state(f5)
            self._cache.set("floor_5", f5, CacheTier.WARM)
        except Exception:
            log.warning("Floor 5 warm poll failed", exc_info=True)

        return partial

    def get_aggregated_state(self) -> DashboardState | None:
        """Return the last fully polled DashboardState, or None if never polled."""
        return self._last_state

    def get_state_snapshot(
        self, components: list[str] | None = None
    ) -> dict[str, Any]:
        """Return a subset of the aggregated state by component name.

        Args:
            components: List of component names to include.
                If None, returns all cached components.

        Returns:
            Dict mapping component name → cached data.
        """
        if components is None:
            return {
                "floor_1": self._cache.get("floor_1"),
                "floor_2": self._cache.get("floor_2"),
                "floor_3": self._cache.get("floor_3"),
                "floor_4": self._cache.get("floor_4"),
                "floor_5": self._cache.get("floor_5"),
                "side_a": self._cache.get("side_a"),
                "side_c": self._cache.get("side_c"),
            }

        return {c: self._cache.get(c) for c in components if self._cache.get(c) is not None}

    # ── Internal state builders ──

    def _apply_floor_1(self, state: DashboardState, data: dict[str, Any]) -> DashboardState:
        health_detail = ComponentHealthDetail(
            name="floor_1",
            state=data.get("connection_status", "UNKNOWN"),
            lifecycle=data.get("source_health", {}).get("lifecycle_state", "UNKNOWN"),
        )
        state.health.floors["floor_1"] = health_detail
        state.market = self._build_market_snapshot(data)
        return state

    def _apply_floor_2(self, state: DashboardState, data: dict[str, Any]) -> DashboardState:
        from junior_aladdin.shared.types import DataHealth

        health_val = data.get("data_health", "UNKNOWN")
        try:
            state.health.data_health_signal = DataHealth(health_val)
        except ValueError:
            pass

        health_detail = ComponentHealthDetail(
            name="floor_2",
            state=health_val,
        )
        state.health.floors["floor_2"] = health_detail
        return state

    def _apply_floor_3(self, state: DashboardState, data: dict[str, Any]) -> DashboardState:
        """Apply Floor 3 CMSP + domain data to the dashboard state."""
        cmsp = data.get("cmsp", {})
        if cmsp:
            state.health.floors["floor_3"] = ComponentHealthDetail(
                name="floor_3",
                state="HEALTHY",
                detail=f"CMSP: {len(cmsp.get('key_levels', []))} key levels",
            )
        else:
            state.health.floors["floor_3"] = ComponentHealthDetail(
                name="floor_3", state="DEGRADED"
            )
        return state

    def _apply_floor_4(self, state: DashboardState, data: dict[str, Any]) -> DashboardState:
        state.floor_summary = self._build_floor_summary(data)
        return state

    def _apply_floor_5(self, state: DashboardState, data: dict[str, Any]) -> DashboardState:
        state.captain = self._build_captain_state(data)
        health_detail = ComponentHealthDetail(
            name="floor_5",
            state="HEALTHY" if data.get("captain_state") else "SILENT",
        )
        state.health.floors["floor_5"] = health_detail
        return state

    def _apply_side_a(self, state: DashboardState, data: dict[str, Any]) -> DashboardState:
        state.execution = self._build_execution_state(data)
        # Side A health
        exec_state = data.get("execution_state", {})
        es = exec_state.get("escalation_level", "NORMAL")
        health_map = {"NORMAL": "HEALTHY", "CAUTION": "DEGRADED", "SEVERE": "DEGRADED", "EMERGENCY": "UNAVAILABLE"}
        state.health.sides["side_a"] = ComponentHealthDetail(
            name="side_a",
            state=health_map.get(es, "HEALTHY"),
        )
        return state

    def _build_health_snapshot(self, state: DashboardState) -> SystemHealthSnapshot:
        """Recompute the overall health snapshot from all components."""
        statuses = []
        for comp in state.health.floors.values():
            statuses.append(comp.state)
        for comp in state.health.sides.values():
            statuses.append(comp.state)

        from junior_aladdin.shared.types import DataHealth

        if "CRITICAL" in statuses:
            overall = DataHealth.CRITICAL
        elif "UNAVAILABLE" in statuses:
            overall = DataHealth.CRITICAL
        elif "DEGRADED" in statuses or "ERROR" in statuses:
            overall = DataHealth.DEGRADED
        elif "STALE" in statuses:
            overall = DataHealth.STALE
        else:
            overall = DataHealth.GOOD

        state.health.overall_status = overall
        return state.health

    def _build_market_snapshot(self, f1_data: dict[str, Any]) -> MarketDataSnapshot:
        return MarketDataSnapshot(
            symbol="NIFTY 50",
            ltp=f1_data.get("source_health", {}).get("ltp", 0.0),
        )

    def _build_captain_state(self, f5_data: dict[str, Any]) -> CaptainDisplayState:
        cs = f5_data.get("captain_state", {})
        return CaptainDisplayState(
            mood=cs.get("mood", "OBSERVER"),
            decision=cs.get("decision", "WAIT"),
            conviction_score=cs.get("conviction_score", 0.0),
            conviction_band=cs.get("conviction_band", "REJECT"),
            market_story_summary=cs.get("market_story_summary", ""),
            reason_summary=cs.get("silence_reason", ""),
            silence_reason=cs.get("silence_reason"),
            active_plan_count=len(f5_data.get("armed_plans", [])),
        )

    def _build_floor_summary(self, f4_data: dict[str, Any]) -> FloorSummaryDisplay:
        fs = f4_data.get("floor_summary", {})
        heads = f4_data.get("head_reports", [])
        return FloorSummaryDisplay(
            floor_bias=fs.get("floor_bias_snapshot", {}).get("bias", "NEUTRAL"),
            floor_confidence=fs.get("floor_confidence_snapshot", {}).get("confidence", 0.0),
            active_setup_count=fs.get("active_setup_count", 0),
            ready_heads=fs.get("ready_heads_count", 0),
            uncertain_heads=fs.get("uncertain_heads_count", 0),
            stale_heads=fs.get("stale_heads_count", 0),
            heads=[
                HeadReportDisplay(
                    head_name=h.get("head_name", ""),
                    state=h.get("state", "READY"),
                    bias=h.get("bias", "NEUTRAL"),
                    confidence=h.get("confidence", 0.0),
                    freshness_tag=h.get("freshness_tag", "FRESH"),
                    context_quality_score=h.get("context_quality_score"),
                    primary_setup=h.get("primary_setup"),
                    backup_setup=h.get("backup_setup"),
                    no_setup_flag=h.get("no_setup_flag", False),
                )
                for h in heads
            ],
        )

    def _build_execution_state(self, sa_data: dict[str, Any]) -> ExecutionDisplayState:
        es = sa_data.get("execution_state", {})

        # ── Read from control cache first, fall back to Side A raw data ──
        # This ensures operator commands (mode, kill_switch, capital) are reflected
        # in the UI immediately even before Side A processes them.

        # Mode
        mode = es.get("mode", "ALERT")
        try:
            mode_cmd = self._cache.get("control:mode")
            if mode_cmd and "params" in mode_cmd:
                cached_mode = mode_cmd["params"].get("mode")
                if cached_mode:
                    mode = cached_mode
        except Exception:
            pass

        # Kill switch state
        kill_switch_state = es.get("kill_switch_state", "NORMAL")
        try:
            ks_cmd = self._cache.get("control:kill_switch")
            if ks_cmd and "params" in ks_cmd:
                cached_ks = ks_cmd["params"].get("state")
                if cached_ks:
                    kill_switch_state = cached_ks
        except Exception:
            pass

        # Capital limit
        capital_limit: float | None = es.get("capital_limit")
        if capital_limit is None:
            try:
                capital_cmd = self._cache.get("control:capital")
                if capital_cmd and "params" in capital_cmd:
                    capital_limit = capital_cmd["params"].get("capital_limit")
            except Exception:
                pass

        return ExecutionDisplayState(
            mode=mode,
            state=es.get("state", "IDLE"),
            escalation_level=es.get("escalation_level", "NORMAL"),
            capital_limit=capital_limit,
            kill_switch_state=kill_switch_state,
        )


# Singleton default
_default_aggregator: DataAggregator | None = None


def get_default_aggregator() -> DataAggregator:
    """Return the module-level singleton data aggregator."""
    global _default_aggregator  # noqa: PLW0603
    if _default_aggregator is None:
        _default_aggregator = DataAggregator()
    return _default_aggregator
