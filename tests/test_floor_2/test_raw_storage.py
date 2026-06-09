"""Tests for Floor 2 Raw Storage sub-system (Step 2.3).

Tests cover:
- original_raw_store: store, get, query, delete, clear, properties
- normalized_raw_store: store, get, query, update_transform_stage, delete, clear
- raw_retention_manager: policies, expiry, purge, cross-store operations
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from junior_aladdin.floor_2_datacenter.datacenter_contracts import Floor2IngestPayload
from junior_aladdin.floor_2_datacenter.datacenter_types import TransformStage
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.raw.original_raw_store import OriginalRawStore
from junior_aladdin.floor_2_datacenter.raw.raw_retention_manager import (
    DEFAULT_MAJOR_RETENTION_S,
    DEFAULT_MINOR_RETENTION_S,
    RawRetentionManager,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def payload_spot() -> Floor2IngestPayload:
    """A typical spot tick ingest payload."""
    return Floor2IngestPayload(
        original_raw_packet={"ltp": 18500.0, "volume": 1500},
        minimal_source_envelope={
            "source": "angel_one",
            "feed_type": "spot_tick",
            "connection_id": "conn_001",
            "packet_id": "pkt_spot_001",
            "routing_id": "SPOT_FEED",
            "received_at": "2026-01-15T10:30:00+00:00",
        },
        feed_routing_identity="SPOT_FEED",
        source_health_facts={"lifecycle_state": "HEALTHY"},
        manual_source_tags=None,
        ingested_at=datetime.now(timezone.utc),
        ingest_batch_id="ig_batch_001",
    )


@pytest.fixture
def payload_vix() -> Floor2IngestPayload:
    """A VIX tick ingest payload."""
    return Floor2IngestPayload(
        original_raw_packet={"value": 14.5},
        minimal_source_envelope={
            "source": "angel_one",
            "feed_type": "vix_tick",
            "connection_id": "conn_001",
            "packet_id": "pkt_vix_001",
            "routing_id": "VIX_FEED",
            "received_at": "2026-01-15T10:30:01+00:00",
        },
        feed_routing_identity="VIX_FEED",
        source_health_facts={"lifecycle_state": "HEALTHY"},
        manual_source_tags=None,
        ingested_at=datetime.now(timezone.utc),
        ingest_batch_id="ig_batch_001",
    )


@pytest.fixture
def payload_manual() -> Floor2IngestPayload:
    """A manual calendar event ingest payload."""
    return Floor2IngestPayload(
        original_raw_packet={"event": "NIFTY expiry", "date": "2026-03-26"},
        minimal_source_envelope={
            "source": "manual",
            "feed_type": "calendar_event",
            "connection_id": "conn_manual",
            "packet_id": "pkt_manual_001",
            "routing_id": "MANUAL",
            "received_at": "2026-01-15T10:30:00+00:00",
        },
        feed_routing_identity="",
        source_health_facts={},
        manual_source_tags={"tag": "expiry_update", "value": "2026-03-26"},
        ingested_at=datetime.now(timezone.utc),
        ingest_batch_id="ig_batch_002",
    )


@pytest.fixture
def original_store() -> OriginalRawStore:
    return OriginalRawStore()


@pytest.fixture
def normalized_store() -> NormalizedRawStore:
    return NormalizedRawStore()


@pytest.fixture
def retention_manager() -> RawRetentionManager:
    return RawRetentionManager()


# =============================================================================
# OriginalRawStore tests
# =============================================================================


class TestOriginalRawStore:
    """Tests for ``OriginalRawStore``."""

    def test_store_and_get(self, original_store: OriginalRawStore,
                           payload_spot: Floor2IngestPayload) -> None:
        pid = original_store.store(payload_spot)
        assert pid == "pkt_spot_001"

        record = original_store.get("pkt_spot_001")
        assert record is not None
        assert record["data"] == {"ltp": 18500.0, "volume": 1500}
        assert record["source"] == "angel_one"
        assert record["feed_type"] == "spot_tick"

    def test_store_returns_none_if_no_packet_id(
        self, original_store: OriginalRawStore,
    ) -> None:
        payload = Floor2IngestPayload(
            minimal_source_envelope={},
        )
        pid = original_store.store(payload)
        assert pid is None

    def test_get_raw_data(self, original_store: OriginalRawStore,
                          payload_spot: Floor2IngestPayload) -> None:
        original_store.store(payload_spot)
        data = original_store.get_raw_data("pkt_spot_001")
        assert data == {"ltp": 18500.0, "volume": 1500}

    def test_get_raw_data_missing(self, original_store: OriginalRawStore) -> None:
        assert original_store.get_raw_data("nonexistent") is None

    def test_store_many(self, original_store: OriginalRawStore,
                        payload_spot: Floor2IngestPayload,
                        payload_vix: Floor2IngestPayload) -> None:
        pids = original_store.store_many([payload_spot, payload_vix])
        assert pids == ["pkt_spot_001", "pkt_vix_001"]
        assert original_store.count == 2

    def test_query_by_source(self, original_store: OriginalRawStore,
                             payload_spot: Floor2IngestPayload,
                             payload_vix: Floor2IngestPayload,
                             payload_manual: Floor2IngestPayload) -> None:
        original_store.store_many([payload_spot, payload_vix, payload_manual])

        results = original_store.query(source="angel_one")
        assert len(results) == 2

        results = original_store.query(source="manual")
        assert len(results) == 1

    def test_query_by_feed_type(self, original_store: OriginalRawStore,
                                payload_spot: Floor2IngestPayload,
                                payload_vix: Floor2IngestPayload) -> None:
        original_store.store_many([payload_spot, payload_vix])

        results = original_store.query(feed_type="spot_tick")
        assert len(results) == 1
        assert results[0]["data"]["ltp"] == 18500.0

    def test_query_by_time(self, original_store: OriginalRawStore,
                           payload_spot: Floor2IngestPayload) -> None:
        original_store.store(payload_spot)

        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)

        results = original_store.query(start_time=past)
        assert len(results) == 1

        results = original_store.query(start_time=future)
        assert len(results) == 0

    def test_delete(self, original_store: OriginalRawStore,
                    payload_spot: Floor2IngestPayload) -> None:
        original_store.store(payload_spot)
        assert original_store.count == 1

        assert original_store.delete("pkt_spot_001") is True
        assert original_store.count == 0
        assert original_store.get("pkt_spot_001") is None

    def test_delete_nonexistent(self, original_store: OriginalRawStore) -> None:
        assert original_store.delete("nonexistent") is False

    def test_clear(self, original_store: OriginalRawStore,
                   payload_spot: Floor2IngestPayload) -> None:
        original_store.store(payload_spot)
        original_store.clear()
        assert original_store.count == 0

    def test_properties(self, original_store: OriginalRawStore,
                        payload_spot: Floor2IngestPayload,
                        payload_vix: Floor2IngestPayload) -> None:
        assert original_store.count == 0
        assert original_store.total_stored == 0
        assert original_store.sources == set()
        assert original_store.feed_types == set()

        original_store.store_many([payload_spot, payload_vix])

        assert original_store.count == 2
        assert original_store.total_stored == 2
        assert original_store.sources == {"angel_one"}
        assert original_store.feed_types == {"spot_tick", "vix_tick"}

    def test_total_stored_persists_after_delete(
        self, original_store: OriginalRawStore,
        payload_spot: Floor2IngestPayload,
    ) -> None:
        original_store.store(payload_spot)
        original_store.delete("pkt_spot_001")
        assert original_store.total_stored == 1
        assert original_store.count == 0

    def test_packet_ids(self, original_store: OriginalRawStore,
                        payload_spot: Floor2IngestPayload,
                        payload_vix: Floor2IngestPayload) -> None:
        original_store.store_many([payload_spot, payload_vix])
        assert set(original_store.packet_ids) == {"pkt_spot_001", "pkt_vix_001"}


# =============================================================================
# NormalizedRawStore tests
# =============================================================================


class TestNormalizedRawStore:
    """Tests for ``NormalizedRawStore``."""

    def test_store_and_get(self, normalized_store: NormalizedRawStore,
                           payload_spot: Floor2IngestPayload) -> None:
        pid = normalized_store.store(payload_spot)
        assert pid == "pkt_spot_001"

        record = normalized_store.get("pkt_spot_001")
        assert record is not None
        assert record["feed_routing_identity"] == "SPOT_FEED"
        assert record["transform_stage"] == "RAW"
        assert record["ingest_batch_id"] == "ig_batch_001"
        assert "stored_at" in record

    def test_get_payload(self, normalized_store: NormalizedRawStore,
                         payload_spot: Floor2IngestPayload) -> None:
        normalized_store.store(payload_spot)
        result = normalized_store.get_payload("pkt_spot_001")
        assert result is not None
        assert result["feed_routing_identity"] == "SPOT_FEED"
        assert result["ingest_batch_id"] == "ig_batch_001"
        assert result["original_raw_packet"] == {"ltp": 18500.0, "volume": 1500}

    def test_get_payload_missing(self, normalized_store: NormalizedRawStore) -> None:
        assert normalized_store.get_payload("nonexistent") is None

    def test_get_missing(self, normalized_store: NormalizedRawStore) -> None:
        assert normalized_store.get("nonexistent") is None

    def test_store_returns_none_if_no_packet_id(
        self, normalized_store: NormalizedRawStore,
    ) -> None:
        payload = Floor2IngestPayload(minimal_source_envelope={})
        assert normalized_store.store(payload) is None

    def test_store_many(self, normalized_store: NormalizedRawStore,
                        payload_spot: Floor2IngestPayload,
                        payload_vix: Floor2IngestPayload) -> None:
        pids = normalized_store.store_many([payload_spot, payload_vix])
        assert len(pids) == 2
        assert normalized_store.count == 2

    def test_query_by_source(self, normalized_store: NormalizedRawStore,
                             payload_spot: Floor2IngestPayload,
                             payload_manual: Floor2IngestPayload) -> None:
        normalized_store.store_many([payload_spot, payload_manual])

        results = normalized_store.query(source="angel_one")
        assert len(results) == 1

        results = normalized_store.query(source="manual")
        assert len(results) == 1

    def test_query_by_feed_type(self, normalized_store: NormalizedRawStore,
                                payload_spot: Floor2IngestPayload,
                                payload_vix: Floor2IngestPayload) -> None:
        normalized_store.store_many([payload_spot, payload_vix])

        results = normalized_store.query(feed_type="vix_tick")
        assert len(results) == 1

    def test_update_transform_stage(self, normalized_store: NormalizedRawStore,
                                    payload_spot: Floor2IngestPayload) -> None:
        normalized_store.store(payload_spot)

        # Initial stage should be RAW
        record = normalized_store.get("pkt_spot_001")
        assert record is not None
        assert record["transform_stage"] == "RAW"

        # Update to VALIDATED
        result = normalized_store.update_transform_stage(
            "pkt_spot_001", TransformStage.VALIDATED,
        )
        assert result is True

        record = normalized_store.get("pkt_spot_001")
        assert record is not None
        assert record["transform_stage"] == "VALIDATED"

    def test_update_transform_stage_nonexistent(
        self, normalized_store: NormalizedRawStore,
    ) -> None:
        result = normalized_store.update_transform_stage(
            "nonexistent", TransformStage.CLEANED,
        )
        assert result is False

    def test_update_transform_stage_sequence(
        self, normalized_store: NormalizedRawStore,
        payload_spot: Floor2IngestPayload,
    ) -> None:
        """Should allow progression through all stages."""
        normalized_store.store(payload_spot)
        stages = [
            TransformStage.VALIDATED,
            TransformStage.CLEANED,
            TransformStage.STRUCTURED,
        ]
        for stage in stages:
            assert normalized_store.update_transform_stage("pkt_spot_001", stage)

        record = normalized_store.get("pkt_spot_001")
        assert record is not None
        assert record["transform_stage"] == "STRUCTURED"

    def test_delete(self, normalized_store: NormalizedRawStore,
                    payload_spot: Floor2IngestPayload) -> None:
        normalized_store.store(payload_spot)
        assert normalized_store.count == 1

        assert normalized_store.delete("pkt_spot_001") is True
        assert normalized_store.count == 0

    def test_delete_nonexistent(self, normalized_store: NormalizedRawStore) -> None:
        assert normalized_store.delete("nonexistent") is False

    def test_clear(self, normalized_store: NormalizedRawStore,
                   payload_spot: Floor2IngestPayload) -> None:
        normalized_store.store(payload_spot)
        normalized_store.clear()
        assert normalized_store.count == 0

    def test_properties(self, normalized_store: NormalizedRawStore,
                        payload_spot: Floor2IngestPayload,
                        payload_vix: Floor2IngestPayload) -> None:
        assert normalized_store.count == 0
        assert normalized_store.packet_ids == []
        assert normalized_store.sources == set()
        assert normalized_store.feed_types == set()

        normalized_store.store_many([payload_spot, payload_vix])

        assert normalized_store.count == 2
        assert normalized_store.sources == {"angel_one"}
        assert normalized_store.feed_types == {"spot_tick", "vix_tick"}


# =============================================================================
# RawRetentionManager tests
# =============================================================================


class TestRawRetentionManager:
    """Tests for ``RawRetentionManager``."""

    def test_default_major_retention(self, retention_manager: RawRetentionManager) -> None:
        """MAJOR feeds should have 7-day retention."""
        duration = retention_manager.get_retention_duration_s("spot_tick")
        assert duration == DEFAULT_MAJOR_RETENTION_S

    def test_default_minor_retention(self, retention_manager: RawRetentionManager) -> None:
        """MINOR feeds should have 1-day retention."""
        duration = retention_manager.get_retention_duration_s("calendar_event")
        assert duration == DEFAULT_MINOR_RETENTION_S

    def test_unknown_feed_retention(self, retention_manager: RawRetentionManager) -> None:
        """Unknown feeds should fall back to 1-day default."""
        duration = retention_manager.get_retention_duration_s("unknown_feed")
        assert duration == 86400  # 1 day

    def test_custom_policy(self, retention_manager: RawRetentionManager) -> None:
        retention_manager.set_policy("spot_tick", duration_s=3600)
        duration = retention_manager.get_retention_duration_s("spot_tick")
        assert duration == 3600

    def test_remove_policy(self, retention_manager: RawRetentionManager) -> None:
        retention_manager.set_policy("spot_tick", duration_s=3600)
        assert retention_manager.remove_policy("spot_tick") is True
        # Should revert to default
        duration = retention_manager.get_retention_duration_s("spot_tick")
        assert duration == DEFAULT_MAJOR_RETENTION_S

    def test_remove_nonexistent_policy(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        assert retention_manager.remove_policy("nonexistent") is False

    def test_clear_policies(self, retention_manager: RawRetentionManager) -> None:
        retention_manager.set_policy("spot_tick", duration_s=3600)
        retention_manager.set_policy("vix_tick", duration_s=7200)
        retention_manager.clear_policies()

        assert retention_manager.get_retention_duration_s("spot_tick") == DEFAULT_MAJOR_RETENTION_S
        assert retention_manager.get_retention_duration_s("vix_tick") == DEFAULT_MAJOR_RETENTION_S

    def test_expiry_cutoff_is_in_past(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        cutoff = retention_manager.get_expiry_cutoff("spot_tick")
        assert cutoff < datetime.now(timezone.utc)

    def test_is_expired_fresh_packet(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        """A packet stored now should NOT be expired."""
        now = datetime.now(timezone.utc)
        assert not retention_manager.is_expired(now, "spot_tick")

    def test_is_expired_old_packet(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        """A packet stored 10 days ago SHOULD be expired."""
        old = datetime.now(timezone.utc) - timedelta(days=10)
        assert retention_manager.is_expired(old, "spot_tick")

    def test_is_expired_none_stored_at(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        """A packet with no stored_at should NOT be expired."""
        assert not retention_manager.is_expired(None, "spot_tick")

    def test_is_expired_packet_just_below_retention(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        """A packet stored just below retention threshold should NOT be expired."""
        recent = datetime.now(timezone.utc) - timedelta(hours=23)
        assert not retention_manager.is_expired(recent, "calendar_event")

    def test_report_policies(self, retention_manager: RawRetentionManager) -> None:
        report = retention_manager.report_policies()
        assert report["default_major_s"] == DEFAULT_MAJOR_RETENTION_S
        assert report["default_minor_s"] == DEFAULT_MINOR_RETENTION_S
        assert report["overrides"] == {}

    def test_report_policies_with_overrides(
        self, retention_manager: RawRetentionManager,
    ) -> None:
        retention_manager.set_policy("spot_tick", duration_s=3600)
        report = retention_manager.report_policies()
        assert report["overrides"] == {"spot_tick": 3600}

    # ── Cross-store operations ─────────────────────────────────────────

    def test_get_expired_ids_empty_store(
        self, retention_manager: RawRetentionManager,
        original_store: OriginalRawStore,
    ) -> None:
        assert retention_manager.get_expired_ids(original_store) == []

    def test_get_expired_ids_fresh_packets(
        self, retention_manager: RawRetentionManager,
        original_store: OriginalRawStore,
        payload_spot: Floor2IngestPayload,
    ) -> None:
        original_store.store(payload_spot)
        expired = retention_manager.get_expired_ids(original_store)
        assert expired == []

    def test_purge_expired_no_effect_on_fresh(
        self, retention_manager: RawRetentionManager,
        original_store: OriginalRawStore,
        payload_spot: Floor2IngestPayload,
    ) -> None:
        original_store.store(payload_spot)
        purged = retention_manager.purge_expired(original_store)
        assert purged == 0
        assert original_store.count == 1

    def test_purge_expired_with_overridden_policy(
        self, retention_manager: RawRetentionManager,
        original_store: OriginalRawStore,
    ) -> None:
        """Override retention to 0s so all packets expire immediately."""
        retention_manager.set_policy("spot_tick", duration_s=0)

        # Use a timestamp clearly in the past so it's expired
        past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        payload = Floor2IngestPayload(
            original_raw_packet={"ltp": 18500.0},
            minimal_source_envelope={
                "source": "test",
                "feed_type": "spot_tick",
                "connection_id": "c1",
                "packet_id": "pkt_expired",
                "routing_id": "SPOT_FEED",
                "received_at": "2026-01-15T10:30:00+00:00",
            },
            feed_routing_identity="SPOT_FEED",
            source_health_facts={},
            manual_source_tags=None,
            ingested_at=past_time,
            ingest_batch_id="ig_batch",
        )
        original_store.store(payload)

        purged = retention_manager.purge_expired(original_store)
        assert purged == 1
        assert original_store.count == 0

    def test_purge_expired_works_on_normalized_store(
        self, retention_manager: RawRetentionManager,
        normalized_store: NormalizedRawStore,
    ) -> None:
        """Should work with NormalizedRawStore too."""
        retention_manager.set_policy("spot_tick", duration_s=0)

        past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        payload = Floor2IngestPayload(
            original_raw_packet={"ltp": 18500.0},
            minimal_source_envelope={
                "source": "test",
                "feed_type": "spot_tick",
                "connection_id": "c1",
                "packet_id": "pkt_expired_norm",
                "routing_id": "SPOT_FEED",
                "received_at": "2026-01-15T10:30:00+00:00",
            },
            feed_routing_identity="SPOT_FEED",
            source_health_facts={},
            manual_source_tags=None,
            ingested_at=past_time,
            ingest_batch_id="ig_batch",
        )
        normalized_store.store(payload)

        purged = retention_manager.purge_expired(normalized_store)
        assert purged == 1
        assert normalized_store.count == 0
