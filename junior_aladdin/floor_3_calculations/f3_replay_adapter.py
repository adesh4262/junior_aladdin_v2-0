"""Floor 3 — Replay Adapter (Side C REPLAY_REF bridge).

Bridges Side C's REPLAY_REF store to Floor 3's ingress layer. When Floor 3
runs in REPLAY MODE (e.g., for debugging, auditing, or trade review), this
adapter retrieves replayed data from Side C's reference store, validates it
through the ReplayContract, and feeds it into f3_ingress for calculation
re-execution.

Architecture rules:
- Side C REPLAY_REF stores replay session METADATA (session_id, timerange,
  packet_count). The actual packet data is loaded separately.
- Two load modes:
  1. SIDE_C mode: Queries Side C reference_store for replay session refs,
     then loads actual packets directly (since the full Floor 2 → Side C →
     Floor 3 packet passthrough is not yet fully wired).
  2. DIRECT mode: Accepts a pre-built list of PacketEnvelope (tests,
     standalone usage).
- All packets pass through ReplayContract validation before ingress.
- Output goes through the FULL Floor 3 pipeline.

Replay flow:
    Side C REPLAY_REF  ─┐
                         ├──→ Floor3ReplayAdapter
    Direct PacketEnvelopes ─┘
         → ReplayContract validation
         → PacketEnvelope list
         → f3_ingress.consume_floor2_output(replay_mode=True)
         → f3_orchestrator.handle_calculation_cycle()
         → OutputContract
         → f3_validator.quick_validate()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import MarketPhase
from junior_aladdin.floor_3_calculations.f3_contracts import (
    OutputContract,
    ReplayContract,
)
from junior_aladdin.floor_3_calculations.f3_ingress import (
    consume_floor2_output,
)
from junior_aladdin.floor_3_calculations.f3_orchestrator import (
    handle_calculation_cycle,
)
from junior_aladdin.floor_3_calculations.f3_validator import quick_validate
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import PacketEnvelope

# ── Side C imports (optional — stubs gracefully if not available) ──────────
try:
    from junior_aladdin.side_c_memory.reference_store import lookup_by_key
    _SIDE_C_AVAILABLE = True
except ImportError:
    _SIDE_C_AVAILABLE = False

logger = get_logger("f3_replay_adapter")

ADAPTER_VERSION = "1.0"


# =============================================================================
# REPLAY LOAD RESULT
# =============================================================================


@dataclass
class ReplayLoadResult:
    """Result of loading replay data via the adapter.

    Fields:
        packets: List of validated PacketEnvelope ready for ingress.
        replay_session_id: Optional replay session ID from Side C (if loaded
            via SIDE_C mode).
        replay_ref: The raw MemoryEnvelope from Side C's REPLAY_REF store
            (if loaded via SIDE_C mode).
        replay_range_start: Start of the replayed time range (ISO string).
        replay_range_end: End of the replayed time range (ISO string).
        source: Original data source (if available from REPLAY_REF).
        packet_count: Number of packets in the replayed range.
        accepted_count: Number of packets validated successfully.
        rejected_count: Number of packets rejected during validation.
        validation_errors: List of validation error dicts from ReplayContract.
        load_mode: How the data was loaded (``"SIDE_C"`` or ``"DIRECT"``).
    """
    packets: list[PacketEnvelope] = field(default_factory=list)
    replay_session_id: str = ""
    replay_ref: Any = None
    replay_range_start: str = ""
    replay_range_end: str = ""
    source: str = ""
    packet_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    validation_errors: list[dict[str, Any]] = field(default_factory=list)
    load_mode: str = "DIRECT"

    @property
    def success(self) -> bool:
        """Whether the load was successful (no validation rejections)."""
        return self.rejected_count == 0 and bool(self.packets)

    @property
    def summary(self) -> dict[str, Any]:
        """Return a compact summary dict for logging/reporting."""
        return {
            "load_mode": self.load_mode,
            "packets": self.accepted_count,
            "rejected": self.rejected_count,
            "replay_session_id": self.replay_session_id or None,
            "range": (
                f"{self.replay_range_start} → {self.replay_range_end}"
                if self.replay_range_start and self.replay_range_end
                else None
            ),
            "success": self.success,
        }


# =============================================================================
# FLOOR 3 REPLAY ADAPTER
# =============================================================================


class Floor3ReplayAdapter:
    """Bridge between Side C's REPLAY_REF store and Floor 3 ingress.

    Two load modes:

    **SIDE_C mode** (``load_from_replay_ref``):
        Queries Side C's reference_store for REPLAY_REF entries by
        ref_key (e.g., ``"trade_id:T123"``). Retrieves replay session
        metadata (session_id, timerange, packet_count). Actual packet
        data is loaded via ``load_direct()`` since the full packet
        passthrough pipeline is not yet wired.

    **DIRECT mode** (``load_direct``):
        Accepts a pre-built list of PacketEnvelope objects directly.
        Used for tests, standalone scripts, and as the fallback after
        resolving packet data via Side C metadata.

    Args:
        replay_mode: Whether ingress should run in replay mode (skips
            timestamp age checks). Default ``True``.
    """

    def __init__(self, replay_mode: bool = True) -> None:
        self._replay_mode = replay_mode
        self._contract = ReplayContract(replay_mode=replay_mode)
        logger.info(
            "Floor3ReplayAdapter initialised",
            extra={
                "replay_mode": replay_mode,
                "side_c_available": _SIDE_C_AVAILABLE,
                "version": ADAPTER_VERSION,
            },
        )

    # ── SIDE_C Mode ─────────────────────────────────────────────────────

    def load_from_replay_ref(
        self,
        ref_key: str,
    ) -> ReplayLoadResult:
        """Load replay data from Side C's REPLAY_REF store by ref_key.

        Queries the reference store for REPLAY_REF entries matching the
        given ref_key (e.g., ``"trade_id:T123"`` or
        ``"decision_id:D456"``). Returns the replay session metadata and
        validates through ReplayContract.

        The actual packet data is loaded via ``load_direct()`` using the
        metadata from the reference.

        Args:
            ref_key: Reference key to look up (e.g., ``"trade_id:T123"``).

        Returns:
            A ``ReplayLoadResult`` with the validated replay data.
        """
        if not _SIDE_C_AVAILABLE:
            logger.warning(
                "Side C not available — cannot load from REPLAY_REF",
                extra={"ref_key": ref_key},
            )
            return ReplayLoadResult(
                rejected_count=1,
                validation_errors=[{
                    "field": "side_c",
                    "reason": "Side C module not available",
                    "severity": "REJECT",
                }],
                load_mode="SIDE_C",
            )

        # ── Step 1: Query Side C REPLAY_REF store ──────────────────────
        logger.info(
            "Loading replay data from Side C",
            extra={"ref_key": ref_key},
        )

        envelopes = lookup_by_key(ref_key)

        if not envelopes:
            logger.warning(
                "No REPLAY_REF entries found for ref_key",
                extra={"ref_key": ref_key},
            )
            return ReplayLoadResult(
                rejected_count=1,
                validation_errors=[{
                    "field": "ref_key",
                    "reason": f"No REPLAY_REF entries found for ref_key {ref_key!r}",
                    "severity": "REJECT",
                }],
                load_mode="SIDE_C",
            )

        # ── Step 2: Use the most recent REPLAY_REF envelope ─────────────
        latest = envelopes[-1]  # Most recent by timestamp
        refs = latest.refs or {}

        # NOTE: MemoryEnvelope.refs carries indexed metadata (ref_key).
        # The full payload (replay_session_id, timerange) is stored
        # separately behind payload_ref and is not directly accessible
        # from the envelope. This is a stub limitation — full replay
        # pipeline not yet wired.
        replay_session_id = _extract_str(refs, "replay_session_id", "")
        source = _extract_str(refs, "source", "floor_2")
        replay_range_start = ""
        replay_range_end = ""

        # ── Step 3: Determine packet count from metadata ───────────────
        # The actual packet data is not carried in Side C — only metadata.
        # The caller should provide packets via load_direct() after getting
        # the session context.

        result = ReplayLoadResult(
            replay_session_id=replay_session_id,
            replay_ref=latest,
            replay_range_start=replay_range_start,
            replay_range_end=replay_range_end,
            source=source,
            packet_count=0,
            accepted_count=0,
            rejected_count=0,
            load_mode="SIDE_C",
        )

        logger.info(
            "Replay reference loaded from Side C",
            extra={
                "ref_key": ref_key,
                "replay_session_id": replay_session_id,
                "source": source,
            },
        )

        return result

    def load_from_session_id(
        self,
        session_id: str,
    ) -> ReplayLoadResult:
        """Load replay data from Side C by a specific replay session ID.

        Queries the reference store for REPLAY_REF entries matching the
        given session_id (looked up via ref_key ``"replay_session_id:<id>"``).

        Args:
            session_id: The replay session ID to look up.

        Returns:
            A ``ReplayLoadResult`` with the validated replay metadata.
        """
        return self.load_from_replay_ref(f"replay_session_id:{session_id}")

    # ── DIRECT Mode ────────────────────────────────────────────────────

    def load_direct(
        self,
        packets: list[PacketEnvelope],
    ) -> ReplayLoadResult:
        """Load replay data directly from a list of PacketEnvelope.

        Validates every packet against the ReplayContract. Valid packets
        are passed through; invalid packets are logged and rejected.

        This is the primary method for loading actual packet data. The
        SIDE_C load methods provide session context but the actual packet
        data must be provided here.

        Args:
            packets: List of PacketEnvelope to validate and load.

        Returns:
            A ``ReplayLoadResult`` with validated packets and rejection stats.
        """
        if not packets:
            return ReplayLoadResult(load_mode="DIRECT")

        all_errors: list[dict[str, Any]] = []
        valid_packets: list[PacketEnvelope] = []

        for packet in packets:
            errors = self._contract.validate_replay_packet(packet)
            if errors:
                for err in errors:
                    err["packet_id"] = packet.packet_id
                all_errors.extend(errors)
                logger.warning(
                    "Replay packet rejected",
                    extra={
                        "packet_id": packet.packet_id,
                        "errors": errors,
                    },
                )
            else:
                valid_packets.append(packet)

        return ReplayLoadResult(
            packets=valid_packets,
            accepted_count=len(valid_packets),
            rejected_count=len(all_errors),
            validation_errors=all_errors,
            packet_count=len(valid_packets),
            load_mode="DIRECT",
        )

    # ── Convenience ────────────────────────────────────────────────────

    @property
    def replay_mode(self) -> bool:
        """Whether this adapter is in replay mode."""
        return self._replay_mode


# =============================================================================
# CONVENIENCE — run_replay_cycle
# =============================================================================


@dataclass
class ReplayCycleResult:
    """Complete result of a replay calculation cycle.

    Captures every stage: load → validate → ingress → orchestrate →
    output → validate.

    Fields:
        load_result: Result from the adapter load phase.
        ingress_result: Result from f3_ingress.consume_floor2_output.
        output_contract: OutputContract from f3_orchestrator.
        validation_result: ValidationResult from f3_validator.
        load_mode: Which adapter load mode was used.
        duration_ms: Total wall-clock duration of the cycle.
    """
    load_result: ReplayLoadResult | None = None
    ingress_result: Any = None
    output_contract: OutputContract | None = None
    validation_result: Any = None
    load_mode: str = "DIRECT"
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        """Whether the entire cycle succeeded end-to-end."""
        if self.output_contract is None:
            return False
        # quick_validate() returns bool (True = passed, False = HALT errors)
        if self.validation_result is not None:
            return bool(self.validation_result)
        return True

    @property
    def summary(self) -> dict[str, Any]:
        """Return a compact summary dict for logging/reporting."""
        oc = self.output_contract
        return {
            "load_mode": self.load_mode,
            "signals": len(oc.signals) if oc else 0,
            "engine_reports": len(oc.engine_reports) if oc else 0,
            "has_summary": oc.floor_summary is not None if oc else False,
            "validation_passed": (
                bool(self.validation_result)
                if self.validation_result is not None
                else None
            ),
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
        }


def run_replay_cycle(
    packets_or_ref_key: list[PacketEnvelope] | str,
    market_phase: MarketPhase = MarketPhase.OPEN,
    config: F3Config | None = None,
    symbol: str = "NIFTY",
) -> ReplayCycleResult:
    """Run a complete replay calculation cycle end-to-end.

    Convenience function that:
    1. Loads replay data (DIRECT if list, SIDE_C if string ref_key).
    2. Validates packets through ReplayContract.
    3. Feeds into f3_ingress (replay_mode=True).
    4. Runs f3_orchestrator on each accepted CalculationInput.
    5. Validates the OutputContract through f3_validator.

    Args:
        packets_or_ref_key: Either:
            - A ``list[PacketEnvelope]`` for DIRECT mode.
            - A ``str`` ref_key (e.g., ``"trade_id:T123"``) for SIDE_C mode.
        market_phase: Market phase to use for all inputs.
        config: Optional F3Config. Uses defaults if None.
        symbol: Trading symbol (default ``"NIFTY"``).

    Returns:
        A ``ReplayCycleResult`` capturing all stages of the cycle.
    """
    import time

    cycle_start = time.time()
    cfg = config or F3Config()
    adapter = Floor3ReplayAdapter(replay_mode=True)

    # ── Step 1: Load ───────────────────────────────────────────────────
    if isinstance(packets_or_ref_key, str):
        # SIDE_C mode — load ref, then expect caller to provide packets
        load_result = adapter.load_from_replay_ref(packets_or_ref_key)
        logger.info(
            "Replay cycle: loaded Side C reference",
            extra=load_result.summary,
        )
        # SIDE_C mode only loads metadata (no packet data).
        # To run a full calculation cycle, first call load_direct() with
        # the actual PacketEnvelope data, then call run_replay_cycle()
        # again with the packet list (DIRECT mode).
        if not load_result.success:
            logger.warning(
                "Replay cycle: Side C ref not found",
                extra={"ref_key": packets_or_ref_key},
            )
        else:
            logger.info(
                "Replay cycle: Side C ref loaded — call load_direct() "
                "with packet data to run calculations",
                extra={"ref_key": packets_or_ref_key},
            )
        return ReplayCycleResult(
            load_result=load_result,
            load_mode="SIDE_C",
            duration_ms=(time.time() - cycle_start) * 1000,
        )
    else:
        # DIRECT mode
        load_result = adapter.load_direct(packets_or_ref_key)
        load_mode = "DIRECT"

    if not load_result.success:
        logger.warning(
            "Replay cycle: load failed",
            extra=load_result.summary,
        )
        return ReplayCycleResult(
            load_result=load_result,
            load_mode=load_mode,
            duration_ms=(time.time() - cycle_start) * 1000,
        )

    # ── Step 2: Ingress ────────────────────────────────────────────────
    ingress_result = consume_floor2_output(
        packets=load_result.packets,
        replay_mode=True,
    )

    if ingress_result.rejected_count > 0:
        logger.warning(
            "Replay cycle: some packets rejected at ingress",
            extra={
                "accepted": len(ingress_result.accepted),
                "rejected": ingress_result.rejected_count,
            },
        )

    if not ingress_result.accepted:
        logger.warning("Replay cycle: no packets accepted at ingress")
        return ReplayCycleResult(
            load_result=load_result,
            ingress_result=ingress_result,
            load_mode=load_mode,
            duration_ms=(time.time() - cycle_start) * 1000,
        )

    # ── Step 3: Orchestrate + Output + Validate ────────────────────────
    # Run the orchestrator on the FIRST accepted input only.
    # Bulk replays with multiple inputs should iterate manually.
    calc_input = ingress_result.accepted[0]
    output_contract = handle_calculation_cycle(calc_input, cfg)

    if len(ingress_result.accepted) > 1:
        logger.info(
            "Replay cycle processed first input only",
            extra={
                "total_accepted": len(ingress_result.accepted),
                "processed": 1,
            },
        )

    # ── Step 4: Validate ───────────────────────────────────────────────
    # quick_validate() returns bool (True = passed, False = HALT errors)
    validation_passed = quick_validate(output_contract)

    cycle_duration = (time.time() - cycle_start) * 1000

    logger.info(
        "Replay cycle complete",
        extra={
            "signals": len(output_contract.signals),
            "engines": len(output_contract.engine_reports),
            "validation_passed": validation_passed,
            "duration_ms": round(cycle_duration, 2),
        },
    )

    return ReplayCycleResult(
        load_result=load_result,
        ingress_result=ingress_result,
        output_contract=output_contract,
        validation_result=validation_passed,
        load_mode=load_mode,
        duration_ms=cycle_duration,
    )


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _extract_str(
    data: dict[str, Any],
    key: str,
    default: str = "",
) -> str:
    """Extract a string value from a dict, with safe fallback.

    Args:
        data: The source dict.
        key: The key to extract.
        default: Fallback value if key is missing or not a string.

    Returns:
        The string value, or default.
    """
    value = data.get(key, default)
    if isinstance(value, str):
        return value
    if value is not None:
        return str(value)
    return default
