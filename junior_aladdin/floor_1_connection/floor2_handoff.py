"""Floor 1 → Floor 2 handoff service.

Assembles all 5 payload families from the ingress router's handoff payload
and forwards them to Floor 2.

5 payload families:
    1. original_raw_packet  — raw source data (unmodified)
    2. minimal_source_envelope — governance envelope (dict form of PacketEnvelope)
    3. feed_routing_identity — FeedType enum value string
    4. source_health_facts   — lifecycle state + health metrics
    5. manual_source_tags    — manual source info (None for live data)

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import FeedType, Floor2Handoff, PacketEnvelope

logger = get_logger("floor2_handoff")

# The set of keys that MUST be present in every ingress handoff payload.
REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "source_name",
        "feed_type",
        "raw_data",
        "envelope",
        "routing_identity",
        "health_facts",
        "manual_source_tag",
    }
)

# FeedType.value → readable routing identity string
# e.g. FeedType.SPOT_FEED.value → "SPOT_FEED"


class Floor2HandoffService:
    """Assembles and dispatches Floor 1 → Floor 2 handoff payloads.

    Receives routed data from IngressRouter via :meth:`send_to_floor2`,
    validates the required fields, builds the ``Floor2Handoff`` dataclass
    containing all 5 payload families, logs the handoff for traceability,
    and stores it for downstream consumption.

    Usage::

        handoff_service = Floor2HandoffService()
        router.on_handoff(handoff_service.send_to_floor2)
    """

    def __init__(self, store_handoffs: bool = True) -> None:
        self._store_handoffs: bool = store_handoffs
        self._handoffs: list[Floor2Handoff] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_to_floor2(self, ingress_payload: dict[str, Any]) -> Floor2Handoff:
        """Validate, assemble, and dispatch a Floor 2 handoff.

        Args:
            ingress_payload: Dict from ``IngressRouter`` with keys:
                - ``source_name``: str
                - ``feed_type``: str
                - ``raw_data``: dict — original raw payload
                - ``envelope``: PacketEnvelope
                - ``routing_identity``: FeedType | None
                - ``health_facts``: dict | None
                - ``manual_source_tag``: str | None

        Returns:
            A fully populated :class:`Floor2Handoff` dataclass with all
            5 payload families.

        Raises:
            ContractViolationError: If any mandatory field is missing,
                or the envelope is not a PacketEnvelope.
        """
        self._validate(ingress_payload)

        # --- Assemble 5 families ---
        handoff = Floor2Handoff(
            original_raw_packet=ingress_payload["raw_data"],
            minimal_source_envelope=self._build_minimal_source_envelope(
                ingress_payload["envelope"]
            ),
            feed_routing_identity=self._build_feed_routing_identity(
                ingress_payload["routing_identity"],
                ingress_payload["feed_type"],
            ),
            source_health_facts=self._build_source_health_facts(
                ingress_payload["health_facts"]
            ),
            manual_source_tags=self._build_manual_source_tags(
                ingress_payload["manual_source_tag"]
            ),
        )

        # --- Traceability logging ---
        self._log_handoff(handoff, ingress_payload)

        # --- Store for downstream consumption ---
        if self._store_handoffs:
            self._handoffs.append(handoff)

        return handoff

    @property
    def handoff_count(self) -> int:
        """Number of handoffs processed since service creation."""
        return len(self._handoffs) if self._store_handoffs else 0

    @property
    def last_handoff(self) -> Floor2Handoff | None:
        """The most recently processed handoff, or None."""
        if self._store_handoffs and len(self._handoffs) > 0:
            return self._handoffs[-1]
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate(self, payload: dict[str, Any]) -> None:
        """Raise ContractViolationError if any mandatory contract is broken."""
        missing = REQUIRED_KEYS - set(payload.keys())
        if missing:
            raise ContractViolationError(
                "Floor 2 handoff payload missing required keys",
                details={"missing_keys": sorted(missing)},
            )

        if not isinstance(payload["envelope"], PacketEnvelope):
            raise ContractViolationError(
                "Floor 2 handoff 'envelope' must be a PacketEnvelope instance",
                details={
                    "actual_type": type(payload["envelope"]).__name__,
                },
            )

        if not isinstance(payload["raw_data"], dict):
            raise ContractViolationError(
                "Floor 2 handoff 'raw_data' must be a dict",
                details={
                    "actual_type": type(payload["raw_data"]).__name__,
                },
            )

    @staticmethod
    def _build_minimal_source_envelope(envelope: PacketEnvelope) -> dict[str, Any]:
        """Convert PacketEnvelope to a dict with ISO-formatted timestamps."""
        return {
            "source": envelope.source,
            "feed_type": envelope.feed_type,
            "connection_id": envelope.connection_id,
            "packet_id": envelope.packet_id,
            "routing_id": envelope.routing_id,
            "received_at": envelope.received_at.isoformat()
            if envelope.received_at
            else None,
        }

    @staticmethod
    def _build_feed_routing_identity(
        routing_identity: FeedType | None,
        feed_type: str,
    ) -> str:
        """Convert FeedType enum to its string value.

        For manual packets the routing identity is intentionally empty;
        the caller can inspect ``manual_source_tags`` to classify it.
        """
        if routing_identity is not None:
            return routing_identity.value
        return ""

    @staticmethod
    def _build_source_health_facts(
        health_facts: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return health facts dict (defaults to empty if None)."""
        return health_facts or {}

    @staticmethod
    def _build_manual_source_tags(
        manual_source_tag: str | None,
    ) -> dict[str, Any] | None:
        """Wrap manual source tag into a dict, or return None for live data."""
        if manual_source_tag is None:
            return None
        return {"manual_source_tag": manual_source_tag}

    @staticmethod
    def _log_handoff(
        handoff: Floor2Handoff,
        ingress_payload: dict[str, Any],
    ) -> None:
        """Log the handoff for traceability."""
        routing = handoff.feed_routing_identity or "NONE"
        is_manual = handoff.manual_source_tags is not None
        logger.info(
            "Handoff: %s | %s | routing=%s | manual=%s",
            ingress_payload.get("source_name", "?"),
            ingress_payload.get("feed_type", "?"),
            routing,
            is_manual,
            extra={
                "families_present": {
                    "original_raw_packet": bool(handoff.original_raw_packet),
                    "minimal_source_envelope": bool(handoff.minimal_source_envelope),
                    "feed_routing_identity": bool(handoff.feed_routing_identity),
                    "source_health_facts": bool(handoff.source_health_facts),
                    "manual_source_tags": handoff.manual_source_tags is not None,
                },
            },
        )
