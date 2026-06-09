"""Floor 2 Raw Storage — original raw store.

Stores the exact original raw data from Floor 1 (``original_raw_packet`` family)
with minimal processing.

Architecture rules:
- ORIGINAL RAW = exact copy as received — NEVER modified.
- Useful for source bug investigation, audit, and replay.
- In-memory dict storage for dev; interface is swappable to SQLite later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.shared.logging import get_logger

logger = get_logger("original_raw_store")


class OriginalRawStore:
    """In-memory store for original raw packets.

    Thread-safe. Stores each packet indexed by ``packet_id`` with an
    associated timestamp for expiry-based purging.

    Typical usage::

        store = OriginalRawStore()
        store.store(normalised_payload)
        packet = store.get("pkt_001")
        results = store.query(source="angel_one")
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # packet_id -> { "data": dict, "timestamp": datetime, "source": str, "feed_type": str }
        self._store: dict[str, dict[str, Any]] = {}
        self._total_stored: int = 0

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def store(self, payload: Floor2IngestPayload) -> str | None:
        """Store a single original raw packet.

        Uses the ``packet_id`` from the source envelope as the key.

        Args:
            payload: The normalised ingest payload from the ingress pipeline.

        Returns:
            The ``packet_id`` of the stored packet, or ``None`` if the
            envelope has no ``packet_id``.
        """
        packet_id = payload.minimal_source_envelope.get("packet_id")
        if not packet_id:
            logger.warning(
                "Cannot store original raw packet — no packet_id in envelope",
            )
            return None

        record = {
            "data": payload.original_raw_packet,
            "timestamp": payload.ingested_at or datetime.now(timezone.utc),
            "source": payload.minimal_source_envelope.get("source", "unknown"),
            "feed_type": payload.minimal_source_envelope.get("feed_type", "unknown"),
            "ingested_at": payload.ingested_at,
            "ingest_batch_id": payload.ingest_batch_id,
            "feed_routing_identity": payload.feed_routing_identity,
            "source_health_facts": payload.source_health_facts,
            "manual_source_tags": payload.manual_source_tags,
        }

        with self._lock:
            self._store[packet_id] = record
            self._total_stored += 1

        logger.debug(
            "Original raw packet stored",
            extra={
                "packet_id": packet_id,
                "source": record["source"],
                "feed_type": record["feed_type"],
            },
        )
        return packet_id

    def store_many(self, payloads: list[Floor2IngestPayload]) -> list[str]:
        """Store multiple original raw packets.

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
        """Retrieve a single original raw packet by ID.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The stored record dict, or ``None`` if not found.
        """
        with self._lock:
            return self._store.get(packet_id)

    def get_raw_data(self, packet_id: str) -> dict[str, Any] | None:
        """Retrieve only the raw data dict for a packet.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The ``original_raw_packet`` data, or ``None`` if not found.
        """
        record = self.get(packet_id)
        if record is None:
            return None
        return record.get("data")

    def query(
        self,
        source: str | None = None,
        feed_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Query original raw packets by source, feed_type, and/or time range.

        Args:
            source: Filter by source name.
            feed_type: Filter by feed type.
            start_time: Include packets ingested at or after this time.
            end_time: Include packets ingested at or before this time.

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
                ts = record.get("timestamp")
                if start_time and ts and ts < start_time:
                    continue
                if end_time and ts and ts > end_time:
                    continue
                results.append(record)
        return results

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
            self._total_stored = 0
        logger.info("OriginalRawStore cleared")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total packets currently in the store."""
        with self._lock:
            return len(self._store)

    @property
    def total_stored(self) -> int:
        """Total packets stored since creation (includes deleted)."""
        with self._lock:
            return self._total_stored

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
