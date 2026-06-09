"""Floor 2 Output — Floor 3 handoff builder.

Provides the **Floor3HandoffBuilder** class that assembles the complete
Floor 2 → Floor 3 handoff payload with ALL 7 mandatory output categories.

7 Output Categories:
1. ``validated_tick_stream`` — Structured tick stream from ``StructuredWriter``.
2. ``validated_candle_streams`` — 1m OHLCV candles from ``StructuredWriter``.
3. ``options_snapshots`` — OI snapshots from ``StructuredWriter``.
4. ``session_packets`` — Session context packets from ``SessionStreamRouter``.
5. ``macro_support_packets`` — Structured macro/context feeds from ``StructuredWriter``.
6. ``metadata_side_channel`` — Quality facts, traceability, review signal
   from ``MetadataSidechannelBuilder``.
7. ``computed_ready_hooks`` — Stable computation staging interfaces.

Architecture rules:
- ALL 7 categories must be present in every handoff.
- Missing mandatory category → ``ContractViolationError``.
- No intelligence/opinion in any output field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    CandleStream,
    ComputedReadyHook,
    Floor3Handoff,
    MacroSupportStream,
    OptionsSnapshotStream,
    SessionPacket,
    TickStream,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType
from junior_aladdin.floor_2_datacenter.governance.runtime_contract_checks import (
    RuntimeContractChecks,
)
from junior_aladdin.floor_2_datacenter.output.metadata_sidechannel_builder import (
    MetadataSidechannelBuilder,
)
from junior_aladdin.floor_2_datacenter.output.session_stream_router import (
    SessionStreamRouter,
)
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)
from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.logging import get_logger

logger = get_logger("floor3_handoff_builder")

# Default computed-ready hooks for Floor 3 computation staging
_DEFAULT_COMPUTED_HOOKS: list[ComputedReadyHook] = [
    ComputedReadyHook(
        hook_name="tick_to_candle",
        version="1.0",
        input_schema={"ticks": "list[ValidatedTick]", "timeframe": "str"},
        output_format="CandleStream",
        description="Aggregate validated ticks into 1m OHLCV candles",
    ),
    ComputedReadyHook(
        hook_name="candle_to_higher_tf",
        version="1.0",
        input_schema={"candles": "list[Candle]", "target_timeframe": "str"},
        output_format="list[Candle]",
        description="Build higher timeframe candles from 1m foundation",
    ),
    ComputedReadyHook(
        hook_name="options_snapshot_analysis",
        version="1.0",
        input_schema={"snapshots": "list[OptionsSnapshot]"},
        output_format="dict",
        description="Analyze OI changes, IV trends across snapshots",
    ),
]


class Floor3HandoffBuilder:
    """Assembles the complete Floor 3 handoff payload.

    Builds all 7 mandatory categories from structured data, metadata,
    and session context.

    Typical usage::

        builder = Floor3HandoffBuilder(
            structured_writer=writer,
            sidechannel_builder=metadata_builder,
            session_router=session_router,
            contract_checks=runtime_checks,
        )

        handoff = builder.build_handoff(source=\"angel_one\")
    """

    def __init__(
        self,
        structured_writer: StructuredWriter,
        sidechannel_builder: MetadataSidechannelBuilder,
        session_router: SessionStreamRouter,
        contract_checks: RuntimeContractChecks | None = None,
        computed_hooks: list[ComputedReadyHook] | None = None,
    ) -> None:
        """Initialise the handoff builder.

        Args:
            structured_writer: The structured writer for categories 1-5.
            sidechannel_builder: The metadata side-channel builder for
                category 6.
            session_router: The session stream router for category 4.
            contract_checks: Optional runtime contract checks for
                post-build enforcement.
            computed_hooks: Optional list of ``ComputedReadyHook``
                instances. Defaults to standard hooks if not provided.
        """
        self._structured_writer = structured_writer
        self._sidechannel_builder = sidechannel_builder
        self._session_router = session_router
        self._contract_checks = contract_checks
        self._computed_hooks = computed_hooks or _DEFAULT_COMPUTED_HOOKS

    # ------------------------------------------------------------------
    # Main Build API
    # ------------------------------------------------------------------

    def build_handoff(
        self,
        source: str | None = None,
        enforce: bool = True,
        now: datetime | None = None,
    ) -> Floor3Handoff:
        """Build the complete Floor 3 handoff with all 7 categories.

        Args:
            source: Optional source scope for metadata side-channel.
            enforce: If ``True`` (default), enforce contract compliance
                after building (raises on missing categories).
            now: Current timestamp for session detection.

        Returns:
            A fully populated ``Floor3Handoff`` with all 7 categories.

        Raises:
            ContractViolationError: If ``enforce=True`` and any mandatory
                category is missing or has critical issues.
        """
        now = now or datetime.now(timezone.utc)

        # Build category 1: Validated Tick Stream
        tick_stream = self._build_tick_stream()

        # Build category 2: Validated Candle Streams
        candle_stream = self._build_candle_streams()

        # Build category 3: Options Snapshots
        options_snapshots = self._build_options_snapshots()

        # Build category 4: Session Packets
        session_packets = self._session_router.route_for_handoff(now)

        # Build category 5: Macro Support Packets
        macro_support = self._build_macro_support()

        # Build category 6: Metadata Side-Channel
        metadata_side_channel = self._sidechannel_builder.build_sidechannel(
            source=source,
        )

        # Build category 7: Computed-Ready Hooks
        computed_hooks = list(self._computed_hooks)

        handoff = Floor3Handoff(
            validated_tick_stream=tick_stream,
            validated_candle_streams=candle_stream,
            options_snapshots=options_snapshots,
            session_packets=session_packets,
            macro_support_packets=macro_support,
            metadata_side_channel=metadata_side_channel,
            computed_ready_hooks=computed_hooks,
        )

        # Enforce contract compliance if requested
        if enforce and self._contract_checks is not None:
            self._contract_checks.enforce_floor3_handoff(handoff)
            logger.info(
                "Floor 3 handoff built and enforced",
                extra={
                    "source": source,
                    "tick_count": tick_stream.tick_count,
                    "candle_count": len(candle_stream.candles),
                    "session_count": len(session_packets),
                    "hook_count": len(computed_hooks),
                },
            )
        else:
            logger.info(
                "Floor 3 handoff built",
                extra={"source": source},
            )

        return handoff

    def build_handoff_with_check(
        self,
        source: str | None = None,
        now: datetime | None = None,
    ) -> tuple[Floor3Handoff, list[dict[str, Any]]]:
        """Build the handoff and return it with issues (non-raising).

        Args:
            source: Optional source scope.
            now: Current timestamp for session detection.

        Returns:
            A tuple of ``(Floor3Handoff, issues_list)``.
        """
        handoff = self.build_handoff(source=source, enforce=False, now=now)
        issues = []
        if self._contract_checks is not None:
            issues = self._contract_checks.check_floor3_handoff(handoff)
        return handoff, issues

    # ------------------------------------------------------------------
    # Category Builders
    # ------------------------------------------------------------------

    def _build_tick_stream(self) -> TickStream:
        """Build category 1: Validated Tick Stream.

        Returns:
            A ``TickStream`` from the structured writer, or an empty
            ``TickStream`` if none available.
        """
        stream_data = self._structured_writer.get_stream_data(StreamType.TICK_STREAM)
        if stream_data is not None:
            if isinstance(stream_data, TickStream):
                return stream_data
            if isinstance(stream_data, dict):
                return TickStream(
                    stream_id=stream_data.get("stream_id", ""),
                    ticks=stream_data.get("ticks", []),
                    start_time=stream_data.get("start_time"),
                    end_time=stream_data.get("end_time"),
                    tick_count=stream_data.get("tick_count", 0),
                    gaps=stream_data.get("gaps", []),
                )
        return TickStream()

    def _build_candle_streams(self) -> CandleStream:
        """Build category 2: Validated Candle Streams (1m minimum).

        Returns:
            A ``CandleStream`` from the structured writer, or an empty
            ``CandleStream`` if none available.
        """
        stream_data = self._structured_writer.get_stream_data(StreamType.CANDLE_STREAM)
        if stream_data is not None:
            if isinstance(stream_data, CandleStream):
                return stream_data
            if isinstance(stream_data, dict):
                return CandleStream(
                    stream_id=stream_data.get("stream_id", ""),
                    candles=stream_data.get("candles", []),
                    source=stream_data.get("source", ""),
                    feed_type=stream_data.get("feed_type", ""),
                )
        return CandleStream()

    def _build_options_snapshots(self) -> OptionsSnapshotStream:
        """Build category 3: Options Snapshots.

        Returns:
            An ``OptionsSnapshotStream`` from the structured writer, or
            an empty one if none available.
        """
        stream_data = self._structured_writer.get_stream_data(StreamType.OPTIONS_SNAPSHOT)
        if stream_data is not None:
            if isinstance(stream_data, OptionsSnapshotStream):
                return stream_data
            if isinstance(stream_data, dict):
                return OptionsSnapshotStream(
                    stream_id=stream_data.get("stream_id", ""),
                    interval_minutes=stream_data.get("interval_minutes", 5),
                    snapshots=stream_data.get("snapshots", []),
                )
        return OptionsSnapshotStream()

    def _build_macro_support(self) -> list[MacroSupportStream]:
        """Build category 5: Macro Support Packets.

        Returns:
            A list of ``MacroSupportStream`` from the structured writer,
            or empty list if none available.
        """
        entries = self._structured_writer.get_by_type(StreamType.MACRO_SUPPORT)
        streams: list[MacroSupportStream] = []

        for entry in entries:
            stream_data = entry.get("stream_data")
            if stream_data is not None:
                if isinstance(stream_data, MacroSupportStream):
                    streams.append(stream_data)
                elif isinstance(stream_data, dict):
                    streams.append(MacroSupportStream(
                        stream_id=stream_data.get("stream_id", ""),
                        data_type=stream_data.get("data_type", ""),
                        packets=stream_data.get("packets", []),
                    ))

        return streams
