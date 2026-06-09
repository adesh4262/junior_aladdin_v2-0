"""Floor 2 Ingress — raw ingest router.

Orchestrates the Floor 2 ingress pipeline:
1. Receives a Floor 1 5-family handoff payload.
2. Normalises it via :mod:`source_envelope_builder`.
3. Records metrics via :class:`ingress_monitor`.
4. Routes the normalised payload to raw storage (or raises on error).

Can be registered as a handoff callback on Floor 1's ``IngressRouter``
via the :meth:`RawIngestRouter.ingest` method.

Architecture rules:
- ADDITIVE only: never modifies Floor 1 data, only wraps it.
- Validation errors are raised — the caller decides retry/block behaviour.
- Monitor stats are kept separate from the data pipeline.
"""

from __future__ import annotations

from typing import Any, Callable

from junior_aladdin.floor_2_datacenter.datacenter_types import IngestPayload
from junior_aladdin.floor_2_datacenter.ingress.ingress_monitor import IngressMonitor
from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.floor_2_datacenter.ingress.source_envelope_builder import (
    build_source_envelope,
)
from junior_aladdin.shared.errors import ValidationError
from junior_aladdin.shared.logging import get_logger

logger = get_logger("raw_ingest_router")


class RawIngestRouter:
    """Orchestrate the Floor 2 ingress pipeline.

    Accepts Floor 1 handoff payloads, normalises them, records metrics,
    and routes the result to downstream storage or a registered callback.

    Typical setup::

        router = RawIngestRouter()

        # Register as Floor 1 on_handoff callback:
        floor1_router.on_handoff(router.ingest)

        # Or call directly:
        result = router.ingest(floor1_payload)

    Args:
        monitor: An optional :class:`IngressMonitor` instance. A default
            one is created if not provided.
        downstream_callback: An optional callable that receives the
            normalised :class:`Floor2IngestPayload` after successful ingest.
            This will be connected to the raw storage layer in Step 2.3.
    """

    def __init__(
        self,
        monitor: IngressMonitor | None = None,
        downstream_callback: Callable[[Any], None] | None = None,
    ) -> None:
        self._monitor = monitor or IngressMonitor()
        self._downstream_callback = downstream_callback

        # Stats
        self._total_ingested: int = 0
        self._total_errors: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def monitor(self) -> IngressMonitor:
        """The attached :class:`IngressMonitor` instance."""
        return self._monitor

    @property
    def total_ingested(self) -> int:
        """Total payloads successfully ingested."""
        return self._total_ingested

    @property
    def total_errors(self) -> int:
        """Total payloads that failed ingestion."""
        return self._total_errors

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def ingest(self, floor1_payload: dict[str, Any]) -> dict[str, Any] | None:
        """Ingest a single Floor 1 5-family handoff payload.

        Steps:
        1. Validate key presence via ``validate_floor1_payload()``.
        2. Normalise into ``Floor2IngestPayload`` via ``build_source_envelope()``.
        3. Record success metrics in the monitor.
        4. Call the downstream callback (if registered) with the normalised payload.
        5. Return the normalised payload as an ``IngestPayload`` dict.

        Args:
            floor1_payload: The 5-family dict from Floor 1's handoff.

        Returns:
            The normalised ``IngestPayload`` dict on success, or ``None``
            if validation fails.

        Note:
            The returned dict has the same structure as ``Floor2IngestPayload``
            but as a plain dict for cross-boundary compatibility.
        """
        # Extract source/feed info for logging before validation
        envelope = floor1_payload.get("minimal_source_envelope", {})
        source = envelope.get("source", "unknown")
        feed_type = envelope.get("feed_type", "unknown")

        try:
            # ── 1. Normalise ──────────────────────────────────────────────
            normalised = build_source_envelope(floor1_payload)

        except ValidationError as e:
            logger.error(
                "Ingest validation failed",
                extra={
                    "source": source,
                    "feed_type": feed_type,
                    "error": str(e),
                },
            )
            self._total_errors += 1
            self._monitor.record_error(
                source=source,
                feed_type=feed_type,
                error_message=str(e),
            )
            return None

        except Exception as e:
            logger.error(
                "Unexpected ingest error",
                extra={
                    "source": source,
                    "feed_type": feed_type,
                    "error": str(e),
                },
            )
            self._total_errors += 1
            self._monitor.record_error(
                source=source,
                feed_type=feed_type,
                error_message=str(e),
            )
            return None

        # ── 2. Record metrics ────────────────────────────────────────────
        self._monitor.record_ingest(
            source=normalised.minimal_source_envelope.get("source", source),
            feed_type=normalised.minimal_source_envelope.get("feed_type", feed_type),
        )
        self._total_ingested += 1

        # ── 3. Downstream callback ───────────────────────────────────────
        if self._downstream_callback:
            try:
                self._downstream_callback(normalised)
            except Exception as e:
                logger.error(
                    "Downstream callback failed",
                    extra={"error": str(e)},
                )

        # ── 4. Return as dict for cross-boundary compatibility ────────────
        return self._to_ingest_payload(normalised)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def register_downstream(self, callback: Callable[[Any], None]) -> None:
        """Register (or replace) the downstream callback.

        The callback receives the normalised :class:`Floor2IngestPayload`
        after each successful ingest.

        Args:
            callback: A callable accepting a single argument (the payload).
        """
        self._downstream_callback = callback

    @staticmethod
    def _to_ingest_payload(payload: Floor2IngestPayload) -> dict[str, Any]:
        """Convert a ``Floor2IngestPayload`` to a plain dict."""
        return {
            "original_raw_packet": payload.original_raw_packet,
            "minimal_source_envelope": payload.minimal_source_envelope,
            "feed_routing_identity": payload.feed_routing_identity,
            "source_health_facts": payload.source_health_facts,
            "manual_source_tags": payload.manual_source_tags,
            "ingested_at": payload.ingested_at,
            "ingest_batch_id": payload.ingest_batch_id,
        }
