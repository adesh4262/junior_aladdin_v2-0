"""Tests for data_health_policy.py — DataHealthPolicy.

Covers:
- All 5 DataHealth states mapped to correct responses
- get_execution_strictness for all responses
- is_entry_blocked for all responses
- describe() for all responses
- check_health() convenience method
- Edge cases: None, invalid type, unmapped values
"""

from __future__ import annotations

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import DataHealth
from junior_aladdin.side_a_execution.data_health_policy import (
    DataHealthPolicy,
    DEFAULT_STRICTNESS_NORMAL,
    DEFAULT_STRICTNESS_STRICT,
    DEFAULT_STRICTNESS_BLOCKED,
    DEFAULT_STRICTNESS_ESCALATE,
)
from junior_aladdin.side_a_execution.side_a_types import DataHealthExecutionResponse


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def policy() -> DataHealthPolicy:
    return DataHealthPolicy()


# =============================================================================
# Health → Response Mapping Tests
# =============================================================================


class TestEvaluate:
    """Test evaluate() maps each DataHealth to the correct response."""

    @pytest.mark.parametrize(
        ("health", "expected_response"),
        [
            (DataHealth.GOOD, DataHealthExecutionResponse.ALLOW_NORMAL),
            (DataHealth.CAUTION, DataHealthExecutionResponse.ALLOW_NORMAL),
            (DataHealth.DEGRADED, DataHealthExecutionResponse.ALLOW_STRICT),
            (DataHealth.STALE, DataHealthExecutionResponse.BLOCK_NEW),
            (DataHealth.CRITICAL, DataHealthExecutionResponse.ESCALATE_FLATTEN),
        ],
    )
    def test_evaluate_mapping(
        self,
        policy: DataHealthPolicy,
        health: DataHealth,
        expected_response: DataHealthExecutionResponse,
    ) -> None:
        result = policy.evaluate(health)
        assert result == expected_response

    def test_evaluate_none_raises(self, policy: DataHealthPolicy) -> None:
        with pytest.raises(ExecutionError, match="Invalid data health signal"):
            policy.evaluate(None)  # type: ignore[arg-type]

    def test_evaluate_invalid_type_raises(self, policy: DataHealthPolicy) -> None:
        with pytest.raises(ExecutionError, match="Invalid data health signal"):
            policy.evaluate("GOOD")  # type: ignore[arg-type]

    def test_evaluate_int_raises(self, policy: DataHealthPolicy) -> None:
        with pytest.raises(ExecutionError, match="Invalid data health signal"):
            policy.evaluate(123)  # type: ignore[arg-type]

    def test_evaluate_with_static_call(self) -> None:
        """evaluate() is static, should work without instance."""
        result = DataHealthPolicy.evaluate(DataHealth.CRITICAL)
        assert result == DataHealthExecutionResponse.ESCALATE_FLATTEN


# =============================================================================
# get_execution_strictness Tests
# =============================================================================


class TestGetExecutionStrictness:
    """Test get_execution_strictness() returns correct multipliers."""

    @pytest.mark.parametrize(
        ("response", "expected_strictness"),
        [
            (DataHealthExecutionResponse.ALLOW_NORMAL, DEFAULT_STRICTNESS_NORMAL),
            (DataHealthExecutionResponse.ALLOW_STRICT, DEFAULT_STRICTNESS_STRICT),
            (DataHealthExecutionResponse.BLOCK_NEW, DEFAULT_STRICTNESS_BLOCKED),
            (DataHealthExecutionResponse.ESCALATE_FLATTEN, DEFAULT_STRICTNESS_ESCALATE),
        ],
    )
    def test_strictness_values(
        self,
        policy: DataHealthPolicy,
        response: DataHealthExecutionResponse,
        expected_strictness: float,
    ) -> None:
        assert policy.get_execution_strictness(response) == expected_strictness

    def test_strictness_is_static(self) -> None:
        assert DataHealthPolicy.get_execution_strictness(
            DataHealthExecutionResponse.ALLOW_STRICT,
        ) == DEFAULT_STRICTNESS_STRICT


# =============================================================================
# is_entry_blocked Tests
# =============================================================================


class TestIsEntryBlocked:
    """Test is_entry_blocked() returns correct booleans."""

    @pytest.mark.parametrize(
        ("response", "expected_blocked"),
        [
            (DataHealthExecutionResponse.ALLOW_NORMAL, False),
            (DataHealthExecutionResponse.ALLOW_STRICT, False),
            (DataHealthExecutionResponse.BLOCK_NEW, True),
            (DataHealthExecutionResponse.ESCALATE_FLATTEN, True),
        ],
    )
    def test_entry_blocked_values(
        self,
        policy: DataHealthPolicy,
        response: DataHealthExecutionResponse,
        expected_blocked: bool,
    ) -> None:
        assert policy.is_entry_blocked(response) == expected_blocked

    def test_entry_blocked_is_static(self) -> None:
        assert DataHealthPolicy.is_entry_blocked(
            DataHealthExecutionResponse.BLOCK_NEW,
        ) is True


# =============================================================================
# describe Tests
# =============================================================================


class TestDescribe:
    """Test describe() returns meaningful descriptions."""

    def test_describe_allow_normal(self, policy: DataHealthPolicy) -> None:
        desc = policy.describe(DataHealthExecutionResponse.ALLOW_NORMAL)
        assert "Normal execution" in desc

    def test_describe_allow_strict(self, policy: DataHealthPolicy) -> None:
        desc = policy.describe(DataHealthExecutionResponse.ALLOW_STRICT)
        assert "Strict execution" in desc
        assert "1.5x" in desc

    def test_describe_block_new(self, policy: DataHealthPolicy) -> None:
        desc = policy.describe(DataHealthExecutionResponse.BLOCK_NEW)
        assert "blocked" in desc.lower()
        assert "existing" in desc.lower()

    def test_describe_escalate_flatten(self, policy: DataHealthPolicy) -> None:
        desc = policy.describe(DataHealthExecutionResponse.ESCALATE_FLATTEN)
        assert "CRITICAL" in desc
        assert "escalation" in desc.lower()

    def test_describe_is_static(self) -> None:
        desc = DataHealthPolicy.describe(DataHealthExecutionResponse.ALLOW_NORMAL)
        assert isinstance(desc, str)
        assert len(desc) > 0


# =============================================================================
# check_health Tests
# =============================================================================


class TestCheckHealth:
    """Test check_health() convenience method returns complete dict."""

    def test_check_health_good(self, policy: DataHealthPolicy) -> None:
        result = policy.check_health(DataHealth.GOOD)
        assert result["response"] == DataHealthExecutionResponse.ALLOW_NORMAL.value
        assert result["strictness"] == DEFAULT_STRICTNESS_NORMAL
        assert result["entry_blocked"] is False
        assert "Normal execution" in result["description"]

    def test_check_health_degraded(self, policy: DataHealthPolicy) -> None:
        result = policy.check_health(DataHealth.DEGRADED)
        assert result["response"] == DataHealthExecutionResponse.ALLOW_STRICT.value
        assert result["strictness"] == DEFAULT_STRICTNESS_STRICT
        assert result["entry_blocked"] is False

    def test_check_health_stale(self, policy: DataHealthPolicy) -> None:
        result = policy.check_health(DataHealth.STALE)
        assert result["response"] == DataHealthExecutionResponse.BLOCK_NEW.value
        assert result["strictness"] == DEFAULT_STRICTNESS_BLOCKED
        assert result["entry_blocked"] is True

    def test_check_health_critical(self, policy: DataHealthPolicy) -> None:
        result = policy.check_health(DataHealth.CRITICAL)
        assert result["response"] == DataHealthExecutionResponse.ESCALATE_FLATTEN.value
        assert result["strictness"] == DEFAULT_STRICTNESS_ESCALATE
        assert result["entry_blocked"] is True

    def test_check_health_is_classmethod(self) -> None:
        result = DataHealthPolicy.check_health(DataHealth.DEGRADED)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"response", "strictness", "entry_blocked", "description"}

    def test_check_health_invalid_raises(self) -> None:
        with pytest.raises(ExecutionError):
            DataHealthPolicy.check_health(None)  # type: ignore[arg-type]


# =============================================================================
# Cross-module Contract Tests
# =============================================================================


class TestCrossModuleContracts:
    """Verify the policy integrates correctly with risk_gate expectations."""

    def test_all_datahealth_values_have_mappings(self) -> None:
        """Every DataHealth value should have a valid response."""
        for health in DataHealth:
            response = DataHealthPolicy.evaluate(health)
            assert isinstance(response, DataHealthExecutionResponse)

    def test_all_responses_have_strictness(self) -> None:
        """Every response should have a strictness value."""
        for response in DataHealthExecutionResponse:
            strictness = DataHealthPolicy.get_execution_strictness(response)
            assert isinstance(strictness, (int, float))

    def test_all_responses_have_entry_blocked(self) -> None:
        """Every response should have an entry blocked state."""
        for response in DataHealthExecutionResponse:
            blocked = DataHealthPolicy.is_entry_blocked(response)
            assert isinstance(blocked, bool)

    def test_risk_gate_check_12_matches_policy(self) -> None:
        """Risk check 12 logic (DATA_HEALTH) should align with this policy.

        The risk_gate currently has inline logic that blocks on CRITICAL/STALE
        and passes on DEGRADED/GOOD/CAUTION. This test verifies alignment.
        """
        # CRITICAL → blocked
        assert DataHealthPolicy.is_entry_blocked(
            DataHealthPolicy.evaluate(DataHealth.CRITICAL),
        ) is True

        # STALE → blocked
        assert DataHealthPolicy.is_entry_blocked(
            DataHealthPolicy.evaluate(DataHealth.STALE),
        ) is True

        # DEGRADED → allowed (but strict)
        assert DataHealthPolicy.is_entry_blocked(
            DataHealthPolicy.evaluate(DataHealth.DEGRADED),
        ) is False

        # GOOD → allowed
        assert DataHealthPolicy.is_entry_blocked(
            DataHealthPolicy.evaluate(DataHealth.GOOD),
        ) is False

        # CAUTION → allowed
        assert DataHealthPolicy.is_entry_blocked(
            DataHealthPolicy.evaluate(DataHealth.CAUTION),
        ) is False
