"""Side A data source adapter.

Polls Side A (Execution) for current execution state, blocked actions,
and execution logs.

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def poll_side_a() -> dict[str, Any]:
    """Poll Side A for execution state, blocked actions, and logs.

    Returns:
        Dict with keys:
            - execution_state: dict (mode, state, position, orders, escalation)
            - blocked_actions: list[dict] — recent blocked actions
            - execution_logs: list[dict] — filtered log entries
            - last_poll: str (ISO timestamp)
    """
    result: dict[str, Any] = {
        "execution_state": {},
        "blocked_actions": [],
        "execution_logs": [],
        "last_poll": datetime.utcnow().isoformat(),
    }

    try:
        # ── Execution orchestrator state ──
        try:
            from junior_aladdin.side_a_execution.execution_orchestrator import (
                ExecutionOrchestrator,
            )
            from junior_aladdin.side_a_execution.side_a_types import (
                ExecutionSnapshot,
            )

            orchestrator = ExecutionOrchestrator()
            snapshot: ExecutionSnapshot = orchestrator.get_state()

            state_val = (
                snapshot.state.value
                if hasattr(snapshot.state, "value")
                else str(getattr(snapshot, "state", "IDLE"))
            )
            mode_val = (
                snapshot.mode.value
                if hasattr(snapshot.mode, "value")
                else str(getattr(snapshot, "mode", "ALERT"))
            )

            result["execution_state"] = {
                "state": state_val,
                "mode": mode_val,
                "escalation_level": (
                    snapshot.escalation_level.value
                    if hasattr(snapshot, "escalation_level") and hasattr(snapshot.escalation_level, "value")
                    else "NORMAL"
                ),
                "kill_switch_state": (
                    snapshot.kill_switch_state.value
                    if hasattr(snapshot, "kill_switch_state") and hasattr(snapshot.kill_switch_state, "value")
                    else "NORMAL"
                ),
                "timestamp": (
                    snapshot.timestamp.isoformat()
                    if hasattr(snapshot, "timestamp")
                    else ""
                ),
            }

            # Position
            pos = getattr(snapshot, "position", None)
            if pos is not None:
                result["execution_state"]["position"] = {
                    "trade_id": getattr(pos, "trade_id", ""),
                    "direction": getattr(pos, "direction", ""),
                    "filled_qty": getattr(pos, "filled_qty", 0),
                    "avg_price": getattr(pos, "avg_price", 0.0),
                    "sl_price": getattr(pos, "sl_price", None),
                    "target_price": getattr(pos, "target_price", None),
                    "pnl": getattr(pos, "pnl", 0.0),
                    "status": getattr(pos, "status", ""),
                }

            # Orders
            orders = getattr(snapshot, "orders", [])
            result["execution_state"]["orders"] = [
                {
                    "order_id": getattr(o, "order_id", ""),
                    "state": (
                        o.state.value if hasattr(o, "state") and hasattr(o.state, "value") else str(getattr(o, "state", ""))
                    ),
                    "side": getattr(o, "side", ""),
                    "quantity": getattr(o, "quantity", 0),
                    "filled_qty": getattr(o, "filled_qty", 0),
                    "price": getattr(o, "price", 0.0),
                }
                for o in orders
            ]

            # Blocked actions from snapshot
            blocked = getattr(snapshot, "blocked_actions", [])
            result["blocked_actions"] = list(blocked) if isinstance(blocked, list) else []

        except ImportError:
            pass

        # ── Blocked action journal ──
        try:
            from junior_aladdin.side_a_execution.blocked_action_journal import (
                BlockedActionJournal,
            )

            journal = BlockedActionJournal()
            recent_blocks = journal.get_recent(count=10)
            result["blocked_actions"] = [
                {
                    "timestamp": (
                        b.timestamp.isoformat()
                        if hasattr(b, "timestamp")
                        else ""
                    ),
                    "trade_id": getattr(b, "trade_id", ""),
                    "block_reason": getattr(b, "block_reason", ""),
                    "severity": (
                        b.severity.value
                        if hasattr(b, "severity") and hasattr(b.severity, "value")
                        else str(getattr(b, "severity", "INFO"))
                    ),
                }
                for b in recent_blocks
            ]
        except ImportError:
            pass

        # ── Execution logs ──
        try:
            from junior_aladdin.side_a_execution.execution_logging_layer import (
                ExecutionLoggingLayer,
            )

            log_layer = ExecutionLoggingLayer()
            logs = log_layer.get_recent_logs(count=20)
            result["execution_logs"] = [
                {
                    "timestamp": getattr(l, "timestamp", ""),
                    "event": getattr(l, "event", ""),
                    "details": getattr(l, "details", {}),
                }
                for l in logs
            ]
        except ImportError:
            pass

    except ImportError:
        pass
    except Exception:
        pass

    return result
