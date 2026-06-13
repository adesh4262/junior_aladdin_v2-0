"""Floor 5 — Trade Constructor (Step 5.16).

Converts an approved trade decision into a structured executable trade plan
for Side A. Only called if TRADE state is approved.

Architecture (see ROADMAP_FLOOR_05 Section 5.16):
- Direction from confluence → CE or PE
- Capital feasibility within operator-set limit
- Strike hierarchy: ATM → slight ITM → near OTM (must be justified)
- Deep OTM rejected (lottery behavior)
- Entry logic with zone + trigger + confirmation
- Stop loss structure per trade class
- Target structure per trade class
- Capital fit verification

Architecture rules:
- Only imports captain_types + shared/types — NO Floor 3/4 calculation imports
- Trade constructor is called AFTER trade_class_engine
- Not called if decision is WAIT or BLOCKED
- Output feeds CaptainDecision (→ Side A) and ExecutionIntent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionBand,
    ConvictionScore,
    MarketStory,
)
from junior_aladdin.floor_5_captain.trade_class_engine import (
    TradeClassAssignment,
    TradeClassEngine,
)
from junior_aladdin.shared.types import CaptainDecision, DecisionType, TradeClass


# ── Default capital & lot constants ────────────────────────────────────────
# These are sensible defaults; operator sets real values on dashboard.

_DEFAULT_CAPITAL_LIMIT = 25000.0        # 25,000 INR default
_DEFAULT_LOT_SIZE = 50                  # NIFTY 50 lot size
_DEFAULT_STRIKE_INTERVAL = 50           # 50 INR between strikes
_ATM_STRIKE_PRICE = 19500.0             # Default ATM for tests
_DEEP_OTM_THRESHOLD_STRIKES = 2         # 2+ strikes OTM = deep OTM (rejected)


# ── TradePlan dataclass ────────────────────────────────────────────────────


@dataclass
class TradePlan:
    """Structured trade plan produced by the TradeConstructor.

    This is the full construction output that feeds into CaptainDecision
    for delivery to Side A (Execution).

    Fields:
        direction: "BUY" or "SELL".
        option_side: "CE" for BUY, "PE" for SELL.
        selected_strike: The chosen strike price (e.g., "19500").
        strike_type: "ATM", "ITM", "OTM", or "NEAR_OTM".
        trade_class: The assigned TradeClass.
        entry_plan: Dict with zone, trigger, confirmation details.
        invalidation_level: Price level that invalidates the trade.
        stop_loss_plan: Dict with SL price, type, distance_bps.
        target_plan: Dict with target(s), R_multiple, type.
        capital_fit: Dict with lot_size, premium_estimate, capital_limit, fits.
        is_constructable: Whether the plan is fully constructable.
        construction_fail_reason: Reason if not constructable.
        timestamp: When the plan was constructed.
    """
    direction: str = ""
    option_side: str = ""
    selected_strike: str = ""
    strike_type: str = ""
    trade_class: TradeClass | None = None
    entry_plan: dict[str, Any] = field(default_factory=dict)
    invalidation_level: float = 0.0
    stop_loss_plan: dict[str, Any] = field(default_factory=dict)
    target_plan: dict[str, Any] = field(default_factory=dict)
    capital_fit: dict[str, Any] = field(default_factory=lambda: {
        "lot_size": _DEFAULT_LOT_SIZE,
        "premium_estimate": 0.0,
        "capital_limit": _DEFAULT_CAPITAL_LIMIT,
        "fits": True,
    })
    is_constructable: bool = True
    construction_fail_reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


# ── TradeConstructor ───────────────────────────────────────────────────────


class TradeConstructor:
    """Constructs executable trade plans from Captain's approved decisions.

    Only called when TRADE state is approved (post-conviction engine).
    Produces a structured TradePlan that can be converted into a
    CaptainDecision and forwarded to Side A.

    Usage::

        constructor = TradeConstructor()
        plan = constructor.construct_trade(
            direction="BUY",
            trade_class_assignment=assignment,
            conviction_score=scores,
            market_story=story,
            confluence_result=conf_result,
            capital_limit=25000.0,
            atm_strike=19500.0,
        )
        if plan.is_constructable:
            decision = constructor.to_captain_decision(plan, conviction_score)
            # decision → Side A
    """

    def __init__(self, trade_class_engine: TradeClassEngine | None = None) -> None:
        """Initialize the trade constructor.

        Args:
            trade_class_engine: Optional TradeClassEngine for metadata lookup.
        """
        self._tce = trade_class_engine or TradeClassEngine()

    # ------------------------------------------------------------------
    # Main Construction Method
    # ------------------------------------------------------------------

    def construct_trade(
        self,
        direction: str,
        trade_class_assignment: TradeClassAssignment | None = None,
        conviction_score: ConvictionScore | None = None,
        confluence_result: ConfluenceResult | None = None,
        market_story: MarketStory | None = None,
        capital_limit: float = _DEFAULT_CAPITAL_LIMIT,
        atm_strike: float = _ATM_STRIKE_PRICE,
        lot_size: int = _DEFAULT_LOT_SIZE,
        current_price: float = 0.0,
        zone_info: dict[str, Any] | None = None,
    ) -> TradePlan:
        """Construct a full trade plan from approved inputs.

        Steps:
        1. Determine option side (CE/PE) from direction
        2. Verify capital feasibility
        3. Select strike (ATM → ITM → near OTM, reject deep OTM)
        4. Build entry plan (zone + trigger + confirmation)
        5. Set invalidation level
        6. Build stop loss structure (per trade class)
        7. Build target structure (per trade class)
        8. Verify capital fit

        Args:
            direction: "BUY" or "SELL" from trade idea.
            trade_class_assignment: Result from trade_class_engine.
            conviction_score: Result from conviction_engine.
            confluence_result: Result from confluence_engine.
            market_story: Current market story.
            capital_limit: Operator-set capital limit.
            atm_strike: Current ATM strike price.
            lot_size: Contract lot size.
            current_price: Current underlying price.
            zone_info: Optional dict with zone details (label, price, type).

        Returns:
            A fully populated ``TradePlan``.
        """
        dt = datetime.utcnow()
        tc = trade_class_assignment.trade_class if trade_class_assignment else None

        # Step 1: Option side
        option_side = self._determine_option_side(direction)

        # Step 2: Capital feasibility
        if capital_limit <= 0:
            return TradePlan(
                direction=direction,
                trade_class=tc,
                is_constructable=False,
                construction_fail_reason="Capital limit is zero or negative",
                timestamp=dt,
            )

        if not direction:
            return TradePlan(
                direction="",
                trade_class=tc,
                is_constructable=False,
                construction_fail_reason="No direction provided",
                timestamp=dt,
            )

        # Step 3: Strike selection
        strike, strike_type = self._select_strike(
            option_side=option_side,
            atm_strike=atm_strike,
            capital_limit=capital_limit,
            lot_size=lot_size,
            conviction_score=conviction_score,
        )

        if not strike:
            return TradePlan(
                direction=direction,
                option_side=option_side,
                trade_class=tc,
                is_constructable=False,
                construction_fail_reason="No valid strike selected",
                timestamp=dt,
            )

        # Step 4: Build entry plan
        entry_plan = self._build_entry_plan(
            trade_class=tc,
            direction=direction,
            current_price=current_price,
            zone_info=zone_info,
            requires_confirmation=self._requires_confirmation(tc, conviction_score),
        )

        # Step 5: Invalidation level
        invalidation_level = self._determine_invalidation_level(
            trade_class=tc,
            direction=direction,
            current_price=current_price,
            zone_info=zone_info,
        )

        # Step 6: Stop loss structure
        stop_loss_plan = self._build_sl_plan(
            trade_class=tc,
            direction=direction,
            entry_price=entry_plan.get("entry_price", current_price),
        )

        # Step 7: Target structure
        target_plan = self._build_target_plan(
            trade_class=tc,
            direction=direction,
            entry_price=entry_plan.get("entry_price", current_price),
            conviction_score=conviction_score,
        )

        # Step 8: Capital fit verification
        premium_estimate = self._estimate_premium(strike, option_side, lot_size, atm_strike)
        capital_fit = self._verify_capital_fit(
            premium_estimate=premium_estimate,
            capital_limit=capital_limit,
            lot_size=lot_size,
        )

        return TradePlan(
            direction=direction,
            option_side=option_side,
            selected_strike=str(int(strike)),
            strike_type=strike_type,
            trade_class=tc,
            entry_plan=entry_plan,
            invalidation_level=invalidation_level,
            stop_loss_plan=stop_loss_plan,
            target_plan=target_plan,
            capital_fit=capital_fit,
            is_constructable=capital_fit["fits"],
            construction_fail_reason="" if capital_fit["fits"] else "Capital limit exceeded by premium estimate",
            timestamp=dt,
        )

    # ------------------------------------------------------------------
    # Step Methods
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_option_side(direction: str) -> str:
        """Map trade direction to option side.

        Args:
            direction: "BUY" or "SELL".

        Returns:
            "CE" for BUY, "PE" for SELL, or "" if unknown.
        """
        mapping = {
            "BUY": "CE",
            "SELL": "PE",
        }
        return mapping.get(direction, "")

    def _select_strike(
        self,
        option_side: str,
        atm_strike: float,
        capital_limit: float,
        lot_size: int,
        conviction_score: ConvictionScore | None = None,
    ) -> tuple[float | None, str]:
        """Select the appropriate strike price.

        Hierarchy:
        1. ATM (preferred)
        2. Slight ITM (1 strike ITM, if conviction is TRADABLE+)
        3. Near OTM (1 strike OTM, must be justified by STRONG+ conviction)

        Deep OTM (2+ strikes away) is always rejected.

        Args:
            option_side: "CE" or "PE".
            atm_strike: Current ATM strike price.
            capital_limit: Operator-set capital limit.
            lot_size: Contract lot size.
            conviction_score: Current conviction scores (for justification).

        Returns:
            Tuple of ``(strike_price_or_None, strike_type_string)``.
        """
        band = conviction_score.conviction_band if conviction_score else ConvictionBand.REJECT

        # ATM is always preferred
        atm_premium = self._estimate_premium(str(int(atm_strike)), option_side, lot_size, atm_strike)
        if atm_premium <= capital_limit:
            return atm_strike, "ATM"

        # Slight ITM (1 strike ITM) — requires TRADABLE+ conviction
        if band in (ConvictionBand.TRADABLE, ConvictionBand.STRONG, ConvictionBand.ELITE):
            itm_strike = self._get_itm_strike(option_side, atm_strike)
            itm_premium = self._estimate_premium(str(int(itm_strike)), option_side, lot_size, atm_strike)
            if itm_premium <= capital_limit:
                return itm_strike, "ITM"

        # Near OTM (1 strike OTM) — requires STRONG+ conviction justification
        if band in (ConvictionBand.STRONG, ConvictionBand.ELITE):
            otm_strike = self._get_otm_strike(option_side, atm_strike)
            otm_premium = self._estimate_premium(str(int(otm_strike)), option_side, lot_size, atm_strike)
            if otm_premium <= capital_limit:
                return otm_strike, "NEAR_OTM"

        # Fallback: try OTM (may be cheaper, fits budget)
        otm_strike = self._get_otm_strike(option_side, atm_strike)
        otm_premium = self._estimate_premium(str(int(otm_strike)), option_side, lot_size, atm_strike)
        if 0 < otm_premium <= capital_limit:
            return otm_strike, "NEAR_OTM"

        # Deep OTM check — 2 strikes away would be even cheaper
        # If even ATM is too expensive, try ATM as fallback
        if atm_premium > 0:
            return atm_strike, "ATM"

        return None, ""

    @staticmethod
    def _get_itm_strike(option_side: str, atm_strike: float) -> float:
        """Get 1 strike in-the-money from ATM.

        For CE (BUY): ITM = ATM - 1 interval (lower strike = more intrinsic)
        For PE (SELL): ITM = ATM + 1 interval (higher strike = more intrinsic)

        Args:
            option_side: "CE" or "PE".
            atm_strike: Current ATM strike.

        Returns:
            ITM strike price.
        """
        if option_side == "CE":
            return atm_strike - _DEFAULT_STRIKE_INTERVAL
        return atm_strike + _DEFAULT_STRIKE_INTERVAL

    @staticmethod
    def _get_otm_strike(option_side: str, atm_strike: float) -> float:
        """Get 1 strike out-of-the-money from ATM.

        For CE (BUY): OTM = ATM + 1 interval (higher strike = less likely)
        For PE (SELL): OTM = ATM - 1 interval (lower strike = less likely)

        Args:
            option_side: "CE" or "PE".
            atm_strike: Current ATM strike.

        Returns:
            OTM strike price (1 strike away, NOT deep OTM).
        """
        if option_side == "CE":
            return atm_strike + _DEFAULT_STRIKE_INTERVAL
        return atm_strike - _DEFAULT_STRIKE_INTERVAL

    @staticmethod
    def _build_entry_plan(
        trade_class: TradeClass | None,
        direction: str,
        current_price: float,
        zone_info: dict[str, Any] | None = None,
        requires_confirmation: bool = False,
    ) -> dict[str, Any]:
        """Build the entry plan dict.

        Args:
            trade_class: The assigned trade class.
            direction: "BUY" or "SELL".
            current_price: Current underlying price.
            zone_info: Dict with zone label, price, type (e.g., FVG, OB).
            requires_confirmation: Whether an extra confirmation tick is needed.

        Returns:
            Dict with entry_plan fields.
        """
        zone = zone_info or {}
        return {
            "zone_label": zone.get("label", ""),
            "zone_price": zone.get("price", current_price),
            "zone_type": zone.get("type", ""),
            "entry_price": zone.get("price", current_price),
            "entry_condition": f"{direction.upper()} when price reaches zone",
            "requires_confirmation": requires_confirmation,
            "confirmation_type": "second_close" if requires_confirmation else "none",
            "direction": direction,
        }

    @staticmethod
    def _determine_invalidation_level(
        trade_class: TradeClass | None,
        direction: str,
        current_price: float,
        zone_info: dict[str, Any] | None = None,
    ) -> float:
        """Determine the invalidation level for the trade.

        SCALP: tight invalidation (0.2% from entry)
        CONTINUATION: moderate (0.5% from entry)
        REVERSAL: wider (0.8% from entry)
        LIQUIDITY_RECLAIM: beyond sweep level
        OPTIONS_PRESSURE: beyond OI wall

        Args:
            trade_class: The assigned trade class.
            direction: "BUY" or "SELL".
            current_price: Current underlying price.
            zone_info: Optional zone info (may contain invalidation level).

        Returns:
            Price level that invalidates the trade.
        """
        # If zone_info has an explicit invalidation, use it
        if zone_info and "invalidation" in zone_info:
            return zone_info["invalidation"]

        zone_price = (zone_info or {}).get("price", current_price)
        pct = 0.005  # default 0.5%

        if trade_class == TradeClass.SCALP:
            pct = 0.002  # 0.2%
        elif trade_class == TradeClass.CONTINUATION:
            pct = 0.005  # 0.5%
        elif trade_class == TradeClass.REVERSAL:
            pct = 0.008  # 0.8%
        elif trade_class == TradeClass.LIQUIDITY_RECLAIM:
            pct = 0.006  # 0.6%
        elif trade_class == TradeClass.OPTIONS_PRESSURE:
            pct = 0.005  # 0.5%

        if direction == "BUY":
            return round(zone_price * (1.0 - pct), 1)
        else:
            return round(zone_price * (1.0 + pct), 1)

    @staticmethod
    def _build_sl_plan(
        trade_class: TradeClass | None,
        direction: str,
        entry_price: float,
    ) -> dict[str, Any]:
        """Build stop loss plan per trade class.

        Args:
            trade_class: The assigned trade class.
            direction: "BUY" or "SELL".
            entry_price: Entry price for SL calculation.

        Returns:
            Dict with SL plan fields.
        """
        # SL distance as percentage of entry price
        sl_pct = 0.005  # default 0.5%

        if trade_class == TradeClass.SCALP:
            sl_pct = 0.003  # 0.3% — tight SL
        elif trade_class == TradeClass.CONTINUATION:
            sl_pct = 0.005  # 0.5% — moderate
        elif trade_class == TradeClass.REVERSAL:
            sl_pct = 0.008  # 0.8% — wider
        elif trade_class == TradeClass.LIQUIDITY_RECLAIM:
            sl_pct = 0.006  # 0.6%
        elif trade_class == TradeClass.OPTIONS_PRESSURE:
            sl_pct = 0.005  # 0.5%

        if direction == "BUY":
            sl_price = round(entry_price * (1.0 - sl_pct), 1)
        else:
            sl_price = round(entry_price * (1.0 + sl_pct), 1)

        sl_distance_bps = int(sl_pct * 10000)  # Convert to bps

        return {
            "sl_price": sl_price,
            "sl_type": "fixed",
            "sl_distance_bps": sl_distance_bps,
            "sl_pct": sl_pct,
            "trailing": trade_class == TradeClass.CONTINUATION,
        }

    @staticmethod
    def _build_target_plan(
        trade_class: TradeClass | None,
        direction: str,
        entry_price: float,
        conviction_score: ConvictionScore | None = None,
    ) -> dict[str, Any]:
        """Build target plan per trade class.

        SCALP: 1:1 R:R, fixed target
        CONTINUATION: 1:2 R:R preferred, trailing SL
        REVERSAL: 1:1.5 R:R, fixed target
        LIQUIDITY_RECLAIM: 1:2 R:R, structure-based target
        OPTIONS_PRESSURE: 1:1.5 R:R, trail on expansion

        Args:
            trade_class: The assigned trade class.
            direction: "BUY" or "SELL".
            entry_price: Entry price for target calculation.
            conviction_score: Current conviction (higher = more aggressive target).

        Returns:
            Dict with target plan fields.
        """
        r_multiple = 1.5  # default
        target_type = "fixed"

        if trade_class == TradeClass.SCALP:
            r_multiple = 1.0
            target_type = "fixed"
        elif trade_class == TradeClass.CONTINUATION:
            r_multiple = 2.0
            target_type = "trailing"
        elif trade_class == TradeClass.REVERSAL:
            r_multiple = 1.5
            target_type = "fixed"
        elif trade_class == TradeClass.LIQUIDITY_RECLAIM:
            r_multiple = 2.0
            target_type = "structure_based"
        elif trade_class == TradeClass.OPTIONS_PRESSURE:
            r_multiple = 1.5
            target_type = "trail_on_expansion"

        # Boost R multiple for high conviction
        if conviction_score and conviction_score.conviction_band == ConvictionBand.ELITE:
            r_multiple *= 1.33  # 33% more aggressive target

        # Calculate SL distance from entry to estimate risk per unit
        # Use standard SL pct for the class
        sl_pct = 0.005
        if trade_class == TradeClass.SCALP:
            sl_pct = 0.003
        elif trade_class == TradeClass.CONTINUATION:
            sl_pct = 0.005
        elif trade_class == TradeClass.REVERSAL:
            sl_pct = 0.008
        elif trade_class == TradeClass.LIQUIDITY_RECLAIM:
            sl_pct = 0.006

        sl_distance = entry_price * sl_pct
        target_distance = sl_distance * r_multiple

        if direction == "BUY":
            target_price = round(entry_price + target_distance, 1)
        else:
            target_price = round(entry_price - target_distance, 1)

        # Guard against division by zero when entry_price is 0.0
        safe_entry = entry_price if entry_price != 0.0 else 1.0

        return {
            "target_price": target_price,
            "r_multiple": r_multiple,
            "target_type": target_type,
            "target_distance_bps": int((target_distance / safe_entry) * 10000),
            "has_target": True,
        }

    @staticmethod
    def _estimate_premium(
        strike: str,
        option_side: str,
        lot_size: int,
        atm_strike: float = _ATM_STRIKE_PRICE,
    ) -> float:
        """Estimate the premium cost for a given strike.

        Simplified estimation based on strike distance from ATM.
        In production, this would come from live options chain data.

        Args:
            strike: Strike price as string (e.g., "19500").
            option_side: "CE" or "PE".
            lot_size: Contract lot size.
            atm_strike: Current ATM strike price for relative distance.

        Returns:
            Estimated premium cost (lot_size × estimated_option_price).
        """
        try:
            strike_float = float(strike)
        except (ValueError, TypeError):
            return 0.0

        # Simple premium estimation based on distance from ATM
        distance = abs(strike_float - atm_strike)
        # Premium estimate: ATM ~100 INR, decreases by ~5 INR per strike away,
        # minimum 10 INR for deep OTM
        estimated_option_price = max(10.0, 100.0 - (distance / _DEFAULT_STRIKE_INTERVAL) * 5.0)

        return round(estimated_option_price * lot_size, 2)

    @staticmethod
    def _verify_capital_fit(
        premium_estimate: float,
        capital_limit: float,
        lot_size: int,
    ) -> dict[str, Any]:
        """Verify that the premium fits within capital limit.

        Args:
            premium_estimate: Estimated premium cost for the position.
            capital_limit: Operator-set capital limit.
            lot_size: Contract lot size.

        Returns:
            Dict with capital fit details.
        """
        fits = premium_estimate <= capital_limit if capital_limit > 0 else False
        utilization_pct = round((premium_estimate / capital_limit) * 100, 1) if capital_limit > 0 else 0.0

        return {
            "lot_size": lot_size,
            "premium_estimate": premium_estimate,
            "capital_limit": capital_limit,
            "fits": fits,
            "utilization_pct": utilization_pct,
        }

    @staticmethod
    def _requires_confirmation(
        trade_class: TradeClass | None,
        conviction_score: ConvictionScore | None = None,
    ) -> bool:
        """Determine if the trade requires an extra confirmation tick.

        Most trade classes require confirmation except SCALP.
        TRADABLE conviction also requires confirmation regardless of class.

        Args:
            trade_class: The assigned trade class.
            conviction_score: Current conviction.

        Returns:
            True if confirmation is needed.
        """
        if trade_class == TradeClass.SCALP:
            return False

        if conviction_score and conviction_score.conviction_band == ConvictionBand.TRADABLE:
            return True

        # CONTINUATION, REVERSAL, LIQUIDITY_RECLAIM, OPTIONS_PRESSURE all need confirmation
        if trade_class in (
            TradeClass.CONTINUATION,
            TradeClass.REVERSAL,
            TradeClass.LIQUIDITY_RECLAIM,
            TradeClass.OPTIONS_PRESSURE,
        ):
            return True

        return False

    # ------------------------------------------------------------------
    # Conversion to CaptainDecision
    # ------------------------------------------------------------------

    @staticmethod
    def to_captain_decision(
        plan: TradePlan,
        conviction_score: ConvictionScore | None = None,
        reason_summary: str = "",
        snapshot_id: str = "",
    ) -> CaptainDecision:
        """Convert a TradePlan into a CaptainDecision for Side A.

        Args:
            plan: The constructed TradePlan.
            conviction_score: Current conviction score (for top-level fields).
            reason_summary: Human-readable reason summary.
            snapshot_id: Decision snapshot reference.

        Returns:
            A fully populated ``CaptainDecision``.
        """
        is_trade = plan.is_constructable and plan.direction != ""

        return CaptainDecision(
            decision=DecisionType.TRADE if is_trade else DecisionType.WAIT,
            action=plan.direction,
            option_side=plan.option_side,
            selected_strike=plan.selected_strike,
            trade_class=plan.trade_class or TradeClass.SCALP,
            permission_score=conviction_score.permission_score if conviction_score else 0.0,
            conviction_score=conviction_score.conviction_score if conviction_score else 0.0,
            no_trade_score=conviction_score.no_trade_score if conviction_score else 0.0,
            entry_plan=plan.entry_plan,
            invalidation_level=plan.invalidation_level,
            stop_loss_plan=plan.stop_loss_plan,
            target_plan=plan.target_plan,
            reason_summary=reason_summary or (
                f"{plan.direction} {plan.option_side} {plan.selected_strike} "
                f"({plan.trade_class.value if plan.trade_class else '?'})"
            ),
            silence_reason=None if is_trade else plan.construction_fail_reason or "No trade constructed",
            snapshot_id=snapshot_id,
            timestamp=plan.timestamp,
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def get_trade_summary(plan: TradePlan) -> dict[str, Any]:
        """Get a structured summary of the trade plan for dashboard/logging.

        Args:
            plan: The TradePlan to summarize.

        Returns:
            Dict with key plan fields.
        """
        return {
            "direction": plan.direction,
            "option_side": plan.option_side,
            "selected_strike": plan.selected_strike,
            "strike_type": plan.strike_type,
            "trade_class": plan.trade_class.value if plan.trade_class else "",
            "is_constructable": plan.is_constructable,
            "construction_fail_reason": plan.construction_fail_reason,
            "entry_condition": plan.entry_plan.get("entry_condition", ""),
            "invalidation_level": plan.invalidation_level,
            "sl_price": plan.stop_loss_plan.get("sl_price", 0.0),
            "sl_distance_bps": plan.stop_loss_plan.get("sl_distance_bps", 0),
            "target_price": plan.target_plan.get("target_price", 0.0),
            "target_type": plan.target_plan.get("target_type", ""),
            "r_multiple": plan.target_plan.get("r_multiple", 1.0),
            "capital_fits": plan.capital_fit.get("fits", False),
            "capital_utilization_pct": plan.capital_fit.get("utilization_pct", 0.0),
            "premium_estimate": plan.capital_fit.get("premium_estimate", 0.0),
            "has_plan": plan.is_constructable,
            "timestamp": plan.timestamp.isoformat() if plan.timestamp else "",
        }
