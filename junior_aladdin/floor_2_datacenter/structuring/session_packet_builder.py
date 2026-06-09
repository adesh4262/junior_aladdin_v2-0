"""Floor 2 Structuring — session packet builder.

Builds explicit ``SessionPacket`` objects based on market time context.

Session packet types:
- ``PRE_OPEN``: 9:00–9:15 IST
- ``REGULAR``: 9:15–15:30 IST
- ``CLOSING``: 15:15–15:30 IST (last 15 minutes)
- ``POST_CLOSE``: 15:30 onwards

Architecture rules:
- Session packets are DATA, not intelligence — they describe time context.
- Session phases map to NIFTY 50 market hours.
- Each session packet carries references for Asia/London/NY overlaps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import SessionPacket
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType, StructureResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("session_packet_builder")

# NIFTY 50 market session times (UTC = IST - 5:30)
# IST 09:00 = UTC 03:30, IST 09:15 = UTC 03:45
# IST 15:15 = UTC 09:45, IST 15:30 = UTC 10:00
SESSION_RANGES: list[tuple[str, str, int, int, int, int]] = [
    ("PRE_OPEN", "PRE_OPEN", 3, 30, 3, 44),    # 9:00–9:14 IST
    ("REGULAR", "REGULAR", 3, 45, 9, 29),       # 9:15–14:59 IST
    ("CLOSING", "CLOSING", 9, 30, 9, 59),       # 15:00–15:29 IST
    ("POST_CLOSE", "POST_CLOSE", 10, 0, 23, 59), # 15:30 IST onwards
]


def build_session_packet(
    timestamp: datetime | None = None,
    session_id_prefix: str = "sess",
) -> StructureResult:
    """Build a ``SessionPacket`` for the current (or given) time.

    Args:
        timestamp: The time to build the session packet for.
            Defaults to ``datetime.now(timezone.utc)``.
        session_id_prefix: Prefix for the session ID (for traceability).

    Returns:
        A ``StructureResult`` with ``stream_type=SESSION_PACKET``.
    """
    now = timestamp or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # ── Determine session type and phase ──────────────────────────────
    utc_hour = now.hour
    utc_min = now.minute

    session_type: str = "UNKNOWN"
    session_phase: str = "UNKNOWN"

    for stype, phase, start_h, start_m, end_h, end_m in SESSION_RANGES:
        # Check if current time falls within this session range
        start_in_range = (utc_hour > start_h) or (utc_hour == start_h and utc_min >= start_m)
        end_in_range = (utc_hour < end_h) or (utc_hour == end_h and utc_min <= end_m)
        if start_in_range and end_in_range:
            session_type = stype
            session_phase = phase
            break

    # ── Handle overnight / before-market ──────────────────────────────
    if session_type == "UNKNOWN":
        if utc_hour < 3 or (utc_hour == 3 and utc_min < 30):
            session_type = "PRE_MARKET"
            session_phase = "PRE_MARKET"

    # ── Build session ID ──────────────────────────────────────────────
    session_id = (
        f"{session_id_prefix}_{session_type}_"
        f"{now.strftime('%Y%m%d_%H%M%S')}"
    )

    # ── Session references (Asia/London/NY overlap context) ───────────
    # Asia active: 03:00–09:00 UTC, London active: 08:00–16:30 UTC
    # NY active: 13:30–20:00 UTC
    references: dict[str, Any] = {
        "asia_active": 3 <= utc_hour < 9,
        "london_active": 8 <= utc_hour < 16 or (utc_hour == 16 and utc_min <= 30),
        "ny_active": 13 <= utc_hour < 20 or (utc_hour == 13 and utc_min >= 30),
    }

    packet = SessionPacket(
        session_id=session_id,
        session_type=session_type,
        session_phase=session_phase,
        session_status="ACTIVE" if session_type != "POST_CLOSE" else "CLOSED",
        timestamp=now,
        references=references,
    )

    logger.info(
        "Session packet built",
        extra={
            "session_id": session_id,
            "session_type": session_type,
            "session_phase": session_phase,
        },
    )

    return StructureResult(
        stream_type=StreamType.SESSION_PACKET,
        stream_data=packet,
        metadata={
            "session_id": session_id,
            "session_type": session_type,
            "session_phase": session_phase,
            "timestamp": now.isoformat(),
            "references": references,
        },
    )
