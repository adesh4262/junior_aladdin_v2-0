"""Floor 3 data source adapter.

Polls Floor 3 (Calculation Engines) for Common Market State Projection (CMSP),
per-domain summaries (SMC, ICT, Technical, Options, Macro), and chart-ready
OHLCV data.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


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

    try:
        # ── CMSP ──
        try:
            from junior_aladdin.shared.types import CMSP
            from junior_aladdin.floor_3_calculations.f3_orchestrator import (
                get_cmsp,
            )

            cmsp: CMSP = get_cmsp()
            result["cmsp"] = {
                "price_state": cmsp.price_state,
                "volatility_state": cmsp.volatility_state,
                "session_state": cmsp.session_state,
                "regime_state": cmsp.regime_state,
                "key_levels": list(cmsp.key_levels),
            }
        except ImportError:
            pass

        # ── Domain summaries ──
        try:
            from junior_aladdin.floor_3_calculations.f3_orchestrator import (
                get_domain_states,
            )

            states = get_domain_states()
            result["domain_summaries"] = {
                k: (
                    v if isinstance(v, dict) else {"status": str(v)}
                )
                for k, v in states.items()
            }
        except ImportError:
            pass

        # ── Chart data (OHLCV) ──
        try:
            from junior_aladdin.floor_3_calculations.f3_orchestrator import (
                get_chart_data,
            )

            chart = get_chart_data()
            if chart is not None:
                result["chart_data"] = chart
        except ImportError:
            pass

    except ImportError:
        pass
    except Exception:
        pass

    return result
