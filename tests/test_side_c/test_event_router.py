"""Tests for Side C event router (event_router.py)."""

import pytest
from junior_aladdin.shared.types import MemoryEventFamily
from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.side_c_memory.c_types import MemoryEnvelope
from junior_aladdin.side_c_memory.event_router import (
    get_families_for_store,
    get_routing_rule,
    list_routing_rules,
    route_event,
    set_store_callback,
)


class TestRoutingRules:
    def test_trade_journal_to_journal_store(self):
        assert get_routing_rule(MemoryEventFamily.TRADE_JOURNAL) == "journal_store"

    def test_decision_journal_to_journal_store(self):
        assert get_routing_rule(MemoryEventFamily.DECISION_JOURNAL) == "journal_store"

    def test_health_event_to_event_store(self):
        assert get_routing_rule(MemoryEventFamily.HEALTH_EVENT) == "event_store"

    def test_execution_event_to_event_store(self):
        assert get_routing_rule(MemoryEventFamily.EXECUTION_EVENT) == "event_store"

    def test_override_to_event_store(self):
        assert get_routing_rule(MemoryEventFamily.OVERRIDE) == "event_store"

    def test_blocked_action_to_event_store(self):
        assert get_routing_rule(MemoryEventFamily.BLOCKED_ACTION) == "event_store"

    def test_replay_ref_to_reference_store(self):
        assert get_routing_rule(MemoryEventFamily.REPLAY_REF) == "reference_store"

    def test_review_ref_to_reference_store(self):
        assert get_routing_rule(MemoryEventFamily.REVIEW_REF) == "reference_store"

    def test_unknown_family_raises(self):
        with pytest.raises(ContractViolationError, match="Unknown family"):
            get_routing_rule("UNKNOWN_FAMILY")


class TestFamiliesForStore:
    def test_journal_store_families(self):
        families = get_families_for_store("journal_store")
        assert MemoryEventFamily.TRADE_JOURNAL in families
        assert MemoryEventFamily.DECISION_JOURNAL in families
        assert len(families) == 2

    def test_event_store_families(self):
        families = get_families_for_store("event_store")
        assert MemoryEventFamily.HEALTH_EVENT in families
        assert MemoryEventFamily.EXECUTION_EVENT in families
        assert MemoryEventFamily.OVERRIDE in families
        assert MemoryEventFamily.BLOCKED_ACTION in families
        assert len(families) == 4

    def test_reference_store_families(self):
        families = get_families_for_store("reference_store")
        assert MemoryEventFamily.REPLAY_REF in families
        assert MemoryEventFamily.REVIEW_REF in families
        assert len(families) == 2

    def test_unknown_store(self):
        assert get_families_for_store("unknown_store") == []


class TestListRules:
    def test_list_returns_all_stores(self):
        rules = list_routing_rules()
        assert "event_store" in rules
        assert "journal_store" in rules
        assert "reference_store" in rules

    def test_list_contains_all_families(self):
        rules = list_routing_rules()
        all_families = set()
        for families in rules.values():
            all_families.update(families)
        assert len(all_families) == 8


class TestRouteEvent:
    def test_route_without_store_callback(self):
        env = MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            source="floor_1",
            emitter="floor_1",
        )
        store_name = route_event(env)
        assert store_name == "event_store"

    def test_route_with_store_callback(self):
        results = []
        def mock_callback(env):
            results.append(env)
            return "stored_id"

        set_store_callback("event_store", mock_callback)
        env = MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            source="floor_1",
            emitter="floor_1",
        )
        store_name = route_event(env)
        assert store_name == "event_store"
        assert len(results) == 1
        assert results[0].envelope_id == env.envelope_id

        # Cleanup
        set_store_callback("event_store", None)

    def test_route_unknown_family_raises(self):
        env = MemoryEnvelope()
        env.family = "UNKNOWN_FAMILY"  # type: ignore[assignment]
        with pytest.raises(ContractViolationError):
            route_event(env)

    def test_route_missing_envelope_id_raises(self):
        # MemoryEnvelope.__post_init__ auto-generates envelope_id if empty.
        # Bypass that to simulate a genuinely missing ID.
        env = MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            source="floor_1",
        )
        object.__setattr__(env, 'envelope_id', '')
        with pytest.raises(ContractViolationError, match="missing envelope_id"):
            route_event(env)

    def test_route_missing_source_raises(self):
        env = MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            source="",
        )
        with pytest.raises(ContractViolationError, match="missing source"):
            route_event(env)

    def test_set_store_callback_none_disconnects(self):
        set_store_callback("event_store", lambda env: "id")
        set_store_callback("event_store", None)
        env = MemoryEnvelope(
            family=MemoryEventFamily.HEALTH_EVENT,
            source="floor_1",
        )
        # Should NOT raise when no callback connected
        store_name = route_event(env)
        assert store_name == "event_store"
