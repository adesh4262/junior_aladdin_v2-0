"""Floor 5 data source adapter.

Polls Floor 5 (Captain) for current Captain state, recent decision
snapshots, active armed plans, and market story / silence reason.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from junior_aladdin.shared.component_registry import get_registry

log = logging.getLogger(__name__)


def poll_floor_5() -> dict[str, Any]:
    """Poll Floor 5 for captain state, decision snapshots, and armed plans.

    Uses ComponentRegistry.get_captain_engine() to get the SHARED singleton
    (fixes BRUTAL_DEEP_SCAN FINDING #2).

    Returns:
        Dict with keys:
            - captain_state: dict (mood, decision, conviction, market_story, silence_reason)
            - decision_snapshots: list[dict] — recent frozen decisions
            - armed_plans: list[dict] — active conditional plans
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "captain_state": {},
        "decision_snapshots": [],
        "armed_plans": [],
        "last_poll": datetime.utcnow().isoformat(),
    }

    # ── Captain Engine state (via ComponentRegistry) ──
    try:
        registry = get_registry()
        engine = registry.get_captain_engine()
        cs = engine.get_current_state()

        # Pull real data from snapshot_writer for dashboard display
        latest_snap = registry.get_snapshot_writer().get_latest_snapshot()
        fetch_mood = "OBSERVER"
        fetch_decision_state = "WAIT"
        fetch_conviction_band = "REJECT"
        fetch_market_story = ""
        fetch_silence_reason = ""
        fetch_session_phase = ""
        fetch_real_mode_locked = False
        fetch_active_trade = cs.get("has_active_trade", False)

        if latest_snap is not None:
            if hasattr(latest_snap, "mood") and hasattr(latest_snap.mood, "value"):
                fetch_mood = latest_snap.mood.value
            if hasattr(latest_snap, "conviction_score"):
                from junior_aladdin.floor_5_captain.captain_types import (
                    conviction_score_to_band,
                )
                fetch_conviction_band = conviction_score_to_band(
                    latest_snap.conviction_score,
                ).value
            if hasattr(latest_snap, "market_story_summary"):
                fetch_market_story = latest_snap.market_story_summary
            if hasattr(latest_snap, "decision_reason"):
                fetch_decision_state = "TRADE" if fetch_active_trade else "WAIT"

        result["captain_state"] = {
            "mood": fetch_mood,
            "decision_state": fetch_decision_state,
            "conviction_band": fetch_conviction_band,
            "market_story_summary": fetch_market_story,
            "silence_reason": fetch_silence_reason,
            "session_phase": fetch_session_phase,
            "real_mode_locked": fetch_real_mode_locked,
            "active_trade": fetch_active_trade,
        }

        # Decision snapshots — use get_session_snapshots() for latest N
        all_snaps = registry.get_snapshot_writer().get_session_snapshots()
        snapshots = all_snaps[-5:] if len(all_snaps) > 5 else all_snaps
        result["decision_snapshots"] = [
            {
                "snapshot_id": s.snapshot_id,
                "timestamp": (
                    s.timestamp.isoformat()
                    if hasattr(s, "timestamp")
                    else ""
                ),
                "market_story_summary": getattr(s, "market_story_summary", ""),
                "conviction_score": getattr(s, "conviction_score", 0.0),
                "decision_reason": getattr(s, "decision_reason", ""),
                "mood": (
                    s.mood.value
                    if hasattr(s, "mood") and hasattr(s.mood, "value")
                    else ""
                ),
            }
            for s in snapshots
        ]

        # Armed plans
        plans = registry.get_armed_plan_engine().get_active_plans()
        result["armed_plans"] = [
            {
                "plan_id": p.plan_id,
                "direction": getattr(p, "direction", ""),
                "setup_class": getattr(p, "setup_class", ""),
                "readiness": getattr(p, "readiness", "WATCHING"),
                "expiry_condition": getattr(p, "expiry_condition", {}),
                "originating_heads": list(getattr(p, "originating_heads", [])),
            }
            for p in plans
        ]
    except Exception:
        log.warning("Floor 5 poll failed — using defaults", exc_info=True)

    return result
