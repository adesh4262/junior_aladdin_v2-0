"""Floor 4 — Trigger Formatter.

Standard trigger object creation and checking.

Keeps trigger format consistent across all Department Heads.

Hybrid trigger model:
- **Normal trigger**: simple zone trigger (zone hit + one confirmation).
- **Premium trigger**: multi-condition trigger
  (zone + reclaim + volume + context + structural support).

Usage::

    from junior_aladdin.floor_4_heads.trigger_formatter import (
        create_trigger,
        create_premium_trigger,
        check_trigger,
    )

    # Normal trigger
    trigger = create_trigger(
        name="FVG Retest",
        zone={"price_level": 19600.0, "direction": "bullish"},
        trigger_type="zone_touch",
        confirmation_needed="price reclaims above 19600 after touch",
    )

    # Premium trigger (multi-condition)
    premium = create_premium_trigger(
        name="Premium FVG Reclaim",
        zone={"price_level": 19600.0, "direction": "bullish"},
        conditions=[
            {"type": "zone_touch", "level": 19600.0},
            {"type": "volume_spike", "min_volume": 50000},
            {"type": "structure_support", "direction": "bullish"},
        ],
    )

    # Check trigger status against market data
    triggered, details = check_trigger(trigger, market_data={"price": 19610.0})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from junior_aladdin.shared.logging import get_logger

logger = get_logger("trigger_formatter")


# =============================================================================
# Trigger Status Enum
# =============================================================================


class TriggerConditionStatus(Enum):
    """Status of an individual trigger condition check.

    ``PENDING``: Condition hasn't been evaluated yet.
    ``MET``: Condition is satisfied (e.g., zone touched, volume confirmed).
    ``FAILED``: Condition has been evaluated and is not satisfied.
    ``EXPIRED``: The window for this condition to be met has passed.
    """
    PENDING = "PENDING"
    MET = "MET"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


# =============================================================================
# TriggerCheckResult
# =============================================================================


@dataclass
class TriggerCheckResult:
    """Result of checking a trigger against current market data.

    Fields:
        triggered: Whether the trigger condition is fully met.
        trigger_id: Unique reference to the trigger that was checked.
        condition_statuses: Dict mapping each condition description to its status.
        met_count: Number of conditions that are MET.
        total_conditions: Total number of conditions.
        details: Human-readable summary of the check result.
        checked_at: When the check was performed (UTC).
    """
    triggered: bool = False
    trigger_id: str = ""
    condition_statuses: dict[str, TriggerConditionStatus] = field(default_factory=dict)
    met_count: int = 0
    total_conditions: int = 0
    details: str = ""
    checked_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def all_met(self) -> bool:
        """``True`` if EVERY condition is MET."""
        return self.met_count == self.total_conditions > 0


# =============================================================================
# Trigger Data Helpers
# =============================================================================


def create_trigger(
    name: str,
    zone: dict[str, Any],
    trigger_type: str = "zone_touch",
    confirmation_needed: str = "",
    price_level: float | None = None,
) -> dict[str, Any]:
    """Create a **normal** (single-condition) trigger.

    A normal trigger watches one condition: typically a zone touch
    plus an optional confirmation.

    Args:
        name: Human-readable trigger name (e.g., ``\"FVG Retest\"``).
        zone: Zone dict with at minimum ``price_level`` and ``direction``.
        trigger_type: Type string (e.g., ``\"zone_touch\"``, ``\"reclaim\"``).
        confirmation_needed: What confirmation is required after zone touch.
        price_level: Optional explicit price level override. Uses
            ``zone['price_level']`` if None.

    Returns:
        A trigger dict standardised for ``HeadReport.armed_triggers``.
    """
    level = price_level if price_level is not None else zone.get("price_level", 0.0)
    condition_desc = confirmation_needed or f"{trigger_type} at {level}"

    return {
        "trigger_id": f"{name.lower().replace(' ', '_')}_{datetime.utcnow().timestamp():.0f}",
        "name": name,
        "trigger_type": trigger_type,
        "zone_ref": zone.get("zone_type", ""),
        "price_level": level,
        "direction": zone.get("direction", ""),
        "conditions": [
            {
                "type": trigger_type,
                "level": level,
                "description": condition_desc,
                "status": TriggerConditionStatus.PENDING.value,
            }
        ],
        "premium": False,
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
    }


def create_premium_trigger(
    name: str,
    zone: dict[str, Any],
    conditions: list[dict[str, Any]],
    price_level: float | None = None,
) -> dict[str, Any]:
    """Create a **premium** (multi-condition) trigger.

    A premium trigger requires MULTIPLE conditions to be met before firing.
    Examples: zone touch + volume spike + structure confirmation.

    Args:
        name: Human-readable trigger name.
        zone: Zone dict with at minimum ``price_level`` and ``direction``.
        conditions: List of condition dicts, each with:
            - ``type`` (str): e.g., ``\"zone_touch\"``, ``\"volume_spike\"``.
            - ``level`` (float): price or volume level.
            - Optional: ``description``, ``min_volume``, ``direction``.
        price_level: Optional explicit price level override.

    Returns:
        A premium trigger dict for ``HeadReport.armed_triggers``.
    """
    level = price_level if price_level is not None else zone.get("price_level", 0.0)
    processed_conditions = []
    for cond in conditions:
        # Preserve ALL original custom fields (min_volume, direction, etc.)
        processed = dict(cond)
        processed.setdefault("level", cond.get("level", level))
        processed.setdefault("description", f"{cond.get('type', 'unknown')} at {cond.get('level', level)}")
        processed["status"] = TriggerConditionStatus.PENDING.value
        processed_conditions.append(processed)

    return {
        "trigger_id": f"{name.lower().replace(' ', '_')}_{datetime.utcnow().timestamp():.0f}",
        "name": name,
        "trigger_type": "premium",
        "zone_ref": zone.get("zone_type", ""),
        "price_level": level,
        "direction": zone.get("direction", ""),
        "conditions": processed_conditions,
        "premium": True,
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
    }


def check_trigger(
    trigger: dict[str, Any],
    market_data: dict[str, Any],
) -> TriggerCheckResult:
    """Check whether a trigger's conditions are satisfied by current market data.

    Evaluates each condition in the trigger against the provided market data.
    A normal trigger (single condition) is triggered when its one condition is met.
    A premium trigger (multiple conditions) is triggered when ALL conditions are met.

    Args:
        trigger: A trigger dict created by ``create_trigger()`` or
            ``create_premium_trigger()``.
        market_data: Dict with current market state. Supported keys:
            - ``price`` (float): current price.
            - ``volume`` (float): current volume.
            - ``structure_bias`` (str): current structure direction.
            - ``trend_aligned`` (bool): whether trend supports the setup.

    Returns:
        A ``TriggerCheckResult`` with ``.triggered``, ``.condition_statuses``,
        and details.

    Example::

        result = check_trigger(trigger, {"price": 19610.0, "volume": 60000})
        if result.triggered:
            print(f"Trigger fired: {result.details}")
    """
    trigger_id = trigger.get("trigger_id", "unknown")
    conditions = trigger.get("conditions", [])
    direction = trigger.get("direction", "")
    price_level = trigger.get("price_level", 0.0)
    current_price = market_data.get("price", 0.0)

    condition_statuses: dict[str, TriggerConditionStatus] = {}
    met_count = 0

    for cond in conditions:
        cond_type = cond.get("type", "unknown")
        cond_level = cond.get("level", price_level)
        description = cond.get("description", cond_type)
        status = TriggerConditionStatus.PENDING

        if cond_type == "zone_touch":
            # Zone is touched if price has reached the level
            # We check with a small tolerance
            touched = False
            if direction == "bullish" and current_price >= cond_level * 0.995:
                # Price at or above the zone (with 0.5% tolerance for simplicity)
                touched = True
            elif direction == "bearish" and current_price <= cond_level * 1.005:
                touched = True
            elif not direction:
                # No direction — any touch counts
                low = cond_level * 0.99
                high = cond_level * 1.01
                touched = low <= current_price <= high

            status = TriggerConditionStatus.MET if touched else TriggerConditionStatus.FAILED

        elif cond_type == "reclaim":
            # Price has reclaimed above/below the level after touching it
            reclaimed = False
            if direction == "bullish" and current_price > cond_level:
                reclaimed = True
            elif direction == "bearish" and current_price < cond_level:
                reclaimed = True
            status = TriggerConditionStatus.MET if reclaimed else TriggerConditionStatus.FAILED

        elif cond_type == "volume_spike":
            # Volume spike detection
            min_volume = cond.get("min_volume", 0)
            current_volume = market_data.get("volume", 0)
            spike = current_volume >= min_volume
            status = TriggerConditionStatus.MET if spike else TriggerConditionStatus.FAILED

        elif cond_type == "structure_support":
            # Structure direction supports the trigger
            structure_bias = market_data.get("structure_bias", "")
            supports = structure_bias.lower() == direction.lower() if structure_bias else False
            status = TriggerConditionStatus.MET if supports else TriggerConditionStatus.FAILED

        elif cond_type == "trend_aligned":
            # Trend direction aligns with trigger direction
            trend_aligned = market_data.get("trend_aligned", False)
            status = TriggerConditionStatus.MET if trend_aligned else TriggerConditionStatus.FAILED

        elif cond_type == "price_above":
            above = current_price > cond_level
            status = TriggerConditionStatus.MET if above else TriggerConditionStatus.FAILED

        elif cond_type == "price_below":
            below = current_price < cond_level
            status = TriggerConditionStatus.MET if below else TriggerConditionStatus.FAILED

        else:
            # Unknown condition type — mark as FAILED
            status = TriggerConditionStatus.FAILED
            logger.warning(
                "Unknown trigger condition type",
                extra={"trigger_id": trigger_id, "cond_type": cond_type},
            )

        condition_statuses[description] = status
        if status == TriggerConditionStatus.MET:
            met_count += 1

    # A trigger fires when ALL conditions are MET
    total = len(conditions)
    all_met = met_count == total and total > 0

    result = TriggerCheckResult(
        triggered=all_met,
        trigger_id=trigger_id,
        condition_statuses=condition_statuses,
        met_count=met_count,
        total_conditions=total,
        details=(
            f"Trigger {'FIRED' if all_met else 'PENDING'}: "
            f"{met_count}/{total} conditions met"
        ),
        checked_at=datetime.utcnow(),
    )

    if result.triggered:
        logger.info(
            "Trigger fired",
            extra={"trigger_id": trigger_id, "met": met_count, "total": total},
        )

    return result
