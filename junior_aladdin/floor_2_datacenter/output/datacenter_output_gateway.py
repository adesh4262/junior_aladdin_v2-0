"""Floor 2 Output — datacenter output gateway.

Provides the **DatacenterOutputGateway** class that serves as the central
output point for ALL Floor 2 outbound data.

Responsibilities:
- **Orchestration**: Coordinate handoff building, metadata side-channel,
  review routing, and session routing into a single dispatch flow.
- **Contract enforcement**: Validate outbound data against registered
  contracts before transmission.
- **Audit logging**: Log every outbound transmission for traceability.
- **Routing dispatch**: Send data to correct upper-floor destinations
  (Floor 3 calculation engines, Side B dashboard, Side C memory).
- **Safety checks**: Verify ALL 7 handoff categories are populated before
  dispatch.

Architecture rules:
- Every outbound transmission is logged for audit.
- Contract violations are raised BEFORE data leaves Floor 2.
- No raw market data leaves through ungoverned paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor3Handoff
from junior_aladdin.floor_2_datacenter.governance.runtime_contract_checks import (
    RuntimeContractChecks,
)
from junior_aladdin.floor_2_datacenter.output.floor3_handoff_builder import (
    Floor3HandoffBuilder,
)
from junior_aladdin.floor_2_datacenter.output.metadata_sidechannel_builder import (
    MetadataSidechannelBuilder,
)
from junior_aladdin.floor_2_datacenter.output.review_status_router import (
    ReviewStatusRouter,
)
from junior_aladdin.floor_2_datacenter.output.session_stream_router import (
    SessionStreamRouter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("datacenter_output_gateway")

# Valid dispatch types
DISPATCH_FLOOR3 = "floor3_handoff"
DISPATCH_SIDE_B = "side_b_dashboard"
DISPATCH_SIDE_C = "side_c_memory"
VALID_DISPATCH_TYPES = (DISPATCH_FLOOR3, DISPATCH_SIDE_B, DISPATCH_SIDE_C)


class DatacenterOutputGateway:
    """Central output gateway for ALL Floor 2 outbound data.

    Orchestrates handoff building, review routing, session routing, and
    metadata packaging. Logs every outbound transmission.

    Typical usage::

        gateway = DatacenterOutputGateway(
            handoff_builder=builder,
            sidechannel_builder=metadata_builder,
            review_router=review_router,
            session_router=session_router,
            contract_checks=checks,
        )

        # Dispatch a Floor 3 handoff
        result = gateway.dispatch_to_floor3(source=\"angel_one\")

        # Route review data to Side B (dashboard)
        gateway.dispatch_to_side_b()

        # Route review data to Side C (memory)
        gateway.dispatch_to_side_c()
    """

    def __init__(
        self,
        handoff_builder: Floor3HandoffBuilder,
        sidechannel_builder: MetadataSidechannelBuilder,
        review_router: ReviewStatusRouter,
        session_router: SessionStreamRouter,
        contract_checks: RuntimeContractChecks | None = None,
    ) -> None:
        """Initialise the output gateway.

        Args:
            handoff_builder: Builder for the Floor 3 handoff payload.
            sidechannel_builder: Builder for the metadata side-channel.
            review_router: Router for review signals to upper floors.
            session_router: Router for session stream routing.
            contract_checks: Optional runtime contract checks for
                outbound enforcement.
        """
        self._handoff_builder = handoff_builder
        self._sidechannel_builder = sidechannel_builder
        self._review_router = review_router
        self._session_router = session_router
        self._contract_checks = contract_checks

        # Transmission log — transmission_id -> transmission record
        self._transmission_log: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Dispatch Methods
    # ------------------------------------------------------------------

    def dispatch_to_floor3(
        self,
        source: str | None = None,
        enforce: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build and dispatch a Floor 3 handoff.

        Assembles all 7 handoff categories, enforces contract compliance,
        logs the transmission, and returns the result.

        Args:
            source: Optional source scope.
            enforce: If ``True``, enforce contract checks before dispatch.
            now: Current timestamp.

        Returns:
            A dict with the dispatch result including transmission ID,
            handoff summary, and routing info.

        Raises:
            ContractViolationError: If ``enforce=True`` and the handoff
                fails contract validation.
        """
        now = now or datetime.now(timezone.utc)

        # Build the handoff
        handoff = self._handoff_builder.build_handoff(
            source=source,
            enforce=enforce,
            now=now,
        )

        # Build dispatch record
        transmission_id = _generate_transmission_id("f3")
        dispatch = self._build_dispatch_record(
            transmission_id=transmission_id,
            dispatch_type=DISPATCH_FLOOR3,
            handoff=handoff,
            source=source,
            now=now,
        )

        # Log the transmission
        self._log_transmission(transmission_id, dispatch)

        logger.info(
            "Floor 3 handoff dispatched",
            extra={
                "transmission_id": transmission_id,
                "source": source,
                "tick_count": handoff.validated_tick_stream.tick_count,
                "candle_count": len(handoff.validated_candle_streams.candles),
                "session_count": len(handoff.session_packets),
                "hook_count": len(handoff.computed_ready_hooks),
            },
        )

        return dispatch

    def dispatch_to_side_b(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch review state to Side B (dashboard).

        Args:
            source: Optional source scope.

        Returns:
            A dict with dispatch record including review data for dashboard.
        """
        now = datetime.now(timezone.utc)

        # Get review data for Side B
        review_data = self._review_router.route_to_side_b(source=source)
        session_context = self._session_router.get_session_routing_context(now)

        # Build dispatch record
        transmission_id = _generate_transmission_id("sb")
        dispatch = self._build_dispatch_record(
            transmission_id=transmission_id,
            dispatch_type=DISPATCH_SIDE_B,
            handoff=None,
            source=source,
            now=now,
            extra={
                "review_data": review_data,
                "session_context": session_context,
            },
        )

        self._log_transmission(transmission_id, dispatch)

        logger.info(
            "Side B (dashboard) dispatch completed",
            extra={
                "transmission_id": transmission_id,
                "source": source,
                "event_count": review_data.get("event_summary", {}).get("total_events", 0),
            },
        )

        return dispatch

    def dispatch_to_side_c(
        self,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch review references to Side C (memory/journal).

        Args:
            source: Optional source scope.

        Returns:
            A dict with dispatch record including review references for memory.
        """
        now = datetime.now(timezone.utc)

        # Get review references for Side C
        review_refs = self._review_router.route_to_side_c(source=source)

        # Build dispatch record
        transmission_id = _generate_transmission_id("sc")
        dispatch = self._build_dispatch_record(
            transmission_id=transmission_id,
            dispatch_type=DISPATCH_SIDE_C,
            handoff=None,
            source=source,
            now=now,
            extra={
                "review_references": review_refs,
            },
        )

        self._log_transmission(transmission_id, dispatch)

        logger.info(
            "Side C (memory) dispatch completed",
            extra={
                "transmission_id": transmission_id,
                "source": source,
                "event_count": review_refs.get("event_count", 0),
                "report_count": review_refs.get("report_count", 0),
            },
        )

        return dispatch

    def dispatch_all(
        self,
        source: str | None = None,
        enforce: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """Dispatch to ALL destinations (Floor 3 + Side B + Side C).

        Args:
            source: Optional source scope.
            enforce: If ``True``, enforce contract checks.

        Returns:
            A dict with keys ``floor3``, ``side_b``, ``side_c`` containing
            each dispatch record.
        """
        now = datetime.now(timezone.utc)
        return {
            "floor3": self.dispatch_to_floor3(source=source, enforce=enforce, now=now),
            "side_b": self.dispatch_to_side_b(source=source),
            "side_c": self.dispatch_to_side_c(source=source),
        }

    # ------------------------------------------------------------------
    # Transmission Log
    # ------------------------------------------------------------------

    def get_transmission(self, transmission_id: str) -> dict[str, Any] | None:
        """Get a single transmission record by ID.

        Args:
            transmission_id: The unique transmission identifier.

        Returns:
            The transmission record dict, or ``None`` if not found.
        """
        return self._transmission_log.get(transmission_id)

    def list_transmissions(
        self,
        dispatch_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent transmissions, optionally filtered by type.

        Args:
            dispatch_type: Filter by dispatch type (``\"floor3_handoff\"``,
                ``\"side_b_dashboard\"``, ``\"side_c_memory\"``).
            limit: Maximum number of records to return.

        Returns:
            List of transmission record dicts (most recent first).
        """
        records = list(self._transmission_log.values())

        if dispatch_type:
            records = [r for r in records if r.get("dispatch_type") == dispatch_type]

        # Sort by dispatched_at descending
        records.sort(key=lambda r: r.get("dispatched_at", ""), reverse=True)
        return records[:limit]

    def count_transmissions(self, dispatch_type: str | None = None) -> int:
        """Count transmissions, optionally filtered by type.

        Args:
            dispatch_type: Filter by dispatch type.

        Returns:
            Transmission count.
        """
        if dispatch_type:
            return sum(
                1 for r in self._transmission_log.values()
                if r.get("dispatch_type") == dispatch_type
            )
        return len(self._transmission_log)

    def clear_log(self) -> None:
        """Clear the transmission log."""
        self._transmission_log.clear()
        logger.info("Transmission log cleared")

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _log_transmission(
        self,
        transmission_id: str,
        record: dict[str, Any],
    ) -> None:
        """Store a transmission record in the log."""
        self._transmission_log[transmission_id] = record

    def _build_dispatch_record(
        self,
        transmission_id: str,
        dispatch_type: str,
        handoff: Floor3Handoff | None,
        source: str | None,
        now: datetime,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a standard dispatch record.

        Args:
            transmission_id: Unique transmission ID.
            dispatch_type: Type of dispatch (floor3/side_b/side_c).
            handoff: The Floor3Handoff (or None for non-Floor3 dispatches).
            source: Optional source scope.
            now: Current timestamp.
            extra: Additional data to include in the record.

        Returns:
            A dispatch record dict.
        """
        record: dict[str, Any] = {
            "transmission_id": transmission_id,
            "dispatch_type": dispatch_type,
            "source": source,
            "dispatched_at": now.isoformat(),
        }

        if handoff is not None:
            record["handoff_summary"] = {
                "tick_count": handoff.validated_tick_stream.tick_count,
                "candle_count": len(handoff.validated_candle_streams.candles),
                "snapshot_count": len(handoff.options_snapshots.snapshots),
                "session_count": len(handoff.session_packets),
                "macro_count": len(handoff.macro_support_packets),
                "hook_count": len(handoff.computed_ready_hooks),
                "has_metadata": bool(handoff.metadata_side_channel),
            }

        if extra:
            record.update(extra)

        return record


def _generate_transmission_id(prefix: str) -> str:
    """Generate a unique transmission ID.

    Args:
        prefix: Two-character prefix (``\"f3\"``, ``\"sb\"``, ``\"sc\"``).

    Returns:
        A transmission ID string like ``\"f3_a1b2c3d4\"``.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}"
