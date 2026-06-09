"""Floor 2 Governance — runtime contract checks.

Provides the **RuntimeContractChecks** class that enforces contract
compliance on data flowing through the Floor 2 pipeline at runtime.

Responsibilities:
- **Pipeline checks**: Validate data at each pipeline stage (ingress, raw,
  validation, cleaning, structuring, output).
- **Data dict checks**: Validate dicts against registered contracts.
- **Output enforcement**: Verify ALL 7 Floor 3 handoff categories are present.
- **Logging**: Log all violations, raise on critical mismatches.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.data_contract_registry import (
    DataContractRegistry,
)
from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    Floor3Handoff,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    FeedContract,
)
from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.logging import get_logger

logger = get_logger("runtime_contract_checks")


class RuntimeContractChecks:
    """Runtime enforcement of contract compliance.

    Validates data at each stage of the Floor 2 pipeline against registered
    contracts.

    Typical usage::

        registry = DataContractRegistry()
        checks = RuntimeContractChecks(registry)

        # Validate a packet at the raw stage
        errors = checks.check_raw_packet(packet_data)

        # Enforce Floor 3 handoff completeness
        checks.enforce_floor3_handoff(handoff)
    """

    def __init__(self, registry: DataContractRegistry) -> None:
        """Initialise with a contract registry.

        Args:
            registry: The ``DataContractRegistry`` to validate against.
        """
        self._registry = registry

    # ------------------------------------------------------------------
    # Stage-Specific Checks
    # ------------------------------------------------------------------

    def check_ingress_packet(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate an incoming Floor 1 packet against its feed contract.

        Args:
            packet: The incoming Floor 1 5-family payload.

        Returns:
            List of validation errors. Empty if valid.
        """
        errors: list[dict[str, Any]] = []

        # Check that feed_routing_identity is present
        routing_id = packet.get("feed_routing_identity", "")
        if not routing_id:
            errors.append({
                "stage": "ingress",
                "field": "feed_routing_identity",
                "message": "Missing feed routing identity",
            })

        # Determine feed type from envelope
        envelope = packet.get("minimal_source_envelope", {})
        feed_type = envelope.get("feed_type", "")
        if feed_type:
            contract_errors = self._registry.validate_data(feed_type, packet.get("original_raw_packet", {}))
            for err in contract_errors:
                err["stage"] = "ingress"
            errors.extend(contract_errors)

        return errors

    def check_raw_packet(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate a raw store record against its contract.

        Args:
            record: A record dict from a raw store.

        Returns:
            List of validation errors. Empty if valid.
        """
        errors: list[dict[str, Any]] = []
        feed_type = record.get("feed_type", "")

        if feed_type:
            # Validate the original raw packet data
            raw_data = record.get("original_raw_packet", {})
            contract_errors = self._registry.validate_data(feed_type, raw_data)
            for err in contract_errors:
                err["stage"] = "raw"
            errors.extend(contract_errors)

        # Check source is expected
        if feed_type and record.get("source"):
            if not self._registry.check_source(feed_type, record["source"]):
                errors.append({
                    "stage": "raw",
                    "field": "source",
                    "message": f"Source {record['source']!r} not expected for feed {feed_type!r}",
                })

        return errors

    def check_cleaned_packet(self, cleaned_entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate a cleaned record against its contract.

        Args:
            cleaned_entry: A cleaned record entry from ``CleanedLayerWriter``.

        Returns:
            List of validation errors. Empty if valid.
        """
        errors: list[dict[str, Any]] = []
        feed_type = cleaned_entry.get("feed_type", "")
        cleaned_data = cleaned_entry.get("cleaned_data", {})

        if feed_type and cleaned_data:
            contract_errors = self._registry.validate_data(feed_type, cleaned_data)
            for err in contract_errors:
                err["stage"] = "cleaned"
            errors.extend(contract_errors)

        return errors

    def check_structured_output(
        self,
        structure_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Validate a structured product against its contract.

        Args:
            structure_result: A structured product entry dict.

        Returns:
            List of validation errors. Empty if valid.
        """
        errors: list[dict[str, Any]] = []

        stream_type = structure_result.get("stream_type", "")
        metadata = structure_result.get("metadata", {})
        stream_data = structure_result.get("stream_data")

        # Check stream type is known
        if not stream_type:
            errors.append({
                "stage": "structured",
                "field": "stream_type",
                "message": "Missing stream type",
            })

        # Check stream data is present
        if stream_data is None:
            errors.append({
                "stage": "structured",
                "field": "stream_data",
                "message": f"Missing stream data for type {stream_type}",
            })

        # Check mandatory metadata fields
        for field in ["stream_id"]:
            if not metadata.get(field):
                errors.append({
                    "stage": "structured",
                    "field": f"metadata.{field}",
                    "message": f"Missing mandatory metadata field: {field}",
                })

        return errors

    # ------------------------------------------------------------------
    # Floor 3 Handoff Enforcement
    # ------------------------------------------------------------------

    def enforce_floor3_handoff(self, handoff: Floor3Handoff) -> None:
        """Enforce that a Floor 3 handoff has ALL 7 mandatory categories.

        Args:
            handoff: The ``Floor3Handoff`` to validate.

        Raises:
            ContractViolationError: If any mandatory category is missing
                or has critical issues.
        """
        missing: list[str] = []

        if not self._is_populated_tick_stream(handoff.validated_tick_stream):
            missing.append("validated_tick_stream")
        if not self._is_populated_candle_stream(handoff.validated_candle_streams):
            missing.append("validated_candle_streams")
        if not self._is_populated_options(handoff.options_snapshots):
            missing.append("options_snapshots")
        if not handoff.session_packets:
            missing.append("session_packets")
        if not handoff.macro_support_packets:
            missing.append("macro_support_packets")
        if not handoff.metadata_side_channel:
            missing.append("metadata_side_channel")
        if not handoff.computed_ready_hooks:
            missing.append("computed_ready_hooks")

        if missing:
            msg = f"Floor 3 handoff missing categories: {missing}"
            logger.critical(msg, extra={"missing_categories": missing})
            raise ContractViolationError(
                msg,
                details={
                    "contract_name": "Floor3Handoff",
                    "errors": [{"field": cat, "message": f"Missing mandatory category: {cat}"} for cat in missing],
                },
            )

    def check_floor3_handoff(self, handoff: Floor3Handoff) -> list[dict[str, Any]]:
        """Check a Floor 3 handoff for issues without raising.

        Args:
            handoff: The ``Floor3Handoff`` to check.

        Returns:
            List of issues found. Empty if all categories are present.
        """
        issues: list[dict[str, Any]] = []

        if not self._is_populated_tick_stream(handoff.validated_tick_stream):
            issues.append({"category": "validated_tick_stream", "message": "Empty or missing tick stream"})

        if not self._is_populated_candle_stream(handoff.validated_candle_streams):
            issues.append({"category": "validated_candle_streams", "message": "Empty or missing candle stream"})

        if not self._is_populated_options(handoff.options_snapshots):
            issues.append({"category": "options_snapshots", "message": "Empty or missing options snapshots"})

        if not handoff.session_packets:
            issues.append({"category": "session_packets", "message": "No session packets"})

        if not handoff.macro_support_packets:
            issues.append({"category": "macro_support_packets", "message": "No macro support packets"})

        if not handoff.metadata_side_channel:
            issues.append({"category": "metadata_side_channel", "message": "Empty metadata side-channel"})

        if not handoff.computed_ready_hooks:
            issues.append({"category": "computed_ready_hooks", "message": "No computed-ready hooks"})

        return issues

    @property
    def registry(self) -> DataContractRegistry:
        """Get the underlying registry instance."""
        return self._registry

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_populated_tick_stream(stream: Any) -> bool:
        """Check if a tick stream has data."""
        if stream is None:
            return False
        tick_count = getattr(stream, "tick_count", 0) or 0
        return tick_count > 0

    @staticmethod
    def _is_populated_candle_stream(stream: Any) -> bool:
        """Check if a candle stream has data."""
        if stream is None:
            return False
        candles = getattr(stream, "candles", None) or []
        return len(candles) > 0

    @staticmethod
    def _is_populated_options(snapshots: Any) -> bool:
        """Check if options snapshots have data."""
        if snapshots is None:
            return False
        snaps = getattr(snapshots, "snapshots", None) or []
        return len(snaps) > 0
