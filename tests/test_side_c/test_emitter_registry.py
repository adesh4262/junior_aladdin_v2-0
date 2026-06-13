"""Tests for Side C emitter registry (contracts/emitter_registry.py)."""

import pytest
from junior_aladdin.shared.types import MemoryEventFamily
from junior_aladdin.side_c_memory.contracts.emitter_registry import (
    family_allowed_for_emitter,
    get_allowed_families,
    get_emitter_info,
    is_emitter_approved,
    list_approved_emitters,
    register_emitter,
)


class TestEmitterRegistry:
    """Verify the 4 locked emitters."""

    def test_four_approved_emitters(self):
        emitters = list_approved_emitters()
        assert len(emitters) == 4

    def test_floor_1_is_approved(self):
        assert is_emitter_approved("floor_1") is True

    def test_floor_2_is_approved(self):
        assert is_emitter_approved("floor_2") is True

    def test_floor_5_is_approved(self):
        assert is_emitter_approved("floor_5") is True

    def test_side_a_is_approved(self):
        assert is_emitter_approved("side_a") is True

    def test_unknown_emitter_not_approved(self):
        assert is_emitter_approved("unknown_floor") is False
        assert is_emitter_approved("floor_3") is False

    def test_floor_1_allowed_families(self):
        families = get_allowed_families("floor_1")
        assert families == [MemoryEventFamily.HEALTH_EVENT]

    def test_floor_2_allowed_families(self):
        families = get_allowed_families("floor_2")
        assert MemoryEventFamily.HEALTH_EVENT in families
        assert MemoryEventFamily.REPLAY_REF in families
        assert MemoryEventFamily.REVIEW_REF in families

    def test_floor_5_allowed_families(self):
        families = get_allowed_families("floor_5")
        assert families == [MemoryEventFamily.DECISION_JOURNAL]

    def test_side_a_allowed_families(self):
        families = get_allowed_families("side_a")
        assert MemoryEventFamily.TRADE_JOURNAL in families
        assert MemoryEventFamily.EXECUTION_EVENT in families
        assert MemoryEventFamily.BLOCKED_ACTION in families
        assert MemoryEventFamily.OVERRIDE in families
        assert len(families) == 4

    def test_family_allowed_for_emitter(self):
        assert family_allowed_for_emitter("floor_1", MemoryEventFamily.HEALTH_EVENT) is True
        assert family_allowed_for_emitter("floor_1", MemoryEventFamily.TRADE_JOURNAL) is False
        assert family_allowed_for_emitter("side_a", MemoryEventFamily.TRADE_JOURNAL) is True
        assert family_allowed_for_emitter("floor_5", MemoryEventFamily.DECISION_JOURNAL) is True
        assert family_allowed_for_emitter("floor_5", MemoryEventFamily.HEALTH_EVENT) is False

    def test_family_allowed_unknown_emitter_returns_false(self):
        assert family_allowed_for_emitter("unknown", MemoryEventFamily.HEALTH_EVENT) is False

    def test_unknown_emitter_key_error(self):
        with pytest.raises(KeyError):
            get_allowed_families("unknown_emitter")

    def test_get_emitter_info_known(self):
        info = get_emitter_info("floor_1")
        assert info is not None
        assert info["emitter_id"] == "floor_1"
        assert "HEALTH_EVENT" in info["allowed_families"]
        assert "Floor 1" in info["source_owner"]

    def test_get_emitter_info_unknown(self):
        assert get_emitter_info("unknown") is None

    def test_register_emitter_dynamically(self):
        register_emitter(
            "test_emitter",
            [MemoryEventFamily.HEALTH_EVENT],
            "Test Owner",
            "Test emitter for testing",
        )
        assert is_emitter_approved("test_emitter") is True
        assert get_allowed_families("test_emitter") == [MemoryEventFamily.HEALTH_EVENT]
