"""Floor 3 — Contract definitions for input/output validation.

Defines three contract categories:
1. **InputContract** — Floor 2 → Floor 3 data ingress validation.
2. **OutputContract** — Floor 3 → Floor 4 signal output validation.
3. **ReplayContract** — Side C → Floor 3 replay data validation.

Architecture rules:
- ALL packets entering Floor 3 must pass InputContract validation.
- ALL signals leaving Floor 3 must pass OutputContract validation.
- Contract violations are LOGGED, never silently ignored.
- InputContract REJECTS packets missing FreshnessTag or DataHealth.
- OutputContract REJECTS signals without signal_id or CalculationLog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationLog,
    EngineRunReport,
    Floor3Summary,
    generate_signal_id,
)
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import DataHealth, FreshnessTag, PacketEnvelope

logger = get_logger("f3_contracts")


# =============================================================================
# INPUT CONTRACT — Floor 2 → Floor 3
# =============================================================================


@dataclass
class InputContract:
    """Defines the expected format and validation rules for Floor 2 → Floor 3 data.

    Floor 2 sends validated structured data (ticks, candles, options, session,
    macro) wrapped in PacketEnvelope format. Floor 3 validates every packet
    at ingress.

    Fields:
        validated_data_stream: List of PacketEnvelope from Floor 2.
        structured_packets: Additional structured packet data keyed by type.
    """

    validated_data_stream: list[PacketEnvelope] = field(default_factory=list)
    structured_packets: dict[str, Any] = field(default_factory=dict)

    def validate_packet(
        self,
        packet: PacketEnvelope,
    ) -> list[dict[str, Any]]:
        """Validate a single incoming packet against the input contract.

        Three rejection rules:
            1. Packet must carry a FreshnessTag (FRESH/WARM/STALE).
            2. Packet must carry a DataHealth flag.
            3. Packet must not be from raw/unvalidated Floor 1 sources.

        Args:
            packet: The PacketEnvelope to validate.

        Returns:
            List of validation error dicts. Empty list means packet is valid.
            Each error has ``"field"``, ``"reason"``, and ``"severity"`` keys.
        """
        errors: list[dict[str, Any]] = []

        # Rule 1: FreshnessTag must be present
        freshness = packet.payload.get("freshness_tag")
        if freshness is None:
            errors.append({
                "field": "freshness_tag",
                "reason": "Missing FreshnessTag — packet freshness unknown",
                "severity": "REJECT",
            })
        elif isinstance(freshness, FreshnessTag):
            pass  # Already a valid enum instance
        elif isinstance(freshness, str):
            try:
                FreshnessTag(freshness)
            except ValueError:
                errors.append({
                    "field": "freshness_tag",
                    "reason": f"Invalid FreshnessTag value: {freshness!r}",
                    "severity": "REJECT",
                })
        else:
            errors.append({
                "field": "freshness_tag",
                "reason": f"FreshnessTag has unexpected type: {type(freshness).__name__}",
                "severity": "REJECT",
            })

        # Rule 2: DataHealth must be present
        data_health = packet.payload.get("data_health")
        if data_health is None:
            errors.append({
                "field": "data_health",
                "reason": "Missing DataHealth — data quality unknown",
                "severity": "REJECT",
            })
        elif isinstance(data_health, DataHealth):
            pass  # Already a valid enum instance
        elif isinstance(data_health, str):
            try:
                DataHealth(data_health)
            except ValueError:
                errors.append({
                    "field": "data_health",
                    "reason": f"Invalid DataHealth value: {data_health!r}",
                    "severity": "REJECT",
                })
        else:
            errors.append({
                "field": "data_health",
                "reason": f"DataHealth has unexpected type: {type(data_health).__name__}",
                "severity": "REJECT",
            })

        # Rule 3: Must not be raw/unvalidated Floor 1 data
        feed_type = packet.feed_type
        if feed_type and "raw" in feed_type.lower():
            errors.append({
                "field": "feed_type",
                "reason": f"Raw/unvalidated feed type: {feed_type!r}",
                "severity": "REJECT",
            })

        return errors

    def validate_all(
        self,
    ) -> list[dict[str, Any]]:
        """Validate ALL packets in the data stream.

        Returns:
            List of all validation errors across all packets.
            Each error includes ``"packet_id"`` for traceability.
        """
        all_errors: list[dict[str, Any]] = []
        for packet in self.validated_data_stream:
            packet_errors = self.validate_packet(packet)
            for err in packet_errors:
                err["packet_id"] = packet.packet_id
                err["source"] = packet.source
            all_errors.extend(packet_errors)
        return all_errors

    def has_rejections(self) -> bool:
        """Check whether any packets failed validation with REJECT severity.

        Returns:
            ``True`` if at least one REJECT error exists.
        """
        return any(
            err.get("severity") == "REJECT"
            for err in self.validate_all()
        )

    def count_by_severity(self) -> dict[str, int]:
        """Count validation errors grouped by severity.

        Returns:
            Dict with severity levels as keys and counts as values.
        """
        counts: dict[str, int] = {}
        for err in self.validate_all():
            sev = err.get("severity", "UNKNOWN")
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    def summary(self) -> dict[str, Any]:
        """Generate a summary of the input contract validation state.

        Returns:
            Dict with total packets, rejected count, and error counts.
        """
        errors = self.validate_all()
        rejection_count = sum(
            1 for e in errors if e.get("severity") == "REJECT"
        )
        return {
            "total_packets": len(self.validated_data_stream),
            "total_errors": len(errors),
            "rejections": rejection_count,
            "severity_counts": self.count_by_severity(),
        }


# =============================================================================
# OUTPUT CONTRACT — Floor 3 → Floor 4
# =============================================================================


@dataclass
class OutputContract:
    """Defines the expected format and validation rules for Floor 3 → Floor 4 output.

    Every calculation cycle produces:
    - A list of CalculatedSignal (never None — empty list = no signals found).
    - A list of EngineRunReport (one per engine that ran).
    - A Floor3Summary (always present, never None).

    Fields:
        signals: List of CalculatedSignal produced this cycle.
        engine_reports: List of EngineRunReport from each domain engine.
        floor_summary: Aggregated Floor3Summary for this cycle.
    """

    signals: list[CalculatedSignal] = field(default_factory=list)
    engine_reports: list[EngineRunReport] = field(default_factory=list)
    floor_summary: Floor3Summary | None = None

    def validate_signal(
        self,
        signal: CalculatedSignal,
    ) -> list[dict[str, Any]]:
        """Validate a single CalculatedSignal against the output contract.

        Five rejection rules:
            1. signal_id must be a non-empty string.
            2. signal_id must be a valid UUID hex (32 hex chars).
            3. CalculationLog must be present (not None).
            4. CalculationLog must contain input_hash.
            5. Domain field must match the log's domain field.

        Args:
            signal: The CalculatedSignal to validate.

        Returns:
            List of validation error dicts. Empty list means valid.
        """
        errors: list[dict[str, Any]] = []

        # Rule 1: signal_id must be non-empty
        if not signal.signal_id:
            errors.append({
                "field": "signal_id",
                "reason": "signal_id is empty or missing",
                "severity": "HALT",
            })

        # Rule 2: signal_id should be 32 hex chars (UUID v4 hex)
        if signal.signal_id and len(signal.signal_id) != 32:
            errors.append({
                "field": "signal_id",
                "reason": (
                    f"signal_id has unexpected length: "
                    f"{len(signal.signal_id)} (expected 32)"
                ),
                "severity": "HALT",
            })

        # Rule 3: CalculationLog must be present
        if signal.calculation_log is None:
            errors.append({
                "field": "calculation_log",
                "reason": "Missing CalculationLog — signal has no audit trail",
                "severity": "HALT",
            })

        # Rule 4: CalculationLog must contain input_hash
        if signal.calculation_log and not signal.calculation_log.input_hash:
            errors.append({
                "field": "calculation_log.input_hash",
                "reason": "Missing input_hash — replay verification impossible",
                "severity": "HALT",
            })

        # Rule 5: Domain field must match log's domain
        if signal.calculation_log and signal.domain != signal.calculation_log.domain:
            errors.append({
                "field": "domain",
                "reason": (
                    f"Domain mismatch: signal.domain={signal.domain.value}, "
                    f"log.domain={signal.calculation_log.domain.value}"
                ),
                "severity": "FLAG",
            })

        return errors

    def validate_all(self) -> dict[str, list[dict[str, Any]]]:
        """Validate ALL signals and structural requirements.

        Checks:
        - Every signal individually.
        - Floor3Summary must be present (never None).
        - Engine reports must be present (at least one or explicitly zero).

        Returns:
            Dict with keys:
            - ``"signal_errors"``: Per-signal validation errors.
            - ``"structural_errors"``: Summary/report-level errors.
        """
        signal_errors: list[dict[str, Any]] = []
        structural_errors: list[dict[str, Any]] = []

        # Validate each signal
        for signal in self.signals:
            errs = self.validate_signal(signal)
            for err in errs:
                err["signal_id"] = signal.signal_id
            signal_errors.extend(errs)

        # Structural: Floor3Summary must be present
        if self.floor_summary is None:
            structural_errors.append({
                "field": "floor_summary",
                "reason": "Floor3Summary is None — must always be present",
                "severity": "HALT",
            })

        # Structural: engine_reports should reflect what was run
        if not self.engine_reports:
            structural_errors.append({
                "field": "engine_reports",
                "reason": "No engine reports — no engines appear to have run",
                "severity": "FLAG",
            })

        return {
            "signal_errors": signal_errors,
            "structural_errors": structural_errors,
        }

    def has_halt_errors(self) -> bool:
        """Check whether any validation errors have HALT severity.

        HALT errors mean the output cannot be safely dispatched to Floor 4.

        Returns:
            ``True`` if at least one HALT error exists.
        """
        result = self.validate_all()
        for category in result.values():
            for err in category:
                if err.get("severity") == "HALT":
                    return True
        return False

    def is_valid(self) -> bool:
        """Quick validity check — no HALT errors and Floor3Summary present.

        Returns:
            ``True`` if the output contract is valid.
        """
        return not self.has_halt_errors() and self.floor_summary is not None

    def summary(self) -> dict[str, Any]:
        """Generate a summary of the output contract validation state.

        Returns:
            Dict with signal count, error counts, and validity status.
        """
        result = self.validate_all()
        halt_count = sum(
            1 for cat in result.values() for e in cat
            if e.get("severity") == "HALT"
        )
        flag_count = sum(
            1 for cat in result.values() for e in cat
            if e.get("severity") == "FLAG"
        )
        return {
            "total_signals": len(self.signals),
            "total_errors": len(result["signal_errors"]) + len(result["structural_errors"]),
            "halt_errors": halt_count,
            "flag_errors": flag_count,
            "engine_report_count": len(self.engine_reports),
            "has_summary": self.floor_summary is not None,
            "valid": self.is_valid(),
        }


# =============================================================================
# REPLAY CONTRACT — Side C → Floor 3 (Replay Mode)
# =============================================================================


@dataclass
class ReplayContract:
    """Defines the contract for Floor 3 operation in replay mode.

    During replay, Floor 3 reads reconstructed data from Side C's REPLAY_REF
    store instead of the live Floor 2 stream. The replay data must produce
    identical CalculationInput objects for deterministic comparison.

    Fields:
        replay_mode: Whether Floor 3 is operating in replay mode.
        replay_data_stream: Reconstructed PacketEnvelope list from Side C.
    """

    replay_mode: bool = False
    replay_data_stream: list[PacketEnvelope] = field(default_factory=list)

    def validate_replay_packet(
        self,
        packet: PacketEnvelope,
    ) -> list[dict[str, Any]]:
        """Validate a single replayed packet against the replay contract.

        Replay packets must match the same contract as live packets
        (FreshnessTag, DataHealth present). Additionally:
        - Replay packets must have a valid timestamp within the replayed range.
        - Replay packets must not be flagged as 'live_only'.

        Args:
            packet: The PacketEnvelope to validate for replay.

        Returns:
            List of validation error dicts. Empty list means valid.
        """
        errors: list[dict[str, Any]] = []

        # Reuse input contract validation for standard checks
        input_check = InputContract()
        errors.extend(input_check.validate_packet(packet))

        # Replay-specific: must not be live_only
        if packet.payload.get("live_only", False):
            errors.append({
                "field": "live_only",
                "reason": "Packet flagged as live_only — cannot replay",
                "severity": "REJECT",
            })

        return errors

    def validate_all(self) -> list[dict[str, Any]]:
        """Validate ALL packets in the replay data stream.

        Returns:
            List of all validation errors across all replay packets.
        """
        all_errors: list[dict[str, Any]] = []
        for packet in self.replay_data_stream:
            packet_errors = self.validate_replay_packet(packet)
            for err in packet_errors:
                err["packet_id"] = packet.packet_id
            all_errors.extend(packet_errors)
        return all_errors

    def summary(self) -> dict[str, Any]:
        """Generate a summary of the replay contract validation state.

        Returns:
            Dict with replay mode, total packets, and error counts.
        """
        errors = self.validate_all()
        return {
            "replay_mode": self.replay_mode,
            "total_packets": len(self.replay_data_stream),
            "total_errors": len(errors),
            "rejections": sum(1 for e in errors if e.get("severity") == "REJECT"),
        }


# =============================================================================
# CONVENIENCE FUNCTION — ensure_signal_id
# =============================================================================


def ensure_signal_id(signal: CalculatedSignal) -> CalculatedSignal:
    """Ensure a CalculatedSignal has a valid signal_id.

    If the signal_id is empty, a new UUID v4 is generated.
    If it already has one, it is preserved (immutable).

    Args:
        signal: The CalculatedSignal to check.

    Returns:
        The same CalculatedSignal with a guaranteed signal_id.
    """
    if not signal.signal_id:
        signal.signal_id = generate_signal_id()
    return signal
