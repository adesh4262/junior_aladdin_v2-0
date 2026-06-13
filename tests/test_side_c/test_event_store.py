"""Tests for Side C event store (event_store.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope
from junior_aladdin.side_c_memory.event_store import (
    append_event,
    clear,
    count_events,
    get_event,
    query_events,
)


@pytest.fixture(autouse=True)
def reset_store():
    clear()
    yield
    clear()


def make_envelope(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1",
                  severity=Severity.INFO, **kwargs):
    return MemoryEnvelope(
        family=family,
        event_type=kwargs.get("event_type", "test_event"),
        source=source,
        emitter=kwargs.get("emitter", source),
        timestamp=kwargs.get("ts", datetime.now(timezone.utc)),
        severity=severity,
        refs=kwargs.get("refs", {}),
    )


class TestEventStoreAppend:
    def test_append_health_event(self):
        env = make_envelope()
        event_id = append_event(env)
        assert event_id is not None
        assert event_id.startswith("evt_")

    def test_append_execution_event(self):
        env = make_envelope(family=MemoryEventFamily.EXECUTION_EVENT, source="side_a")
        event_id = append_event(env)
        assert event_id is not None

    def test_append_override(self):
        env = make_envelope(family=MemoryEventFamily.OVERRIDE, source="side_a")
        event_id = append_event(env)
        assert event_id is not None

    def test_append_blocked_action(self):
        env = make_envelope(family=MemoryEventFamily.BLOCKED_ACTION, source="side_a")
        event_id = append_event(env)
        assert event_id is not None

    def test_append_wrong_family_raises(self):
        env = make_envelope(family=MemoryEventFamily.TRADE_JOURNAL)
        with pytest.raises(ValueError, match="does not support family"):
            append_event(env)

    def test_payload_ref_updated(self):
        env = make_envelope()
        event_id = append_event(env)
        assert env.payload_ref == event_id


class TestEventStoreGet:
    def test_get_existing_event(self):
        env = make_envelope()
        event_id = append_event(env)
        retrieved = get_event(event_id)
        assert retrieved is not None
        assert retrieved.envelope_id == env.envelope_id

    def test_get_non_existent(self):
        assert get_event("nonexistent") is None


class TestEventStoreQuery:
    def test_query_all(self):
        for i in range(5):
            append_event(make_envelope())
        results = query_events()
        assert len(results) == 5

    def test_query_by_family(self):
        append_event(make_envelope(family=MemoryEventFamily.HEALTH_EVENT))
        append_event(make_envelope(family=MemoryEventFamily.EXECUTION_EVENT, source="side_a"))
        health_results = query_events(families=[MemoryEventFamily.HEALTH_EVENT])
        assert len(health_results) == 1
        assert health_results[0].family == MemoryEventFamily.HEALTH_EVENT

    def test_query_by_source(self):
        append_event(make_envelope(source="floor_1"))
        append_event(make_envelope(source="floor_2"))
        results = query_events(source="floor_1")
        assert len(results) == 1

    def test_query_by_severity(self):
        append_event(make_envelope(severity=Severity.INFO))
        append_event(make_envelope(severity=Severity.SEVERE))
        results = query_events(severity="SEVERE")
        assert len(results) == 1

    def test_query_with_limit(self):
        for i in range(10):
            append_event(make_envelope())
        results = query_events(limit=3)
        assert len(results) == 3

    def test_query_with_offset(self):
        for i in range(5):
            append_event(make_envelope())
        results = query_events(offset=3)
        assert len(results) == 2

    def test_query_empty_with_limit_zero(self):
        for i in range(5):
            append_event(make_envelope())
        results = query_events(limit=0)
        assert len(results) == 0

    def test_query_by_timerange(self):
        old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        new_ts = datetime(2026, 6, 9, tzinfo=timezone.utc)
        append_event(make_envelope(ts=old_ts))
        append_event(make_envelope(ts=new_ts))
        results = query_events(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        assert len(results) == 1

    def test_query_returns_sorted_by_timestamp(self):
        ts1 = datetime(2026, 1, 3, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts3 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        append_event(make_envelope(ts=ts1))
        append_event(make_envelope(ts=ts2))
        append_event(make_envelope(ts=ts3))
        results = query_events()
        assert results[0].timestamp == ts2
        assert results[1].timestamp == ts3
        assert results[2].timestamp == ts1


class TestEventStoreCount:
    def test_count_all(self):
        for i in range(5):
            append_event(make_envelope())
        assert count_events() == 5

    def test_count_by_family(self):
        append_event(make_envelope(family=MemoryEventFamily.HEALTH_EVENT))
        append_event(make_envelope(family=MemoryEventFamily.EXECUTION_EVENT, source="side_a"))
        assert count_events(families=[MemoryEventFamily.HEALTH_EVENT]) == 1

    def test_count_by_timerange(self):
        old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        append_event(make_envelope(ts=old_ts))
        append_event(make_envelope(ts=datetime.now(timezone.utc)))
        assert count_events(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ) == 1


class TestEventStoreNoMutation:
    def test_no_delete_method(self):
        assert not hasattr(append_event, "delete")
        assert not hasattr(append_event, "remove")

    def test_append_first_enforced(self):
        env = make_envelope()
        event_id = append_event(env)
        retrieved = get_event(event_id)
        assert retrieved.envelope_id == env.envelope_id
        assert retrieved.family == env.family
        assert retrieved.source == env.source
