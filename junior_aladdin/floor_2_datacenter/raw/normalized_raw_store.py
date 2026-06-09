"""Floor 2 Raw Storage — normalized raw store.

Stores the normalised raw envelope (``Floor2IngestPayload``) — the standardised
operational form of the source data wrapped with Floor 2 ingest metadata.

Architecture rules:
- NORMALISED RAW = source truth wrapped in standard operational envelope.
- Every stored packet includes ``TransformStage.RAW`` in its trackable metadata.
- In-memory dict storage for dev; interface is swappable to SQLite later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.floor_2_datacenter.datacenter_types import TransformStage
from junior_aladdin.shared.logging import get_logger

logger = get_logger("normalized_raw_store")


class NormalizedRawStore:
    """In-memory store for normalised raw envelopes.

    Thread-safe. Stores the full ``Floor2IngestPayload`` indexed by
    ``packet_id`` with pipeline stage tracking.

    Typical usage::

        store = NormalizedRawStore()
        store.store(normalised_payload)
        record = store.get("pkt_001")
        results = store.query(feed_type="spot_tick")
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # packet_id -> full record dict
        self._store: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def store(self, payload: Floor2IngestPayload) -> str | None:
        """Store a single normalised raw envelope.

        Uses the ``packet_id`` from the source envelope as the key.
        Adds pipeline stage tracking (``TransformStage.RAW``).

        Args:
            payload: The normalised ingest payload from the ingress pipeline.

        Returns:
            The ``packet_id`` of the stored packet, or ``None`` if the
            envelope has no ``packet_id``.
        """
        packet_id = payload.minimal_source_envelope.get("packet_id")
        if not packet_id:
            logger.warning(
                "Cannot store normalised raw packet — no packet_id in envelope",
            )
            return None

        record = {
            "packet_id": packet_id,
            "original_raw_packet": payload.original_raw_packet,
            "minimal_source_envelope": dict(payload.minimal_source_envelope),
            "feed_routing_identity": payload.feed_routing_identity,
            "source_health_facts": dict(payload.source_health_facts),
            "manual_source_tags": (
                dict(payload.manual_source_tags) if payload.manual_source_tags else None
            ),
            "ingested_at": payload.ingested_at,
            "ingest_batch_id": payload.ingest_batch_id,
            "source": payload.minimal_source_envelope.get("source", "unknown"),
            "feed_type": payload.minimal_source_envelope.get("feed_type", "unknown"),
            "transform_stage": TransformStage.RAW.value,
            "stored_at": datetime.now(timezone.utc),
        }

        with self._lock:
            self._store[packet_id] = record

        logger.debug(
            "Normalised raw envelope stored",
            extra={
                "packet_id": packet_id,
                "source": record["source"],
                "feed_type": record["feed_type"],
            },
        )
        return packet_id

    def store_many(self, payloads: list[Floor2IngestPayload]) -> list[str]:
        """Store multiple normalised raw envelopes.

        Args:
            payloads: List of normalised ingest payloads.

        Returns:
            List of successfully stored ``packet_id`` values.
        """
        stored = []
        for p in payloads:
            pid = self.store(p)
            if pid:
                stored.append(pid)
        return stored

    def get(self, packet_id: str) -> dict[str, Any] | None:
        """Retrieve a single normalised raw record by ID.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The full record dict, or ``None`` if not found.
        """
        with self._lock:
            return self._store.get(packet_id)

    def get_payload(self, packet_id: str) -> dict[str, Any] | None:
        """Retrieve the ingest payload fields for a packet.

        Returns a dict with the same shape as ``IngestPayload``.
        """
        record = self.get(packet_id)
        if record is None:
            return None
        return {
            "original_raw_packet": record.get("original_raw_packet", {}),
            "minimal_source_envelope": record.get("minimal_source_envelope", {}),
            "feed_routing_identity": record.get("feed_routing_identity", ""),
            "source_health_facts": record.get("source_health_facts", {}),
            "manual_source_tags": record.get("manual_source_tags"),
            "ingested_at": record.get("ingested_at"),
            "ingest_batch_id": record.get("ingest_batch_id", ""),
        }

    def query(
        self,
        source: str | None = None,
        feed_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Query normalised raw records by source, feed_type, and/or time range.

        Args:
            source: Filter by source name.
            feed_type: Filter by feed type.
            start_time: Include packets stored at or after this time.
            end_time: Include packets stored at or before this time.

        Returns:
            List of matching record dicts.
        """
        results: list[dict[str, Any]] = []
        with self._lock:
            for record in self._store.values():
                if source and record.get("source") != source:
                    continue
                if feed_type and record.get("feed_type") != feed_type:
                    continue
                ts = record.get("stored_at")
                if start_time and ts and ts < start_time:
                    continue
                if end_time and ts and ts > end_time:
                    continue
                results.append(record)
        return results

    def update_transform_stage(self, packet_id: str, stage: TransformStage) -> bool:
        """Update the transform stage for a packet.

        Args:
            packet_id: The unique packet identifier.
            stage: The new :class:`TransformStage` value.

        Returns:
            ``True`` if updated, ``False`` if packet not found.
        """
        with self._lock:
            if packet_id not in self._store:
                return False
            self._store[packet_id]["transform_stage"] = stage.value
            return True

    def delete(self, packet_id: str) -> bool:
        """Delete a single packet by ID.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        with self._lock:
            if packet_id in self._store:
                del self._store[packet_id]
                return True
            return False

    def clear(self) -> None:
        """Remove ALL packets from the store."""
        with self._lock:
            self._store.clear()
        logger.info("NormalizedRawStore cleared")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total packets currently in the store."""
        with self._lock:
            return len(self._store)

    @property
    def packet_ids(self) -> list[str]:
        """List of all packet IDs currently in the store."""
        with self._lock:
            return list(self._store.keys())

    @property
    def sources(self) -> set[str]:
        """Set of all source names in the store."""
        with self._lock:
            return {r.get("source", "unknown") for r in self._store.values()}

    @property
    def feed_types(self) -> set[str]:
        """Set of all feed types in the store."""
        with self._lock:
            return {r.get("feed_type", "unknown") for r in self._store.values()}
