"""Floor 3 data source adapter.

Polls Floor 3 (Calculation Engines) for Common Market State Projection (CMSP),
per-domain summaries (SMC, ICT, Technical, Options, Macro), and chart-ready
OHLCV data.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def poll_floor_3() -> dict[str, Any]:
    """Poll Floor 3 for domain summaries, CMSP, and chart data.

    Returns:
        Dict with keys:
            - cmsp: dict (price_state, volatility_state, session_state, regime_state, key_levels)
            - domain_summaries: dict per-domain (smc, ict, technical, options, macro)
            - chart_data: dict | None (OHLCV series)
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "cmsp": {},
        "domain_summaries": {},
        "chart_data": None,
        "last_poll": datetime.utcnow().isoformat(),
    }

    # ── CMSP via F3Orchestrator ──
    # Run a lightweight calculation cycle to get current market state.
    # Floor 3 engines need candle data to produce signals.
    # Without WebSocket (no tick data), engines return empty signal sets.
    try:
        from junior_aladdin.floor_3_calculations.f3_types import (
            CalculationInput,
            MarketPhase,
        )
        from junior_aladdin.floor_3_calculations.f3_config import F3Config
        from junior_aladdin.shared.component_registry import get_registry

        calc_input = CalculationInput(
            packet_envelope_id="dashboard_poll",
            market_phase=MarketPhase.OPEN,
            symbol="NIFTY",
            timestamp=datetime.utcnow(),
            data={
                "current_price": 0.0,  # No live tick data yet
                "candles": [],  # No WebSocket — no candles
                "options_snapshots": {},
            },
        )

        f3 = get_registry().get_f3_orchestrator()
        oc = f3(calc_input, F3Config())

        if oc.floor_summary:
            result["cmsp"] = {
                "price_state": oc.floor_summary.domain_summaries.get("SMC", {}),
                "signals_count": oc.floor_summary.signals_count,
                "engine_statuses": oc.floor_summary.engine_statuses,
                "data_health": oc.floor_summary.data_health.value,
            }
            result["domain_summaries"] = oc.floor_summary.domain_summaries

    except Exception:
        log.debug("Floor 3 orchestrator poll failed", exc_info=True)

    return result
