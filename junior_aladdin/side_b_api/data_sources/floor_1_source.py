"""Floor 1 data source adapter.

Polls Floor 1 (Market Connection) for source health, connection status,
latency, and lifecycle state.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.shared.types import LifecycleState, SourceHealth


def poll_floor_1() -> dict[str, Any]:
    """Poll Floor 1 for source health and connection status.

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
        from junior_aladdin.floor_1_connection.source_health import SourceHealthMonitor

        monitor = SourceHealthMonitor()
        health: SourceHealth = monitor.get_health()

        result["source_health"] = {
            "lifecycle_state": health.lifecycle_state.value,
            "latency_ms": health.latency_ms,
            "heartbeat_age_s": health.heartbeat_age_s,
            "reconnect_count": health.reconnect_count,
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

    except ImportError:
        result["connection_status"] = "UNAVAILABLE"
    except Exception:
        result["connection_status"] = "ERROR"

    return result
