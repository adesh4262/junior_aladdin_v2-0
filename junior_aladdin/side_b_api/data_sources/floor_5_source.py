"""Floor 5 data source adapter.

Polls Floor 5 (Captain) for current Captain state, recent decision
snapshots, active armed plans, and market story / silence reason.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def poll_floor_5() -> dict[str, Any]:
    """Poll Floor 5 for captain state, decision snapshots, and armed plans.

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

    try:
        # ── Captain Engine state ──
        try:
            from junior_aladdin.floor_5_captain.captain_engine import CaptainEngine

            engine = CaptainEngine()
            state = engine.get_state()

            result["captain_state"] = {
                "mood": (
                    state.mood.value
                    if hasattr(state, "mood") and hasattr(state.mood, "value")
                    else str(getattr(state, "mood", "OBSERVER"))
                ),
                "decision_state": (
                    state.decision_state.value
                    if hasattr(state, "decision_state") and hasattr(state.decision_state, "value")
                    else str(getattr(state, "decision_state", "WAIT"))
                ),
                "conviction_band": (
                    state.conviction_band.value
                    if hasattr(state, "conviction_band") and hasattr(state.conviction_band, "value")
                    else str(getattr(state, "conviction_band", "REJECT"))
                ),
                "market_story_summary": getattr(state, "market_story_summary", ""),
                "silence_reason": getattr(state, "silence_reason", ""),
                "session_phase": (
                    state.session_phase.value
                    if hasattr(state, "session_phase") and hasattr(state.session_phase, "value")
                    else str(getattr(state, "session_phase", ""))
                ),
                "real_mode_locked": getattr(state, "real_mode_locked", False),
                "active_trade": getattr(state, "active_trade", False),
            }
        except ImportError:
            pass

        # ── Decision snapshots ──
        try:
            from junior_aladdin.floor_5_captain.decision_snapshot_writer import (
                DecisionSnapshotWriter,
            )

            writer = DecisionSnapshotWriter()
            snapshots = writer.get_recent(count=5)
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
        except ImportError:
            pass

        # ── Armed plans ──
        try:
            from junior_aladdin.floor_5_captain.armed_plan_engine import (
                ArmedPlanEngine,
            )

            plan_engine = ArmedPlanEngine()
            plans = plan_engine.get_active_plans()
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
        except ImportError:
            pass

    except ImportError:
        pass
    except Exception:
        pass

    return result
