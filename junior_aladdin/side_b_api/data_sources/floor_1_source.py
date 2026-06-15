"""Floor 1 data source adapter.

Polls Floor 1 (Market Connection) for source health, connection status,
latency, and lifecycle state.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from junior_aladdin.shared.component_registry import get_registry
from junior_aladdin.shared.types import LifecycleState

log = logging.getLogger(__name__)


def poll_floor_1() -> dict[str, Any]:
    """Poll Floor 1 for source health and connection status.

    Uses ComponentRegistry.get_source_health_monitor() for shared singleton.

    Returns:
        Dict with keys:
            - source_health: dict (lifecycle_state, latency_ms, reconnect_count)
            - connection_status: str ("CONNECTED" / "DISCONNECTED" / "DEGRADED")
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "source_health": {},
        "connection_status": "UNKNOWN",
        "last_poll": datetime.utcnow().isoformat(),
    }

    try:
        monitor = get_registry().get_source_health_monitor()
        health = monitor.get_state()

        result["source_health"] = {
            "lifecycle_state": health.lifecycle_state.value,
            "latency_ms": health.latency_ms,
            "heartbeat_age_s": health.heartbeat_age_s,
            "reconnect_count": health.reconnect_count,
            "ltp": health.ltp,
        }

        if health.lifecycle_state == LifecycleState.HEALTHY:
            result["connection_status"] = "CONNECTED"
        elif health.lifecycle_state in (
            LifecycleState.DEGRADED,
            LifecycleState.STALE,
        ):
            result["connection_status"] = "DEGRADED"
        else:
            result["connection_status"] = "DISCONNECTED"

    except Exception:
        log.warning("Floor 1 poll failed — using defaults", exc_info=True)
        result["connection_status"] = "ERROR"

    return result
