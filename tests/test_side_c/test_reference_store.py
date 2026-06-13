"""Tests for Side C reference store (reference_store.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope
from junior_aladdin.side_c_memory.reference_store import (
    clear,
    get_reference,
    lookup_by_key,
    query_references,
    store_reference,
)


@pytest.fixture(autouse=True)
def reset_store():
    clear()
    yield
    clear()


def make_ref(family=MemoryEventFamily.REPLAY_REF, source="floor_2",
             ref_key=None, **kwargs):
    refs = {}
    if ref_key:
        refs["ref_key"] = ref_key
    return MemoryEnvelope(
        family=family,
        event_type=kwargs.get("event_type", "ref_created"),
        source=source,
        emitter=kwargs.get("emitter", source),
        timestamp=kwargs.get("ts", datetime.now(timezone.utc)),
        severity=Severity.INFO,
        refs=refs,
    )


class TestReferenceStoreStore:
    def test_store_replay_ref(self):
        ref = make_ref(family=MemoryEventFamily.REPLAY_REF, ref_key="trade_id:T123")
        ref_id = store_reference(ref)
        assert ref_id is not None
        assert ref_id.startswith("ref_")

    def test_store_review_ref(self):
        ref = make_ref(family=MemoryEventFamily.REVIEW_REF, ref_key="decision_id:D456")
        ref_id = store_reference(ref)
        assert ref_id is not None

    def test_store_wrong_family_raises(self):
        ref = make_ref(family=MemoryEventFamily.HEALTH_EVENT)
        with pytest.raises(ValueError, match="does not support family"):
            store_reference(ref)

    def test_payload_ref_updated(self):
        ref = make_ref(ref_key="trade_id:T123")
        ref_id = store_reference(ref)
        assert ref.payload_ref == ref_id


class TestReferenceStoreGet:
    def test_get_existing(self):
        ref = make_ref(ref_key="trade_id:T123")
        ref_id = store_reference(ref)
        retrieved = get_reference(ref_id)
        assert retrieved is not None
        assert retrieved.envelope_id == ref.envelope_id

    def test_get_non_existent(self):
        assert get_reference("nonexistent") is None


class TestReferenceStoreLookupByKey:
    def test_lookup_by_key(self):
        ref = make_ref(ref_key="trade_id:T123")
        store_reference(ref)
        results = lookup_by_key("trade_id:T123")
        assert len(results) == 1

    def test_lookup_by_key_multiple(self):
        store_reference(make_ref(ref_key="trade_id:T123"))
        store_reference(make_ref(ref_key="trade_id:T123"))
        results = lookup_by_key("trade_id:T123")
        assert len(results) == 2

    def test_lookup_by_key_not_found(self):
        results = lookup_by_key("nonexistent_key")
        assert results == []


class TestReferenceStoreQuery:
    def test_query_all(self):
        for i in range(3):
            store_reference(make_ref(ref_key=f"key_{i}"))
        assert len(query_references()) == 3

    def test_query_by_type(self):
        store_reference(make_ref(family=MemoryEventFamily.REPLAY_REF, ref_key="k1"))
        store_reference(make_ref(family=MemoryEventFamily.REVIEW_REF, ref_key="k2"))
        results = query_references(ref_types=[MemoryEventFamily.REPLAY_REF])
        assert len(results) == 1

    def test_query_by_ref_key(self):
        store_reference(make_ref(ref_key="trade_id:T123"))
        store_reference(make_ref(ref_key="trade_id:T456"))
        results = query_references(ref_key="trade_id:T123")
        assert len(results) == 1

    def test_query_with_limit(self):
        for i in range(5):
            store_reference(make_ref(ref_key=f"key_{i}"))
        results = query_references(limit=2)
        assert len(results) == 2

    def test_query_by_timerange(self):
        old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        new_ts = datetime(2026, 6, 9, tzinfo=timezone.utc)
        store_reference(make_ref(ref_key="old", ts=old_ts))
        store_reference(make_ref(ref_key="new", ts=new_ts))
        results = query_references(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(results) == 1
