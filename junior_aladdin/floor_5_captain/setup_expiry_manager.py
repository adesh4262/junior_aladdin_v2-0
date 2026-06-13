"""Floor 5 — Setup Expiry Manager (Step 5.14).

Manages setup validity windows by trade class. Determines when a setup
or plan is too old based on its trade class, and provides methods to
check expiry and purge expired items.

Architecture (see ROADMAP_FLOOR_05 Section 15):
- Setup validity is setup-specific and dynamic by trade class
- SCALP: 1-2 candles, tight window
- CONTINUATION: 2-4 candles, wider window
- REVERSAL: 2-3 candles, moderate window
- LIQUIDITY_RECLAIM: until sweep reclaimed or fails (0 = not candle-bound)
- OPTIONS_PRESSURE: until wall tested or pressure collapses (0 = not candle-bound)
- Differs from confidence decay: expiry is HARD cutoff, decay is gradual softening
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import ArmedPlanState
from junior_aladdin.shared.types import ArmedPlan, TradeClass


# ── Expiry windows by trade class (LOCKED) ─────────────────────────────────
# Max candles before the setup expires. 0 = not candle-bound.

_CLASS_EXPIRY_WINDOWS: dict[TradeClass, int] = {
    TradeClass.SCALP: 2,
    TradeClass.CONTINUATION: 4,
    TradeClass.REVERSAL: 3,
    TradeClass.LIQUIDITY_RECLAIM: 0,   # Until sweep reclaimed or fails
    TradeClass.OPTIONS_PRESSURE: 0,    # Until wall tested or collapses
}

# Recovery/fallback windows when trade class is unknown
_DEFAULT_EXPIRY_CANDLES = 3


# ── SetupExpiryManager ────────────────────────────────────────────────────


class SetupExpiryManager:
    """Manages setup and plan expiry based on trade class windows.

    Works alongside ``ArmedPlanEngine``'s built-in expiry conditions.
    This manager provides class-level default windows and batch expiry
    purging for the heavy cycle.

    Usage::

        manager = SetupExpiryManager()
        candles = manager.get_expiry_candles(TradeClass.SCALP)  # 2

        expired = manager.purge_expired(armed_plans, candle_index=150)
        for plan in expired:
            logger.info(f"Plan {plan.plan_id} expired (class expiry)")
    """

    def __init__(self) -> None:
        """Initialize the setup expiry manager."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_expiry_candles(self, trade_class: TradeClass | None) -> int:
        """Get the maximum number of candles before a setup expires.

        Args:
            trade_class: The trade class to look up.

        Returns:
            Candle count (0 = not candle-bound, > 0 = max candles).
        """
        if trade_class is None:
            return _DEFAULT_EXPIRY_CANDLES
        return _CLASS_EXPIRY_WINDOWS.get(trade_class, _DEFAULT_EXPIRY_CANDLES)

    def is_expired(
        self,
        item: ArmedPlan | dict[str, Any],
        current_candle_index: int,
    ) -> bool:
        """Check if a setup or plan has exceeded its expiry window.

        Args:
            item: An ``ArmedPlan`` or dict with ``created_at_candle`` or
                  ``created_at`` field + optional ``setup_class``.
            current_candle_index: Current 1m candle index from session start.

        Returns:
            True if the item has exceeded its class expiry window.
        """
        if isinstance(item, dict):
            return self._is_dict_expired(item, current_candle_index)
        return self._is_plan_expired(item, current_candle_index)

    def purge_expired(
        self,
        items: list[ArmedPlan],
        current_candle_index: int,
    ) -> list[ArmedPlan]:
        """Filter out expired plans and return them separately.

        Does NOT mutate the input list — returns a new list of expired items.

        Args:
            items: List of ArmedPlan to check.
            current_candle_index: Current candle index.

        Returns:
            List of expired plans.
        """
        expired: list[ArmedPlan] = []
        # We don't mutate the original list; we just identify expired ones
        for plan in items:
            if self.is_expired(plan, current_candle_index):
                expired.append(plan)
        return expired

    def get_expiry_reason(
        self,
        item: ArmedPlan | dict[str, Any],
        current_candle_index: int,
    ) -> str:
        """Get a human-readable reason for why a setup expired.

        Args:
            item: An ``ArmedPlan`` or dict with setup info.
            current_candle_index: Current candle index.

        Returns:
            Human-readable expiry reason string.
        """
        if isinstance(item, dict):
            setup_class = item.get("setup_class", "UNKNOWN")
        else:
            setup_class = item.setup_class

        # Determine the expiry candles
        try:
            tc = TradeClass(setup_class) if setup_class in TradeClass._value2member_map_ else None
        except (ValueError, KeyError):
            tc = None
        expiry_candles = self.get_expiry_candles(tc)

        if expiry_candles == 0:
            return f"{setup_class} is not candle-bound (manual/watch-based expiry)"

        if isinstance(item, dict):
            created_candle = item.get("created_at_candle", 0)
        else:
            created_candle = getattr(item, "created_at_candle", 0)

        elapsed = current_candle_index - created_candle
        return (
            f"{setup_class} expired: {elapsed}/{expiry_candles} candles elapsed"
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_expiry_summary(self) -> dict[str, Any]:
        """Get a summary of all class expiry windows.

        Returns:
            Dict mapping trade class names to their expiry candle counts.
        """
        return {
            tc.value: self.get_expiry_candles(tc)
            for tc in TradeClass
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _is_plan_expired(
        self,
        plan: ArmedPlan,
        current_candle_index: int,
    ) -> bool:
        """Check if an ArmedPlan has exceeded its expiry window.

        Args:
            plan: The ArmedPlan to check.
            current_candle_index: Current candle index.

        Returns:
            True if expired.
        """
        # Parse setup_class to TradeClass
        try:
            tc = TradeClass(plan.setup_class) if plan.setup_class in TradeClass._value2member_map_ else None
        except (ValueError, KeyError):
            tc = None

        expiry_candles = self.get_expiry_candles(tc)

        # 0 = not candle-bound
        if expiry_candles == 0:
            return False

        # Get creation candle index from expiry_condition
        created_candle = plan.expiry_condition.get("created_at_candle", 0)
        if created_candle == 0:
            # No candle recorded — use plan's readiness (only active plans are checked)
            return False

        elapsed = current_candle_index - created_candle
        return elapsed >= expiry_candles

    def _is_dict_expired(
        self,
        item: dict[str, Any],
        current_candle_index: int,
    ) -> bool:
        """Check if a dict-based setup has exceeded its expiry window.

        Expects dict with keys: ``setup_class``, ``created_at_candle`` (optional).

        Args:
            item: Dict with setup info.
            current_candle_index: Current candle index.

        Returns:
            True if expired.
        """
        setup_class = item.get("setup_class", "")
        try:
            tc = TradeClass(setup_class) if setup_class in TradeClass._value2member_map_ else None
        except (ValueError, KeyError):
            tc = None

        expiry_candles = self.get_expiry_candles(tc)

        if expiry_candles == 0:
            return False

        created_candle = item.get("created_at_candle", 0)
        if created_candle == 0:
            return False

        elapsed = current_candle_index - created_candle
        return elapsed >= expiry_candles
