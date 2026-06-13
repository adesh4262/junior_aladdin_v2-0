"""Floor 4 data source adapter.

Polls Floor 4 (Department Heads) for the aggregated FloorSummary,
individual HeadReports per head, and per-head operational states and
freshness.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def poll_floor_4() -> dict[str, Any]:
    """Poll Floor 4 for floor summary, head reports, and head states.

    Returns:
        Dict with keys:
            - floor_summary: dict (floor_bias, confidence, setup counts, head health)
            - head_reports: list[dict] — per-head report summaries
            - head_states: dict[str, str] — per-head: READY / UNCERTAIN / STALE
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "floor_summary": {},
        "head_reports": [],
        "head_states": {},
        "last_poll": datetime.utcnow().isoformat(),
    }

    try:
        # ── Floor Summary ──
        try:
            from junior_aladdin.floor_4_heads.floor_summary_builder import (
                FloorSummaryBuilder,
            )

            builder = FloorSummaryBuilder()
            summary = builder.get_latest_summary()
            if summary is not None:
                result["floor_summary"] = {
                    "summary_timestamp": (
                        summary.summary_timestamp.isoformat()
                        if hasattr(summary, "summary_timestamp")
                        else ""
                    ),
                    "floor_bias_snapshot": summary.floor_bias_snapshot,
                    "floor_confidence_snapshot": summary.floor_confidence_snapshot,
                    "active_setup_count": summary.active_setup_count,
                    "ready_heads_count": summary.ready_heads_count,
                    "uncertain_heads_count": summary.uncertain_heads_count,
                    "stale_heads_count": summary.stale_heads_count,
                    "conflict_present": summary.conflict_present,
                    "data_health_signal": (
                        summary.data_health_signal.value
                        if hasattr(summary.data_health_signal, "value")
                        else str(summary.data_health_signal)
                    ),
                    "head_health_snapshot": dict(summary.head_health_snapshot),
                    "core_head_health_snapshot": dict(
                        summary.core_head_health_snapshot
                    ),
                    "setup_presence": summary.setup_presence,
                    "setup_absence_context": summary.setup_absence_context,
                }
        except ImportError:
            pass

        # ── Head Reports ──
        try:
            from junior_aladdin.floor_4_heads.head_base import get_all_head_reports

            reports = get_all_head_reports()
            result["head_reports"] = [
                {
                    "head_name": r.head_name,
                    "state": r.state.value if hasattr(r.state, "value") else str(r.state),
                    "bias": r.bias.value if hasattr(r.bias, "value") else str(r.bias),
                    "confidence": r.confidence,
                    "freshness_tag": (
                        r.freshness_tag.value
                        if hasattr(r.freshness_tag, "value")
                        else str(r.freshness_tag)
                    ),
                    "context_quality_score": r.context_quality_score,
                    "primary_setup": r.primary_setup,
                    "backup_setup": r.backup_setup,
                    "invalidation_summary": str(r.invalidation),
                    "no_setup_flag": r.primary_setup is None and r.backup_setup is None,
                }
                for r in reports
            ]
            result["head_states"] = {
                r.head_name: (
                    r.state.value if hasattr(r.state, "value") else str(r.state)
                )
                for r in reports
            }
        except ImportError:
            pass

    except ImportError:
        pass
    except Exception:
        pass

    return result
