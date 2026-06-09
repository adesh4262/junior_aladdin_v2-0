"""Floor 2 Cleaning — cleaned layer writer.

Stores cleaned records in an in-memory store, indexed by ``packet_id``,
with references to the original raw record metadata and the cleaning
result.

Architecture rules:
- Cleaned layer = validation-passed, anomaly-repaired data.
- Every cleaned record is traceable back to its original raw packet.
- In-memory dict storage for dev; interface is swappable to SQLite later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import CleaningResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("cleaned_layer_writer")


class CleanedLayerWriter:
    """In-memory store for cleaned packet records.

    Thread-safe. Indexed by ``packet_id`` with full traceability back to
    the original raw packet.

    Typical usage::

        writer = CleanedLayerWriter()
        writer.write(record, cleaning_result)
        cleaned = writer.get("pkt_001")
        results = writer.query(feed_type="spot_tick")
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # packet_id -> cleaned record dict
        self._store: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def write(
        self,
        record: dict[str, Any],
        cleaning_result: CleaningResult,
    ) -> str | None:
        """Store a cleaned record.

        Args:
            record: The original packet record (for metadata traceability).
            cleaning_result: The output from a cleaner or anomaly repair.

        Returns:
            The ``packet_id`` if stored, or ``None`` if the packet was
            removed (``cleaning_result.removed=True``).
        """
        if cleaning_result.removed:
            return None

        packet_id = record.get("packet_id", "")
        if not packet_id:
            logger.warning("Cannot store cleaned record — no packet_id")
            return None

        cleaned_entry = {
            "packet_id": packet_id,
            "cleaned_data": cleaning_result.cleaned_record,
            "source": record.get("source", "unknown"),
            "feed_type": record.get("feed_type", "unknown"),
            "original_packet_id": packet_id,
            "repaired": cleaning_result.repaired,
            "repair_action": cleaning_result.repair_action,
            "anomaly_flags": list(cleaning_result.anomaly_flags),
            "written_at": datetime.now(timezone.utc),
            "original_values": cleaning_result.original_values,
        }

        with self._lock:
            self._store[packet_id] = cleaned_entry

        logger.debug(
            "Cleaned record stored",
            extra={
                "packet_id": packet_id,
                "feed_type": cleaned_entry["feed_type"],
                "repaired": cleaning_result.repaired,
                "anomalies": len(cleaning_result.anomaly_flags),
            },
        )
        return packet_id

    def get(self, packet_id: str) -> dict[str, Any] | None:
        """Retrieve a cleaned record by ID.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The cleaned record dict, or ``None`` if not found.
        """
        with self._lock:
            return self._store.get(packet_id)

    def get_cleaned_data(self, packet_id: str) -> dict[str, Any] | None:
        """Retrieve only the cleaned data dict for a packet.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The ``cleaned_data`` dict, or ``None`` if not found.
        """
        entry = self.get(packet_id)
        if entry is None:
            return None
        return entry.get("cleaned_data")

    def query(
        self,
        feed_type: str | None = None,
        source: str | None = None,
        only_repaired: bool = False,
    ) -> list[dict[str, Any]]:
        """Query cleaned records by feed_type, source, or repair status.

        Args:
            feed_type: Filter by feed type.
            source: Filter by source name.
            only_repaired: If ``True``, return only records that were repaired.

        Returns:
            List of matching cleaned record entries.
        """
        results: list[dict[str, Any]] = []
        with self._lock:
            for entry in self._store.values():
                if feed_type and entry.get("feed_type") != feed_type:
                    continue
                if source and entry.get("source") != source:
                    continue
                if only_repaired and not entry.get("repaired"):
                    continue
                results.append(entry)
        return results

    def count_repaired(self) -> int:
        """Return the number of records that had repairs applied."""
        with self._lock:
            return sum(1 for e in self._store.values() if e.get("repaired"))

    def delete(self, packet_id: str) -> bool:
        """Delete a single cleaned record by ID.

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
        """Remove ALL cleaned records."""
        with self._lock:
            self._store.clear()
        logger.info("CleanedLayerWriter cleared")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total cleaned records in the store."""
        with self._lock:
            return len(self._store)

    @property
    def packet_ids(self) -> list[str]:
        """List of all packet IDs currently in the store."""
        with self._lock:
            return list(self._store.keys())

    @property
    def feed_types(self) -> set[str]:
        """Set of all feed types in the store."""
        with self._lock:
            return {e.get("feed_type", "unknown") for e in self._store.values()}
