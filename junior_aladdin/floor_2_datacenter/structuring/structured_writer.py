"""Floor 2 Structuring — structured writer.

Stores structured products (``StructureResult`` objects) in an in-memory
store, indexed by stream type and stream ID.

Architecture rules:
- Each stored product is traceable to its stream type and build time.
- Supports query by stream type for downstream consumption (Floor 3 handoff).
- In-memory dict storage for dev; interface is swappable to SQLite later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType, StructureResult
from junior_aladdin.shared.logging import get_logger

logger = get_logger("structured_writer")


class StructuredWriter:
    """In-memory store for structured products.

    Thread-safe. Indexed by ``stream_id`` with a secondary index on
    ``stream_type`` for type-based queries.

    Typical usage::

        writer = StructuredWriter()
        writer.write(tick_stream_result)
        writer.write(candle_stream_result)
        all_ticks = writer.get_by_type(StreamType.TICK_STREAM)
        latest = writer.get_latest(StreamType.CANDLE_STREAM)
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # stream_id -> StructureResult-like dict
        self._store: dict[str, dict[str, Any]] = {}
        # stream_type -> list of stream_ids (maintains order)
        self._type_index: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def write(self, result: StructureResult) -> str:
        """Store a structured product.

        Args:
            result: The ``StructureResult`` from any builder.

        Returns:
            The ``stream_id`` under which the product was stored.
        """
        stream_id = (
            result.metadata.get("stream_id")
            or f"{result.stream_type.value}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
        )

        entry = {
            "stream_id": stream_id,
            "stream_type": result.stream_type.value,
            "stream_data": result.stream_data,
            "metadata": dict(result.metadata),
            "written_at": datetime.now(timezone.utc),
        }

        with self._lock:
            self._store[stream_id] = entry
            type_key = result.stream_type.value
            if type_key not in self._type_index:
                self._type_index[type_key] = []
            self._type_index[type_key].append(stream_id)

        logger.debug(
            "Structured product stored",
            extra={
                "stream_id": stream_id,
                "stream_type": result.stream_type.value,
            },
        )
        return stream_id

    def get(self, stream_id: str) -> dict[str, Any] | None:
        """Retrieve a structured product by stream ID.

        Args:
            stream_id: The unique stream identifier.

        Returns:
            The entry dict, or ``None`` if not found.
        """
        with self._lock:
            return self._store.get(stream_id)

    def get_by_type(self, stream_type: StreamType) -> list[dict[str, Any]]:
        """Retrieve all entries of a given stream type.

        Args:
            stream_type: The stream type to query.

        Returns:
            List of entry dicts, ordered by write time.
        """
        with self._lock:
            ids = self._type_index.get(stream_type.value, [])
            return [self._store[sid] for sid in ids if sid in self._store]

    def get_latest(self, stream_type: StreamType) -> dict[str, Any] | None:
        """Retrieve the most recently written entry of a given stream type.

        Args:
            stream_type: The stream type to query.

        Returns:
            The latest entry dict, or ``None`` if none exist.
        """
        entries = self.get_by_type(stream_type)
        if not entries:
            return None
        # Entries are ordered by write time, last is most recent
        return entries[-1]

    def get_stream_data(self, stream_type: StreamType) -> Any:
        """Get the raw stream data of the latest entry for a stream type.

        Convenience method for Floor 3 handoff building.

        Args:
            stream_type: The stream type to query.

        Returns:
            The ``stream_data`` of the latest entry, or a default empty
            object if none exist.
        """
        latest = self.get_latest(stream_type)
        if latest is None:
            return None
        return latest.get("stream_data")

    def delete(self, stream_id: str) -> bool:
        """Delete a single structured product by ID.

        Args:
            stream_id: The unique stream identifier.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        with self._lock:
            if stream_id not in self._store:
                return False
            entry = self._store.pop(stream_id)
            type_key = entry.get("stream_type", "")
            if type_key in self._type_index:
                try:
                    self._type_index[type_key].remove(stream_id)
                except ValueError:
                    pass
            return True

    def clear(self) -> None:
        """Remove ALL structured products."""
        with self._lock:
            self._store.clear()
            self._type_index.clear()
        logger.info("StructuredWriter cleared")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total structured products in the store."""
        with self._lock:
            return len(self._store)

    @property
    def stream_types(self) -> set[str]:
        """Set of all stream types in the store."""
        with self._lock:
            return set(self._type_index.keys())

    def count_by_type(self, stream_type: StreamType) -> int:
        """Count entries of a given stream type."""
        with self._lock:
            return len(self._type_index.get(stream_type.value, []))
