"""Floor 2 data source adapter.

Polls Floor 2 (Data Center) for data health signal, validation statistics,
replay status, and metadata side-channel information.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def poll_floor_2() -> dict[str, Any]:
    """Poll Floor 2 for data health, validation stats, and replay status.

    Returns:
        Dict with keys:
            - data_health: str (GOOD / CAUTION / DEGRADED / CRITICAL)
            - review_signal: str (GOOD / CAUTION / DEGRADED / CRITICAL)
            - replay_active: bool
            - replay_session_id: str | None
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "data_health": "UNKNOWN",
        "review_signal": "UNKNOWN",
        "validation_stats": {"total": 0, "passed": 0, "failed": 0, "warned": 0},
        "replay_active": False,
        "replay_session_id": None,
        "last_poll": datetime.utcnow().isoformat(),
    }

    try:
        from junior_aladdin.shared.types import DataHealth
        from junior_aladdin.floor_2_datacenter.datacenter_types import ReviewSignal

        # ── Data health: check ReviewSignal from metadata side-channel ──
        try:
            from junior_aladdin.floor_2_datacenter.review.health_monitor import (
                get_current_health,
            )

            health = get_current_health()
            if hasattr(health, "value"):
                result["data_health"] = health.value
            else:
                result["data_health"] = str(health)
        except ImportError:
            pass

        # ── Validation stats ──
        try:
            from junior_aladdin.floor_2_datacenter.validation.validation_router import (
                get_validation_stats,
            )

            stats = get_validation_stats()
            result["validation_stats"] = {
                "total": stats.get("total", 0),
                "passed": stats.get("passed", 0),
                "failed": stats.get("failed", 0),
                "warned": stats.get("warned", 0),
            }
        except ImportError:
            pass

        # ── Replay status ──
        try:
            from junior_aladdin.floor_2_datacenter.replay.replay_engine import (
                get_active_session,
            )

            session = get_active_session()
            if session is not None:
                result["replay_active"] = True
                result["replay_session_id"] = str(
                    getattr(session, "session_id", None)
                )
        except ImportError:
            pass

    except ImportError:
        pass
    except Exception:
        pass

    return result
