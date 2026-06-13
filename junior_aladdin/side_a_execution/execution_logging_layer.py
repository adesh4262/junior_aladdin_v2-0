"""Side A — Execution Logging Layer: Journal all events to Side C Memory and dashboard.

Bridges every Side A execution event (from the orchestrator and all sub-modules)
into structured MemoryEvent records for Side C's ingest_layer, and provides a
real-time callback for Side B (dashboard) consumption.

Architecture rules (LOCKED):
- Side C receives structured MemoryEvent objects via ingest_event()
- Emitter ID is always "side_a"
- Event mapping: orchestrator event_type → correct EventFamily + payload
- Dashboard callback receives the same structured data for real-time display
- Non-critical events are logged at Severity.INFO
- Errors/rejections are logged at Severity.CAUTION or Severity.SEVERE
- Failures in the logging layer NEVER crash the execution pipeline
- Recent events are buffered for dashboard query (last 100 by default)

Event Type → Side C Family Mapping:
    EXECUTION_EVENT:
        DECISION_ACCEPTED, DECISION_ALERT_ONLY, DECISION_REJECTED
        ORDER_SUBMIT_FAILED, ORDER_ALREADY_REGISTERED, ORDER_REGISTER_FAILED
        FILL_PROCESSED, FILL_HANDLE_FAILED, FILL_POSITION_*
        ACKNOWLEDGEMENT_PROCESSED
        REJECTION_PROCESSED, REJECTION_HANDLE_FAILED
        PROTECTION_STAGED, PROTECTION_STAGE_FAILED
        EMERGENCY_FLATTEN, CRITICAL_LOCK, EMERGENCY_SKIPPED
        RECONCILE_COMPLETE, RECONCILE_ESCALATED
        EXIT_COMPLETE, EXIT_SKIPPED
        MODE_CHANGED, MODE_CHANGE_BLOCKED
        KILL_SWITCH_SOFT, KILL_SWITCH_NORMAL
        RECONNECT_COMPLETE
    BLOCKED_ACTION:
        DECISION_BLOCKED
    TRADE_JOURNAL:
        TRADE_COMPLETE
    OVERRIDE:
        OVERRIDE_APPLIED
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import MemoryEvent, Severity
from junior_aladdin.side_c_memory.c_types import EventFamily

logger = get_logger(__name__)


# =============================================================================
# Event Type → Family Mapping
# =============================================================================

#: Event types that map to EXECUTION_EVENT family
_EXECUTION_EVENT_TYPES: frozenset[str] = frozenset({
    "DECISION_ACCEPTED",
    "DECISION_ALERT_ONLY",
    "DECISION_REJECTED",
    "ORDER_SUBMIT_FAILED",
    "ORDER_ALREADY_REGISTERED",
    "ORDER_REGISTER_FAILED",
    "FILL_PROCESSED",
    "FILL_HANDLE_FAILED",
    "FILL_POSITION_OPEN_FAILED",
    "FILL_POSITION_UPDATE_FAILED",
    "ACKNOWLEDGEMENT_PROCESSED",
    "REJECTION_PROCESSED",
    "REJECTION_HANDLE_FAILED",
    "PROTECTION_STAGED",
    "PROTECTION_STAGE_FAILED",
    "EMERGENCY_FLATTEN",
    "CRITICAL_LOCK",
    "EMERGENCY_SKIPPED",
    "RECONCILE_COMPLETE",
    "RECONCILE_ESCALATED",
    "EXIT_COMPLETE",
    "EXIT_SKIPPED",
    "MODE_CHANGED",
    "MODE_CHANGE_BLOCKED",
    "KILL_SWITCH_SOFT",
    "KILL_SWITCH_NORMAL",
    "RECONNECT_COMPLETE",
})

#: Event types that map to BLOCKED_ACTION family
_BLOCKED_ACTION_TYPES: frozenset[str] = frozenset({
    "DECISION_BLOCKED",
})

#: Event types that map to TRADE_JOURNAL family
_TRADE_JOURNAL_TYPES: frozenset[str] = frozenset({
    "TRADE_COMPLETE",
})

#: Event types that map to OVERRIDE family
_OVERRIDE_TYPES: frozenset[str] = frozenset({
    "OVERRIDE_APPLIED",
})

#: Union of all known event types
_KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    _EXECUTION_EVENT_TYPES | _BLOCKED_ACTION_TYPES | _TRADE_JOURNAL_TYPES | _OVERRIDE_TYPES
)


#: Fields promoted to MemoryEvent top-level (stripped from payload)
_RESERVED_PAYLOAD_FIELDS: frozenset[str] = frozenset({
    "family", "source", "emitter", "timestamp", "severity", "refs",
})


# =============================================================================
# Severity Mapping
# =============================================================================

#: Event types that map to elevated severity
_SEVERE_EVENT_TYPES: frozenset[str] = frozenset({
    "EMERGENCY_FLATTEN",
    "CRITICAL_LOCK",
    "RECONCILE_ESCALATED",
    "FILL_HANDLE_FAILED",
    "PROTECTION_STAGE_FAILED",
})

_CAUTION_EVENT_TYPES: frozenset[str] = frozenset({
    "DECISION_REJECTED",
    "DECISION_BLOCKED",
    "ORDER_SUBMIT_FAILED",
    "REJECTION_PROCESSED",
    "REJECTION_HANDLE_FAILED",
    "MODE_CHANGE_BLOCKED",
    "EMERGENCY_SKIPPED",
    "EXIT_SKIPPED",
    "FILL_POSITION_OPEN_FAILED",
    "FILL_POSITION_UPDATE_FAILED",
    "ORDER_REGISTER_FAILED",
})


# =============================================================================
# ExecutionLoggingLayer
# =============================================================================


class ExecutionLoggingLayer:
    """Bridges Side A execution events to Side C Memory and dashboard.

    Acts as the ``on_log_callback`` for all Side A modules (orchestrator,
    position manager, order lifecycle manager, protection model,
    reconciliation engine, execution core).  Transforms each event into
    a structured ``MemoryEvent``, ingests it into Side C via
    ``ingest_event()``, and forwards a copy to the dashboard callback.

    The layer is designed to NEVER crash the execution pipeline —
    all exceptions during logging are caught and logged.

    Usage::

        # Construct with Side C ingest and optional dashboard callback
        logging_layer = ExecutionLoggingLayer(
            side_c_ingest=ingest_event,
            on_dashboard_event=my_dashboard_ws_send,
        )

        # Pass as on_log_callback to orchestrator and sub-modules
        orchestrator = ExecutionOrchestrator(
            ...,
            on_log_callback=logging_layer.log,
        )
        pm = PositionManager(
            ...,
            on_log_callback=logging_layer.log,
        )

        # Or call directly
        logging_layer.log("DECISION_ACCEPTED", {
            "trade_id": "T123",
            "order_id": "ORD001",
        })
    """

    def __init__(
        self,
        side_c_ingest: Callable[..., Any] | None = None,
        on_dashboard_event: Callable[[str, dict[str, Any]], None] | None = None,
        emitter_id: str = "side_a",
        max_recent_events: int = 100,
    ) -> None:
        """Initialize the ExecutionLoggingLayer.

        Args:
            side_c_ingest: The ``ingest_event`` function from Side C.
                If ``None``, Side C ingestion is skipped (e.g. during
                testing or when Side C is not yet connected).
            on_dashboard_event: Optional callback for real-time dashboard
                display.  Receives ``(event_type, data)``.
            emitter_id: Side C emitter ID (default ``"side_a"``).
            max_recent_events: Maximum number of recent events to buffer
                for dashboard query (default 100).
        """
        self._side_c_ingest = side_c_ingest
        self._dashboard_callback = on_dashboard_event
        self._emitter_id = emitter_id
        self._max_recent_events = max_recent_events

        #: Ring buffer of recent events for dashboard / query consumption
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=max_recent_events)

    # ------------------------------------------------------------------
    # Main entry point (matches on_log_callback signature)
    # ------------------------------------------------------------------

    def log(self, event_type: str, data: dict[str, Any]) -> None:
        """Log an execution event to Side C Memory and dashboard.

        This is the ``Callable[[str, dict[str, Any]], None]`` callback
        used by all Side A modules as their ``on_log_callback``.

        Args:
            event_type: The type of event (e.g. ``"DECISION_ACCEPTED"``,
                ``"FILL_PROCESSED"``, ``"PROTECTION_STAGED"``).
            data: Event-specific data dict.

        Raises:
            RuntimeError: For CRITICAL severity events, re-raises the
                underlying exception after logging so the caller knows
                the logging layer failed for a critical event. Normal
                events (INFO/CAUTION) never raise.
        """
        try:
            # --- Step 1: Determine event family and severity ---
            family = self._resolve_family(event_type)
            severity = self._resolve_severity(event_type)

            # --- Step 2: Build structured payload ---
            payload = self._build_payload(event_type, data)

            # --- Step 3: Build refs from trade_id if present ---
            refs: dict[str, Any] = {}
            trade_id = data.get("trade_id", "")
            if trade_id:
                refs["trade_id"] = trade_id
            order_id = data.get("order_id", "")
            if order_id:
                refs["order_id"] = order_id

            # --- Step 4: Create MemoryEvent for Side C ---
            memory_event = MemoryEvent(
                event_type=event_type,
                source="side_a",
                family=family.value,
                emitter=self._emitter_id,
                timestamp=datetime.utcnow(),
                severity=severity,
                payload=payload,
                refs=refs,
            )

            # --- Step 5: Ingest into Side C ---
            if self._side_c_ingest is not None:
                try:
                    self._side_c_ingest(
                        event_data={
                            "event_type": memory_event.event_type,
                            "source": memory_event.source,
                            "emitter": memory_event.emitter,
                            "family": memory_event.family,
                            "timestamp": memory_event.timestamp.isoformat() if memory_event.timestamp else "",
                            "severity": memory_event.severity.value,
                            "payload": memory_event.payload,
                            "refs": memory_event.refs,
                        },
                        emitter_id=self._emitter_id,
                    )
                except (ValueError, KeyError) as e:
                    # Side C validation failure — log but don't crash
                    logger.warning(
                        "Side C ingestion rejected event",
                        extra={
                            "event_type": event_type,
                            "error": str(e),
                        },
                    )

            # --- Step 6: Buffer for dashboard ---
            self._recent_events.append({
                "event_type": event_type,
                "family": family.value,
                "severity": severity.value,
                "timestamp": memory_event.timestamp.isoformat() if memory_event.timestamp else "",
                "payload": payload,
                "refs": refs,
            })

            # --- Step 7: Forward to dashboard callback ---
            if self._dashboard_callback is not None:
                try:
                    self._dashboard_callback(event_type, {
                        "family": family.value,
                        "severity": severity.value,
                        "payload": payload,
                        "refs": refs,
                        "timestamp": memory_event.timestamp.isoformat() if memory_event.timestamp else "",
                    })
                except Exception:
                    # Dashboard callback failure — log but don't crash
                    logger.warning(
                        "Dashboard callback failed for event",
                        extra={"event_type": event_type},
                    )

        except Exception as e:
            # Last resort — log the failure
            logger.error(
                "ExecutionLoggingLayer failed to log event",
                extra={
                    "event_type": event_type,
                    "error": str(e),
                },
            )
            # For SEVERE+ events, re-raise so the caller knows logging failed
            severity = self._resolve_severity(event_type)
            if severity in (Severity.SEVERE, Severity.CRITICAL):
                raise RuntimeError(
                    f"Logging layer failure for {severity.value} event {event_type}: {e}"
                ) from e

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_recent_events(
        self,
        limit: int = 50,
        event_type_filter: str | None = None,
        family_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent buffered events for dashboard display.

        Args:
            limit: Maximum number of events to return (default 50).
            event_type_filter: Optional event type to filter by.
            family_filter: Optional family value to filter by.

        Returns:
            List of recent event dicts, newest first.
        """
        results = list(self._recent_events)

        # Filter
        if event_type_filter:
            results = [e for e in results if e.get("event_type") == event_type_filter]
        if family_filter:
            results = [e for e in results if e.get("family") == family_filter]

        # Newest first, then limit
        results.reverse()
        return results[:limit]

    def count_events(
        self,
        event_type: str | None = None,
        family: str | None = None,
    ) -> int:
        """Count buffered events matching optional filters.

        Args:
            event_type: Optional event type to count.
            family: Optional family value to count.

        Returns:
            Number of matching events in the buffer.
        """
        results = list(self._recent_events)
        if event_type:
            results = [e for e in results if e.get("event_type") == event_type]
        if family:
            results = [e for e in results if e.get("family") == family]
        return len(results)

    def export_for_audit(self, trade_id: str) -> dict[str, Any]:
        """Export a full execution audit trail for a specific trade.

        Collects ALL events related to the given trade_id from the
        recent buffer.  Returns a structured audit trail including:
        - All events in chronological order
        - Risk status transitions
        - Order lifecycle summary
        - Protection status
        - Blocked actions
        - Reconcile outcomes

        Args:
            trade_id: The trade to export audit trail for.

        Returns:
            Dict with audit trail for the trade, or empty dict if no
            events found for the trade.
        """
        if not trade_id:
            return {"error": "trade_id is required", "events": []}

        # Collect all events for this trade from the buffer
        events = [
            e for e in self._recent_events
            if e.get("refs", {}).get("trade_id") == trade_id
        ]

        if not events:
            return {"trade_id": trade_id, "events": [], "note": "No events found in buffer"}

        # Sort chronologically (oldest first)
        events.sort(key=lambda e: e.get("timestamp", ""))

        # Build summary
        event_types = [e.get("event_type", "UNKNOWN") for e in events]
        severities = [e.get("severity", "INFO") for e in events]

        return {
            "trade_id": trade_id,
            "event_count": len(events),
            "events": events,
            "event_sequence": event_types,
            "severity_breakdown": {
                sev: severities.count(sev) for sev in set(severities)
            },
            "first_event": events[0] if events else None,
            "last_event": events[-1] if events else None,
            "exported_at": datetime.utcnow().isoformat(),
        }

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary of event counts by type and severity.

        Returns:
            Dict with event_type counts, severity counts, and total.
        """
        events = list(self._recent_events)
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_family: dict[str, int] = {}

        for e in events:
            et = e.get("event_type", "UNKNOWN")
            by_type[et] = by_type.get(et, 0) + 1

            sev = e.get("severity", "INFO")
            by_severity[sev] = by_severity.get(sev, 0) + 1

            fam = e.get("family", "UNKNOWN")
            by_family[fam] = by_family.get(fam, 0) + 1

        return {
            "total_events": len(events),
            "by_event_type": by_type,
            "by_severity": by_severity,
            "by_family": by_family,
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _resolve_family(self, event_type: str) -> EventFamily:
        """Resolve an event type to its Side C event family.

        Args:
            event_type: The orchestrator event type string.

        Returns:
            The corresponding ``EventFamily`` enum value.
        """
        if event_type in _BLOCKED_ACTION_TYPES:
            return EventFamily.BLOCKED_ACTION
        if event_type in _TRADE_JOURNAL_TYPES:
            return EventFamily.TRADE_JOURNAL
        if event_type in _OVERRIDE_TYPES:
            return EventFamily.OVERRIDE
        # Default to EXECUTION_EVENT (covers all known execution events
        # and any unknown event types — graceful fallback)
        return EventFamily.EXECUTION_EVENT

    def _resolve_severity(self, event_type: str) -> Severity:
        """Resolve an event type to its severity level.

        Args:
            event_type: The orchestrator event type string.

        Returns:
            The corresponding ``Severity`` enum value.
        """
        if event_type in _SEVERE_EVENT_TYPES:
            return Severity.SEVERE
        if event_type in _CAUTION_EVENT_TYPES:
            return Severity.CAUTION
        return Severity.INFO

    def _build_payload(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a structured payload dict from the raw event data.

        Strips out fields that are already handled as top-level
        MemoryEvent fields (family, source, emitter, etc.) and
        preserves the rest as payload content.

        Args:
            event_type: The event type (included for context).
            data: The raw data dict from the orchestrator.

        Returns:
            A dict suitable for the MemoryEvent payload field.
        """
        # Fields that are promoted to MemoryEvent top-level
        payload = {
            k: v for k, v in data.items()
            if k not in _RESERVED_PAYLOAD_FIELDS
        }

        # Always include event_type for forward compatibility
        payload["event_type"] = event_type

        return payload
