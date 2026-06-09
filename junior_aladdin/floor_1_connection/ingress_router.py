"""Central ingress router for Floor 1.

Accepts packets from all source adapters, routes through the correct feed
adapter for identity tagging, applies the PacketEnvelope, and forwards the
assembled handoff data to Floor 2's handoff callback.

Data flow:
    Source Adapter (raw data)
        → route_packet()
        → Feed Adapter (identity tagging → envelope-ready dict)
        → build_envelope() (PacketEnvelope)
        → Handoff callback (Floor 2 handoff)

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from typing import Any, Callable

from junior_aladdin.floor_1_connection.manual_ingress import (
    VALID_EVENT_TYPES,
    create_manual_packet,
)
from junior_aladdin.floor_1_connection.packet_envelope import build_envelope
from junior_aladdin.floor_1_connection.shared_utils import generate_connection_id
from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import FeedType, PacketEnvelope

logger = get_logger("ingress_router")

# Type alias for the handoff receiver callback.
# floor2_handoff (Step 1.9) registers a callable matching this signature.
HandoffPayload = dict[str, Any]
HandoffCallback = Callable[[HandoffPayload], None]

# Mapping from feed_type strings → FeedType enum for routing identity.
FEED_TYPE_TO_ROUTING_IDENTITY: dict[str, FeedType] = {
    "spot_tick": FeedType.SPOT_FEED,
    "options_snapshot": FeedType.OPTIONS_FEED,
    "vix_tick": FeedType.VIX_FEED,
    "macro_data": FeedType.MACRO_FEED,
    "calendar_event": FeedType.CALENDAR_FEED,
}


class IngressRouter:
    """Central ingress router: accept, tag, envelope, forward.

    The router owns a registry of source adapters and feed adapters.
    When :meth:`start_routing` is called, it registers an internal data
    callback on every source adapter so raw data flows through the full
    pipeline automatically.

    Typical setup::

        router = IngressRouter(
            source_adapters={
                "angel_one": angel_one_adapter,
                "manual": manual_adapter,
            },
            feed_adapters={
                "spot_tick": spot_feed,
                "options_snapshot": options_feed,
                "vix_tick": vix_feed,
                ...
            },
        )
        router.on_handoff(floor2_handoff.send_to_floor2)
        router.start_routing()
    """

    def __init__(
        self,
        source_adapters: dict[str, Any] | None = None,
        feed_adapters: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the ingress router.

        Args:
            source_adapters: Dict mapping source name → adapter instance.
                Expected adapters: AngelOneAdapter, ManualSourceAdapter.
            feed_adapters: Dict mapping feed_type → feed adapter instance.
                Expected adapters: SpotFeedAdapter, OptionsFeedAdapter,
                VixFeedAdapter, MacroFeedAdapter, CalendarFeedAdapter.
        """
        self._source_adapters: dict[str, Any] = source_adapters or {}
        self._feed_adapters: dict[str, Any] = feed_adapters or {}

        # A dedicated connection_id for manual ingress packets.
        self._manual_connection_id: str = generate_connection_id()

        # Handoff callbacks — floor2_handoff registers here.
        self._handoff_callbacks: list[HandoffCallback] = []

        # Routing state
        self._routing_active: bool = False
        self._data_handler: Callable[[str, str, dict[str, Any]], None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route_packet(
        self,
        source_name: str,
        feed_type: str,
        raw_data: dict[str, Any],
    ) -> None:
        """Route a raw packet through the full pipeline.

        Accepts raw data from any source adapter, finds the appropriate
        feed adapter for identity tagging, wraps the result in a
        PacketEnvelope, and notifies all registered handoff callbacks.

        If ``source_name`` is ``\"manual\"``, the manual_ingress lane is
        used instead of a feed adapter.

        Args:
            source_name: Source identifier (e.g., ``\"angel_one\"``,
                ``\"manual\"``).
            feed_type: Feed type string (e.g., ``\"spot_tick\"``,
                ``\"MANUAL_CALENDAR\"``).
            raw_data: The raw payload from the source.
        """
        if not self._routing_active:
            logger.warning(
                "Packet received but routing is not active — ignoring",
                extra={"source": source_name, "feed_type": feed_type},
            )
            return

        try:
            # ---- 1. Manual source lane ----
            if source_name == "manual":
                handoff = self._route_manual_packet(feed_type, raw_data)
            else:
                handoff = self._route_live_packet(source_name, feed_type, raw_data)

            # ---- 4. Notify handoff callbacks ----
            if not handoff:
                return  # packet could not be routed (unknown feed/manual type)

            for cb in self._handoff_callbacks:
                try:
                    cb(handoff)
                except Exception:
                    logger.error(
                        "Handoff callback failed",
                        extra={
                            "source": source_name,
                            "feed_type": feed_type,
                            "error": "exception in callback",
                        },
                    )

        except Exception as e:
            logger.error(
                "Failed to route packet",
                extra={
                    "source": source_name,
                    "feed_type": feed_type,
                    "error": str(e),
                },
            )

    def start_routing(self) -> None:
        """Register data callbacks on all source adapters.

        When a source adapter receives data, it will automatically flow
        through :meth:`route_packet`.

        Safe to call multiple times — duplicate callbacks are not added.
        """
        self._routing_active = True

        def _on_source_data(source_name: str, feed_type: str, data: dict[str, Any]) -> None:
            self.route_packet(source_name, feed_type, data)

        self._data_handler = _on_source_data

        for name, adapter in self._source_adapters.items():
            if hasattr(adapter, "on_data") and callable(adapter.on_data):
                adapter.on_data(_on_source_data)
                logger.info(
                    "Registered data handler for source",
                    extra={"source": name},
                )

        logger.info("Routing started")

    def stop_routing(self) -> None:
        """Stop routing packets.

        Sets routing as inactive so any packets that arrive after this
        call are silently ignored.
        """
        self._routing_active = False
        logger.info("Routing stopped")

    @property
    def is_routing_active(self) -> bool:
        """Whether the router is currently processing packets."""
        return self._routing_active

    def on_handoff(self, callback: HandoffCallback) -> None:
        """Register a callback to receive assembled handoff data.

        The callback receives a dict with:
        - ``source_name``: str
        - ``feed_type``: str
        - ``raw_data``: dict — original raw payload
        - ``envelope``: PacketEnvelope — wrapped envelope
        - ``routing_identity``: FeedType | None — feed routing enum
        - ``health_facts``: dict | None — source health facts
        - ``manual_source_tag``: str | None — manual source tag

        Args:
            callback: A callable accepting a single dict argument.
        """
        if callback not in self._handoff_callbacks:
            self._handoff_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _route_live_packet(
        self,
        source_name: str,
        feed_type: str,
        raw_data: dict[str, Any],
    ) -> HandoffPayload:
        """Route a live (non-manual) packet through feed adapter + envelope."""
        # ---- 1. Look up feed adapter ----
        feed_adapter = self._feed_adapters.get(feed_type)
        if feed_adapter is None:
            logger.warning(
                "No feed adapter registered for feed type — ignoring",
                extra={"feed_type": feed_type, "source": source_name},
            )
            return {}

        # ---- 2. Feed adapter identity tagging ----
        envelope_ready = feed_adapter.handle_data(raw_data)

        # ---- 3. Get connection_id from source adapter ----
        connection_id = self._get_source_connection_id(source_name)

        # ---- 4. Build envelope ----
        envelope = build_envelope(
            raw_payload=envelope_ready,
            source=source_name,
            feed_type=feed_type,
            connection_id=connection_id,
        )

        # ---- 5. Assemble handoff payload ----
        routing_identity = FEED_TYPE_TO_ROUTING_IDENTITY.get(feed_type)
        health_facts = self._collect_health_facts(source_name)

        return {
            "source_name": source_name,
            "feed_type": feed_type,
            "raw_data": raw_data,
            "envelope": envelope,
            "routing_identity": routing_identity,
            "health_facts": health_facts,
            "manual_source_tag": None,
        }

    def _route_manual_packet(
        self,
        feed_type: str,
        raw_data: dict[str, Any],
    ) -> HandoffPayload:
        """Route a manual packet via manual_ingress + envelope."""
        # ---- 1. Validate event type & create envelope-ready dict ----
        if feed_type not in VALID_EVENT_TYPES:
            logger.warning(
                "Invalid manual feed type — ignoring",
                extra={"feed_type": feed_type},
            )
            return {}

        manual_packet = create_manual_packet(
            event_type=feed_type,
            data=raw_data,
            source_tag="manual_ingress",
            connection_id=self._manual_connection_id,
        )

        # ---- 2. Build envelope ----
        envelope = build_envelope(
            raw_payload=manual_packet["payload"],
            source=manual_packet["source"],
            feed_type=manual_packet["feed_type"],
            connection_id=self._manual_connection_id,
        )

        # Attach manual source tag to payload for downstream traceability
        envelope.payload["manual_source_tag"] = manual_packet["manual_source_tag"]

        # ---- 3. Assemble handoff payload ----
        return {
            "source_name": "manual",
            "feed_type": feed_type,
            "raw_data": raw_data,
            "envelope": envelope,
            "routing_identity": None,  # manual packets have no FeedType identity
            "health_facts": None,
            "manual_source_tag": manual_packet["manual_source_tag"],
        }

    def _get_source_connection_id(self, source_name: str) -> str:
        """Retrieve the connection_id from a registered source adapter.

        Falls back to a generated ID if the adapter doesn't expose one.
        """
        adapter = self._source_adapters.get(source_name)
        if adapter is not None and hasattr(adapter, "connection_id"):
            return adapter.connection_id
        return generate_connection_id()

    def _collect_health_facts(self, source_name: str) -> dict[str, Any] | None:
        """Collect source health facts from a registered source adapter.

        Looks for ``get_lifecycle_state()`` and ``is_connected()`` methods.
        Returns None if the adapter doesn't expose health information.
        """
        adapter = self._source_adapters.get(source_name)
        if adapter is None:
            return None

        facts: dict[str, Any] = {}

        if hasattr(adapter, "get_lifecycle_state") and callable(adapter.get_lifecycle_state):
            state = adapter.get_lifecycle_state()
            facts["lifecycle_state"] = state.value if hasattr(state, "value") else str(state)
        if hasattr(adapter, "is_connected") and callable(adapter.is_connected):
            facts["is_connected"] = adapter.is_connected()

        return facts or None
