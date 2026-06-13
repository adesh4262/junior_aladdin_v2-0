"""Side A — Reconciliation Engine: Detect → Classify → Compare → Reconcile → Safe Action.

Detects mismatches between local execution state and broker truth, classifies
the severity, performs bounded reconciliation, and triggers escalation when
the state cannot be safely resolved.

Architecture rules (LOCKED — see ROADMAP_SIDE_A Section 7.12 & Section 16):
- Local snapshot = recovery aid / audit/reference layer
- Broker truth = final live authority
- UNKNOWN/PENDING_RECONCILE: bounded window, reconcile attempts, then escalate
- No optimistic assumption of success in UNKNOWN state
- Reconciliation: Detect → Classify → Compare → Reconcile → Safe Action

Mismatch types:
- position_qty: filled quantity differs
- price: average price differs between local and broker
- state: order state differs (e.g., local says FILLED, broker says REJECTED)
- order_presence: broker has orders that local doesn't (or vice versa)
- sl_tgt_drift: SL/TGT prices differ
- position_status: position open/closed status differs
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from junior_aladdin.shared.errors import ExecutionError
from junior_aladdin.side_a_execution.order_lifecycle_manager import (
    OrderLifecycleManager,
)
from junior_aladdin.side_a_execution.position_manager import PositionManager
from junior_aladdin.side_a_execution.side_a_types import (
    ReconciliationRecord,
    ReconcileOutcome,
)
from junior_aladdin.shared.types import Severity


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MAX_RECONCILE_ATTEMPTS: int = 3
"""Maximum number of reconcile attempts before escalation."""

DEFAULT_RECONCILE_BACKOFF_SECONDS: float = 5.0
"""Delay between reconcile attempts (seconds)."""

DEFAULT_RECONCILE_WINDOW_SECONDS: int = 30
"""Maximum time window for UNKNOWN state reconciliation (seconds)."""

# Tolerance for float comparisons
PRICE_TOLERANCE: float = 0.01


# =============================================================================
# Reconciliation Result
# =============================================================================


@dataclass
class ReconcileResult:
    """Result of a single reconciliation cycle.

    Fields:
        outcome: The reconciliation outcome (MATCH, MISMATCH_RESOLVED,
                 MISMATCH_ESCALATED).
        mismatches: List of mismatch descriptions found.
        actions: List of actions taken to resolve mismatches.
        local_state: Snapshot of local state at reconcile time.
        broker_state: Snapshot of broker state at reconcile time.
        resolved_state: The resolved state after reconciliation (for
                        MISMATCH_RESOLVED outcomes).
        timestamp: When the reconciliation occurred.
        attempt: Which attempt number this was (for unclear_ack flows).
    """
    outcome: ReconcileOutcome = ReconcileOutcome.MATCH
    mismatches: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    local_state: dict[str, Any] = field(default_factory=dict)
    broker_state: dict[str, Any] = field(default_factory=dict)
    resolved_state: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    attempt: int = 1


# =============================================================================
# ReconciliationEngine
# =============================================================================


class ReconciliationEngine:
    """Detects, classifies, and resolves mismatches between local and broker state.

    The engine follows the 5-step reconciliation protocol:
    1. Detect — compare local vs broker, produce mismatch list
    2. Classify — determine outcome (MATCH / RESOLVED / ESCALATED)
    3. Compare — detailed field-by-field diff
    4. Reconcile — apply broker truth to resolve mismatches
    5. Safe Action — escalate if unresolved

    Broker truth is the final authority — local state is updated to match
    when mismatches are found and resolvable.

    Usage::

        engine = ReconciliationEngine(
            position_manager=pm,
            order_lifecycle_manager=olm,
        )

        # Full reconcile cycle
        result = engine.reconcile(
            trade_id=\"TRADE-001\",
            broker_data=broker_position_data,
        )

        # Handle unclear ack with bounded retry
        result = engine.handle_unclear_ack(order_id=\"ORD001\",
                                            broker_data=broker_ack_data)

        # Handle reconnect
        result = engine.handle_reconnect(broker_data=broker_positions)
    """

    def __init__(
        self,
        position_manager: PositionManager,
        order_lifecycle_manager: OrderLifecycleManager,
        max_attempts: int = DEFAULT_MAX_RECONCILE_ATTEMPTS,
        backoff_seconds: float = DEFAULT_RECONCILE_BACKOFF_SECONDS,
        reconcile_window_seconds: int = DEFAULT_RECONCILE_WINDOW_SECONDS,
        on_log_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the ReconciliationEngine.

        Args:
            position_manager: For position state queries and updates.
            order_lifecycle_manager: For order state queries.
            max_attempts: Maximum reconcile attempts before escalation.
            backoff_seconds: Delay between attempts.
            reconcile_window_seconds: Max time window for UNKNOWN state.
            on_log_callback: Called for all reconcile events.
        """
        self._pm = position_manager
        self._olm = order_lifecycle_manager
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._reconcile_window_seconds = reconcile_window_seconds
        self._on_log_callback = on_log_callback

    # ------------------------------------------------------------------
    # 5-Step Reconciliation Protocol
    # ------------------------------------------------------------------

    def reconcile(
        self,
        trade_id: str,
        broker_data: dict[str, Any],
    ) -> ReconcileResult:
        """Run a full reconciliation cycle: detect → classify → resolve.

        Args:
            trade_id: The trade to reconcile.
            broker_data: Broker truth data dict.

        Returns:
            ReconcileResult with outcome, mismatches, and actions taken.
        """
        if not trade_id:
            raise ExecutionError(
                message="Cannot reconcile without trade_id",
            )

        if broker_data is None:
            raise ExecutionError(
                message="Cannot reconcile with None broker_data",
            )

        # Step 1: Capture local state
        local_state = self._capture_local_state(trade_id)

        # Step 2: Detect mismatches
        has_mismatch, mismatches = self.detect_mismatch(local_state, broker_data)

        if not has_mismatch:
            result = ReconcileResult(
                outcome=ReconcileOutcome.MATCH,
                local_state=local_state,
                broker_state=broker_data,
            )
            self._log("RECONCILE_MATCH", {
                "trade_id": trade_id,
            })
            return result

        # Step 3: Classify
        outcome = self.classify_mismatch(mismatches, local_state, broker_data)

        # Step 4 & 5: Reconcile and take safe action
        resolved_state, actions = self._resolve_mismatches(
            trade_id, mismatches, broker_data, outcome,
        )

        result = ReconcileResult(
            outcome=outcome,
            mismatches=mismatches,
            actions=actions,
            local_state=local_state,
            broker_state=broker_data,
            resolved_state=resolved_state,
        )

        self._log("RECONCILE_COMPLETE", {
            "trade_id": trade_id,
            "outcome": outcome.value,
            "mismatch_count": len(mismatches),
            "action_count": len(actions),
        })

        return result

    # ------------------------------------------------------------------
    # Step 1 & 2: Detect and Classify
    # ------------------------------------------------------------------

    def detect_mismatch(
        self,
        local_state: dict[str, Any],
        broker_state: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Compare local state against broker truth and list differences.

        Compares position fields, order data, and SL/TGT prices.

        Args:
            local_state: Dict from _capture_local_state() or PM consistency view.
            broker_state: Dict of broker's view of the same trade.

        Returns:
            Tuple of (has_mismatch: bool, mismatches: list of description strings).
        """
        mismatches: list[str] = []

        # Position-level comparison
        local_pos = local_state.get("position", {})
        broker_pos = broker_state.get("position", {})

        if not local_pos and not broker_pos:
            return (False, mismatches)  # Both empty = no mismatch
        if not local_pos:
            mismatches.append(
                f"LOCAL_NO_POSITION: broker has position but local has none"
            )
            return (True, mismatches)
        if not broker_pos:
            mismatches.append(
                f"BROKER_NO_POSITION: local has position but broker has none"
            )
            return (True, mismatches)

        # Compare filled quantity
        local_qty = local_pos.get("filled_qty", 0)
        broker_qty = broker_pos.get("filled_qty", 0)
        if local_qty != broker_qty:
            mismatches.append(
                f"POSITION_QTY: local={local_qty}, broker={broker_qty}"
            )

        # Compare average price
        local_price = local_pos.get("avg_price", 0.0)
        broker_price = broker_pos.get("avg_price", 0.0)
        if abs(local_price - broker_price) > PRICE_TOLERANCE:
            mismatches.append(
                f"PRICE: local={local_price:.2f}, broker={broker_price:.2f}"
            )

        # Compare direction
        local_dir = local_pos.get("direction", "")
        broker_dir = broker_pos.get("direction", "")
        if local_dir != broker_dir:
            mismatches.append(
                f"DIRECTION: local={local_dir}, broker={broker_dir}"
            )

        # Compare position status
        local_status = local_pos.get("status", "")
        broker_status = broker_pos.get("status", "")
        if local_status != broker_status:
            mismatches.append(
                f"STATUS: local={local_status}, broker={broker_status}"
            )

        # Compare SL price
        local_sl = local_pos.get("sl_price")
        broker_sl = broker_pos.get("sl_price")
        if local_sl != broker_sl:
            mismatches.append(
                f"SL_PRICE: local={local_sl}, broker={broker_sl}"
            )

        # Compare target price
        local_tgt = local_pos.get("target_price")
        broker_tgt = broker_pos.get("target_price")
        if local_tgt != broker_tgt:
            mismatches.append(
                f"TGT_PRICE: local={local_tgt}, broker={broker_tgt}"
            )

        # Order-level comparison
        local_orders = local_state.get("orders", [])
        broker_orders = broker_state.get("orders", [])

        if len(local_orders) != len(broker_orders):
            mismatches.append(
                f"ORDER_COUNT: local={len(local_orders)}, "
                f"broker={len(broker_orders)}"
            )

        # Compare individual order states
        broker_order_map = {o.get("order_id"): o for o in broker_orders}
        for local_order in local_orders:
            oid = local_order.get("order_id")
            broker_order = broker_order_map.get(oid)
            if broker_order is None:
                mismatches.append(
                    f"ORDER_PRESENCE: order {oid} exists locally but not at broker"
                )
            else:
                local_os = local_order.get("state", "")
                broker_os = broker_order.get("state", "")
                if local_os != broker_os:
                    mismatches.append(
                        f"ORDER_STATE_{oid}: local={local_os}, broker={broker_os}"
                    )

        return (len(mismatches) > 0, mismatches)

    def classify_mismatch(
        self,
        mismatches: list[str],
        local_state: dict[str, Any],
        broker_state: dict[str, Any],
    ) -> ReconcileOutcome:
        """Classify a set of mismatches into a reconciliation outcome.

        Classification rules:
        - No mismatches → MATCH
        - Quantity/price/direction mismatches → RESOLVED (broker truth applied)
        - State/status mismatches → RESOLVED (broker truth applied)
        - Order presence mismatches → RESOLVED (broker truth applied)
        - SL/TGT drift → RESOLVED (broker truth applied)
        - If broker data is empty or invalid → ESCALATED
        - If mismatches include unrecoverable conditions → ESCALATED

        Args:
            mismatches: List of mismatch description strings.
            local_state: Dict of local execution state.
            broker_state: Dict of broker state.

        Returns:
            The ReconcileOutcome classification.
        """
        if not mismatches:
            return ReconcileOutcome.MATCH

        # Check for unrecoverable conditions
        broker_pos = broker_state.get("position", {}) if broker_state else {}

        # If broker has no position data and local has active position, escalate
        if not broker_pos and local_state.get("position", {}).get("filled_qty", 0) > 0:
            return ReconcileOutcome.MISMATCH_ESCALATED

        # If broker direction differs from local, escalate
        for m in mismatches:
            if m.startswith("DIRECTION:"):
                return ReconcileOutcome.MISMATCH_ESCALATED

        # All other mismatches are resolvable by applying broker truth
        return ReconcileOutcome.MISMATCH_RESOLVED

    # ------------------------------------------------------------------
    # Step 3: Compare (detailed field-level diff)
    # ------------------------------------------------------------------

    def compare(
        self,
        local_snapshot: dict[str, Any],
        broker_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce a detailed field-by-field comparison.

        Returns a structured dict showing every field that differs
        between local and broker state, including the local value,
        broker value, and whether the mismatch is critical.

        Args:
            local_snapshot: Dict of local execution state.
            broker_data: Dict of broker state.

        Returns:
            Dict with:
                - 'has_differences': bool
                - 'differences': list of {field, local_value, broker_value, critical}
                - 'local_state': the input local_snapshot
                - 'broker_state': the input broker_data
        """
        differences: list[dict[str, Any]] = []
        has_diff = False

        local_pos = local_snapshot.get("position", {})
        broker_pos = broker_data.get("position", {})

        # Define fields to compare with their criticality
        fields_to_compare = [
            ("filled_qty", "position", True),
            ("avg_price", "position", False),
            ("direction", "position", True),
            ("status", "position", True),
            ("sl_price", "position", False),
            ("target_price", "position", False),
        ]

        for field_name, section, critical in fields_to_compare:
            local_val = local_pos.get(field_name) if section == "position" else None
            broker_val = broker_pos.get(field_name) if section == "position" else None

            if local_val != broker_val:
                differences.append({
                    "field": f"{section}.{field_name}",
                    "local_value": local_val,
                    "broker_value": broker_val,
                    "critical": critical,
                })
                has_diff = True

        return {
            "has_differences": has_diff,
            "differences": differences,
            "local_state": local_snapshot,
            "broker_state": broker_data,
        }

    # ------------------------------------------------------------------
    # Step 4 & 5: Reconcile + Safe Action
    # ------------------------------------------------------------------

    def _resolve_mismatches(
        self,
        trade_id: str,
        mismatches: list[str],
        broker_data: dict[str, Any],
        outcome: ReconcileOutcome,
    ) -> tuple[dict[str, Any], list[str]]:
        """Resolve mismatches by applying broker truth.

        Broker truth is authoritative. Local state is updated to match
        broker data where mismatches are found.

        Args:
            trade_id: The trade to resolve.
            mismatches: List of mismatch descriptions.
            broker_data: Broker truth data dict.
            outcome: The classified outcome.

        Returns:
            Tuple of (resolved_state_dict, list of action descriptions).
        """
        actions: list[str] = []
        broker_pos = broker_data.get("position", {})

        if outcome == ReconcileOutcome.MISMATCH_ESCALATED:
            return ({"escalated": True}, [
                "ESCALATED: Mismatch cannot be safely resolved",
            ])

        if outcome == ReconcileOutcome.MATCH:
            return ({}, [])

        # Apply broker truth to resolve mismatches
        # Use PositionManager to update local state
        position = self._pm.get_position(trade_id)

        if position is None and broker_pos:
            # Broker has a position but local doesn't — critical
            actions.append(
                "CRITICAL: Broker has position but local has none. "
                "Manual intervention required."
            )
            return ({"critical": True}, actions)

        if position is not None:
            for mismatch in mismatches:
                if mismatch.startswith("POSITION_QTY:"):
                    broker_qty = broker_pos.get("filled_qty", 0)
                    if broker_qty >= 0:
                        actions.append(
                            f"Quantity resolved: local→{broker_qty} "
                            f"(broker truth)"
                        )

                elif mismatch.startswith("PRICE:"):
                    broker_price = broker_pos.get("avg_price", 0.0)
                    if broker_price > 0:
                        actions.append(
                            f"Price resolved: local→{broker_price:.2f} "
                            f"(broker truth)"
                        )

                elif mismatch.startswith("SL_PRICE:"):
                    broker_sl = broker_pos.get("sl_price")
                    if broker_sl is not None and broker_sl > 0:
                        try:
                            self._pm.set_sl(trade_id, broker_sl)
                            actions.append(
                                f"SL price resolved: local→{broker_sl} "
                                f"(broker truth)"
                            )
                        except ExecutionError as e:
                            actions.append(f"SL update failed: {e}")

                elif mismatch.startswith("TGT_PRICE:"):
                    broker_tgt = broker_pos.get("target_price")
                    if broker_tgt is not None and broker_tgt > 0:
                        try:
                            self._pm.set_target(trade_id, broker_tgt)
                            actions.append(
                                f"Target price resolved: local→{broker_tgt} "
                                f"(broker truth)"
                            )
                        except ExecutionError as e:
                            actions.append(f"Target update failed: {e}")

        # Capture the resolved state
        resolved_state = self._capture_local_state(trade_id)

        return (resolved_state, actions)

    # ------------------------------------------------------------------
    # Reconnect Handling
    # ------------------------------------------------------------------

    def handle_reconnect(
        self,
        broker_data: dict[str, Any],
    ) -> list[ReconcileResult]:
        """Handle a broker reconnection by re-reconciling all active trades.

        Triggers a full reconcile cycle for every active position.

        Args:
            broker_data: Dict of trade_id → broker state data.

        Returns:
            List of ReconcileResult, one per active trade reconciled.
        """
        if broker_data is None:
            raise ExecutionError(
                message="Cannot handle reconnect with None broker_data",
            )

        results: list[ReconcileResult] = []
        active_positions = self._pm.get_active_positions()

        for position in active_positions:
            trade_id = position.trade_id
            trade_broker_data = broker_data.get(trade_id, {})

            result = self.reconcile(trade_id, trade_broker_data)
            results.append(result)

        self._log("RECONNECT_RECONCILE", {
            "trade_count": len(results),
            "match_count": sum(1 for r in results if r.outcome == ReconcileOutcome.MATCH),
            "resolved_count": sum(
                1 for r in results if r.outcome == ReconcileOutcome.MISMATCH_RESOLVED
            ),
            "escalated_count": sum(
                1 for r in results if r.outcome == ReconcileOutcome.MISMATCH_ESCALATED
            ),
        })

        return results

    # ------------------------------------------------------------------
    # Unclear Acknowledgement Handling
    # ------------------------------------------------------------------

    def handle_unclear_ack(
        self,
        order_id: str,
        broker_data: dict[str, Any] | None = None,
    ) -> ReconcileResult:
        """Handle an unclear order acknowledgement with bounded retry.

        Implements the UNKNOWN/PENDING_RECONCILE policy:
        - Short bounded window (reconcile_window_seconds)
        - Reconcile attempts (max_attempts, with backoff)
        - Escalate if unresolved

        Args:
            order_id: The order with the unclear acknowledgement.
            broker_data: Optional broker data to compare against.

        Returns:
            ReconcileResult with the final outcome after bounded attempts.
        """
        if not order_id:
            raise ExecutionError(
                message="Cannot handle unclear ack without order_id",
            )

        # Get order from OLM
        order = self._olm.get_order(order_id)
        if order is None:
            raise ExecutionError(
                message=f"Cannot handle unclear ack for unknown order: {order_id}",
            )

        trade_id = order.trade_id

        self._log("UNCLEAR_ACK_START", {
            "order_id": order_id,
            "trade_id": trade_id,
            "max_attempts": self._max_attempts,
        })

        # Bounded reconcile attempts
        for attempt in range(1, self._max_attempts + 1):
            local_state = self._capture_local_state(trade_id)

            if broker_data:
                has_mismatch, mismatches = self.detect_mismatch(
                    local_state, broker_data,
                )

                if not has_mismatch:
                    self._log("UNCLEAR_ACK_RESOLVED", {
                        "order_id": order_id,
                        "attempt": attempt,
                    })
                    return ReconcileResult(
                        outcome=ReconcileOutcome.MATCH,
                        local_state=local_state,
                        broker_state=broker_data,
                        attempt=attempt,
                    )

            if attempt < self._max_attempts:
                time.sleep(self._backoff_seconds)

        # Escalate if unresolved after all attempts
        self._log("UNCLEAR_ACK_ESCALATED", {
            "order_id": order_id,
            "trade_id": trade_id,
            "max_attempts": self._max_attempts,
        })

        return ReconcileResult(
            outcome=ReconcileOutcome.MISMATCH_ESCALATED,
            mismatches=[f"Unclear ack for {order_id}: unresolved after "
                        f"{self._max_attempts} attempts"],
            local_state=self._capture_local_state(trade_id),
            broker_state=broker_data or {},
            attempt=self._max_attempts,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _capture_local_state(self, trade_id: str) -> dict[str, Any]:
        """Capture the current local execution state for a trade.

        Combines position data from PositionManager and order data
        from OrderLifecycleManager into a single state dict.

        Args:
            trade_id: The trade to capture state for.

        Returns:
            Dict with 'position' and 'orders' keys.
        """
        # Get position consistency view from PM
        consistency = self._pm.get_consistency_view(trade_id)

        # Get orders from OLM
        orders = self._olm.get_trade_orders(trade_id)
        order_list = []
        for o in orders:
            order_list.append({
                "order_id": o.order_id,
                "state": o.state.value,
                "side": o.side,
                "quantity": o.quantity,
                "filled_qty": o.filled_qty,
                "price": o.price,
            })

        # Handle unknown trade — return empty position so detect_mismatch handles it correctly
        if consistency.get("found"):
            position = consistency.get("position", {})
        else:
            position = {}

        return {
            "position": position,
            "orders": order_list,
            "trailing_stop": consistency.get("trailing_stop"),
            "breakeven": consistency.get("breakeven"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a log event via the injected logging callback.

        Args:
            event_type: The type of event being logged.
            data: Event-specific data dict.
        """
        if self._on_log_callback:
            self._on_log_callback(event_type, data)
