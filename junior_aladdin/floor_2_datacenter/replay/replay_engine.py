"""Floor 2 Replay Engine — query and replay packets from pipeline stages.

Provides the **ReplayEngine** class that queries packets from any pipeline
stage (RAW, CLEANED, STRUCTURED) and replays them with full traceability.

Responsibilities:
- **RAW replay**: Query packets from ``NormalizedRawStore`` or ``OriginalRawStore``.
- **CLEANED replay**: Query cleaned records from ``CleanedLayerWriter``.
- **STRUCTURED replay**: Query structured products from ``StructuredWriter``.
- **Cross-stage replay**: Compare the same packet across multiple stages.
- **Replay result**: Package replayed packets with metadata (count, time range).

Architecture rules:
- Replay is FACTUAL — returns exact copies of stored data, never modified.
- Replay does NOT re-run validation, cleaning, or structuring.
- Supports time-range, source, and feed-type filtering.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    ReplayQuery,
    ReplaySession,
    TransformStage,
)
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.raw.original_raw_store import OriginalRawStore
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("replay_engine")


class ReplayEngine:
    """Queries and replays packets from any pipeline stage.

    Supports replay from three stages:
    - ``RAW``: Queries ``NormalizedRawStore`` (and optionally ``OriginalRawStore``).
    - ``CLEANED``: Queries ``CleanedLayerWriter``.
    - ``STRUCTURED``: Queries ``StructuredWriter``.

    Typical usage::

        engine = ReplayEngine(normalized_store, cleaned_writer, structured_writer)
        query = ReplayQuery(start_time=..., end_time=...)
        result = engine.replay(query)
        raw_packets = engine.replay_raw(query)
        cleaned = engine.replay_cleaned(query)
    """

    def __init__(
        self,
        normalized_store: NormalizedRawStore,
        cleaned_writer: CleanedLayerWriter | None = None,
        structured_writer: StructuredWriter | None = None,
        original_store: OriginalRawStore | None = None,
    ) -> None:
        """Initialise the replay engine.

        Args:
            normalized_store: The normalised raw store (required).
            cleaned_writer: The cleaned layer writer (optional, needed for
                CLEANED replay).
            structured_writer: The structured writer (optional, needed for
                STRUCTURED replay).
            original_store: The original raw store (optional, for cross-stage
                comparisons).
        """
        self._normalized_store = normalized_store
        self._cleaned_writer = cleaned_writer
        self._structured_writer = structured_writer
        self._original_store = original_store

    # ------------------------------------------------------------------
    # Main Replay API
    # ------------------------------------------------------------------

    def replay(self, query: ReplayQuery) -> dict[str, Any]:
        """Replay packets according to the given query.

        Args:
            query: The ``ReplayQuery`` specifying time range, filters, and
                transform stage.

        Returns:
            A dict with:
            - ``packets``: List of replayed packet dicts.
            - ``count``: Number of packets replayed.
            - ``stage``: The ``TransformStage`` used for replay.
            - ``start_time``: ISO timestamp of the earliest packet.
            - ``end_time``: ISO timestamp of the latest packet.
            - ``query``: The original query parameters.
        """
        stage = query.transform_stage

        if stage == TransformStage.RAW:
            return self._replay_from_raw(query)
        elif stage == TransformStage.CLEANED:
            return self._replay_from_cleaned(query)
        elif stage == TransformStage.STRUCTURED:
            return self._replay_from_structured(query)
        else:
            logger.warning(
                "Unsupported transform stage for replay",
                extra={"stage": stage.value},
            )
            return {
                "packets": [],
                "count": 0,
                "stage": stage.value,
                "start_time": None,
                "end_time": None,
                "query": self._query_to_dict(query),
            }

    # ------------------------------------------------------------------
    # Stage-Specific Replay
    # ------------------------------------------------------------------

    def replay_raw(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        sources: list[str] | None = None,
        feed_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Replay raw packets from the normalised store.

        Args:
            start_time: Include packets at or after this time.
            end_time: Include packets at or before this time.
            sources: Filter by source names.
            feed_types: Filter by feed types.

        Returns:
            A replay result dict with replayed raw packets.
        """
        records = self._normalized_store.query(
            source=sources[0] if sources else None,
            feed_type=feed_types[0] if feed_types else None,
            start_time=start_time,
            end_time=end_time,
        )

        # Apply multi-source/feed-type filtering (query() only supports single)
        if sources and len(sources) > 1:
            records = [r for r in records if r.get("source") in sources]
        if feed_types and len(feed_types) > 1:
            records = [r for r in records if r.get("feed_type") in feed_types]

        return self._build_result(
            packets=records,
            stage=TransformStage.RAW,
            query_sources=sources,
            query_feed_types=feed_types,
        )

    def replay_cleaned(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        sources: list[str] | None = None,
        feed_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Replay cleaned records from the cleaned layer writer.

        Args:
            start_time: Include records at or after this time.
            end_time: Include records at or before this time.
            sources: Filter by source names.
            feed_types: Filter by feed types.

        Returns:
            A replay result dict with replayed cleaned records.
        """
        if self._cleaned_writer is None:
            return self._empty_result(TransformStage.CLEANED)

        records = self._cleaned_writer.query(
            feed_type=feed_types[0] if feed_types else None,
            source=sources[0] if sources else None,
        )

        # Apply time range filtering
        if start_time or end_time:
            records = [
                r for r in records
                if self._in_time_range(r.get("written_at"), start_time, end_time)
            ]

        # Apply multi-source/feed-type filtering
        if sources and len(sources) > 1:
            records = [r for r in records if r.get("source") in sources]
        if feed_types and len(feed_types) > 1:
            records = [r for r in records if r.get("feed_type") in feed_types]

        return self._build_result(
            packets=records,
            stage=TransformStage.CLEANED,
            query_sources=sources,
            query_feed_types=feed_types,
        )

    def replay_structured(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        sources: list[str] | None = None,
        feed_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Replay structured products from the structured writer.

        Args:
            start_time: Include products at or after this time.
            end_time: Include products at or before this time.
            sources: Filter by source names (from metadata).
            feed_types: Filter by feed types (from metadata).

        Returns:
            A replay result dict with replayed structured products.
        """
        if self._structured_writer is None:
            return self._empty_result(TransformStage.STRUCTURED)

        # Query all entries, filter by time and source/feed_type from metadata
        all_entries: list[dict[str, Any]] = []
        for stream_type_key in self._structured_writer.stream_types:
            from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType
            try:
                stream_type = StreamType(stream_type_key)
                entries = self._structured_writer.get_by_type(stream_type)
                all_entries.extend(entries)
            except (ValueError, TypeError):
                pass

        # Apply time range filtering
        if start_time or end_time:
            all_entries = [
                e for e in all_entries
                if self._in_time_range(e.get("written_at"), start_time, end_time)
            ]

        # Apply source/feed_type filtering from metadata
        if sources:
            all_entries = [
                e for e in all_entries
                if e.get("metadata", {}).get("source") in sources
                or e.get("stream_data", {}).get("source") in sources
            ]
        if feed_types:
            all_entries = [
                e for e in all_entries
                if e.get("metadata", {}).get("feed_type") in feed_types
                or e.get("stream_data", {}).get("feed_type") in feed_types
            ]

        return self._build_result(
            packets=all_entries,
            stage=TransformStage.STRUCTURED,
            query_sources=sources,
            query_feed_types=feed_types,
        )

    # ------------------------------------------------------------------
    # Cross-Stage Comparison
    # ------------------------------------------------------------------

    def compare_across_stages(
        self,
        packet_id: str,
    ) -> dict[str, Any]:
        """Fetch the same packet across all available stages.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            A dict with keys ``raw``, ``cleaned``, ``structured`` — each
            containing the record from that stage, or ``None`` if not
            available.
        """
        raw = self._normalized_store.get(packet_id)
        cleaned = self._cleaned_writer.get(packet_id) if self._cleaned_writer else None
        structured = None
        if self._structured_writer:
            for sid in self._structured_writer.stream_types:
                from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType
                try:
                    entries = self._structured_writer.get_by_type(StreamType(sid))
                    for entry in entries:
                        meta_id = entry.get("metadata", {}).get("stream_id")
                        if meta_id == packet_id:
                            structured = entry
                            break
                except (ValueError, TypeError):
                    pass

        return {
            "packet_id": packet_id,
            "raw": raw,
            "cleaned": cleaned,
            "structured": structured,
        }

    def get_available_stages(self, packet_id: str) -> list[str]:
        """List which stages have data for a given packet.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            List of stage names that have data for this packet.
        """
        stages = []
        if self._normalized_store.get(packet_id):
            stages.append("RAW")
        if self._cleaned_writer and self._cleaned_writer.get(packet_id):
            stages.append("CLEANED")
        # Structured writer uses stream_ids, not packet_ids — check metadata
        if self._structured_writer:
            for sid in self._structured_writer.stream_types:
                from junior_aladdin.floor_2_datacenter.datacenter_types import StreamType
                try:
                    entries = self._structured_writer.get_by_type(StreamType(sid))
                    for entry in entries:
                        if entry.get("metadata", {}).get("stream_id") == packet_id:
                            stages.append("STRUCTURED")
                            break
                except (ValueError, TypeError):
                    pass
                    break

        return stages

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _replay_from_raw(self, query: ReplayQuery) -> dict[str, Any]:
        """Replay from the normalised raw store using query params."""
        return self.replay_raw(
            start_time=query.start_time,
            end_time=query.end_time,
            sources=query.sources,
            feed_types=query.feed_types,
        )

    def _replay_from_cleaned(self, query: ReplayQuery) -> dict[str, Any]:
        """Replay from the cleaned layer writer using query params."""
        return self.replay_cleaned(
            start_time=query.start_time,
            end_time=query.end_time,
            sources=query.sources,
            feed_types=query.feed_types,
        )

    def _replay_from_structured(self, query: ReplayQuery) -> dict[str, Any]:
        """Replay from the structured writer using query params."""
        return self.replay_structured(
            start_time=query.start_time,
            end_time=query.end_time,
            sources=query.sources,
            feed_types=query.feed_types,
        )

    def _build_result(
        self,
        packets: list[dict[str, Any]],
        stage: TransformStage,
        query_sources: list[str] | None = None,
        query_feed_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a standardised replay result dict."""
        timestamps = []
        for p in packets:
            ts = (
                p.get("stored_at")
                or p.get("written_at")
                or p.get("timestamp")
                or p.get("ingested_at")
            )
            if ts:
                timestamps.append(ts)

        return {
            "packets": packets,
            "count": len(packets),
            "stage": stage.value,
            "start_time": min(timestamps).isoformat() if timestamps else None,
            "end_time": max(timestamps).isoformat() if timestamps else None,
            "query": {
                "sources": query_sources,
                "feed_types": query_feed_types,
                "transform_stage": stage.value,
            },
        }

    def _empty_result(self, stage: TransformStage) -> dict[str, Any]:
        """Return an empty result when a store is not available."""
        return {
            "packets": [],
            "count": 0,
            "stage": stage.value,
            "start_time": None,
            "end_time": None,
            "query": {
                "sources": None,
                "feed_types": None,
                "transform_stage": stage.value,
            },
        }

    @staticmethod
    def _in_time_range(
        ts: Any,
        start: datetime | None,
        end: datetime | None,
    ) -> bool:
        """Check if a timestamp falls within the given range."""
        if ts is None:
            return True
        if start and ts < start:
            return False
        if end and ts > end:
            return False
        return True

    @staticmethod
    def _query_to_dict(query: ReplayQuery) -> dict[str, Any]:
        """Convert a ReplayQuery to a dict for result metadata."""
        return {
            "start_time": query.start_time.isoformat() if query.start_time else None,
            "end_time": query.end_time.isoformat() if query.end_time else None,
            "sources": query.sources,
            "feed_types": query.feed_types,
            "transform_stage": query.transform_stage.value,
        }
