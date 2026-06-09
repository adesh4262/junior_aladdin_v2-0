"""Floor 4 — Invalidation Formatter.

Standard invalidation object creation, checking, and merging.

Invalidation is **MANDATORY** in ALL heads (non-negotiable).
Every Head must define at least one invalidation rule.

Why mandatory:
Captain's thesis integrity tracking and active trade supervision depend on
invalidation. Without it, a head says "I like this" but never says
"I am wrong if this breaks."

Invalidation creation:
- ``create_invalidation()`` — build an invalidation dict from rules.
- ``check_invalidation()`` — evaluate rules against market data.
- ``merge_invalidations()`` — combine multiple invalidation summaries.

Usage::

    from junior_aladdin.floor_4_heads.invalidation_formatter import (
        create_invalidation,
        check_invalidation,
        merge_invalidations,
    )

    # Create
    invalidation = create_invalidation(
        rules=[
            {"condition": "Structure breaks below 19500", "price_level": 19500.0,
             "reason": "Bullish structure invalidated"},
            {"condition": "FVG at 19600 fully mitigated", "price_level": 19600.0,
             "reason": "Setup gap closed"},
        ],
    )

    # Check
    result = check_invalidation(invalidation, {"price": 19400.0})
    if result.triggered:
        print(f"Invalidation FIRED: {result.details}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.shared.logging import get_logger

logger = get_logger("invalidation_formatter")

# ── Severity levels ─────────────────────────────────────────────────────────


class InvalidationSeverity:
    """Severity classification for invalidation rules.

    ``HARD``: Structure definitively broken — thesis is invalid.
    ``SOFT``: Context weakened but not yet broken — thesis needs watching.
    ``WARNING``: Early signal that invalidation conditions are forming.
    """
    HARD = "HARD"
    SOFT = "SOFT"
    WARNING = "WARNING"


# =============================================================================
# InvalidationCheckResult
# =============================================================================


@dataclass
class InvalidationCheckResult:
    """Result of checking an invalidation against market data.

    Fields:
        triggered: Whether ANY rule has been triggered (HARD/ SOFT rules).
        trigger_reasons: List of human-readable reasons for triggered rules.
        triggered_rules: List of rule dicts that were triggered.
        pending_rules: List of rule dicts that are not yet triggered.
        total_rules: Total number of invalidation rules evaluated.
        triggered_at: When the check was performed (UTC).
        details: Human-readable summary.
    """
    triggered: bool = False
    trigger_reasons: list[str] = field(default_factory=list)
    triggered_rules: list[dict[str, Any]] = field(default_factory=list)
    pending_rules: list[dict[str, Any]] = field(default_factory=list)
    total_rules: int = 0
    triggered_at: datetime = field(default_factory=datetime.utcnow)
    details: str = ""


# =============================================================================
# Invalidation Format Helpers
# =============================================================================


def create_invalidation(
    rules: list[dict[str, Any]] | None = None,
    summary: str = "",
    severity: str = InvalidationSeverity.HARD,
) -> dict[str, Any]:
    """Create a standardised invalidation dict for a HeadReport.

    Args:
        rules: List of rule dicts, each with:
            - ``condition`` (str): Human-readable condition.
            - ``price_level`` (float): Price level at which invalidation occurs.
            - ``reason`` (str): Why this invalidation exists.
            - Optional: ``severity`` (str): HARD / SOFT / WARNING.
        summary: Optional override summary. Auto-generated if empty.
        severity: Default severity for rules that don't specify their own.

    Returns:
        An invalidation dict with ``rules``, ``summary``, ``severity``,
        and ``created_at`` keys.
    """
    rules_list = list(rules) if rules else []

    # Process rules: ensure each has required fields
    processed_rules = []
    for rule in rules_list:
        processed_rules.append({
            "condition": rule.get("condition", "No condition specified"),
            "price_level": float(rule.get("price_level", 0.0)),
            "reason": rule.get("reason", "No reason specified"),
            "severity": rule.get("severity", severity),
        })

    # Auto-generate summary if not provided
    if not summary and processed_rules:
        reasons = [r["reason"] for r in processed_rules[:3]]
        summary = "; ".join(reasons)
    elif not summary:
        summary = "No invalidation rules defined"

    return {
        "rules": processed_rules,
        "summary": summary,
        "severity": severity,
        "created_at": datetime.utcnow().isoformat(),
        "triggered": False,
    }


def check_invalidation(
    invalidation: dict[str, Any],
    market_data: dict[str, Any],
) -> InvalidationCheckResult:
    """Check whether any invalidation rules are triggered by current market data.

    Evaluates each rule's condition against the provided market state.
    A rule is triggered if the current price has crossed the rule's
    ``price_level`` in the wrong direction.

    Args:
        invalidation: An invalidation dict from ``create_invalidation()``.
        market_data: Dict with current market state. Supported keys:
            - ``price`` (float): current price.
            - ``low`` (float): current session low.
            - ``high`` (float): current session high.
            - ``structure_bias`` (str): current structure direction.
            - ``structure_broken`` (bool): whether structure has broken.

    Returns:
        An ``InvalidationCheckResult`` with ``.triggered``, ``.trigger_reasons``,
        ``.triggered_rules``, ``.pending_rules``, and ``.details``.

    Example::

        inv = create_invalidation(rules=[...])
        result = check_invalidation(inv, {"price": 19400.0, "low": 19350.0})
        if result.triggered:
            # HALT — thesis is broken
    """
    rules = invalidation.get("rules", [])
    if not rules:
        return InvalidationCheckResult(
            triggered=False,
            details="No invalidation rules to check",
            total_rules=0,
        )

    current_price = market_data.get("price", 0.0)
    current_low = market_data.get("low", current_price)
    current_high = market_data.get("high", current_price)
    structure_broken = market_data.get("structure_broken", False)
    structure_bias = market_data.get("structure_bias", "")

    triggered_rules: list[dict[str, Any]] = []
    pending_rules: list[dict[str, Any]] = []
    trigger_reasons: list[str] = []

    for rule in rules:
        condition = rule.get("condition", "")
        price_level = rule.get("price_level", 0.0)
        reason = rule.get("reason", "")
        rule_triggered = False

        cond_lower = condition.lower()

        # Check price-based conditions — ORDER MATTERS: check "above" before
        # "break" because "break" is a substring of "breaks" which appears
        # in both "break below" and "break above" conditions.
        if "above" in cond_lower:
            # Price breaking above a level
            if price_level > 0 and current_price >= price_level:
                rule_triggered = True
            elif price_level > 0 and current_high >= price_level:
                rule_triggered = True

        elif "break" in cond_lower or "below" in cond_lower:
            # Price breaking below a level
            if price_level > 0 and current_price <= price_level:
                rule_triggered = True
            elif price_level > 0 and current_low <= price_level:
                rule_triggered = True

        elif "structure" in cond_lower:
            # Structure-based invalidation
            if structure_broken:
                rule_triggered = True
            elif "flip" in cond_lower and structure_bias and structure_broken:
                rule_triggered = True

        elif "mitigated" in cond_lower or "closed" in cond_lower:
            # Zone mitigation — price has reached the zone level
            if price_level > 0 and current_price >= price_level:
                rule_triggered = True

        if rule_triggered:
            triggered_rules.append(rule)
            trigger_reasons.append(f"{reason} ({condition})")
        else:
            pending_rules.append(rule)

    result = InvalidationCheckResult(
        triggered=len(triggered_rules) > 0,
        trigger_reasons=trigger_reasons,
        triggered_rules=triggered_rules,
        pending_rules=pending_rules,
        total_rules=len(rules),
        triggered_at=datetime.utcnow(),
        details=(
            f"{len(triggered_rules)}/{len(rules)} invalidation rules triggered"
            if triggered_rules
            else f"0/{len(rules)} invalidation rules triggered — thesis intact"
        ),
    )

    if result.triggered:
        logger.warning(
            "Invalidation triggered",
            extra={
                "triggered_count": len(triggered_rules),
                "total_rules": len(rules),
                "reasons": trigger_reasons,
            },
        )

    return result


def merge_invalidations(
    invalidation_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge multiple invalidation dicts into one combined summary.

    Useful when a Head has multiple independent invalidation sources
    (e.g., structure break + zone mitigation) and wants a single
    consolidated invalidation dict for the HeadReport.

    Args:
        invalidation_list: List of invalidation dicts to merge.

    Returns:
        A single invalidation dict with ALL unique rules combined.
        The summary is generated from all unique reasons.
    """
    if not invalidation_list:
        return create_invalidation(
            rules=[{"condition": "No invalidation", "price_level": 0.0,
                     "reason": "No invalidation rules defined"}],
            summary="No invalidation defined",
        )

    seen_conditions: set[str] = set()
    merged_rules: list[dict[str, Any]] = []
    merged_triggered = False

    for inv in invalidation_list:
        for rule in inv.get("rules", []):
            condition = rule.get("condition", "")
            if condition not in seen_conditions:
                seen_conditions.add(condition)
                merged_rules.append(rule)

        # If ANY invalidation is triggered, the merged result is triggered
        if inv.get("triggered", False):
            merged_triggered = True

    # Build combined summary from unique reasons
    reasons = [r["reason"] for r in merged_rules[:5]]
    combined_summary = "; ".join(reasons) if reasons else "Combined invalidation"

    return {
        "rules": merged_rules,
        "summary": combined_summary,
        "severity": InvalidationSeverity.HARD,
        "created_at": datetime.utcnow().isoformat(),
        "triggered": merged_triggered,
        "merged_from": len(invalidation_list),
    }


# =============================================================================
# InvalidationManager
# =============================================================================


class InvalidationManager:
    """Manages invalidation lifecycle for a single Department Head.

    Tracks whether invalidation has been triggered, stores the active
    invalidation state, and integrates with ``HeadReport`` generation.

    Args:
        head_name: Name of the Head (for logging).
        rules: Initial list of invalidation rule dicts.

    Example::

        manager = InvalidationManager(
            head_name="smc",
            rules=[
                {"condition": "Structure breaks below last swing low",
                 "price_level": 19500.0,
                 "reason": "Bullish structure invalidated"},
            ],
        )

        # Get invalidation dict for HeadReport
        invalidation = manager.get_invalidation()
        report.invalidation = invalidation

        # Check against market data
        result = manager.check({"price": 19400.0})
        if result.triggered:
            manager.mark_triggered()
            # Captain should re-evaluate this Head's setups
    """

    def __init__(
        self,
        head_name: str = "",
        rules: list[dict[str, Any]] | None = None,
    ) -> None:
        self._head_name = head_name
        self._rules = list(rules) if rules else []
        self._triggered = False
        self._triggered_at: datetime | None = None
        self._trigger_reasons: list[str] = []
        self._invalidation = create_invalidation(rules=self._rules)

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def triggered(self) -> bool:
        """Whether invalidation has been triggered."""
        return self._triggered

    @property
    def triggered_at(self) -> datetime | None:
        """When invalidation was triggered (``None`` if not triggered)."""
        return self._triggered_at

    @property
    def trigger_reasons(self) -> list[str]:
        """Human-readable reasons for the trigger."""
        return list(self._trigger_reasons)

    # ── API ─────────────────────────────────────────────────────────────

    def get_invalidation(self) -> dict[str, Any]:
        """Get the current invalidation dict for a HeadReport.

        Returns:
            An invalidation dict with current trigger state.
        """
        self._invalidation["triggered"] = self._triggered
        return self._invalidation

    def check(self, market_data: dict[str, Any]) -> InvalidationCheckResult:
        """Check current invalidation rules against market data.

        Args:
            market_data: Dict with current market state.

        Returns:
            An ``InvalidationCheckResult``.
        """
        result = check_invalidation(self._invalidation, market_data)

        if result.triggered and not self._triggered:
            self._triggered = True
            self._triggered_at = result.triggered_at
            self._trigger_reasons = list(result.trigger_reasons)
            logger.info(
                "InvalidationManager: invalidation triggered",
                extra={
                    "head": self._head_name,
                    "reasons": result.trigger_reasons,
                },
            )

        return result

    def mark_triggered(self, reasons: list[str] | None = None) -> None:
        """Manually mark invalidation as triggered.

        Args:
            reasons: Optional override reasons. Uses existing reasons if None.
        """
        self._triggered = True
        self._triggered_at = datetime.utcnow()
        if reasons:
            self._trigger_reasons = list(reasons)

    def reset(self) -> None:
        """Reset invalidation state (for new setup / new cycle)."""
        self._triggered = False
        self._triggered_at = None
        self._trigger_reasons = []
        self._invalidation = create_invalidation(rules=self._rules)
        logger.debug(
            "InvalidationManager reset",
            extra={"head": self._head_name},
        )

    def add_rule(self, rule: dict[str, Any]) -> None:
        """Add a new invalidation rule.

        Args:
            rule: Dict with ``condition``, ``price_level``, and ``reason``.
        """
        self._rules.append(rule)
        self._invalidation = create_invalidation(rules=self._rules)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the full invalidation state (for Side C / review)."""
        return {
            "head_name": self._head_name,
            "triggered": self._triggered,
            "triggered_at": self._triggered_at.isoformat() if self._triggered_at else None,
            "trigger_reasons": self._trigger_reasons,
            "invalidation": self._invalidation,
        }
