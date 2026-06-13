"""Tests for Side A — Reconciliation Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    OrderLifecycleManager,
    OrderState,
    OrderRecord,
    SLTGTLinkage,
)
from junior_aladdin.side_a_execution.position_manager import (
    PositionManager,
    PositionState,
)
from junior_aladdin.side_a_execution.reconciliation_engine import (
    DEFAULT_MAX_RECONCILE_ATTEMPTS,
    DEFAULT_RECONCILE_BACKOFF_SECONDS,
    DEFAULT_RECONCILE_WINDOW_SECONDS,
    PRICE_TOLERANCE,
    ReconcileResult,
    ReconciliationEngine,
)
from junior_aladdin.side_a_execution.side_a_types import ReconcileOutcome


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def pm():
    """PositionManager fixture."""
    pm_inst = PositionManager()
    pm_inst.open_position(
        trade_id="TRADE-001",
        direction="BUY",
        filled_qty=25,
        price=150.0,
    )
    pm_inst.set_sl("TRADE-001", 148.0)
    pm_inst.set_target("TRADE-001", 155.0)
    return pm_inst


@pytest.fixture
def olm():
    """OrderLifecycleManager fixture with a registered order."""
    olm_inst = OrderLifecycleManager()
    order = OrderRecord(
        order_id="ORD001",
        trade_id="TRADE-001",
        side="BUY",
        quantity=25,
        price=150.0,
        state=OrderState.ACKNOWLEDGED,
    )
    olm_inst._orders["ORD001"] = order
    olm_inst._trade_orders.setdefault("TRADE-001", []).append("ORD001")

    order_filled = OrderRecord(
        order_id="ORD002",
        trade_id="TRADE-001",
        side="BUY",
        quantity=25,
        price=150.0,
        state=OrderState.FILLED,
    )
    olm_inst._orders["ORD002"] = order_filled
    olm_inst._trade_orders.setdefault("TRADE-001", []).append("ORD002")
    return olm_inst


@pytest.fixture
def engine(pm, olm):
    """ReconciliationEngine fixture."""
    return ReconciliationEngine(
        position_manager=pm,
        order_lifecycle_manager=olm,
    )


@pytest.fixture
def broker_data():
    """Standard broker data matching local state (2 orders)."""
    return {
        "position": {
            "filled_qty": 25,
            "avg_price": 150.0,
            "direction": "BUY",
            "status": "OPEN",
            "sl_price": 148.0,
            "target_price": 155.0,
        },
        "orders": [
            {"order_id": "ORD002", "state": "FILLED"},
            {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
        ],
    }


@pytest.fixture
def broker_data_mismatch():
    """Broker data with differences from local state."""
    return {
        "position": {
            "filled_qty": 20,  # differs
            "avg_price": 151.0,  # differs
            "direction": "BUY",
            "status": "OPEN",
            "sl_price": 148.0,  # matches
            "target_price": 156.0,  # differs
        },
        "orders": [
            {"order_id": "ORD002", "state": "FILLED"},
            {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
        ],
    }


# =============================================================================
# ReconcileResult Tests
# =============================================================================


class TestReconcileResult:
    """Tests for the ReconcileResult dataclass."""

    def test_default_construction(self):
        result = ReconcileResult()
        assert result.outcome == ReconcileOutcome.MATCH
        assert result.mismatches == []
        assert result.actions == []
        assert result.attempt == 1
        assert isinstance(result.timestamp, datetime)

    def test_custom_construction(self):
        now = datetime.utcnow()
        result = ReconcileResult(
            outcome=ReconcileOutcome.MISMATCH_ESCALATED,
            mismatches=["POSITION_QTY: local=25, broker=20"],
            actions=["Escalated: mismatch cannot be resolved"],
            local_state={"position": {"filled_qty": 25}},
            broker_state={"position": {"filled_qty": 20}},
            resolved_state={"escalated": True},
            timestamp=now,
            attempt=3,
        )
        assert result.outcome == ReconcileOutcome.MISMATCH_ESCALATED
        assert len(result.mismatches) == 1
        assert len(result.actions) == 1
        assert result.attempt == 3


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInit:
    """Tests for ReconciliationEngine initialization."""

    def test_init_defaults(self, pm, olm):
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )
        assert engine._pm is pm
        assert engine._olm is olm
        assert engine._max_attempts == DEFAULT_MAX_RECONCILE_ATTEMPTS
        assert engine._backoff_seconds == DEFAULT_RECONCILE_BACKOFF_SECONDS
        assert engine._reconcile_window_seconds == DEFAULT_RECONCILE_WINDOW_SECONDS
        assert engine._on_log_callback is None

    def test_init_custom(self, pm, olm):
        def callback(e, d):
            pass
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
            max_attempts=5,
            backoff_seconds=10.0,
            reconcile_window_seconds=60,
            on_log_callback=callback,
        )
        assert engine._max_attempts == 5
        assert engine._backoff_seconds == 10.0
        assert engine._reconcile_window_seconds == 60
        assert engine._on_log_callback is callback


# =============================================================================
# detect_mismatch Tests
# =============================================================================


class TestDetectMismatch:
    """Tests for detect_mismatch — Step 1 of the reconciliation protocol."""

    def test_match(self, engine, broker_data):
        """Both empty = no mismatch."""
        has, mismatches = engine.detect_mismatch({}, {})
        assert not has
        assert mismatches == []

    def test_match_with_local_and_broker(self, engine, broker_data):
        """Local matches broker = no mismatch."""
        local_state = engine._capture_local_state("TRADE-001")
        has, mismatches = engine.detect_mismatch(local_state, broker_data)
        assert not has
        assert mismatches == []

    def test_local_no_position(self, engine, broker_data):
        """Local has no position but broker does."""
        has, mismatches = engine.detect_mismatch(
            {"position": {}, "orders": []},
            broker_data,
        )
        assert has
        assert any("LOCAL_NO_POSITION" in m for m in mismatches)

    def test_broker_no_position(self, engine):
        """Local has position but broker has none."""
        local_state = engine._capture_local_state("TRADE-001")
        has, mismatches = engine.detect_mismatch(
            local_state,
            {"position": {}, "orders": []},
        )
        assert has
        assert any("BROKER_NO_POSITION" in m for m in mismatches)

    def test_quantity_mismatch(self, engine):
        """Different filled quantities."""
        local = {"position": {"filled_qty": 25}, "orders": []}
        broker = {"position": {"filled_qty": 20}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("POSITION_QTY" in m and "local=25" in m and "broker=20" in m for m in mismatches)

    def test_price_mismatch(self, engine):
        """Different average prices (beyond tolerance)."""
        local = {"position": {"filled_qty": 25, "avg_price": 150.0}, "orders": []}
        broker = {"position": {"filled_qty": 25, "avg_price": 151.0}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("PRICE" in m and "local=150.00" in m and "broker=151.00" in m for m in mismatches)

    def test_price_tolerance(self, engine):
        """Small price differences within tolerance should not trigger mismatch."""
        local = {"position": {"filled_qty": 25, "avg_price": 150.005}, "orders": []}
        broker = {"position": {"filled_qty": 25, "avg_price": 150.008}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        # Difference is 0.003 < PRICE_TOLERANCE (0.01)
        assert not any("PRICE" in m for m in mismatches)

    def test_direction_mismatch(self, engine):
        """Different direction."""
        local = {"position": {"filled_qty": 25, "direction": "BUY"}, "orders": []}
        broker = {"position": {"filled_qty": 25, "direction": "SELL"}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("DIRECTION" in m for m in mismatches)

    def test_status_mismatch(self, engine):
        """Different position status."""
        local = {"position": {"filled_qty": 25, "status": "OPEN"}, "orders": []}
        broker = {"position": {"filled_qty": 25, "status": "CLOSED"}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("STATUS" in m for m in mismatches)

    def test_sl_mismatch(self, engine):
        """Different SL prices."""
        local = {"position": {"filled_qty": 25, "sl_price": 148.0}, "orders": []}
        broker = {"position": {"filled_qty": 25, "sl_price": 147.5}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("SL_PRICE" in m for m in mismatches)

    def test_tgt_mismatch(self, engine):
        """Different target prices."""
        local = {"position": {"filled_qty": 25, "target_price": 155.0}, "orders": []}
        broker = {"position": {"filled_qty": 25, "target_price": 156.0}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("TGT_PRICE" in m for m in mismatches)

    def test_order_count_mismatch(self, engine):
        """Different number of orders."""
        local = {"position": {"filled_qty": 25}, "orders": [{"order_id": "O1", "state": "FILLED"}, {"order_id": "O2", "state": "PLACED"}]}
        broker = {"position": {"filled_qty": 25}, "orders": [{"order_id": "O1", "state": "FILLED"}]}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("ORDER_COUNT" in m for m in mismatches)

    def test_order_state_mismatch(self, engine):
        """Same order but different state."""
        local = {"position": {"filled_qty": 25}, "orders": [{"order_id": "ORD001", "state": "FILLED"}]}
        broker = {"position": {"filled_qty": 25}, "orders": [{"order_id": "ORD001", "state": "PLACED"}]}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("ORDER_STATE_ORD001" in m for m in mismatches)

    def test_order_presence_mismatch(self, engine):
        """Order exists locally but not at broker."""
        local = {"position": {"filled_qty": 25}, "orders": [{"order_id": "ORD001", "state": "FILLED"}, {"order_id": "ORD002", "state": "PLACED"}]}
        broker = {"position": {"filled_qty": 25}, "orders": [{"order_id": "ORD001", "state": "FILLED"}]}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert any("ORDER_PRESENCE" in m and "ORD002" in m for m in mismatches)

    def test_multiple_mismatches(self, engine):
        """Multiple differences detected simultaneously."""
        local = {"position": {"filled_qty": 25, "avg_price": 150.0, "direction": "BUY", "status": "OPEN", "sl_price": 148.0, "target_price": 155.0}, "orders": []}
        broker = {"position": {"filled_qty": 20, "avg_price": 151.0, "direction": "SELL", "status": "PARTIALLY_CLOSED", "sl_price": 147.0, "target_price": 156.0}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert has
        assert len(mismatches) >= 6  # qty + price + dir + status + sl + tgt


# =============================================================================
# classify_mismatch Tests
# =============================================================================


class TestClassifyMismatch:
    """Tests for classify_mismatch — Step 2 of the reconciliation protocol."""

    def test_no_mismatches(self, engine):
        """Empty mismatches → MATCH."""
        result = engine.classify_mismatch([], {}, {})
        assert result == ReconcileOutcome.MATCH

    def test_escalate_broker_no_position(self, engine):
        """Broker has no position but local has active position → ESCALATED."""
        mismatches = ["POSITION_QTY: local=25, broker=0"]
        local_state = {"position": {"filled_qty": 25}}
        broker_state = {"position": {}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_ESCALATED

    def test_escalate_direction_mismatch(self, engine):
        """Direction differs → ESCALATED."""
        mismatches = ["DIRECTION: local=BUY, broker=SELL"]
        local_state = {"position": {"filled_qty": 25, "direction": "BUY"}}
        broker_state = {"position": {"filled_qty": 25, "direction": "SELL"}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_ESCALATED

    def test_resolve_quantity(self, engine):
        """Quantity mismatch → RESOLVED."""
        mismatches = ["POSITION_QTY: local=25, broker=20"]
        local_state = {"position": {"filled_qty": 25}}
        broker_state = {"position": {"filled_qty": 20}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_RESOLVED

    def test_resolve_price(self, engine):
        """Price mismatch → RESOLVED."""
        mismatches = ["PRICE: local=150.00, broker=151.00"]
        local_state = {"position": {"filled_qty": 25, "avg_price": 150.0}}
        broker_state = {"position": {"filled_qty": 25, "avg_price": 151.0}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_RESOLVED

    def test_resolve_sl_tgt(self, engine):
        """SL/TGT price drift → RESOLVED."""
        mismatches = ["SL_PRICE: local=148.0, broker=147.5"]
        local_state = {"position": {"filled_qty": 25, "sl_price": 148.0}}
        broker_state = {"position": {"filled_qty": 25, "sl_price": 147.5}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_RESOLVED

    def test_resolve_order_state(self, engine):
        """Order state mismatch → RESOLVED."""
        mismatches = ["ORDER_STATE_ORD001: local=FILLED, broker=PLACED"]
        local_state = {"position": {"filled_qty": 25}}
        broker_state = {"position": {"filled_qty": 25}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_RESOLVED

    def test_resolve_order_presence(self, engine):
        """Order presence mismatch → RESOLVED."""
        mismatches = ["ORDER_PRESENCE: order ORD002 exists locally but not at broker"]
        local_state = {"position": {"filled_qty": 25}}
        broker_state = {"position": {"filled_qty": 25}}
        result = engine.classify_mismatch(mismatches, local_state, broker_state)
        assert result == ReconcileOutcome.MISMATCH_RESOLVED

    def test_escalate_no_broker_state(self, engine):
        """Broker_state is None or empty and local active → ESCALATED."""
        mismatches = ["POSITION_QTY: local=25, broker=0"]
        local_state = {"position": {"filled_qty": 25}}
        result = engine.classify_mismatch(mismatches, local_state, {})
        assert result == ReconcileOutcome.MISMATCH_ESCALATED


# =============================================================================
# compare Tests
# =============================================================================


class TestCompare:
    """Tests for compare — Step 3 (detailed field-level diff)."""

    def test_no_differences(self, engine):
        """Identical state → no differences."""
        local = {"position": {"filled_qty": 25, "avg_price": 150.0, "direction": "BUY", "status": "OPEN", "sl_price": 148.0, "target_price": 155.0}}
        broker = {"position": {"filled_qty": 25, "avg_price": 150.0, "direction": "BUY", "status": "OPEN", "sl_price": 148.0, "target_price": 155.0}}
        result = engine.compare(local, broker)
        assert not result["has_differences"]
        assert result["differences"] == []

    def test_all_fields_differ(self, engine):
        """All fields differ."""
        local = {"position": {"filled_qty": 25, "avg_price": 150.0, "direction": "BUY", "status": "OPEN", "sl_price": 148.0, "target_price": 155.0}}
        broker = {"position": {"filled_qty": 20, "avg_price": 151.0, "direction": "SELL", "status": "CLOSED", "sl_price": 147.0, "target_price": 156.0}}
        result = engine.compare(local, broker)
        assert result["has_differences"]
        assert len(result["differences"]) == 6

    def test_critical_fields(self, engine):
        """filled_qty and direction and status are marked critical."""
        local = {"position": {"filled_qty": 25, "direction": "BUY", "status": "OPEN"}}
        broker = {"position": {"filled_qty": 20, "direction": "SELL", "status": "CLOSED"}}
        result = engine.compare(local, broker)
        diff_by_field = {d["field"]: d for d in result["differences"]}
        assert diff_by_field["position.filled_qty"]["critical"] is True
        assert diff_by_field["position.direction"]["critical"] is True
        assert diff_by_field["position.status"]["critical"] is True

    def test_local_and_broker_state_preserved(self, engine):
        """Input states are preserved in output."""
        local = {"position": {"filled_qty": 25}}
        broker = {"position": {"filled_qty": 20}}
        result = engine.compare(local, broker)
        assert result["local_state"] == local
        assert result["broker_state"] == broker


# =============================================================================
# reconcile Tests
# =============================================================================


class TestReconcile:
    """Tests for the full reconcile cycle."""

    def test_match(self, engine, broker_data):
        """Local matches broker → MATCH outcome."""
        result = engine.reconcile("TRADE-001", broker_data)
        assert result.outcome == ReconcileOutcome.MATCH
        assert result.mismatches == []
        assert result.actions == []

    def test_quantity_resolved(self, engine, broker_data_mismatch):
        """Quantity mismatch → RESOLVED."""
        result = engine.reconcile("TRADE-001", broker_data_mismatch)
        assert result.outcome == ReconcileOutcome.MISMATCH_RESOLVED
        assert len(result.mismatches) > 0
        assert len(result.actions) > 0
        assert "Quantity resolved" in " ".join(result.actions)

    def test_sl_resolved(self, engine):
        """SL price mismatch → RESOLVED with SL update."""
        broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": 147.5,
                "target_price": 155.0,
            },
            "orders": [
                {"order_id": "ORD002", "state": "FILLED"},
                {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
            ],
        }
        result = engine.reconcile("TRADE-001", broker)
        assert result.outcome == ReconcileOutcome.MISMATCH_RESOLVED
        assert any("SL price resolved" in a for a in result.actions)

    def test_tgt_resolved(self, engine):
        """Target price mismatch → RESOLVED with TGT update."""
        broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": 148.0,
                "target_price": 156.0,
            },
            "orders": [
                {"order_id": "ORD002", "state": "FILLED"},
                {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
            ],
        }
        result = engine.reconcile("TRADE-001", broker)
        assert result.outcome == ReconcileOutcome.MISMATCH_RESOLVED
        assert any("Target price resolved" in a for a in result.actions)

    def test_escalated(self, engine):
        """Broker reports different position direction → ESCALATED."""
        broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "SELL",
                "status": "OPEN",
                "sl_price": 148.0,
                "target_price": 155.0,
            },
            "orders": [
                {"order_id": "ORD002", "state": "FILLED"},
                {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
            ],
        }
        result = engine.reconcile("TRADE-001", broker)
        assert result.outcome == ReconcileOutcome.MISMATCH_ESCALATED
        assert "ESCALATED" in " ".join(result.actions)

    def test_reconcile_unknown_trade(self, engine, broker_data):
        """Unknown trade_id with broker data → mismatch resolved."""
        result = engine.reconcile("UNKNOWN-TRADE", broker_data)
        # Local doesn't have the position but broker does → MISMATCH_RESOLVED
        assert result.outcome == ReconcileOutcome.MISMATCH_RESOLVED

    def test_empty_trade_id(self, engine, broker_data):
        """Empty trade_id → ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot reconcile without trade_id"):
            engine.reconcile("", broker_data)

    def test_none_broker_data(self, engine):
        """None broker_data → ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot reconcile with None broker_data"):
            engine.reconcile("TRADE-001", None)


# =============================================================================
# handle_unclear_ack Tests
# =============================================================================


class TestHandleUnclearAck:
    """Tests for handle_unclear_ack — bounded retry for unclear acknowledgements."""

    def test_resolved_on_first_attempt(self, engine, broker_data):
        """Unclear ack resolved immediately — broker data matches."""
        result = engine.handle_unclear_ack("ORD001", broker_data)
        assert result.outcome == ReconcileOutcome.MATCH
        assert result.attempt == 1

    def test_escalated_after_max_attempts(self, engine):
        """Unclear ack not resolved after max attempts → ESCALATED."""
        mismatched_broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "SELL",
                "status": "OPEN",
            },
            "orders": [],
        }
        engine._max_attempts = 2
        result = engine.handle_unclear_ack("ORD001", mismatched_broker)
        assert result.outcome == ReconcileOutcome.MISMATCH_ESCALATED
        assert result.attempt == 2
        assert any("unresolved after" in m for m in result.mismatches)

    def test_resolved_without_broker_data(self, engine):
        """No broker data provided → defaults to escalation after max attempts."""
        engine._max_attempts = 1
        result = engine.handle_unclear_ack("ORD001")
        assert result.outcome == ReconcileOutcome.MISMATCH_ESCALATED

    def test_unknown_order(self, engine):
        """Unknown order_id → ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot handle unclear ack for unknown order"):
            engine.handle_unclear_ack("UNKNOWN_ORDER")

    def test_empty_order_id(self, engine):
        """Empty order_id → ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot handle unclear ack without order_id"):
            engine.handle_unclear_ack("")

    def test_attempts_saved_in_result(self, engine):
        """The attempt number is saved in the result."""
        mismatched_broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "SELL",
                "status": "OPEN",
            },
            "orders": [],
        }
        engine._max_attempts = 1
        result = engine.handle_unclear_ack("ORD001", mismatched_broker)
        assert result.attempt == 1

    def test_escalated_logs_event(self, engine):
        """Escalation logs the UNCLEAR_ACK_ESCALATED event."""
        log_events = []

        def log_cb(event_type, data):
            log_events.append((event_type, data))

        engine._on_log_callback = log_cb
        engine._max_attempts = 1
        result = engine.handle_unclear_ack("ORD001", {})
        assert result.outcome == ReconcileOutcome.MISMATCH_ESCALATED
        assert any(t == "UNCLEAR_ACK_ESCALATED" for t, d in log_events)


# =============================================================================
# handle_reconnect Tests
# =============================================================================


class TestHandleReconnect:
    """Tests for handle_reconnect — re-reconcile all active trades."""

    def test_reconnect_match(self, engine, broker_data):
        """Reconnect with matching broker data."""
        broker_positions = {"TRADE-001": broker_data}
        results = engine.handle_reconnect(broker_positions)
        assert len(results) == 1
        assert results[0].outcome == ReconcileOutcome.MATCH

    def test_reconnect_no_active(self, engine):
        """No active positions → empty results."""
        engine._pm.close_position("TRADE-001", close_qty=25, close_price=150.0)
        results = engine.handle_reconnect({"TRADE-001": {}})
        assert results == []

    def test_reconnect_none_broker_data(self, engine, broker_data):
        """None broker_data → ExecutionError."""
        with pytest.raises(ExecutionError, match="Cannot handle reconnect with None broker_data"):
            engine.handle_reconnect(None)

    def test_reconnect_logs_summary(self, engine, broker_data):
        """Reconnect logs a RECONNECT_RECONCILE summary event."""
        log_events = []

        def log_cb(event_type, data):
            log_events.append((event_type, data))

        engine._on_log_callback = log_cb
        broker_positions = {"TRADE-001": broker_data}
        engine.handle_reconnect(broker_positions)
        assert any(t == "RECONNECT_RECONCILE" for t, d in log_events)

    def test_reconnect_multiple_trades(self, engine, broker_data):
        """Multiple active trades → result for each."""
        pos2 = PositionState(trade_id="TRADE-002", direction="SELL", filled_qty=10, avg_price=200.0)
        engine._pm._positions["TRADE-002"] = pos2

        broker_positions = {
            "TRADE-001": broker_data,
            "TRADE-002": {
                "position": {
                    "filled_qty": 10,
                    "avg_price": 200.0,
                    "direction": "SELL",
                    "status": "OPEN",
                },
                "orders": [],
            },
        }
        results = engine.handle_reconnect(broker_positions)
        assert len(results) == 2

    def test_reconnect_partial_mismatch(self, engine, broker_data):
        """One trade matches, one trade mismatches."""
        pos2 = PositionState(trade_id="TRADE-002", direction="SELL", filled_qty=10, avg_price=200.0)
        engine._pm._positions["TRADE-002"] = pos2

        broker_positions = {
            "TRADE-001": broker_data,
            "TRADE-002": {
                "position": {
                    "filled_qty": 8,
                    "avg_price": 200.0,
                    "direction": "SELL",
                    "status": "OPEN",
                },
                "orders": [],
            },
        }
        results = engine.handle_reconnect(broker_positions)
        assert len(results) == 2


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_log_callback_called_on_reconcile(self, engine, broker_data):
        """Log callback is called for reconcile events."""
        log_events = []

        def log_cb(event_type, data):
            log_events.append((event_type, data))

        engine._on_log_callback = log_cb
        engine.reconcile("TRADE-001", broker_data)
        assert any(t in ("RECONCILE_MATCH", "RECONCILE_COMPLETE") for t, d in log_events)

    def test_log_callback_called_on_reconcile_mismatch(self, engine, broker_data_mismatch):
        """Log callback called for reconcile complete event on mismatch."""
        log_events = []

        def log_cb(event_type, data):
            log_events.append((event_type, data))

        engine._on_log_callback = log_cb
        engine.reconcile("TRADE-001", broker_data_mismatch)
        assert any(t == "RECONCILE_COMPLETE" for t, d in log_events)

    def test_capture_local_state_unknown_trade(self, engine):
        """Unknown trade returns empty state."""
        state = engine._capture_local_state("UNKNOWN")
        assert state["position"] == {}
        assert state["orders"] == []

    def test_reconcile_preserves_state_in_result(self, engine, broker_data_mismatch):
        """Reconcile result preserves local and broker state."""
        result = engine.reconcile("TRADE-001", broker_data_mismatch)
        assert "position" in result.local_state
        assert "orders" in result.local_state
        assert result.broker_state == broker_data_mismatch
        assert bool(result.resolved_state)

    def test_engine_without_log_callback(self, engine, broker_data):
        """Engine works without log callback."""
        engine._on_log_callback = None
        result = engine.reconcile("TRADE-001", broker_data)
        assert result.outcome == ReconcileOutcome.MATCH

    def test_detect_mismatch_with_none_values(self, engine):
        """SL and TGT can be None."""
        local = {"position": {"filled_qty": 25, "sl_price": None, "target_price": None}, "orders": []}
        broker = {"position": {"filled_qty": 25, "sl_price": None, "target_price": None}, "orders": []}
        has, mismatches = engine.detect_mismatch(local, broker)
        assert not has

    def test_resolve_mismatches_with_none_sl(self, engine):
        """SL mismatch resolution handles None values safely."""
        pm2 = PositionManager()
        pm2.open_position("TRADE-001", "BUY", 25, 150.0)
        olm2 = OrderLifecycleManager()
        engine2 = ReconciliationEngine(
            position_manager=pm2,
            order_lifecycle_manager=olm2,
        )

        broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": None,
                "target_price": None,
            },
            "orders": [],
        }
        result = engine2.reconcile("TRADE-001", broker)
        assert result.outcome == ReconcileOutcome.MATCH

    def test_unclear_ack_with_backoff(self, engine):
        """Multiple attempts with backoff are made."""
        engine._max_attempts = 3
        engine._backoff_seconds = 0.01
        start = datetime.utcnow()
        mismatched_broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "SELL",
                "status": "OPEN",
            },
            "orders": [],
        }
        result = engine.handle_unclear_ack("ORD001", mismatched_broker)
        elapsed = (datetime.utcnow() - start).total_seconds()
        assert result.attempt == 3
        assert elapsed >= 0.02

    def test_handle_reconnect_non_active_positions(self, engine, broker_data):
        """Only active positions are reconciled during reconnect."""
        engine._pm.close_position("TRADE-001", close_qty=25, close_price=150.0)
        results = engine.handle_reconnect({"TRADE-001": broker_data})
        assert results == []


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration-level tests combining engine with real PM/OLM."""

    def test_full_reconcile_cycle(self):
        """Complete reconcile cycle with real PM and OLM."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)
        pm.set_sl("TRADE-001", 148.0)
        pm.set_target("TRADE-001", 155.0)
        order = OrderRecord(
            order_id="ORD001",
            trade_id="TRADE-001",
            side="BUY",
            quantity=25,
            price=150.0,
            state=OrderState.ACKNOWLEDGED,
        )
        olm._orders["ORD001"] = order
        olm._trade_orders.setdefault("TRADE-001", []).append("ORD001")

        broker_data = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": 148.0,
                "target_price": 155.0,
            },
            "orders": [
                {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
            ],
        }

        result = engine.reconcile("TRADE-001", broker_data)
        assert result.outcome == ReconcileOutcome.MATCH

    def test_reconcile_updates_sl_price(self):
        """SL price mismatch is corrected via PM."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)
        pm.set_sl("TRADE-001", 148.0)

        broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": 147.5,
                "target_price": None,
            },
            "orders": [],
        }

        result = engine.reconcile("TRADE-001", broker)
        assert result.outcome == ReconcileOutcome.MISMATCH_RESOLVED
        assert any("SL price resolved" in a for a in result.actions)

        pos = pm.get_position("TRADE-001")
        assert pos.sl_price == 147.5

    def test_reconcile_updates_target_price(self):
        """Target price mismatch is corrected via PM."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)
        pm.set_target("TRADE-001", 155.0)

        broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": None,
                "target_price": 156.0,
            },
            "orders": [],
        }

        result = engine.reconcile("TRADE-001", broker)
        assert result.outcome == ReconcileOutcome.MISMATCH_RESOLVED
        assert any("Target price resolved" in a for a in result.actions)

        pos = pm.get_position("TRADE-001")
        assert pos.target_price == 156.0

    def test_handle_unclear_ack_with_real_olm(self):
        """Unclear ack with real OLM state."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)
        order = OrderRecord(
            order_id="ORD001",
            trade_id="TRADE-001",
            side="BUY",
            quantity=25,
            price=150.0,
            state=OrderState.ACKNOWLEDGED,
        )
        olm._orders["ORD001"] = order
        olm._trade_orders.setdefault("TRADE-001", []).append("ORD001")

        matching_broker = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": None,
                "target_price": None,
            },
            "orders": [
                {"order_id": "ORD001", "state": "ACKNOWLEDGED"},
            ],
        }

        result = engine.handle_unclear_ack("ORD001", matching_broker)
        assert result.outcome == ReconcileOutcome.MATCH

    def test_handle_reconnect_single(self):
        """Reconnect with a single active position."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)
        order = OrderRecord(
            order_id="ORD001",
            trade_id="TRADE-001",
            side="BUY",
            quantity=25,
            price=150.0,
            state=OrderState.FILLED,
        )
        olm._orders["ORD001"] = order
        olm._trade_orders.setdefault("TRADE-001", []).append("ORD001")

        broker_positions = {
            "TRADE-001": {
                "position": {
                    "filled_qty": 25,
                    "avg_price": 150.0,
                    "direction": "BUY",
                    "status": "OPEN",
                    "sl_price": None,
                    "target_price": None,
                },
                "orders": [
                    {"order_id": "ORD001", "state": "FILLED"},
                ],
            },
        }

        results = engine.handle_reconnect(broker_positions)
        assert len(results) == 1
        assert results[0].outcome == ReconcileOutcome.MATCH

    def test_reconcile_after_sl_already_set(self):
        """Reconciling after SL is already set on position."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)
        pm.set_sl("TRADE-001", 148.0)

        broker_same = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "BUY",
                "status": "OPEN",
                "sl_price": 148.0,
                "target_price": None,
            },
            "orders": [],
        }
        result = engine.reconcile("TRADE-001", broker_same)
        assert result.outcome == ReconcileOutcome.MATCH

    def test_reconcile_escalated_direction_mismatch(self):
        """Direction mismatch leads to escalation in full reconcile cycle."""
        pm = PositionManager()
        olm = OrderLifecycleManager()
        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        pm.open_position("TRADE-001", "BUY", 25, 150.0)

        broker_reversed = {
            "position": {
                "filled_qty": 25,
                "avg_price": 150.0,
                "direction": "SELL",
                "status": "OPEN",
                "sl_price": None,
                "target_price": None,
            },
            "orders": [],
        }

        result = engine.reconcile("TRADE-001", broker_reversed)
        assert result.outcome == ReconcileOutcome.MISMATCH_ESCALATED

    def test_detect_mismatch_both_empty(self, engine):
        """Both positions empty -> no mismatch."""
        has_mismatch, mismatches = engine.detect_mismatch(
            {"position": {}, "orders": []},
            {"position": {}, "orders": []},
        )
        assert not has_mismatch
        assert mismatches == []
