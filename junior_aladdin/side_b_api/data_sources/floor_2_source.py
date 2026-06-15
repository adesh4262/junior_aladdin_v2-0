"""Floor 2 data source adapter.

Polls Floor 2 (Data Center) for data health signal, validation statistics,
replay status, and metadata side-channel information.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def poll_floor_2() -> dict[str, Any]:
    """Poll Floor 2 for data health, validation stats, and replay status.

    Returns:
        Dict with keys:
            - data_health: str (GOOD / CAUTION / DEGRADED / CRITICAL)
            - review_signal: str (GOOD / CAUTION / DEGRADED / CRITICAL)
            - validation_stats: dict with total/passed/failed/warned counts
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

    # ── Data health ──
    # Floor 2 is event-driven (processes Floor 1 data through the pipeline).
    # No global state exists until SystemRunner activates the pipeline.
    # UNKNOWN default is correct until data actually flows through Floor 2.
    log.debug("Floor 2: no data pipeline active (SystemRunner required)")

    # ── Validation stats (graceful default — no validation without data flow) ──
    # ValidationRouter requires a NormalizedRawStore which needs incoming data.
    # Floor 2 data flows only when SystemRunner is active.
    log.debug("Floor 2 validation stats: no data pipeline active (SystemRunner required)")

    # ── Replay status (graceful default — no data to replay without pipeline) ──
    # ReplayEngine requires stores that are only populated by active data flow.
    log.debug("Floor 2 replay: not available until data pipeline is active")

    return result
