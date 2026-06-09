"""Tests for Floor 2 Replay Engine sub-system (Step 2.9).

Tests cover:
- ReplayEngine: replay from RAW/CLEANED/STRUCTURED stages, cross-stage compare
- ReplaySessionManager: session lifecycle, progress tracking, listing
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from junior_aladdin.floor_2_datacenter.cleaning.cleaned_layer_writer import (
    CleanedLayerWriter,
)
from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    CleaningResult,
    ReplayQuery,
    StructureResult,
    TransformStage,
    StreamType,
)
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.replay.replay_engine import ReplayEngine
from junior_aladdin.floor_2_datacenter.replay.session_manager import (
    SESSION_ACTIVE,
    SESSION_COMPLETED,
    SESSION_FAILED,
    ReplaySessionManager,
)
from junior_aladdin.floor_2_datacenter.structuring.structured_writer import (
    StructuredWriter,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_payload(
    packet_id: str,
    source: str = "angel_one",
    feed_type: str = "spot_tick",
    ingested_at: datetime | None = None,
) -> Floor2IngestPayload:
    """Create a Floor2IngestPayload for testing."""
    now = ingested_at or datetime.now(timezone.utc)
    return Floor2IngestPayload(
        original_raw_packet={"ltp": 18500.0, "volume": 1000},
        minimal_source_envelope={
            "packet_id": packet_id,
            "source": source,
            "feed_type": feed_type,
            "received_at": now.isoformat(),
        },
        feed_routing_identity="spot_tick_v1",
        source_health_facts={},
        manual_source_tags=None,
        ingested_at=now,
        ingest_batch_id="batch_001",
    )


def _populate_normalized_store(store: NormalizedRawStore) -> None:
    """Pre-populate a NormalizedRawStore with test data."""
    base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        ts = base_time + timedelta(seconds=i * 10)
        store.store(_make_payload(
            f"pkt_{i:03d}", source="angel_one", feed_type="spot_tick",
            ingested_at=ts,
        ))
    # Add a macro_data packet
    store.store(_make_payload(
        "pkt_macro", source="manual", feed_type="macro_data",
        ingested_at=base_time + timedelta(seconds=60),
    ))


# =============================================================================
# ReplayEngine Tests
# =============================================================================


class TestReplayEngine:
    @pytest.fixture
    def normalized_store(self) -> NormalizedRawStore:
        store = NormalizedRawStore()
        _populate_normalized_store(store)
        return store

    @pytest.fixture
    def cleaned_writer(self, normalized_store: NormalizedRawStore) -> CleanedLayerWriter:
        writer = CleanedLayerWriter()
        for pid in normalized_store.packet_ids:
            record = normalized_store.get(pid)
            if record:
                writer.write(
                    record,
                    CleaningResult(cleaned_record={"ltp": 18600.0, "volume": 500}),
                )
        return writer

    @pytest.fixture
    def structured_writer(self) -> StructuredWriter:
        writer = StructuredWriter()
        writer.write(StructureResult(
            stream_type=StreamType.TICK_STREAM,
            stream_data={"ticks": [1, 2, 3]},
            metadata={"stream_id": "ts_001", "source": "angel_one", "feed_type": "spot_tick"},
        ))
        writer.write(StructureResult(
            stream_type=StreamType.CANDLE_STREAM,
            stream_data={"candles": [{"o": 18500, "c": 18600}]},
            metadata={"stream_id": "cs_001", "source": "angel_one", "feed_type": "spot_tick"},
        ))
        return writer

    @pytest.fixture
    def engine(
        self,
        normalized_store: NormalizedRawStore,
        cleaned_writer: CleanedLayerWriter,
        structured_writer: StructuredWriter,
    ) -> ReplayEngine:
        return ReplayEngine(normalized_store, cleaned_writer, structured_writer)

    # ── RAW Replay ────────────────────────────────────────────────────

    def test_replay_raw_all(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            transform_stage=TransformStage.RAW,
        )
        result = engine.replay(query)
        assert result["count"] == 6
        assert result["stage"] == "RAW"
        assert len(result["packets"]) == 6

    def test_replay_raw_filtered_by_source(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            sources=["manual"],
            transform_stage=TransformStage.RAW,
        )
        result = engine.replay(query)
        assert result["count"] == 1
        assert result["packets"][0]["source"] == "manual"

    def test_replay_raw_filtered_by_feed_type(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            feed_types=["macro_data"],
            transform_stage=TransformStage.RAW,
        )
        result = engine.replay(query)
        assert result["count"] == 1
        assert result["packets"][0]["feed_type"] == "macro_data"

    def test_replay_raw_no_results(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 2, tzinfo=timezone.utc),  # No data in 2025
            transform_stage=TransformStage.RAW,
        )
        result = engine.replay(query)
        assert result["count"] == 0
        assert result["start_time"] is None

    def test_replay_raw_convenience(self, engine: ReplayEngine) -> None:
        result = engine.replay_raw()
        assert result["count"] == 6

    def test_replay_raw_with_time_range(self, engine: ReplayEngine) -> None:
        """Time filtering works; all test packets have stored_at=now so all pass."""
        start = datetime(2026, 1, 15, 10, 0, 20, tzinfo=timezone.utc)
        result = engine.replay_raw(start_time=start)
        assert result["count"] == 6  # All have stored_at=now, all pass filter

    # ── CLEANED Replay ────────────────────────────────────────────────

    def test_replay_cleaned_all(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            transform_stage=TransformStage.CLEANED,
        )
        result = engine.replay(query)
        assert result["count"] == 6
        assert result["stage"] == "CLEANED"

    def test_replay_cleaned_no_store(self) -> None:
        engine = ReplayEngine(NormalizedRawStore())
        result = engine.replay_cleaned()
        assert result["count"] == 0

    def test_replay_cleaned_filtered(self, engine: ReplayEngine) -> None:
        result = engine.replay_cleaned(feed_types=["macro_data"])
        assert result["count"] == 1

    # ── STRUCTURED Replay ─────────────────────────────────────────────

    def test_replay_structured_all(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            transform_stage=TransformStage.STRUCTURED,
        )
        result = engine.replay(query)
        assert result["count"] == 2
        assert result["stage"] == "STRUCTURED"

    def test_replay_structured_no_store(self) -> None:
        engine = ReplayEngine(NormalizedRawStore())
        result = engine.replay_structured()
        assert result["count"] == 0

    def test_replay_unsupported_stage(self, engine: ReplayEngine) -> None:
        """VALIDATED is not a supported replay stage."""
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            transform_stage=TransformStage.VALIDATED,
        )
        result = engine.replay(query)
        assert result["count"] == 0

    # ── Cross-Stage Comparison ────────────────────────────────────────

    def test_compare_across_stages(self, engine: ReplayEngine) -> None:
        compare = engine.compare_across_stages("pkt_000")
        assert compare["packet_id"] == "pkt_000"
        assert compare["raw"] is not None
        assert compare["cleaned"] is not None
        assert compare["structured"] is None  # Structured uses stream_ids

    def test_compare_across_stages_not_found(self, engine: ReplayEngine) -> None:
        compare = engine.compare_across_stages("nonexistent")
        assert compare["raw"] is None
        assert compare["cleaned"] is None

    def test_get_available_stages(self, engine: ReplayEngine) -> None:
        stages = engine.get_available_stages("pkt_000")
        assert "RAW" in stages
        assert "CLEANED" in stages

    def test_get_available_stages_not_found(self, engine: ReplayEngine) -> None:
        stages = engine.get_available_stages("nonexistent")
        assert stages == []

    # ── Result Shape ──────────────────────────────────────────────────

    def test_replay_result_shape(self, engine: ReplayEngine) -> None:
        query = ReplayQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
            transform_stage=TransformStage.RAW,
        )
        result = engine.replay(query)
        assert "packets" in result
        assert "count" in result
        assert "stage" in result
        assert "start_time" in result
        assert "end_time" in result
        assert "query" in result

    def test_replay_has_time_range(self, engine: ReplayEngine) -> None:
        result = engine.replay_raw()
        assert result["start_time"] is not None
        assert result["end_time"] is not None

    def test_replay_multiple_sources(self, engine: ReplayEngine) -> None:
        """Query uses first source; multi-source filter applies post-query."""
        result = engine.replay_raw(sources=["angel_one", "manual"])
        # Query fetches only angel_one (first source), then filters -> 5 remain
        assert result["count"] == 5

    def test_replay_multiple_feed_types(self, engine: ReplayEngine) -> None:
        """Query uses first feed_type; multi-feed filter applies post-query."""
        result = engine.replay_raw(feed_types=["spot_tick", "macro_data"])
        # Query fetches only spot_tick (first feed_type), then filters -> 5 remain
        assert result["count"] == 5


# =============================================================================
# ReplaySessionManager Tests
# =============================================================================


class TestReplaySessionManager:
    @pytest.fixture
    def manager(self) -> ReplaySessionManager:
        return ReplaySessionManager()

    @pytest.fixture
    def query(self) -> ReplayQuery:
        return ReplayQuery(
            start_time=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc),
            sources=["angel_one"],
            feed_types=["spot_tick"],
            transform_stage=TransformStage.RAW,
        )

    # ── Session Creation ──────────────────────────────────────────────

    def test_create_session(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        session = manager.create_session(query)
        assert session.session_id.startswith("sess_")
        assert session.status == SESSION_ACTIVE
        assert session.packets_replayed == 0
        assert session.query == query

    def test_create_session_with_custom_id(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query, session_id="my_session_001")
        assert session.session_id == "my_session_001"

    def test_create_session_with_metadata(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query, metadata={"description": "audit"})
        meta = manager.get_session_metadata(session.session_id)
        assert meta is not None
        assert meta.get("description") == "audit"

    # ── Session Lifecycle ─────────────────────────────────────────────

    def test_complete_session(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        session = manager.create_session(query)
        assert manager.complete_session(session.session_id) is True
        updated = manager.get_session(session.session_id)
        assert updated is not None
        assert updated.status == SESSION_COMPLETED

    def test_fail_session(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        session = manager.create_session(query)
        assert manager.fail_session(session.session_id, "Connection lost") is True
        updated = manager.get_session(session.session_id)
        assert updated is not None
        assert updated.status == SESSION_FAILED

        meta = manager.get_session_metadata(session.session_id)
        assert meta is not None
        assert meta.get("error_message") == "Connection lost"

    def test_complete_nonexistent_session(self, manager: ReplaySessionManager) -> None:
        assert manager.complete_session("nonexistent") is False

    def test_fail_nonexistent_session(self, manager: ReplaySessionManager) -> None:
        assert manager.fail_session("nonexistent") is False

    def test_cannot_recomplete_session(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query)
        manager.complete_session(session.session_id)
        assert manager.complete_session(session.session_id) is False

    def test_cannot_fail_completed_session(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query)
        manager.complete_session(session.session_id)
        assert manager.fail_session(session.session_id) is False

    # ── Progress Tracking ─────────────────────────────────────────────

    def test_increment_replayed(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query)
        assert manager.increment_replayed(session.session_id) is True
        updated = manager.get_session(session.session_id)
        assert updated is not None
        assert updated.packets_replayed == 1

    def test_increment_replayed_multiple(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query)
        manager.increment_replayed(session.session_id, count=10)
        updated = manager.get_session(session.session_id)
        assert updated is not None
        assert updated.packets_replayed == 10

    def test_set_replayed_count(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query)
        assert manager.set_replayed_count(session.session_id, 25) is True
        updated = manager.get_session(session.session_id)
        assert updated is not None
        assert updated.packets_replayed == 25

    def test_increment_nonexistent(self, manager: ReplaySessionManager) -> None:
        assert manager.increment_replayed("nonexistent") is False

    # ── Session Querying ──────────────────────────────────────────────

    def test_get_session(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        session = manager.create_session(query)
        retrieved = manager.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    def test_get_session_nonexistent(self, manager: ReplaySessionManager) -> None:
        assert manager.get_session("nonexistent") is None

    def test_get_session_metadata(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query, metadata={"key": "val"})
        meta = manager.get_session_metadata(session.session_id)
        assert meta is not None
        assert meta.get("key") == "val"

    def test_get_session_metadata_nonexistent(self, manager: ReplaySessionManager) -> None:
        assert manager.get_session_metadata("nonexistent") is None

    def test_list_sessions(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        manager.create_session(query)
        manager.create_session(query)
        assert len(manager.list_sessions()) == 2

    def test_list_sessions_by_status(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        s1 = manager.create_session(query)
        s2 = manager.create_session(query, session_id="sess_002")
        manager.complete_session(s1.session_id)

        active = manager.list_sessions(status=SESSION_ACTIVE)
        assert len(active) == 1
        assert active[0].session_id == s2.session_id

        completed = manager.list_sessions(status=SESSION_COMPLETED)
        assert len(completed) == 1

    def test_get_active_sessions(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        s1 = manager.create_session(query)
        manager.create_session(query)
        manager.complete_session(s1.session_id)

        active = manager.get_active_sessions()
        assert len(active) == 1

    def test_count_sessions(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        manager.create_session(query)
        manager.create_session(query)
        assert manager.count_sessions() == 2

    def test_count_sessions_by_status(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        s = manager.create_session(query)
        manager.complete_session(s.session_id)
        assert manager.count_sessions(status=SESSION_ACTIVE) == 0
        assert manager.count_sessions(status=SESSION_COMPLETED) == 1

    def test_has_active_sessions(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        assert manager.has_active_sessions() is False
        manager.create_session(query)
        assert manager.has_active_sessions() is True

    # ── Session Management ────────────────────────────────────────────

    def test_delete_session(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        session = manager.create_session(query)
        assert manager.delete_session(session.session_id) is True
        assert manager.get_session(session.session_id) is None

    def test_delete_nonexistent(self, manager: ReplaySessionManager) -> None:
        assert manager.delete_session("nonexistent") is False

    def test_clear(self, manager: ReplaySessionManager, query: ReplayQuery) -> None:
        manager.create_session(query)
        manager.create_session(query)
        manager.clear()
        assert manager.count_sessions() == 0

    # ── Session Summary ───────────────────────────────────────────────

    def test_get_session_summary(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query, metadata={"description": "test"})
        summary = manager.get_session_summary(session.session_id)
        assert summary is not None
        assert summary["session_id"] == session.session_id
        assert summary["status"] == SESSION_ACTIVE
        assert summary["packets_replayed"] == 0
        assert summary["query"]["sources"] == ["angel_one"]
        assert summary["query"]["transform_stage"] == "RAW"

    def test_get_session_summary_nonexistent(self, manager: ReplaySessionManager) -> None:
        assert manager.get_session_summary("nonexistent") is None

    def test_get_session_summary_failed(
        self, manager: ReplaySessionManager, query: ReplayQuery,
    ) -> None:
        session = manager.create_session(query)
        manager.fail_session(session.session_id, "Error!")
        summary = manager.get_session_summary(session.session_id)
        assert summary is not None
        assert summary["status"] == SESSION_FAILED
        assert summary["error_message"] == "Error!"
