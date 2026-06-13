"""Tests for Side C read contracts (contracts/read_contracts.py)."""

import pytest
from datetime import datetime, timezone
from junior_aladdin.side_c_memory.c_types import MemoryQuery
from junior_aladdin.side_c_memory.contracts.read_contracts import (
    get_read_contract,
    list_query_types,
    validate_query,
)


class TestReadContracts:
    """Verify read contracts for all 5 query types."""

    def test_five_query_types(self):
        types = list_query_types()
        assert len(types) == 5
        assert "trade_history" in types
        assert "decision_review" in types
        assert "health_timeline" in types
        assert "override_history" in types
        assert "blocked_actions" in types

    def test_get_contract_known(self):
        contract = get_read_contract("trade_history")
        assert contract.query_type == "trade_history"
        assert "trade_id" in contract.mandatory_params

    def test_get_contract_unknown_raises(self):
        with pytest.raises(KeyError):
            get_read_contract("unknown_query_type")

    def test_trade_history_valid(self):
        q = MemoryQuery(
            refs_filter={"trade_id": "T123"},
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        is_valid, errors = validate_query(q, "trade_history")
        assert is_valid is True, f"Errors: {errors}"

    def test_trade_history_missing_trade_id(self):
        q = MemoryQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        is_valid, errors = validate_query(q, "trade_history")
        assert is_valid is False
        assert any("trade_id" in e for e in errors)

    def test_decision_review_valid(self):
        q = MemoryQuery(
            refs_filter={"decision_id": "D456"},
        )
        is_valid, errors = validate_query(q, "decision_review")
        assert is_valid is True

    def test_decision_review_missing_decision_id(self):
        q = MemoryQuery()
        is_valid, errors = validate_query(q, "decision_review")
        assert is_valid is False

    def test_health_timeline_valid(self):
        q = MemoryQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        is_valid, errors = validate_query(q, "health_timeline")
        assert is_valid is True

    def test_health_timeline_missing_timerange(self):
        q = MemoryQuery()
        is_valid, errors = validate_query(q, "health_timeline")
        assert is_valid is False
        assert any("start_time" in e for e in errors)
        assert any("end_time" in e for e in errors)

    def test_override_history_valid(self):
        q = MemoryQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        is_valid, errors = validate_query(q, "override_history")
        assert is_valid is True

    def test_blocked_actions_valid(self):
        q = MemoryQuery(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        is_valid, errors = validate_query(q, "blocked_actions")
        assert is_valid is True

    def test_invalid_query_type(self):
        q = MemoryQuery()
        is_valid, errors = validate_query(q, "nonexistent_type")
        assert is_valid is False
        assert any("No read contract defined" in e for e in errors)
