"""Side C Memory Layer — read model / projection builder.

Builds lightweight read models (projections) from Side C stores for
Side B dashboard consumption.  Side B NEVER consumes raw stores —
only these summaries.

Architecture rules (LOCKED):
- These are READ MODELS — factual summaries, NOT raw store views.
- NO market interpretation, NO scoring, NO ranking, NO recommendation.
- NO trade analysis, NO decision analysis.
- May summarise events (counts, severities, lists of reasons).
- May NOT score/rank/recommend/analyze trades or decisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.side_c_memory.c_types import (
    EventFamily,
    MemoryQuery,
    ReadModelSummary,
)
from junior_aladdin.side_c_memory.query_layer import (
    get_decision_history,
    get_health_timeline,
    get_trade_history,
    query as query_cross_store,
)

logger = get_logger(__name__)


# =============================================================================
# Public API
# =============================================================================


def build_trade_history_summary(
    trade_id: str,
    timerange: tuple[datetime, datetime] | None = None,
) -> ReadModelSummary:
    """Build a trade history summary for Side B consumption.

    Fetches the trade journal entry + linked execution events for a
    trade and returns a factual summary.

    Args:
        trade_id: The trade identifier to summarise.
        timerange: Optional ``(start, end)`` datetime tuple.

    Returns:
        A ``ReadModelSummary`` with factual trade data:
        ``trade_id``, ``entry``, ``exit``, ``pnl``, ``mode``.
    """
    envelopes = get_trade_history(trade_id)
    if not envelopes:
        return ReadModelSummary(
            family=EventFamily.TRADE_JOURNAL,
            timerange=timerange,
            event_count=0,
            summary_data={"trade_id": trade_id, "note": "No data found"},
        )

    # Extract factual summary from envelopes
    entries: list[dict[str, Any]] = []
    for env in envelopes:
        entry: dict[str, Any] = {
            "event_type": env.event_type,
            "family": env.family.value,
            "source": env.source,
            "severity": env.severity.value,
            "timestamp": env.timestamp.isoformat() if env.timestamp else "",
        }
        entries.append(entry)

    # Determine timerange from actual data if not provided
    if timerange is None:
        timestamps = [e.timestamp for e in envelopes if e.timestamp]
        actual_start = min(timestamps) if timestamps else None
        actual_end = max(timestamps) if timestamps else None
        timerange = (actual_start, actual_end) if actual_start else None

    return ReadModelSummary(
        family=EventFamily.TRADE_JOURNAL,
        timerange=timerange,
        event_count=len(envelopes),
        summary_data={
            "trade_id": trade_id,
            "related_records": entries,
        },
    )


def build_decision_review_summary(
    decision_id: str,
) -> ReadModelSummary:
    """Build a decision review summary for Side B consumption.

    Fetches the decision journal entry + linked references for a
    decision and returns a factual summary.

    Args:
        decision_id: The decision identifier to summarise.

    Returns:
        A ``ReadModelSummary`` with factual decision data:
        ``decision_id``, ``conviction_band``, ``reason``, ``timestamp``.
    """
    envelopes = get_decision_history(decision_id)
    if not envelopes:
        return ReadModelSummary(
            family=EventFamily.DECISION_JOURNAL,
            event_count=0,
            summary_data={
                "decision_id": decision_id,
                "note": "No data found",
            },
        )

    entries: list[dict[str, Any]] = []
    for env in envelopes:
        entries.append({
            "event_type": env.event_type,
            "family": env.family.value,
            "source": env.source,
            "severity": env.severity.value,
            "timestamp": env.timestamp.isoformat() if env.timestamp else "",
        })

    timestamps = [e.timestamp for e in envelopes if e.timestamp]
    timerange = (
        (min(timestamps), max(timestamps))
        if timestamps
        else None
    )

    return ReadModelSummary(
        family=EventFamily.DECISION_JOURNAL,
        timerange=timerange,
        event_count=len(envelopes),
        summary_data={
            "decision_id": decision_id,
            "related_records": entries,
        },
    )


def build_health_timeline_summary(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> ReadModelSummary:
    """Build a health timeline summary for Side B consumption.

    Aggregates health events into a timeline with state transitions
    and event counts per severity level.

    Args:
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).

    Returns:
        A ``ReadModelSummary`` with factual health data:
        ``transitions`` (list of health state changes),
        ``severity_counts`` (dict of severity → count).
    """
    envelopes = get_health_timeline(start_time, end_time)

    severity_counts: dict[str, int] = {}
    transitions: list[dict[str, Any]] = []
    previous_state: str | None = None

    for env in envelopes:
        sev = env.severity.value
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Track state transitions (from event_type names)
        state = env.event_type
        if state != previous_state:
            transitions.append({
                "timestamp": env.timestamp.isoformat() if env.timestamp else "",
                "state": state,
                "severity": sev,
            })
            previous_state = state

    timerange = (start_time, end_time) if start_time else None

    return ReadModelSummary(
        family=EventFamily.HEALTH_EVENT,
        timerange=timerange,
        event_count=len(envelopes),
        summary_data={
            "transitions": transitions,
            "severity_counts": severity_counts,
        },
    )


def build_override_history_summary(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> ReadModelSummary:
    """Build an override history summary for Side B consumption.

    Fetches OVERRIDE events and returns factual summary with reasons.

    Args:
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).

    Returns:
        A ``ReadModelSummary`` with factual override data:
        ``override_count``, ``reasons`` (list of override reasons).
    """
    envelopes = query_cross_store(
        MemoryQuery(
            families=[EventFamily.OVERRIDE],
            start_time=start_time,
            end_time=end_time,
            limit=-1,
        )
    )

    reasons: list[dict[str, Any]] = []
    for env in envelopes:
        reasons.append({
            "timestamp": env.timestamp.isoformat() if env.timestamp else "",
            "source": env.source,
            "severity": env.severity.value,
            "event_type": env.event_type,
        })

    timerange = (start_time, end_time) if start_time else None

    return ReadModelSummary(
        family=EventFamily.OVERRIDE,
        timerange=timerange,
        event_count=len(envelopes),
        summary_data={
            "override_count": len(envelopes),
            "reasons": reasons,
        },
    )


def build_blocked_actions_summary(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> ReadModelSummary:
    """Build a blocked actions summary for Side B consumption.

    Fetches BLOCKED_ACTION events and returns factual summary with
    severity breakdown.

    Args:
        start_time: Inclusive start of the time range (UTC).
        end_time: Inclusive end of the time range (UTC).

    Returns:
        A ``ReadModelSummary`` with factual blocked-action data:
        ``block_count``, ``severity_breakdown`` (dict of severity → count).
    """
    envelopes = query_cross_store(
        MemoryQuery(
            families=[EventFamily.BLOCKED_ACTION],
            start_time=start_time,
            end_time=end_time,
            limit=-1,
        )
    )

    severity_breakdown: dict[str, int] = {}
    actions: list[dict[str, Any]] = []
    for env in envelopes:
        sev = env.severity.value
        severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
        actions.append({
            "timestamp": env.timestamp.isoformat() if env.timestamp else "",
            "source": env.source,
            "severity": sev,
            "event_type": env.event_type,
        })

    timerange = (start_time, end_time) if start_time else None

    return ReadModelSummary(
        family=EventFamily.BLOCKED_ACTION,
        timerange=timerange,
        event_count=len(envelopes),
        summary_data={
            "block_count": len(envelopes),
            "severity_breakdown": severity_breakdown,
            "actions": actions,
        },
    )
