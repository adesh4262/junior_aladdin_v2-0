"""Tests for risk_gate — all 12 pre-order safety checks, evaluate, is_blocked_for_safety."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from junior_aladdin.shared.types import (
    DataHealth,
    ExecutionIntent,
    ExecutionMode,
    TradeClass,
)
from junior_aladdin.side_a_execution.intent_fingerprint import IntentFingerprintStore
from junior_aladdin.side_a_execution.risk_gate import RiskContext, RiskGate


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fingerprint_store() -> IntentFingerprintStore:
    """A fresh fingerprint store."""
    return IntentFingerprintStore()


@pytest.fixture
def sample_intent() -> ExecutionIntent:
    """A valid ExecutionIntent for risk gate testing."""
    return ExecutionIntent(
        trade_id="trade_snap_001",
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        entry_plan={
            "trigger": "price_above_zone",
            "zone": "19480-19520",
            "confirmation": "1m_close_above_19500",
            "premium": 150.0,
        },
        invalidation_level=19450.0,
        stop_loss_plan={"price": 19450.0, "type": "fixed"},
        target_plan={"targets": [{"price": 19600.0, "size": 0.5}]},
        mode=ExecutionMode.PAPER,
        timestamp=datetime.utcnow(),
    )


@pytest.fixture
def default_context() -> RiskContext:
    """A default context where all checks should pass."""
    return RiskContext(
        available_capital=50000.0,
        required_capital=5000.0,
        max_risk_per_trade=5000.0,
        max_daily_loss=10000.0,
        current_daily_loss=0.0,
        mode=ExecutionMode.PAPER,
        lot_size=25,
        is_real_locked=False,
        has_active_trade=False,
        data_health=DataHealth.GOOD,
    )


@pytest.fixture
def risk_gate(fingerprint_store: IntentFingerprintStore) -> RiskGate:
    """A RiskGate with a fresh fingerprint store and no callbacks."""
    return RiskGate(intent_fingerprint_store=fingerprint_store)


# =============================================================================
# Tests: Check 1 — Available Capital
# =============================================================================


def test_check1_capital_sufficient(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 1 passes when capital is sufficient."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check1_capital_insufficient(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 1 fails when capital is insufficient."""
    ctx = RiskContext(
        available_capital=1000.0,
        required_capital=5000.0,
        mode=ExecutionMode.PAPER,
    )
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("AVAILABLE_CAPITAL" in f[0] for f in failed)


def test_check1_skipped_when_no_capital_limit(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
) -> None:
    """Check 1 skips when no capital limit is configured."""
    ctx = RiskContext(available_capital=0.0, mode=ExecutionMode.PAPER)
    result = risk_gate.evaluate(sample_intent, ctx)
    # Should not fail on capital check
    assert not any("AVAILABLE_CAPITAL" in c[0] and not c[1] for c in result.checks)


# =============================================================================
# Tests: Check 4 — Quantity Sanity
# =============================================================================


def test_check4_quantity_sane(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 4 passes when cost ≤ max_risk."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check4_quantity_exceeds_risk(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 4 fails when cost exceeds max_risk."""
    ctx = RiskContext(max_risk_per_trade=100.0, mode=ExecutionMode.PAPER)
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("QUANTITY_SANITY" in f[0] for f in failed)


# =============================================================================
# Tests: Check 6 — Max Loss Limit
# =============================================================================


def test_check6_loss_within_limit(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 6 passes when daily loss is within limit."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check6_loss_limit_reached(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 6 fails when daily loss limit is reached."""
    ctx = RiskContext(
        max_daily_loss=10000.0,
        current_daily_loss=10000.0,
        mode=ExecutionMode.PAPER,
    )
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("MAX_LOSS_LIMIT" in f[0] for f in failed)


# =============================================================================
# Tests: Check 7 — Mode Validation
# =============================================================================


def test_check7_mode_matches(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 7 passes when intent mode matches context mode."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check7_mode_mismatch(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 7 fails when intent mode does not match context mode."""
    ctx = RiskContext(mode=ExecutionMode.REAL)
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("MODE_VALIDATION" in f[0] for f in failed)


# =============================================================================
# Tests: Check 8 — Real Lock State
# =============================================================================


def test_check8_real_not_locked(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 8 passes when REAL mode is not locked."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check8_real_locked(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 8 fails when REAL mode is locked."""
    sample_intent.mode = ExecutionMode.REAL
    ctx = RiskContext(mode=ExecutionMode.REAL, is_real_locked=True)
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("REAL_LOCK_STATE" in f[0] for f in failed)


def test_check8_skipped_in_paper(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
) -> None:
    """Check 8 skips when not in REAL mode."""
    ctx = RiskContext(mode=ExecutionMode.PAPER, is_real_locked=True)
    result = risk_gate.evaluate(sample_intent, ctx)
    assert not any("REAL_LOCK_STATE" in c[0] and not c[1] for c in result.checks)


def test_check8_callback_overrides_context(
    fingerprint_store: IntentFingerprintStore,
    sample_intent: ExecutionIntent,
) -> None:
    """The is_real_locked_check callback overrides context value."""
    sample_intent.mode = ExecutionMode.REAL
    gate = RiskGate(
        intent_fingerprint_store=fingerprint_store,
        is_real_locked_check=lambda: True,
    )
    ctx = RiskContext(mode=ExecutionMode.REAL, is_real_locked=False)
    result = gate.evaluate(sample_intent, ctx)
    # Callback returns True, so should be blocked
    assert result.passed is False


# =============================================================================
# Tests: Check 9 — Duplicate Execution Prevention
# =============================================================================


def test_check9_no_duplicate(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 9 passes for a new intent."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check9_duplicate_detected(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 9 fails for a duplicate intent."""
    # Evaluate once (succeeds, registers fingerprint)
    risk_gate.evaluate(sample_intent, default_context)

    # Evaluate same intent again (should be duplicate)
    result = risk_gate.evaluate(sample_intent, default_context)
    failed = result.get_failed_checks()
    assert any("DUPLICATE_EXECUTION" in f[0] for f in failed)


def test_check9_different_intent_not_duplicate(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Different intents are not considered duplicates."""
    risk_gate.evaluate(sample_intent, default_context)

    other_intent = ExecutionIntent(
        trade_id="trade_snap_002",
        action="SELL",
        option_side="PE",
        selected_strike="19400",
        trade_class=TradeClass.REVERSAL,
        entry_plan={"premium": 120.0},
        mode=ExecutionMode.PAPER,
        timestamp=sample_intent.timestamp + timedelta(seconds=6),  # Different window
    )
    result = risk_gate.evaluate(other_intent, default_context)
    assert result.passed is True


# =============================================================================
# Tests: Check 10 — One-Trade Enforcement
# =============================================================================


def test_check10_no_active_trade(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 10 passes when no active trade exists."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check10_active_trade_exists(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 10 fails when an active trade exists."""
    ctx = RiskContext(has_active_trade=True, mode=ExecutionMode.PAPER)
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("ONE_TRADE_ENFORCEMENT" in f[0] for f in failed)


def test_check10_callback_overrides_context(
    fingerprint_store: IntentFingerprintStore,
    sample_intent: ExecutionIntent,
) -> None:
    """The has_active_trade_check callback overrides context value."""
    gate = RiskGate(
        intent_fingerprint_store=fingerprint_store,
        has_active_trade_check=lambda: True,
    )
    ctx = RiskContext(has_active_trade=False, mode=ExecutionMode.PAPER)
    result = gate.evaluate(sample_intent, ctx)
    assert result.passed is False


# =============================================================================
# Tests: Check 11 — Stale Intent Detection
# =============================================================================


def test_check11_fresh_intent(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 11 passes for a fresh intent."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check11_stale_intent(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 11 fails for a stale intent."""
    sample_intent.timestamp = datetime.utcnow() - timedelta(seconds=120)
    result = risk_gate.evaluate(sample_intent, default_context)
    failed = result.get_failed_checks()
    assert any("STALE_INTENT" in f[0] for f in failed)


# =============================================================================
# Tests: Check 12 — Data Health
# =============================================================================


def test_check12_good_health(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 12 passes when data health is GOOD."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True


def test_check12_critical_health(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 12 fails when data health is CRITICAL."""
    ctx = RiskContext(data_health=DataHealth.CRITICAL, mode=ExecutionMode.PAPER)
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("DATA_HEALTH" in f[0] for f in failed)


def test_check12_stale_health(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 12 fails when data health is STALE."""
    ctx = RiskContext(data_health=DataHealth.STALE, mode=ExecutionMode.PAPER)
    result = risk_gate.evaluate(sample_intent, ctx)
    failed = result.get_failed_checks()
    assert any("DATA_HEALTH" in f[0] for f in failed)


def test_check12_degraded_health_allows(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """Check 12 allows execution when data health is DEGRADED."""
    ctx = RiskContext(data_health=DataHealth.DEGRADED, mode=ExecutionMode.PAPER)
    result = risk_gate.evaluate(sample_intent, ctx)
    # DEGRADED should pass (with caution)
    health_checks = [(n, ok) for n, ok, _ in result.checks if "DATA_HEALTH" in n]
    if health_checks:
        assert health_checks[0][1] is True


# =============================================================================
# Tests: is_blocked_for_safety
# =============================================================================


def test_is_blocked_for_safety_all_pass(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """is_blocked_for_safety returns False when all checks pass."""
    assert risk_gate.is_blocked_for_safety(sample_intent, default_context) is False


def test_is_blocked_for_safety_blocked(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """is_blocked_for_safety returns True when a check fails."""
    ctx = RiskContext(has_active_trade=True, mode=ExecutionMode.PAPER)
    assert risk_gate.is_blocked_for_safety(sample_intent, ctx) is True


# =============================================================================
# Tests: evaluate — combined flow
# =============================================================================


def test_evaluate_all_checks_present(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """evaluate returns all 12 check results."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert len(result.checks) == 12


def test_evaluate_default_context(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
) -> None:
    """evaluate works with default (permissive) context."""
    result = risk_gate.evaluate(sample_intent)
    # Should still produce checks
    assert len(result.checks) >= 10


def test_evaluate_multiple_failures(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
) -> None:
    """Multiple failures are reported."""
    ctx = RiskContext(
        available_capital=100.0,
        required_capital=5000.0,
        mode=ExecutionMode.REAL,
        is_real_locked=True,
        data_health=DataHealth.CRITICAL,
    )
    result = risk_gate.evaluate(sample_intent, ctx)
    assert result.passed is False
    assert len(result.get_failed_checks()) >= 3


# =============================================================================
# Tests: max_age_seconds property
# =============================================================================


def test_max_age_seconds_default(fingerprint_store: IntentFingerprintStore) -> None:
    """Default max_age_seconds is 60."""
    gate = RiskGate(intent_fingerprint_store=fingerprint_store)
    assert gate.max_age_seconds == 60


def test_max_age_seconds_setter(fingerprint_store: IntentFingerprintStore) -> None:
    """Setting max_age_seconds updates the value."""
    gate = RiskGate(intent_fingerprint_store=fingerprint_store)
    gate.max_age_seconds = 120
    assert gate.max_age_seconds == 120


# =============================================================================
# Tests: ALL 12 checks pass simultaneously
# =============================================================================


def test_all_12_checks_pass(
    risk_gate: RiskGate,
    sample_intent: ExecutionIntent,
    default_context: RiskContext,
) -> None:
    """All 12 checks pass with a valid intent and default context."""
    result = risk_gate.evaluate(sample_intent, default_context)
    assert result.passed is True
    assert result.recommended_action == "PROCEED"
    assert len(result.checks) == 12
