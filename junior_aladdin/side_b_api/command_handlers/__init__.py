"""Side B command handler package.

Each handler follows the pattern:
    request (from route) → validate params → build ControlCommand → cache → return CommandAck

Handlers do NOT execute commands — they validate, build, cache, and ack.
The owner floor/side picks up cached commands on its next poll cycle.

Exported handlers:
    handle_mode_request(cache, mode, reason)       → CommandAck
    handle_capital_request(cache, capital_limit, reason) → CommandAck
    handle_kill_switch_request(cache, state, reason)    → CommandAck
    handle_override_request(cache, reason, trade_id)    → CommandAck
    handle_reconnect_request(cache, target_broker, reason) → CommandAck
    handle_account_reset_request(cache, new_balance, reason) → CommandAck

Reference: ROADMAP_SIDE_B Step 8.9 — Command handlers
"""

from __future__ import annotations

from junior_aladdin.side_b_api.command_handlers.mode_handler import handle_mode_request
from junior_aladdin.side_b_api.command_handlers.capital_handler import handle_capital_request
from junior_aladdin.side_b_api.command_handlers.kill_switch_handler import handle_kill_switch_request
from junior_aladdin.side_b_api.command_handlers.override_handler import handle_override_request
from junior_aladdin.side_b_api.command_handlers.reconnect_handler import handle_reconnect_request
from junior_aladdin.side_b_api.command_handlers.account_handler import handle_account_reset_request

__all__ = [
    "handle_mode_request",
    "handle_capital_request",
    "handle_kill_switch_request",
    "handle_override_request",
    "handle_reconnect_request",
    "handle_account_reset_request",
]
