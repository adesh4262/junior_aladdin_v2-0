"""Floor 2 Output — session stream router.

Provides the **SessionStreamRouter** class that routes per-session
structured outputs to the correct consumers and provides session
context propagation.

Responsibilities:
- **Session extraction**: Extract ``SessionPacket`` objects from the
  structured writer's data.
- **Session context**: Determine current session phase (OPENING, MID,
  CLOSING) and build session context metadata.
- **Consumer routing**: Route session-bound structured outputs to
  appropriate consumers based on session phase.
- **Session context propagation**: Attach session context to handoff
  categories that need it (candle streams, tick streams).

Architecture rules:
- Session data is FACTUAL — session boundaries based on market hours only.
- No session intelligence — just routing and context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    SessionPacket,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("session_stream_router")

# Market session boundaries (India — NSE: 9:15 AM to 3:30 PM IST)
SESSION_PRE_OPEN_START = (9, 0)  # 9:00 AM IST
SESSION_OPEN = (9, 15)  # 9:15 AM IST
SESSION_MID = (12, 0)  # 12:00 PM IST
SESSION_CLOSE_START = (15, 0)  # 3:00 PM IST
SESSION_CLOSE = (15, 30)  # 3:30 PM IST

# Consumer identifiers for session routing
CONSUMER_TICK_STREAMS = "tick_stream_consumers"
CONSUMER_CANDLE_STREAMS = "candle_stream_consumers"
CONSUMER_OPTIONS = "options_consumers"
CONSUMER_MACRO = "macro_consumers"


class SessionStreamRouter:
    """Routes per-session structured outputs to correct consumers.

    Determines the current market session phase, extracts session
    packets from the structured writer, and provides routing context
    for session-bound outputs.

    Typical usage::

        router = SessionStreamRouter(structured_writer)

        # Get current session phase
        phase = router.get_current_session_phase()

        # Extract session packets
        packets = router.extract_session_packets()

        # Get routing context for a given phase
        context = router.get_session_routing_context()
    """

    def __init__(
        self,
        structured_writer: StructuredWriter,
    ) -> None:
        """Initialise the session stream router.

        Args:
            structured_writer: The structured writer to extract session
                data from.
        """
        self._structured_writer = structured_writer

    # ------------------------------------------------------------------
    # Session Phase Detection
    # ------------------------------------------------------------------

    def get_current_session_phase(
        self,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Determine the current market session phase.

        Uses NSE market hours (9:15 AM - 3:30 PM IST) to classify the
        current session phase.

        Args:
            now: The current timestamp (defaults to UTC now). The method
                converts to IST (UTC+5:30) for market hours detection.

        Returns:
            A dict with:
            - ``phase``: ``\"PRE_OPEN\"``, ``\"OPENING\"``, ``\"MID\"``,
              ``\"CLOSING\"``, ``\"CLOSED\"``, or ``\"UNKNOWN\"``.
            - ``session_type``: ``\"REGULAR\"``, ``\"PRE_OPEN\"``, or
              ``\"POST_CLOSE\"``.
            - ``is_market_hours``: ``True`` if within 9:15-3:30 IST.
            - ``label``: Human-readable session label.
        """
        now = now or datetime.now(timezone.utc)

        # Convert to IST for market hours
        # India Standard Time is UTC+5:30
        ist_hour = (now.hour + 5 + (now.minute + 30) // 60) % 24
        ist_minute = (now.minute + 30) % 60

        hour = ist_hour
        minute = ist_minute

        # Determine session phase based on IST time
        if hour < SESSION_PRE_OPEN_START[0] or (hour == SESSION_PRE_OPEN_START[0] and minute < SESSION_PRE_OPEN_START[1]):
            phase = "PRE_OPEN"
            session_type = "PRE_OPEN"
            is_market_hours = False
            label = "Pre-market — before 9:00 AM IST"
        elif hour < SESSION_OPEN[0] or (hour == SESSION_OPEN[0] and minute < SESSION_OPEN[1]):
            phase = "PRE_OPEN"
            session_type = "PRE_OPEN"
            is_market_hours = False
            label = "Pre-open session — 9:00 AM to 9:15 AM IST"
        elif hour < SESSION_MID[0] or (hour == SESSION_MID[0] and minute < SESSION_MID[1]):
            phase = "OPENING"
            session_type = "REGULAR"
            is_market_hours = True
            label = "Opening session — 9:15 AM to 12:00 PM IST"
        elif hour < SESSION_CLOSE_START[0] or (hour == SESSION_CLOSE_START[0] and minute < SESSION_CLOSE_START[1]):
            phase = "MID"
            session_type = "REGULAR"
            is_market_hours = True
            label = "Mid-session — 12:00 PM to 3:00 PM IST"
        elif hour < SESSION_CLOSE[0] or (hour == SESSION_CLOSE[0] and minute < SESSION_CLOSE[1]):
            phase = "CLOSING"
            session_type = "REGULAR"
            is_market_hours = True
            label = "Closing session — 3:00 PM to 3:30 PM IST"
        elif hour == SESSION_CLOSE[0] and minute >= SESSION_CLOSE[1]:
            phase = "CLOSED"
            session_type = "POST_CLOSE"
            is_market_hours = False
            label = "Market closed — after 3:30 PM IST"
        else:
            phase = "CLOSED"
            session_type = "POST_CLOSE"
            is_market_hours = False
            label = "Market closed"

        return {
            "phase": phase,
            "session_type": session_type,
            "is_market_hours": is_market_hours,
            "label": label,
            "ist_time": f"{hour:02d}:{minute:02d} IST",
        }

    # ------------------------------------------------------------------
    # Session Packet Extraction
    # ------------------------------------------------------------------

    def extract_session_packets(self) -> list[SessionPacket]:
        """Extract session packets from the structured writer.

        Retrieves all ``SessionPacket`` objects stored in the structured
        writer's SESSION_PACKET stream type.

        Returns:
            A list of ``SessionPacket`` instances, or empty if none found.
        """
        entries = self._structured_writer.get_by_type(StreamType.SESSION_PACKET)
        packets: list[SessionPacket] = []

        for entry in entries:
            stream_data = entry.get("stream_data")
            if stream_data is not None:
                # stream_data could be a dict or a SessionPacket
                if isinstance(stream_data, dict):
                    packet = SessionPacket(
                        session_id=stream_data.get("session_id", ""),
                        session_type=stream_data.get("session_type", ""),
                        session_phase=stream_data.get("session_phase", ""),
                        session_status=stream_data.get("session_status", ""),
                        timestamp=stream_data.get("timestamp"),
                        references=stream_data.get("references", {}),
                    )
                    packets.append(packet)
                elif isinstance(stream_data, SessionPacket):
                    packets.append(stream_data)

        return packets

    # ------------------------------------------------------------------
    # Session Routing Context
    # ------------------------------------------------------------------

    def get_session_routing_context(
        self,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Get the full session routing context.

        Combines current session phase with extracted session packets
        to provide a routing context dict.

        Args:
            now: Current timestamp for phase detection.

        Returns:
            A dict with session phase info, packets, and routing targets.
        """
        phase_info = self.get_current_session_phase(now)
        packets = self.extract_session_packets()

        # Determine routing targets based on session phase
        routing_targets = self._get_routing_targets(phase_info["phase"])

        return {
            "session_phase": phase_info,
            "session_packets": packets,
            "packet_count": len(packets),
            "routing_targets": routing_targets,
            "consumers": self._get_consumers_for_phase(phase_info["phase"]),
        }

    def route_for_handoff(
        self,
        now: datetime | None = None,
    ) -> list[SessionPacket]:
        """Get session packets suitable for the Floor 3 handoff.

        Returns the most relevant session packets based on current
        session phase.

        Args:
            now: Current timestamp for phase detection.

        Returns:
            List of ``SessionPacket`` instances for handoff.
        """
        packets = self.extract_session_packets()

        # If we have packets, return them (most recent first)
        if packets:
            return packets

        # No stored packets — generate a context packet from current phase
        phase_info = self.get_current_session_phase(now)
        session_id = f"sess_{now.strftime('%Y%m%d')}" if now else "sess_unknown"

        context_packet = SessionPacket(
            session_id=session_id,
            session_type=phase_info["session_type"],
            session_phase=phase_info["phase"],
            session_status="ACTIVE" if phase_info["is_market_hours"] else "CLOSED",
            timestamp=now or datetime.now(timezone.utc),
        )
        return [context_packet]

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _get_routing_targets(self, phase: str) -> list[str]:
        """Get routing target names for a given session phase."""
        targets = []
        if phase in ("OPENING", "MID", "CLOSING"):
            targets = ["tick_stream_consumers", "candle_stream_consumers", "options_consumers"]
        elif phase == "PRE_OPEN":
            targets = ["session_consumers"]
        elif phase == "CLOSED":
            targets = ["candle_stream_consumers", "options_consumers", "macro_consumers"]
        return targets

    def _get_consumers_for_phase(self, phase: str) -> dict[str, list[str]]:
        """Get consumer lists for each output type in the given phase."""
        consumers: dict[str, list[str]] = {}

        if phase in ("OPENING", "MID", "CLOSING"):
            consumers = {
                CONSUMER_TICK_STREAMS: ["Floor 3 — All Domains"],
                CONSUMER_CANDLE_STREAMS: ["Floor 3 — All Domains"],
                CONSUMER_OPTIONS: ["Floor 3 — Options Domain"],
                CONSUMER_MACRO: ["Floor 3 — Macro Domain"],
            }
        elif phase == "PRE_OPEN":
            consumers = {
                "session_consumers": ["Floor 3 — All Domains"],
            }
        elif phase == "CLOSED":
            consumers = {
                CONSUMER_CANDLE_STREAMS: ["Floor 3 — All Domains"],
                CONSUMER_OPTIONS: ["Floor 3 — Options Domain"],
                CONSUMER_MACRO: ["Floor 3 — Macro Domain"],
            }

        return consumers
