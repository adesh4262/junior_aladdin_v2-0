"""Floor 4 data source adapter.

Polls Floor 4 (Department Heads) for the aggregated FloorSummary,
individual HeadReports per head, and per-head operational states and
freshness.

Reads from the shared CaptainEngine singleton which stores the latest
head reports and floor summary from each heavy cycle run by SystemRunner.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from junior_aladdin.shared.component_registry import get_registry

log = logging.getLogger(__name__)


def poll_floor_4() -> dict[str, Any]:
    """Poll Floor 4 for floor summary, head reports, and head states.

    Reads from the shared CaptainEngine singleton which stores the latest
    head reports + floor summary from each heavy cycle.

    Falls back to empty defaults if:
    - CaptainEngine hasn't run any heavy cycle yet
    - No head reports available yet

    Returns:
        Dict with keys:
            - floor_summary: dict (floor_bias_snapshot, confidence, setup counts, head health)
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
        captain = get_registry().get_captain_engine()
        head_reports = captain.get_latest_head_reports()
        floor_summary = captain.get_latest_floor_summary()

        # ── Convert HeadReport objects to dicts ──
        if head_reports:
            head_list: list[dict[str, Any]] = []
            head_states: dict[str, str] = {}

            for head_name, report in head_reports.items():
                head_list.append({
                    "head_name": head_name,
                    "state": report.state.value if hasattr(report.state, "value") else str(report.state),
                    "bias": report.bias.value if hasattr(report.bias, "value") else str(report.bias),
                    "confidence": report.confidence,
                    "freshness_tag": report.freshness_tag.value if hasattr(report.freshness_tag, "value") else str(report.freshness_tag),
                    "context_quality_score": report.context_quality_score,
                    "primary_setup": report.primary_setup,
                    "backup_setup": report.backup_setup,
                    "no_setup_flag": getattr(report, "no_setup_flag", False),
                })
                head_states[head_name] = report.state.value if hasattr(report.state, "value") else str(report.state)

            result["head_reports"] = head_list
            result["head_states"] = head_states

        # ── Convert FloorSummary to dict ──
        if floor_summary is not None:
            fs = floor_summary
            result["floor_summary"] = {
                "floor_bias_snapshot": fs.floor_bias_snapshot if hasattr(fs, "floor_bias_snapshot") else {},
                "floor_confidence_snapshot": fs.floor_confidence_snapshot if hasattr(fs, "floor_confidence_snapshot") else {},
                "active_setup_count": fs.active_setup_count if hasattr(fs, "active_setup_count") else 0,
                "primary_setups_by_head": fs.primary_setups_by_head if hasattr(fs, "primary_setups_by_head") else {},
                "backup_setups_by_head": fs.backup_setups_by_head if hasattr(fs, "backup_setups_by_head") else {},
                "ready_heads_count": fs.ready_heads_count if hasattr(fs, "ready_heads_count") else 0,
                "uncertain_heads_count": fs.uncertain_heads_count if hasattr(fs, "uncertain_heads_count") else 0,
                "stale_heads_count": fs.stale_heads_count if hasattr(fs, "stale_heads_count") else 0,
                "conflict_present": fs.conflict_present if hasattr(fs, "conflict_present") else False,
                "data_health_signal": fs.data_health_signal.value if hasattr(fs.data_health_signal, "value") else str(fs.data_health_signal),
                "summary_witness_lines": fs.summary_witness_lines if hasattr(fs, "summary_witness_lines") else [],
            }

        log.debug(
            "Floor 4 poll: %d head(s), floor_summary=%s",
            len(head_reports),
            "present" if floor_summary else "missing",
        )

    except Exception:
        log.warning("Floor 4 poll failed — returning empty defaults", exc_info=True)

    return result
