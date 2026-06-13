"""Tests for Side C journal store (journal_store.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.shared.types import MemoryEventFamily, Severity
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope
from junior_aladdin.side_c_memory.journal_store import (
    append_journal,
    clear,
    count_journals,
    get_journal,
    query_journals,
)


@pytest.fixture(autouse=True)
def reset_store():
    clear()
    yield
    clear()


def make_journal(family=MemoryEventFamily.TRADE_JOURNAL, source="side_a",
                 trade_id=None, decision_id=None, **kwargs):
    refs = {}
    if trade_id:
        refs["trade_id"] = trade_id
    if decision_id:
        refs["decision_id"] = decision_id
    return MemoryEnvelope(
        family=family,
        event_type=kwargs.get("event_type", "journal_entry"),
        source=source,
        emitter=kwargs.get("emitter", source),
        timestamp=kwargs.get("ts", datetime.now(timezone.utc)),
        severity=Severity.INFO,
        refs=refs,
    )


class TestJournalStoreAppend:
    def test_append_trade_journal(self):
        jnl = make_journal(family=MemoryEventFamily.TRADE_JOURNAL, trade_id="T123")
        jnl_id = append_journal(jnl)
        assert jnl_id is not None
        assert jnl_id.startswith("jnl_")

    def test_append_decision_journal(self):
        jnl = make_journal(family=MemoryEventFamily.DECISION_JOURNAL, source="floor_5", decision_id="D456")
        jnl_id = append_journal(jnl)
        assert jnl_id is not None

    def test_append_wrong_family_raises(self):
        jnl = make_journal(family=MemoryEventFamily.HEALTH_EVENT)
        with pytest.raises(ValueError, match="does not support family"):
            append_journal(jnl)

    def test_payload_ref_updated(self):
        jnl = make_journal(trade_id="T123")
        jnl_id = append_journal(jnl)
        assert jnl.payload_ref == jnl_id


class TestJournalStoreGet:
    def test_get_existing(self):
        jnl = make_journal(trade_id="T123")
        jnl_id = append_journal(jnl)
        retrieved = get_journal(jnl_id)
        assert retrieved is not None
        assert retrieved.envelope_id == jnl.envelope_id

    def test_get_non_existent(self):
        assert get_journal("nonexistent") is None


class TestJournalStoreQuery:
    def test_query_all(self):
        for i in range(3):
            append_journal(make_journal(trade_id=f"T{i}"))
        assert len(query_journals()) == 3

    def test_query_by_family(self):
        append_journal(make_journal(family=MemoryEventFamily.TRADE_JOURNAL, trade_id="T1"))
        append_journal(make_journal(family=MemoryEventFamily.DECISION_JOURNAL, source="floor_5", decision_id="D1"))
        trade_results = query_journals(families=[MemoryEventFamily.TRADE_JOURNAL])
        assert len(trade_results) == 1

    def test_query_by_trade_id(self):
        append_journal(make_journal(trade_id="T123"))
        append_journal(make_journal(trade_id="T456"))
        results = query_journals(trade_id="T123")
        assert len(results) == 1
        assert results[0].refs.get("trade_id") == "T123"

    def test_query_by_decision_id(self):
        append_journal(make_journal(family=MemoryEventFamily.DECISION_JOURNAL, source="floor_5", decision_id="D1"))
        append_journal(make_journal(family=MemoryEventFamily.DECISION_JOURNAL, source="floor_5", decision_id="D2"))
        results = query_journals(decision_id="D1")
        assert len(results) == 1

    def test_query_with_limit(self):
        for i in range(5):
            append_journal(make_journal(trade_id=f"T{i}"))
        results = query_journals(limit=2)
        assert len(results) == 2

    def test_query_by_timerange(self):
        old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        new_ts = datetime(2026, 6, 9, tzinfo=timezone.utc)
        append_journal(make_journal(trade_id="T1", ts=old_ts))
        append_journal(make_journal(trade_id="T2", ts=new_ts))
        results = query_journals(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(results) == 1

    def test_query_empty_with_limit_zero(self):
        append_journal(make_journal(trade_id="T1"))
        results = query_journals(limit=0)
        assert len(results) == 0

    def test_sorted_by_timestamp(self):
        ts1 = datetime(2026, 1, 3, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        append_journal(make_journal(trade_id="T1", ts=ts1))
        append_journal(make_journal(trade_id="T2", ts=ts2))
        results = query_journals()
        assert results[0].refs.get("trade_id") in ["T2"]
        assert results[1].refs.get("trade_id") in ["T1"]


class TestJournalStoreCount:
    def test_count(self):
        for i in range(3):
            append_journal(make_journal(trade_id=f"T{i}"))
        assert count_journals() == 3

    def test_count_by_family(self):
        append_journal(make_journal(family=MemoryEventFamily.TRADE_JOURNAL, trade_id="T1"))
        assert count_journals(families=[MemoryEventFamily.TRADE_JOURNAL]) == 1
