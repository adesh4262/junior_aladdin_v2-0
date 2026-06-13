"""Tests for Side C write contracts (contracts/write_contracts.py)."""

import pytest
from junior_aladdin.shared.types import MemoryEventFamily
from junior_aladdin.side_c_memory.contracts.write_contracts import (
    get_write_contract,
    list_contract_families,
    validate_event_for_family,
)


class TestWriteContracts:
    """Verify write contracts for all 8 families."""

    def test_all_8_families_have_contracts(self):
        families = list_contract_families()
        assert len(families) == 8

    def test_get_contract_known(self):
        contract = get_write_contract(MemoryEventFamily.HEALTH_EVENT)
        assert contract.family == MemoryEventFamily.HEALTH_EVENT
        assert "state" in contract.payload_schema

    def test_get_contract_unknown_raises(self):
        with pytest.raises(KeyError):
            get_write_contract("UNKNOWN_FAMILY")

    def test_valid_health_event_passes(self):
        event = {
            "event_type": "connection_degraded",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "CAUTION",
            "payload": {
                "state": "DEGRADED",
                "source_name": "angel_one_ws",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is True, f"Errors: {errors}"
        assert errors == []

    def test_missing_mandatory_field(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }
        # Missing 'emitter' top-level field
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is False
        assert any("emitter" in e for e in errors)

    def test_missing_payload_field(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY"},  # Missing source_name (required_in_payload)
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is False
        assert any("source_name" in e for e in errors)

    def test_invalid_severity(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INVALID_SEVERITY",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is False

    def test_wrong_family_in_data(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "TRADE_JOURNAL",  # Wrong — we validate against HEALTH_EVENT
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is False
        assert any("Family mismatch" in e for e in errors)

    def test_trade_journal_contract(self):
        event = {
            "event_type": "trade_completed",
            "source": "side_a",
            "emitter": "side_a",
            "family": "TRADE_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "trade_id": "T123",
                "entry": 18500.0,
                "exit": 18650.0,
                "pnl": 1500.0,
                "mode": "PAPER",
            },
            "refs": {"decision_id": "D456"},
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.TRADE_JOURNAL)
        assert is_valid is True, f"Errors: {errors}"

    def test_decision_journal_contract(self):
        event = {
            "event_type": "decision_made",
            "source": "floor_5",
            "emitter": "floor_5",
            "family": "DECISION_JOURNAL",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "decision": "TRADE",
                "conviction_band": "STRONG",
                "reason": "4/5 heads aligned",
                "trade_class": "CONTINUATION",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.DECISION_JOURNAL)
        assert is_valid is True, f"Errors: {errors}"

    def test_execution_event_contract(self):
        event = {
            "event_type": "order_placed",
            "source": "side_a",
            "emitter": "side_a",
            "family": "EXECUTION_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "order_id": "O789",
                "action": "BUY",
                "status": "PLACED",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.EXECUTION_EVENT)
        assert is_valid is True, f"Errors: {errors}"

    def test_override_contract(self):
        event = {
            "event_type": "parameter_override",
            "source": "side_a",
            "emitter": "side_a",
            "family": "OVERRIDE",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "SEVERE",
            "payload": {
                "reason": "Manual intervention required",
                "override_type": "PARAMETER",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.OVERRIDE)
        assert is_valid is True, f"Errors: {errors}"

    def test_blocked_action_contract(self):
        event = {
            "event_type": "order_blocked",
            "source": "side_a",
            "emitter": "side_a",
            "family": "BLOCKED_ACTION",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "CAUTION",
            "payload": {
                "reason": "Risk limit exceeded",
                "action": "BUY",
                "block_level": "HARD",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.BLOCKED_ACTION)
        assert is_valid is True, f"Errors: {errors}"

    def test_replay_ref_contract(self):
        event = {
            "event_type": "replay_created",
            "source": "floor_2",
            "emitter": "floor_2",
            "family": "REPLAY_REF",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "ref_key": "trade_id:T123",
                "replay_session_id": "RS_001",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.REPLAY_REF)
        assert is_valid is True, f"Errors: {errors}"

    def test_review_ref_contract(self):
        event = {
            "event_type": "review_created",
            "source": "floor_2",
            "emitter": "floor_2",
            "family": "REVIEW_REF",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {
                "ref_key": "decision_id:D456",
                "review_session_id": "RV_001",
            },
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.REVIEW_REF)
        assert is_valid is True, f"Errors: {errors}"

    def test_wrong_payload_type(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": "not_a_dict",  # Should be dict
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is False

    def test_refs_not_dict(self):
        event = {
            "event_type": "test",
            "source": "floor_1",
            "emitter": "floor_1",
            "family": "HEALTH_EVENT",
            "timestamp": "2026-06-09T10:00:00Z",
            "severity": "INFO",
            "payload": {"state": "HEALTHY", "source_name": "test"},
            "refs": "not_a_dict",
        }
        is_valid, errors = validate_event_for_family(event, MemoryEventFamily.HEALTH_EVENT)
        assert is_valid is False
