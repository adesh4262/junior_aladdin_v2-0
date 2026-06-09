"""Floor 3 — Data Ingress from Floor 2.

Consumes validated structured data from Floor 2, validates every packet
against the InputContract, and converts valid packets into CalculationInput
objects for the domain engines.

Supports two modes:
- LIVE MODE: Reads data from Floor 2 output stream (PacketEnvelope list).
- REPLAY MODE: Reads data from Side C REPLAY_REF via f3_replay_adapter.

Architecture rules:
- ALL packets must pass InputContract validation before entering Floor 3.
- Rejected packets are LOGGED with specific rejection reason.
- Only validated packets are converted to CalculationInput.
- replay_mode flag propagates to engines for time-dependent calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculationInput,
    MarketPhase,
)
from junior_aladdin.floor_3_calculations.f3_contracts import InputContract
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import PacketEnvelope

logger = get_logger("f3_ingress")

INGRESS_VERSION = "1.0"

# Maximum allowed age for a packet (30 minutes)
_MAX_PACKET_AGE_SECONDS: int = 1800

# Maximum allowed future timestamp deviation (5 seconds)
_MAX_FUTURE_DEVIATION_SECONDS: int = 5


# =============================================================================
# INGRESS STATE
# =============================================================================


@dataclass
class IngressResult:
    """Result of processing a batch of Floor 2 packets.

    Fields:
        accepted: List of CalculationInput objects created from valid packets.
        rejected_count: Number of packets that failed validation.
        rejection_reasons: List of rejection reason strings.
        replay_mode: Whether ingress is operating in replay mode.
    """
    accepted: list[CalculationInput] = field(default_factory=list)
    rejected_count: int = 0
    rejection_reasons: list[str] = field(default_factory=list)
    replay_mode: bool = False


# =============================================================================
# PUBLIC API
# =============================================================================


def consume_floor2_output(
    packets: list[PacketEnvelope],
    replay_mode: bool = False,
) -> IngressResult:
    """Consume validated structured data from Floor 2.

    Validates every packet against the InputContract (FreshnessTag,
    DataHealth, timestamp range). Valid packets are converted to
    CalculationInput objects. Rejected packets are logged.

    Args:
        packets: List of PacketEnvelope from Floor 2 output stream.
        replay_mode: If True, packet age validation is skipped (replayed
            data may have old timestamps).

    Returns:
        An IngressResult with accepted CalculationInputs, rejection
        stats, and replay mode status.
    """
    result = IngressResult(replay_mode=replay_mode)

    if not packets:
        logger.info("No Floor 2 packets to consume")
        return result

    contract = InputContract(validated_data_stream=packets)

    for packet in packets:
        # Step 1: Validate against InputContract
        contract_errors = contract.validate_packet(packet)
        has_reject = any(e.get("severity") == "REJECT" for e in contract_errors)

        # Step 2: Validate timestamp range (skip in replay mode)
        ts_errors = _validate_timestamp(packet, replay_mode)
        if ts_errors:
            contract_errors.extend(ts_errors)
            has_reject = True

        if has_reject:
            result.rejected_count += 1
            reason = _format_rejection(packet, contract_errors)
            result.rejection_reasons.append(reason)
            logger.warning(
                "Packet rejected at ingress",
                extra={
                    "packet_id": packet.packet_id,
                    "source": packet.source,
                    "feed_type": packet.feed_type,
                    "errors": contract_errors,
                },
            )
            continue

        # Step 3: Convert to CalculationInput
        calc_input = _packet_to_calculation_input(packet)
        if calc_input is not None:
            result.accepted.append(calc_input)

    logger.info(
        "Ingress complete",
        extra={
            "total_packets": len(packets),
            "accepted": len(result.accepted),
            "rejected": result.rejected_count,
            "replay_mode": replay_mode,
        },
    )

    return result


def route_to_calculation_input(
    packets: list[dict[str, Any]],
    market_phase: MarketPhase = MarketPhase.OPEN,
    symbol: str = "NIFTY",
) -> list[CalculationInput]:
    """Convert a raw data list directly to CalculationInput objects.

    A convenience function for direct use (e.g., from tests, scripts,
    or when the data source is not Floor 2 PacketEnvelopes).

    Each item in ``packets`` should be a dict with:
    - ``\"candles\"`` (list of OHLCV dicts)
    - ``\"timestamp\"`` (datetime)

    Args:
        packets: List of raw data dicts to convert.
        market_phase: Market phase to use for all inputs. Default OPEN.
        symbol: Trading symbol. Default NIFTY.

    Returns:
        List of CalculationInput objects, one per packet dict.
    """
    inputs: list[CalculationInput] = []
    for i, data in enumerate(packets):
        ts = data.get("timestamp", datetime.min)
        calc_input = CalculationInput(
            packet_envelope_id=f"direct_{i}",
            market_phase=market_phase,
            symbol=symbol,
            timestamp=ts,
            data=data,
        )
        inputs.append(calc_input)
    return inputs


# =============================================================================
# INTERNAL
# =============================================================================


def _validate_timestamp(
    packet: PacketEnvelope,
    replay_mode: bool,
) -> list[dict[str, Any]]:
    """Validate packet timestamp is within acceptable range.

    In live mode, timestamps must not be too old or in the future.
    In replay mode, timestamp validation is skipped.

    Args:
        packet: The PacketEnvelope to validate.
        replay_mode: If True, skip age validation.

    Returns:
        List of validation error dicts. Empty list if valid.
    """
    if replay_mode:
        return []

    errors: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    # Get timestamp from payload or use received_at
    ts = packet.payload.get("timestamp", packet.source_timestamp or packet.received_at)

    if ts is None:
        errors.append({
            "field": "timestamp",
            "reason": "Packet has no timestamp",
            "severity": "REJECT",
        })
        return errors

    # Ensure timestamp is timezone-aware for comparison
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            # Assume naive timestamps are UTC
            ts = ts.replace(tzinfo=timezone.utc)

        age = (now - ts).total_seconds()

        # Too old
        if age > _MAX_PACKET_AGE_SECONDS:
            errors.append({
                "field": "timestamp",
                "reason": f"Packet timestamp is {age:.0f}s old (max {_MAX_PACKET_AGE_SECONDS}s)",
                "severity": "REJECT",
            })

        # Too far in the future
        if age < -_MAX_FUTURE_DEVIATION_SECONDS:
            errors.append({
                "field": "timestamp",
                "reason": f"Packet timestamp is {-age:.0f}s in the future (max {_MAX_FUTURE_DEVIATION_SECONDS}s)",
                "severity": "REJECT",
            })

    return errors


def _packet_to_calculation_input(
    packet: PacketEnvelope,
) -> CalculationInput | None:
    """Convert a validated PacketEnvelope to a CalculationInput.

    Extracts the data payload and metadata from the packet.

    Args:
        packet: The validated PacketEnvelope.

    Returns:
        A CalculationInput, or None if the payload is empty.
    """
    payload = packet.payload or {}
    data = payload.get("data", payload)

    if not data:
        logger.warning(
            "Packet has empty payload, skipping",
            extra={"packet_id": packet.packet_id},
        )
        return None

    # Determine market phase from payload or default to OPEN
    mp_str = payload.get("market_phase", "OPEN")
    try:
        market_phase = MarketPhase(mp_str)
    except ValueError:
        market_phase = MarketPhase.OPEN

    # Determine symbol from payload
    symbol = payload.get("symbol", "NIFTY")

    ts = packet.source_timestamp or packet.received_at

    return CalculationInput(
        packet_envelope_id=packet.packet_id,
        market_phase=market_phase,
        symbol=symbol,
        timestamp=ts,
        data=data if isinstance(data, dict) else {"data": data},
    )


def _format_rejection(
    packet: PacketEnvelope,
    errors: list[dict[str, Any]],
) -> str:
    """Format a human-readable rejection reason string.

    Args:
        packet: The rejected packet.
        errors: The validation errors.

    Returns:
        A formatted rejection string.
    """
    reasons = "; ".join(
        f"{e.get('field', '?')}: {e.get('reason', '?')}"
        for e in errors
    )
    return f"[{packet.packet_id}] {packet.source}/{packet.feed_type}: {reasons}"
