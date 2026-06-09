"""Junior Aladdin — Floor 1: Market Connection Layer.

Floor 1 is the system's window to external market data. It handles
authentication, source connectivity, feed adaptation, packet enveloping,
health monitoring, manual ingress, routing, and handoff to Floor 2.

Architecture rules:
- Floor 1 imports ONLY from shared/. No floor_2+ imports.
- Floor 1 does NOT validate, clean, or interpret data.
- PacketEnvelope is the ONLY cross-floor envelope.
"""

from __future__ import annotations

from junior_aladdin.floor_1_connection.auth_manager import AuthManager
from junior_aladdin.floor_1_connection.feed_adapters import (
    CalendarFeedAdapter,
    MacroFeedAdapter,
    OptionsFeedAdapter,
    SpotFeedAdapter,
    VixFeedAdapter,
)
from junior_aladdin.floor_1_connection.floor2_handoff import Floor2HandoffService
from junior_aladdin.floor_1_connection.ingress_router import IngressRouter
from junior_aladdin.floor_1_connection.manual_ingress import (
    MANUAL_CALENDAR,
    MANUAL_EVENT,
    MANUAL_OVERRIDE,
    build_manual_envelope,
    create_manual_packet,
)
from junior_aladdin.floor_1_connection.packet_envelope import build_envelope
from junior_aladdin.floor_1_connection.shared_utils import (
    generate_connection_id,
    generate_packet_id,
    is_websocket_healthy,
    retry_with_backoff,
    serialize_for_handoff,
)
from junior_aladdin.floor_1_connection.source_adapters import (
    AngelOneAdapter,
    BackupAdapter,
    ManualSourceAdapter,
)
from junior_aladdin.floor_1_connection.source_health import SourceHealthMonitor

__all__ = [
    "AngelOneAdapter",
    "AuthManager",
    "BackupAdapter",
    "CalendarFeedAdapter",
    "Floor2HandoffService",
    "IngressRouter",
    "MANUAL_CALENDAR",
    "MANUAL_EVENT",
    "MANUAL_OVERRIDE",
    "MacroFeedAdapter",
    "ManualSourceAdapter",
    "OptionsFeedAdapter",
    "SourceHealthMonitor",
    "SpotFeedAdapter",
    "VixFeedAdapter",
    "build_envelope",
    "build_manual_envelope",
    "create_manual_packet",
    "generate_connection_id",
    "generate_packet_id",
    "is_websocket_healthy",
    "retry_with_backoff",
    "serialize_for_handoff",
]
