"""Tests for Side C query layer (query_layer.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope, MemoryQuery
from junior_aladdin.side_c_memory.event_store import clear as clear_events, append_event
from junior_aladdin.side_c_memory.journal_store import clear as clear_journals, append_journal
from junior_aladdin.side_c_memory.reference_store import clear as clear_refs, store_reference
from junior_aladdin.side_c_memory.query_layer import (
    get_decision_history,
    get_health_timeline,
    get_trade_history,
    query,
)


@pytest.fixture(autouse=True)
def reset_stores():
    clear_events()
    clear_journals()
    clear_refs()
    yield
    clear_events()
    clear_journals()
    clear_refs()


def env(**kwargs):
    return MemoryEnvelope(**kwargs)


class TestQuery:
    def test_query_no_families_returns_all(self):
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1"))
        append_journal(env(family=MemoryEventFamily.TRADE_JOURNAL, source="side_a", refs={"trade_id": "T1"}))
        store_reference(env(family=MemoryEventFamily.REPLAY_REF, source="floor_2", refs={"ref_key": "k1"}))
        results = query(MemoryQuery())
        assert len(results) == 3

    def test_query_by_family(self):
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1"))
        append_journal(env(family=MemoryEventFamily.TRADE_JOURNAL, source="side_a", refs={"trade_id": "T1"}))
        results = query(MemoryQuery(families=[MemoryEventFamily.HEALTH_EVENT]))
        assert len(results) == 1
        assert results[0].family == MemoryEventFamily.HEALTH_EVENT

    def test_query_by_timerange(self):
        old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        new_ts = datetime(2026, 6, 9, tzinfo=timezone.utc)
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1", timestamp=old_ts))
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1", timestamp=new_ts))
        results = query(MemoryQuery(
            families=[MemoryEventFamily.HEALTH_EVENT],
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        assert len(results) == 1

    def test_query_with_limit(self):
        for i in range(5):
            append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1"))
        results = query(MemoryQuery(limit=2))
        assert len(results) == 2

    def test_query_with_offset(self):
        for i in range(5):
            append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1"))
        results = query(MemoryQuery(limit=3, offset=3))
        assert len(results) == 2

    def test_query_with_refs_filter(self):
        append_journal(env(family=MemoryEventFamily.TRADE_JOURNAL, source="side_a", refs={"trade_id": "T1"}))
        append_journal(env(family=MemoryEventFamily.TRADE_JOURNAL, source="side_a", refs={"trade_id": "T2"}))
        results = query(MemoryQuery(refs_filter={"trade_id": "T1"}))
        assert len(results) == 1

    def test_query_sorted_by_timestamp(self):
        ts1 = datetime(2026, 1, 3, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1", timestamp=ts1))
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1", timestamp=ts2))
        results = query(MemoryQuery())
        assert results[0].timestamp == ts2
        assert results[1].timestamp == ts1

    def test_query_invalid_limit_raises(self):
        with pytest.raises(ValueError, match="limit"):
            query(MemoryQuery(limit=-2))

    def test_query_invalid_offset_raises(self):
        with pytest.raises(ValueError, match="offset"):
            query(MemoryQuery(offset=-1))


class TestGetTradeHistory:
    def test_trade_history_found(self):
        append_journal(env(
            family=MemoryEventFamily.TRADE_JOURNAL, source="side_a",
            refs={"trade_id": "T123"},
        ))
        results = get_trade_history("T123")
        assert len(results) == 1
        assert results[0].refs.get("trade_id") == "T123"

    def test_trade_history_not_found(self):
        results = get_trade_history("NONEXISTENT")
        assert results == []

    def test_trade_history_includes_execution_events(self):
        append_journal(env(family=MemoryEventFamily.TRADE_JOURNAL, source="side_a", refs={"trade_id": "T1"}))
        append_event(env(family=MemoryEventFamily.EXECUTION_EVENT, source="side_a", refs={"trade_id": "T1"}))
        results = get_trade_history("T1")
        assert len(results) == 2


class TestGetDecisionHistory:
    def test_decision_history_found(self):
        append_journal(env(
            family=MemoryEventFamily.DECISION_JOURNAL, source="floor_5",
            refs={"decision_id": "D456"},
        ))
        results = get_decision_history("D456")
        assert len(results) == 1

    def test_decision_history_not_found(self):
        results = get_decision_history("NONEXISTENT")
        assert results == []

    def test_decision_history_includes_review_refs(self):
        append_journal(env(family=MemoryEventFamily.DECISION_JOURNAL, source="floor_5", refs={"decision_id": "D1"}))
        results = get_decision_history("D1")
        assert len(results) == 1


class TestGetHealthTimeline:
    def test_health_timeline_empty_filter(self):
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1"))
        results = get_health_timeline()
        assert len(results) == 1

    def test_health_timeline_with_timerange(self):
        ts = datetime(2026, 6, 9, tzinfo=timezone.utc)
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1", timestamp=ts))
        results = get_health_timeline(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        assert len(results) == 1

    def test_health_timeline_outside_range(self):
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        append_event(env(family=MemoryEventFamily.HEALTH_EVENT, source="floor_1", timestamp=ts))
        results = get_health_timeline(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(results) == 0


class TestQueryLayerNoIntelligence:
    """Verify query_layer has NO score/rank/recommend/analyze methods."""

    def test_no_score_method(self):
        assert not hasattr(query, "score")
        assert not hasattr(get_trade_history, "score")

    def test_no_rank_method(self):
        assert not hasattr(query, "rank")
        assert not hasattr(get_trade_history, "rank")

    def test_no_recommend_method(self):
        assert not hasattr(query, "recommend")

    def test_no_analyze_method(self):
        assert not hasattr(query, "analyze")
