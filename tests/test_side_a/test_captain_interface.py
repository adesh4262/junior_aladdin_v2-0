"""Tests for captain_interface — DecisionOutput → ExecutionIntent translation."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.shared.types import (
    CaptainDecision,
    DecisionType,
    ExecutionIntent,
    ExecutionMode,
    TradeClass,
)
from junior_aladdin.side_a_execution.captain_interface import (
    CaptainInterface,
    _generate_intent_fingerprint,
    _generate_trade_id,
    _validate_trade_decision_fields,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def valid_trade_decision() -> CaptainDecision:
    """A valid TRADE decision with all mandatory fields."""
    return CaptainDecision(
        decision=DecisionType.TRADE,
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        permission_score=75.0,
        conviction_score=72.0,
        no_trade_score=15.0,
        entry_plan={
            "trigger": "price_above_zone",
            "zone": "19480-19520",
            "confirmation": "1m_close_above_19500",
        },
        invalidation_level=19450.0,
        stop_loss_plan={
            "price": 19450.0,
            "type": "fixed",
        },
        target_plan={
            "targets": [{"price": 19600.0, "size": 0.5}, {"price": 19650.0, "size": 0.5}],
            "trailing": {"active": False},
        },
        reason_summary="Strong continuation setup with SMC + ICT confluence",
        snapshot_id="snap_001",
        timestamp=datetime.utcnow(),
    )


@pytest.fixture
def valid_system_context() -> dict:
    """A valid system context dict."""
    return {
        "mode": ExecutionMode.PAPER,
        "available_capital": 50000.0,
        "max_risk_per_trade": 5000.0,
        "intervention_allowed": True,
    }


@pytest.fixture
def interface() -> CaptainInterface:
    """A default CaptainInterface instance."""
    return CaptainInterface()


# =============================================================================
# Tests: receive_intent — success path
# =============================================================================


def test_receive_intent_returns_execution_intent(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
    valid_system_context: dict,
) -> None:
    """Happy path: valid TRADE decision → valid ExecutionIntent."""
    intent = interface.receive_intent(valid_trade_decision, valid_system_context)

    assert isinstance(intent, ExecutionIntent)
    assert intent.trade_id == "trade_snap_001"
    assert intent.action == "BUY"
    assert intent.option_side == "CE"
    assert intent.selected_strike == "19500"
    assert intent.trade_class == TradeClass.CONTINUATION
    assert intent.mode == ExecutionMode.PAPER
    assert intent.intervention_allowed is True
    assert intent.invalidation_level == 19450.0
    assert len(intent.intent_fingerprint) == 32  # SHA256 truncated
    assert intent.timestamp == valid_trade_decision.timestamp


def test_receive_intent_sets_capital_context(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Capital context is populated from system_context."""
    context = {"available_capital": 100000.0, "max_risk_per_trade": 10000.0}
    intent = interface.receive_intent(valid_trade_decision, context)

    assert intent.capital_context["available_capital"] == 100000.0
    assert intent.capital_context["max_risk_per_trade"] == 10000.0


def test_receive_intent_default_context(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Without system_context, defaults to ALERT mode and zero capital."""
    intent = interface.receive_intent(valid_trade_decision)

    assert intent.mode == ExecutionMode.ALERT
    assert intent.capital_context["available_capital"] == 0.0
    assert intent.capital_context["max_risk_per_trade"] == 0.0
    assert intent.intervention_allowed is False


def test_receive_intent_uses_snapshot_id_as_trade_id(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Trade ID is derived from snapshot_id."""
    intent = interface.receive_intent(valid_trade_decision)
    assert intent.trade_id == "trade_snap_001"


def test_receive_intent_generates_trade_id_without_snapshot(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Without snapshot_id, trade_id is generated from timestamp."""
    valid_trade_decision.snapshot_id = ""
    intent = interface.receive_intent(valid_trade_decision)
    assert intent.trade_id.startswith("trade_cap_")


# =============================================================================
# Tests: receive_intent — validation failure path
# =============================================================================


def test_receive_intent_raises_on_non_trade_decision(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Non-TRADE decisions raise ExecutionError."""
    valid_trade_decision.decision = DecisionType.WAIT
    with pytest.raises(ExecutionError, match="non-TRADE"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_blocked_decision(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """BLOCKED decisions raise ExecutionError."""
    valid_trade_decision.decision = DecisionType.BLOCKED
    with pytest.raises(ExecutionError, match="non-TRADE"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_empty_action(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Empty action raises ExecutionError."""
    valid_trade_decision.action = ""
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_invalid_action(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Invalid action value raises ExecutionError."""
    valid_trade_decision.action = "HOLD"
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_empty_option_side(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Empty option_side raises ExecutionError."""
    valid_trade_decision.option_side = ""
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_invalid_option_side(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Invalid option_side raises ExecutionError."""
    valid_trade_decision.option_side = "OTM"
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_empty_strike(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Empty selected_strike raises ExecutionError."""
    valid_trade_decision.selected_strike = ""
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_empty_entry_plan(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Empty entry_plan raises ExecutionError."""
    valid_trade_decision.entry_plan = {}
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_zero_invalidation(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Zero invalidation_level raises ExecutionError."""
    valid_trade_decision.invalidation_level = 0.0
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_empty_sl_plan(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Empty stop_loss_plan raises ExecutionError."""
    valid_trade_decision.stop_loss_plan = {}
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_empty_target_plan(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Empty target_plan raises ExecutionError."""
    valid_trade_decision.target_plan = {}
    with pytest.raises(ExecutionError, match="missing"):
        interface.receive_intent(valid_trade_decision)


def test_receive_intent_raises_on_partial_entry_plan(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Entry plan missing trigger/confirmation keys raises ExecutionError."""
    valid_trade_decision.entry_plan = {"zone": "19480-19520"}  # missing trigger + confirmation
    with pytest.raises(ExecutionError) as exc:
        interface.receive_intent(valid_trade_decision)
    missing = exc.value.details.get("missing_fields", [])
    assert any("trigger" in m for m in missing)
    assert any("confirmation" in m for m in missing)


def test_receive_intent_raises_on_partial_sl_plan(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
) -> None:
    """Stop loss plan missing price key raises ExecutionError."""
    valid_trade_decision.stop_loss_plan = {"type": "fixed"}  # missing price
    with pytest.raises(ExecutionError) as exc:
        interface.receive_intent(valid_trade_decision)
    missing = exc.value.details.get("missing_fields", [])
    assert any("price" in m for m in missing)


# =============================================================================
# Tests: validate_intent_freshness
# =============================================================================


def test_validate_fresh_intent(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
    valid_system_context: dict,
) -> None:
    """A fresh intent (just created) should be valid."""
    intent = interface.receive_intent(valid_trade_decision, valid_system_context)
    assert interface.validate_intent_freshness(intent) is True


def test_validate_stale_intent(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
    valid_system_context: dict,
) -> None:
    """A stale intent (older than max_age) should be invalid."""
    valid_trade_decision.timestamp = datetime.utcnow() - timedelta(seconds=120)
    intent = interface.receive_intent(valid_trade_decision, valid_system_context)
    assert interface.validate_intent_freshness(intent) is False


def test_validate_intent_edge_case(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
    valid_system_context: dict,
) -> None:
    """An intent exactly at the age limit should be fresh."""
    valid_trade_decision.timestamp = datetime.utcnow() - timedelta(seconds=60)
    intent = interface.receive_intent(valid_trade_decision, valid_system_context)
    assert interface.validate_intent_freshness(intent) is True


def test_validate_intent_custom_max_age(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
    valid_system_context: dict,
) -> None:
    """Custom max_age_seconds overrides the instance default."""
    valid_trade_decision.timestamp = datetime.utcnow() - timedelta(seconds=30)
    intent = interface.receive_intent(valid_trade_decision, valid_system_context)
    # Instance default is 60s, so 30s is fresh
    assert interface.validate_intent_freshness(intent, max_age_seconds=60) is True
    # Custom 10s makes it stale
    assert interface.validate_intent_freshness(intent, max_age_seconds=10) is False


# =============================================================================
# Tests: extract_execution_context
# =============================================================================


def test_extract_execution_context(
    interface: CaptainInterface,
    valid_trade_decision: CaptainDecision,
    valid_system_context: dict,
) -> None:
    """extract_execution_context returns expected fields."""
    intent = interface.receive_intent(valid_trade_decision, valid_system_context)
    ctx = interface.extract_execution_context(intent)

    assert ctx["trade_id"] == "trade_snap_001"
    assert ctx["action"] == "BUY"
    assert ctx["option_side"] == "CE"
    assert ctx["strike"] == "19500"
    assert ctx["trade_class"] == "CONTINUATION"
    assert ctx["mode"] == "PAPER"
    assert ctx["intervention_allowed"] is True
    assert ctx["capital"]["available"] == 50000.0
    assert ctx["capital"]["max_risk"] == 5000.0
    assert ctx["conviction_basis"]["invalidation_level"] == 19450.0
    assert len(ctx["intent_fingerprint"]) == 32


# =============================================================================
# Tests: max_age_seconds property
# =============================================================================


def test_max_age_seconds_default() -> None:
    """Default max_age_seconds is 60."""
    interface = CaptainInterface()
    assert interface.max_age_seconds == 60


def test_max_age_seconds_custom() -> None:
    """Custom max_age_seconds is stored."""
    interface = CaptainInterface(max_age_seconds=30)
    assert interface.max_age_seconds == 30


def test_max_age_seconds_setter(interface: CaptainInterface) -> None:
    """Setting max_age_seconds updates the value."""
    interface.max_age_seconds = 120
    assert interface.max_age_seconds == 120


def test_max_age_seconds_setter_raises_on_zero(interface: CaptainInterface) -> None:
    """Setting max_age_seconds to zero raises ExecutionError."""
    with pytest.raises(ExecutionError, match="positive"):
        interface.max_age_seconds = 0


def test_max_age_seconds_setter_raises_on_negative(interface: CaptainInterface) -> None:
    """Setting max_age_seconds to negative raises ExecutionError."""
    with pytest.raises(ExecutionError, match="positive"):
        interface.max_age_seconds = -1


# =============================================================================
# Tests: helper functions
# =============================================================================


def test_generate_trade_id_from_snapshot() -> None:
    """Trade ID generated from snapshot_id."""
    decision = CaptainDecision(
        decision=DecisionType.TRADE,
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.SCALP,
        snapshot_id="snap_xyz",
    )
    trade_id = _generate_trade_id(decision)
    assert trade_id == "trade_snap_xyz"


def test_generate_trade_id_without_snapshot() -> None:
    """Trade ID generated from timestamp when no snapshot_id."""
    decision = CaptainDecision(
        decision=DecisionType.TRADE,
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.SCALP,
        snapshot_id="",
    )
    trade_id = _generate_trade_id(decision)
    assert trade_id.startswith("trade_cap_")


def test_generate_intent_fingerprint_deterministic() -> None:
    """Same inputs produce the same fingerprint."""
    now = datetime.utcnow()
    fp1 = _generate_intent_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = _generate_intent_fingerprint("trade_001", "BUY", "19500", now)
    assert fp1 == fp2
    assert len(fp1) == 32


def test_generate_intent_fingerprint_different_trade() -> None:
    """Different inputs produce different fingerprints."""
    now = datetime.utcnow()
    fp1 = _generate_intent_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = _generate_intent_fingerprint("trade_002", "SELL", "19400", now)
    assert fp1 != fp2


def test_validate_trade_decision_fields_valid(
    valid_trade_decision: CaptainDecision,
) -> None:
    """Valid decision should not raise."""
    # Should not raise any exception
    _validate_trade_decision_fields(valid_trade_decision)


def test_validate_trade_decision_fields_missing_multiple(
    valid_trade_decision: CaptainDecision,
) -> None:
    """Missing multiple fields reports all of them."""
    valid_trade_decision.action = ""
    valid_trade_decision.entry_plan = {}
    valid_trade_decision.invalidation_level = 0.0

    with pytest.raises(ExecutionError) as exc:
        _validate_trade_decision_fields(valid_trade_decision)

    details = exc.value.details
    missing = details.get("missing_fields", [])
    # Should contain action, entry_plan, invalidation_level errors
    assert any("action" in m for m in missing)
    assert any("entry_plan" in m for m in missing)
    assert any("invalidation_level" in m for m in missing)
