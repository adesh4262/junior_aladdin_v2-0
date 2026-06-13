"""Floor 5 — Armed Plan Engine (Step 5.13).

THE KEY FEATURE of the Captain floor. Creates prepared conditional plans
that the light cycle can watch without heavy recomputation.

Built after heavy cycle. Watched by light cycle on every tick.

Armed Plan lifecycle:
WATCHING -> TRIGGERED (condition met -> forward to execution)
WATCHING -> EXPIRED (timeout)
WATCHING -> INVALIDATED (structure broke)
WATCHING -> CANCELLED (explicit cancel)

Architecture rules (see ROADMAP_FLOOR_05 Section 13 & 22):
- Plans created AFTER heavy cycle completes
- Light cycle ONLY calls watch_plans() — no heavy computation
- Plan contains trigger condition + expiry condition + invalidation
- Triggered plans forwarded to execution
- Setup memory store tracks zone trap history
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import ArmedPlanState
from junior_aladdin.floor_5_captain.setup_memory_store import SetupMemoryStore
from junior_aladdin.shared.types import ArmedPlan, TradeClass


# ── MarketData (lightweight struct for light cycle) ─────────────────────────


@dataclass
class MarketDataSnapshot:
    """Minimal market data snapshot for light cycle plan watching.

    Light cycle checks plans against this data — no heavy computation.

    Fields:
        price: Current price level.
        volume: Current volume (if available).
        timestamp: When this snapshot was taken.
        bid: Current bid price (if available).
        ask: Current ask price (if available).
    """
    price: float = 0.0
    volume: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    bid: float = 0.0
    ask: float = 0.0


# ── TriggerCheck result ────────────────────────────────────────────────────


@dataclass
class TriggerCheckResult:
    """Result of checking trigger conditions for a plan.

    Fields:
        plan_id: The plan that was checked.
        triggered: Whether the plan should be triggered.
        expired: Whether the plan has expired.
        invalidated: Whether the plan is invalidated.
        reason: Human-readable reason for the status change.
        price_at_check: Price level when check was performed.
    """
    plan_id: str = ""
    triggered: bool = False
    expired: bool = False
    invalidated: bool = False
    reason: str = ""
    price_at_check: float = 0.0


# ── WatchResult (aggregated light cycle output) ────────────────────────────


@dataclass
class WatchResult:
    """Aggregated result from watching all active plans.

    Fields:
        triggered_plans: Plans that were triggered this cycle.
        expired_plans: Plans that expired this cycle.
        invalidated_plans: Plans invalidated this cycle.
        active_plan_count: Number of plans still WATCHING.
        has_trigger: Whether a plan was triggered.
        checked_at: When the watch cycle ran.
    """
    triggered_plans: list[TriggerCheckResult] = field(default_factory=list)
    expired_plans: list[TriggerCheckResult] = field(default_factory=list)
    invalidated_plans: list[TriggerCheckResult] = field(default_factory=list)
    active_plan_count: int = 0
    has_trigger: bool = False
    checked_at: datetime = field(default_factory=datetime.utcnow)


# ── Trigger condition helpers ──────────────────────────────────────────────


def _check_price_trigger(
    condition: dict[str, Any] | None,
    price: float,
) -> tuple[bool, str]:
    """Check if a price-based trigger condition is met.

    Condition formats:
    - ``{"type": "above", "level": 19500}`` — price crosses above level
    - ``{"type": "below", "level": 19400}`` — price crosses below level
    - ``{"type": "between", "low": 19400, "high": 19500}`` — price inside zone
    - ``{"type": "reclaim", "level": 19450}`` — price sweeps below then reclaims above
    - ``{"type": "touch", "level": 19500}`` — price touches level within 0.1%

    Args:
        condition: The trigger condition dict.
        price: Current market price.

    Returns:
        Tuple of ``(is_met, reason_string)``.
    """
    if condition is None:
        return False, "No trigger condition"

    cond_type = condition.get("type", "")
    level = condition.get("level", 0.0)
    low = condition.get("low", 0.0)
    high = condition.get("high", 0.0)

    if cond_type == "above":
        met = price >= level
        return met, f"Price {price:.2f} {'above' if met else 'below'} {level:.2f}"

    elif cond_type == "below":
        met = price <= level
        return met, f"Price {price:.2f} {'below' if met else 'above'} {level:.2f}"

    elif cond_type == "between":
        met = low <= price <= high
        return met, f"Price {price:.2f} {'inside' if met else 'outside'} [{low:.2f}, {high:.2f}]"

    elif cond_type == "reclaim":
        # Reclaim: price was below level, now back above
        met = price >= level
        return met, f"Price {price:.2f} {'reclaimed' if met else 'below'} {level:.2f}"

    elif cond_type == "touch":
        tolerance = level * 0.001  # 0.1% tolerance
        met = abs(price - level) <= tolerance
        return met, f"Price {price:.2f} {'touched' if met else 'missed'} {level:.2f}"

    return False, f"Unknown trigger type: {cond_type}"


def _check_expiry_condition(
    condition: dict[str, Any] | None,
    created_at: datetime,
    current_price: float,
) -> tuple[bool, str]:
    """Check if a plan has expired based on its expiry condition.

    Condition formats:
    - ``{"type": "candles", "count": 5}`` — expired after N candles
    - ``{"type": "price_beyond", "level": 19600}`` — price moved too far
    - ``{"type": "time", "minutes": 10}`` — expired after N minutes

    Args:
        condition: The expiry condition dict.
        created_at: When the plan was created.
        current_price: Current market price for price-based expiry.

    Returns:
        Tuple of ``(is_expired, reason_string)``.
    """
    if condition is None:
        return False, "No expiry condition (manual only)"

    cond_type = condition.get("type", "")

    if cond_type == "candles":
        # Candles are checked externally; this method trusts the caller
        # to pass the correct candle index via the condition
        count = condition.get("count", 5)
        elapsed = condition.get("elapsed", 0)
        met = elapsed >= count
        return met, f"{elapsed}/{count} candles elapsed{' (expired)' if met else ''}"

    elif cond_type == "price_beyond":
        level = condition.get("level", 0.0)
        direction = condition.get("direction", "any")
        if direction == "above":
            met = current_price > level
        elif direction == "below":
            met = current_price < level
        else:
            met = abs(current_price - level) > abs(level * 0.02)
        return met, f"Price at {current_price:.2f}, beyond level {level:.2f}"

    elif cond_type == "time":
        minutes = condition.get("minutes", 10)
        elapsed_minutes = (datetime.utcnow() - created_at).total_seconds() / 60.0
        met = elapsed_minutes >= minutes
        return met, f"{elapsed_minutes:.1f}/{minutes} min elapsed{' (expired)' if met else ''}"

    return False, f"Unknown expiry type: {cond_type}"


# ── ArmedPlanEngine ────────────────────────────────────────────────────────


class ArmedPlanEngine:
    """Creates, watches, and manages conditional trade plans.

    This is the backbone of Captain's two-speed brain:
    - Heavy cycle builds plans after analysis
    - Light cycle watches plans on every tick

    Usage::

        engine = ArmedPlanEngine(setup_store)
        plan = engine.create_plan(
            direction="BUY",
            setup_class="CONTINUATION",
            trigger_condition={"type": "above", "level": 19500},
            expiry_condition={"type": "candles", "count": 4},
        )

        # In light cycle:
        result = engine.watch_plans(market_data)
        if result.has_trigger:
            triggered = result.triggered_plans[0]
            logger.info(f"Plan {triggered.plan_id} triggered!")
    """

    def __init__(self, setup_store: SetupMemoryStore | None = None) -> None:
        """Initialize the armed plan engine.

        Args:
            setup_store: Optional SetupMemoryStore for zone trap tracking.
        """
        self._plans: dict[str, ArmedPlan] = {}
        self._setup_store = setup_store or SetupMemoryStore()

    # ------------------------------------------------------------------
    # Public API — Plan Management (Heavy Cycle)
    # ------------------------------------------------------------------

    def create_plan(
        self,
        direction: str,
        setup_class: str,
        trigger_condition: dict[str, Any] | None = None,
        expiry_condition: dict[str, Any] | None = None,
        invalidation_level: float = 0.0,
        originating_heads: list[str] | None = None,
        zone_label: str = "",
        candle_index: int = 0,
    ) -> ArmedPlan:
        """Create a new armed conditional plan.

        The plan starts in WATCHING state and is added to the active
        plan list for the light cycle to monitor.

        Args:
            direction: "BUY" or "SELL".
            setup_class: Trade class string (e.g., "SCALP", "CONTINUATION").
            trigger_condition: Dict describing what must happen for trigger.
            expiry_condition: Dict describing when the plan expires.
            invalidation_level: Price level that invalidates the plan.
            originating_heads: Heads that support this plan.
            zone_label: Optional zone label for setup store tracking.

        Returns:
            The newly created ``ArmedPlan`` in WATCHING state.
        """
        plan_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # For candle-based expiry, store creation candle for relative elapsed
        expiry = expiry_condition or {}
        if expiry.get("type") == "candles" and candle_index > 0:
            expiry["created_at_candle"] = candle_index

        plan = ArmedPlan(
            plan_id=plan_id,
            direction=direction,
            setup_class=setup_class,
            trigger_condition=trigger_condition or {},
            expiry_condition=expiry,
            invalidation_level=invalidation_level,
            originating_heads=originating_heads or [],
            readiness=ArmedPlanState.WATCHING.value,
            created_at=now,
        )
        self._plans[plan_id] = plan

        # Track in setup store if zone label provided
        if zone_label:
            self._setup_store.store_setup(
                setup_id=f"plan_{plan_id}",
                direction=direction,
                zone_label=zone_label,
            )

        return plan

    def trigger_plan(self, plan_id: str) -> ArmedPlan | None:
        """Manually trigger a plan (mark as TRIGGERED).

        Called when external logic (e.g., narrative shift confirmation)
        determines the plan should be triggered.

        Args:
            plan_id: The plan to trigger.

        Returns:
            Updated ``ArmedPlan``, or None if not found.
        """
        return self._transition_plan(plan_id, ArmedPlanState.TRIGGERED)

    def expire_plan(self, plan_id: str) -> ArmedPlan | None:
        """Manually expire a plan (mark as EXPIRED).

        Args:
            plan_id: The plan to expire.

        Returns:
            Updated ``ArmedPlan``, or None if not found.
        """
        return self._transition_plan(plan_id, ArmedPlanState.EXPIRED)

    def invalidate_plan(self, plan_id: str) -> ArmedPlan | None:
        """Manually invalidate a plan (mark as INVALIDATED).

        Used when structure breaks or narrative shifts before trigger.

        Args:
            plan_id: The plan to invalidate.

        Returns:
            Updated ``ArmedPlan``, or None if not found.
        """
        result = self._transition_plan(plan_id, ArmedPlanState.INVALIDATED)
        if result is not None:
            self._mark_zone_failed_if_tracked(plan_id)
        return result

    def cancel_plan(self, plan_id: str) -> ArmedPlan | None:
        """Explicitly cancel a plan.

        Args:
            plan_id: The plan to cancel.

        Returns:
            Updated ``ArmedPlan``, or None if not found.
        """
        return self._transition_plan(plan_id, ArmedPlanState.CANCELLED)

    def get_plan(self, plan_id: str) -> ArmedPlan | None:
        """Get a plan by ID.

        Args:
            plan_id: The plan to retrieve.

        Returns:
            ``ArmedPlan`` if found, else None.
        """
        return self._plans.get(plan_id)

    def get_active_plans(self) -> list[ArmedPlan]:
        """Get all plans currently in WATCHING state.

        Returns:
            List of ``ArmedPlan`` with readiness == WATCHING.
        """
        return [
            p for p in self._plans.values()
            if p.readiness == ArmedPlanState.WATCHING.value
        ]

    def get_triggered_plan(self) -> ArmedPlan | None:
        """Get the most recently triggered plan, if any.

        Returns:
            The first TRIGGERED ``ArmedPlan`` found, or None.
        """
        for p in self._plans.values():
            if p.readiness == ArmedPlanState.TRIGGERED.value:
                return p
        return None

    def get_all_plans(self) -> list[ArmedPlan]:
        """Get all plans ever created.

        Returns:
            List of all ``ArmedPlan`` entries.
        """
        return list(self._plans.values())

    def get_plan_count(self) -> int:
        """Get total number of plans ever created.

        Returns:
            Integer count of all plans.
        """
        return len(self._plans)

    # ------------------------------------------------------------------
    # Public API — Light Cycle (Tick Level)
    # ------------------------------------------------------------------

    def watch_plans(
        self,
        market_data: MarketDataSnapshot | None = None,
        candle_index: int = 0,
    ) -> WatchResult:
        """Watch all active plans against current market data.

        THIS IS THE LIGHT CYCLE INTERFACE. Called on every tick.
        Does NOT perform heavy computation — only checks trigger and
        expiry conditions for active WATCHING plans.

        Args:
            market_data: Current market data snapshot (price, volume, etc.).
            candle_index: Current 1m candle index for candle-based expiry.

        Returns:
            ``WatchResult`` with triggered/expired/invalidated plans.
        """
        data = market_data or MarketDataSnapshot()
        now = datetime.utcnow()

        triggered: list[TriggerCheckResult] = []
        expired: list[TriggerCheckResult] = []
        invalidated: list[TriggerCheckResult] = []

        for plan in self.get_active_plans():
            # Update candle elapsed from candle_index (relative to creation candle)
            if (
                plan.expiry_condition.get("type") == "candles"
                and candle_index > 0
                and "created_at_candle" in plan.expiry_condition
            ):
                created = plan.expiry_condition["created_at_candle"]
                plan.expiry_condition["elapsed"] = max(0, candle_index - created)

            # Check invalidation first (price beyond invalidation level)
            if self._check_invalidation(plan, data.price):
                self.invalidate_plan(plan.plan_id)
                invalidated.append(TriggerCheckResult(
                    plan_id=plan.plan_id,
                    invalidated=True,
                    reason=f"Invalidated at {data.price:.2f} (level: {plan.invalidation_level:.2f})",
                    price_at_check=data.price,
                ))
                continue

            # Check expiry
            is_expired, exp_reason = _check_expiry_condition(
                plan.expiry_condition,
                plan.created_at,
                data.price,
            )
            if is_expired:
                self.expire_plan(plan.plan_id)
                expired.append(TriggerCheckResult(
                    plan_id=plan.plan_id,
                    expired=True,
                    reason=exp_reason,
                    price_at_check=data.price,
                ))
                continue

            # Check trigger condition
            is_triggered, trig_reason = _check_price_trigger(
                plan.trigger_condition,
                data.price,
            )
            if is_triggered:
                self.trigger_plan(plan.plan_id)
                triggered.append(TriggerCheckResult(
                    plan_id=plan.plan_id,
                    triggered=True,
                    reason=trig_reason,
                    price_at_check=data.price,
                ))

        return WatchResult(
            triggered_plans=triggered,
            expired_plans=expired,
            invalidated_plans=invalidated,
            active_plan_count=len(self.get_active_plans()),
            has_trigger=len(triggered) > 0,
            checked_at=now,
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _transition_plan(
        self,
        plan_id: str,
        new_state: ArmedPlanState,
    ) -> ArmedPlan | None:
        """Transition a plan to a new state.

        Args:
            plan_id: The plan to transition.
            new_state: The new ArmedPlanState.

        Returns:
            Updated ``ArmedPlan``, or None if not found.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            return None
        plan.readiness = new_state.value
        return plan

    def _check_invalidation(
        self,
        plan: ArmedPlan,
        current_price: float,
    ) -> bool:
        """Check if a plan's invalidation level has been breached.

        For BUY plans: invalidation is below the level.
        For SELL plans: invalidation is above the level.

        Args:
            plan: The plan to check.
            current_price: Current market price.

        Returns:
            True if the plan is invalidated.
        """
        if plan.invalidation_level == 0.0:
            return False

        if plan.direction == "BUY":
            return current_price < plan.invalidation_level
        elif plan.direction == "SELL":
            return current_price > plan.invalidation_level
        return False

    def _mark_zone_failed_if_tracked(self, plan_id: str) -> None:
        """If a plan has a zone tracked in setup store, mark it failed.

        Args:
            plan_id: The plan ID to check.
        """
        setup_id = f"plan_{plan_id}"
        setup = self._setup_store.get_setup(setup_id)
        if setup and setup.zone_label:
            self._setup_store.mark_failed_zone(setup.zone_label)

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def clear_session(self) -> None:
        """Clear all plans for a new trading day."""
        self._plans.clear()
        self._setup_store.clear_session()

    def has_active_plans(self) -> bool:
        """Check if there are any WATCHING plans.

        Returns:
            True if at least one plan is in WATCHING state.
        """
        return any(
            p.readiness == ArmedPlanState.WATCHING.value
            for p in self._plans.values()
        )

    # ------------------------------------------------------------------
    # Summary / Utility
    # ------------------------------------------------------------------

    def get_engine_summary(self) -> dict[str, Any]:
        """Get a structured summary of the engine state.

        Returns:
            Dict with engine summary fields.
        """
        all_plans = self.get_all_plans()
        return {
            "total_plans": len(all_plans),
            "active_plans": len(self.get_active_plans()),
            "triggered_plans": sum(
                1 for p in all_plans
                if p.readiness == ArmedPlanState.TRIGGERED.value
            ),
            "expired_plans": sum(
                1 for p in all_plans
                if p.readiness == ArmedPlanState.EXPIRED.value
            ),
            "invalidated_plans": sum(
                1 for p in all_plans
                if p.readiness == ArmedPlanState.INVALIDATED.value
            ),
            "has_active": self.has_active_plans(),
            "setup_store": self._setup_store.get_store_summary(),
        }
