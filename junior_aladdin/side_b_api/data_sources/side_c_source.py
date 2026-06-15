"""Side C data source adapter — READ MODELS ONLY.

Polls Side C (Memory/Journal) through its query layer and read model
builders.  NEVER queries raw stores directly.

Reference: ROADMAP_SIDE_B Step 8.2, Section 4 (architecture protection)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def poll_side_c() -> dict[str, Any]:
    """Poll Side C read models for trade history, decision history, and health events.

    CRITICAL: All queries go through READ MODELS ONLY.
    Never queries raw event/journal/reference stores.

    Returns:
        Dict with keys:
            - trade_history: list[dict] — recent trade journal entries
            - decision_history: list[dict] — recent decision journal entries
            - health_events: list[dict] — recent health events
            - blocked_action_history: list[dict]
            - override_history: list[dict]
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "trade_history": [],
        "decision_history": [],
        "health_events": [],
        "blocked_action_history": [],
        "override_history": [],
        "last_poll": datetime.utcnow().isoformat(),
    }

    # ── Trade history (read model) ──
    try:
        from junior_aladdin.side_c_memory.read_model_builder import (
            build_trade_history_summary,
        )

        trade_summary = build_trade_history_summary(limit=10)
        result["trade_history"] = (
            list(trade_summary)
            if isinstance(trade_summary, list)
            else [trade_summary]
        )
    except Exception:
        log.debug("Side C trade history poll failed", exc_info=True)

    # ── Decision history (read model) ──
    try:
        from junior_aladdin.side_c_memory.read_model_builder import (
            build_decision_review_summary,
        )

        decision_summary = build_decision_review_summary(limit=10)
        result["decision_history"] = (
            list(decision_summary)
            if isinstance(decision_summary, list)
            else [decision_summary]
        )
    except Exception:
        log.debug("Side C decision history poll failed", exc_info=True)

    # ── Health events (read model) ──
    try:
        from junior_aladdin.side_c_memory.read_model_builder import (
            build_health_timeline_summary,
        )

        health_summary = build_health_timeline_summary(limit=20)
        result["health_events"] = (
            list(health_summary)
            if isinstance(health_summary, list)
            else [health_summary]
        )
    except Exception:
        log.debug("Side C health events poll failed", exc_info=True)

    # ── Blocked action history (read model) ──
    try:
        from junior_aladdin.side_c_memory.read_model_builder import (
            build_blocked_actions_summary,
        )

        blocked_summary = build_blocked_actions_summary(limit=10)
        result["blocked_action_history"] = (
            list(blocked_summary)
            if isinstance(blocked_summary, list)
            else [blocked_summary]
        )
    except Exception:
        log.debug("Side C blocked actions poll failed", exc_info=True)

    # ── Override history (read model) ──
    try:
        from junior_aladdin.side_c_memory.read_model_builder import (
            build_override_history_summary,
        )

        override_summary = build_override_history_summary(limit=10)
        result["override_history"] = (
            list(override_summary)
            if isinstance(override_summary, list)
            else [override_summary]
        )
    except Exception:
        log.debug("Side C override history poll failed", exc_info=True)

    return result
