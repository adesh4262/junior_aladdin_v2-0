"""ICT — Main calculation engine.

Orchestrates all ICT sub-calculators in a single run cycle:
1. Premium/Discount Array (swing levels, zone classification)
2. Kill Zone detection (time-based session windows)
3. Liquidity level detection (swing high/low pools, sweep status)

Collects all results into CalculatedSignal list + EngineRunReport.
Pure orchestration — no state, no external calls.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    CalculationInput,
    CalculationLog,
    CalculationQuality,
    EngineRunReport,
    EngineStatus,
    LiquidityType,
    generate_signal_id,
    compute_input_hash,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.ict.kill_zone_calculator import (
    get_kill_zones,
    get_next_kill_zone,
)
from junior_aladdin.floor_3_calculations.ict.liquidity_calculator import (
    classify_liquidity,
    detect_liquidity_levels,
)
from junior_aladdin.floor_3_calculations.ict.pd_array_calculator import (
    calculate_pd_array,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("ict_engine")

ENGINE_NAME = "ict_engine"
ENGINE_VERSION = "1.0"


def run(
    calc_input: CalculationInput,
    config: F3Config | None = None,
) -> EngineRunReport:
    """Run the ICT calculation engine for one cycle.

    Executes all 3 sub-calculators in order:
    1. PD Array → Premium/Discount/OTE zone levels
    2. Kill Zones → Active/upcoming session windows
    3. Liquidity → Swing high/low liquidity pools with sweep status

    Each step is isolated — an error in one does not block the others.

    Args:
        calc_input: CalculationInput with candle data.
        config: Optional F3Config for parameters. Uses defaults if None.

    Returns:
        EngineRunReport with status, generated signal IDs, and errors.
    """
    cfg = config or F3Config()
    start_time = time.time()
    signals: list[CalculatedSignal] = []
    errors: list[str] = []
    candles = calc_input.data.get("candles", [])

    if not candles:
        return EngineRunReport(
            engine_name=ENGINE_NAME,
            domain=CalculationDomain.ICT,
            status=EngineStatus.COMPLETE,
            signals_generated=[],
            duration_ms=0.0,
            errors=["No candle data provided"],
        )

    params = cfg.get_params_for_domain(CalculationDomain.ICT)
    pd_array_period = params.get("pd_array_period", 20)
    pivot_window = 5  # Default pivot window for liquidity detection

    # Compute input hash for replay verification
    input_hash = compute_input_hash(calc_input.data)

    # ── Step 1: PD Array ──────────────────────────────────────────────
    try:
        levels = calculate_pd_array(candles, period=pd_array_period)
        for level in levels:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="PD_ARRAY",
                value={
                    "pd_type": level.pd_type.value,
                    "level": level.level,
                    "strength": level.strength,
                },
                calc_input=calc_input,
                input_hash=input_hash,
                timestamp=level.timestamp,
            ))
        logger.debug(
            "PD Array calculation complete",
            extra={"levels": len(levels), "period": pd_array_period},
        )
    except Exception as exc:
        errors.append(f"pd_array_calculator error: {exc}")
        logger.warning("PD Array calculation failed", extra={"error": str(exc)})

    # ── Step 2: Kill Zone Detection ───────────────────────────────────
    try:
        ref_ts = calc_input.timestamp or datetime.utcnow()
        all_zones = get_kill_zones(ref_ts, cfg.ict)
        for zone in all_zones:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="KILL_ZONE",
                value={
                    "kill_zone_type": zone.kill_zone_type.value,
                    "active": zone.active,
                    "time_remaining_s": zone.time_remaining_s,
                },
                calc_input=calc_input,
                input_hash=input_hash,
                timestamp=zone.start_time,
            ))

        # Include next upcoming zone as a separate signal
        next_zone = get_next_kill_zone(ref_ts, cfg.ict)
        if next_zone and not next_zone.active:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="NEXT_KILL_ZONE",
                value={
                    "kill_zone_type": next_zone.kill_zone_type.value,
                    "time_until_s": next_zone.time_remaining_s,
                },
                calc_input=calc_input,
                input_hash=input_hash,
                timestamp=next_zone.start_time,
            ))

        logger.debug(
            "Kill zone detection complete",
            extra={"zones": len(all_zones), "active": len([z for z in all_zones if z.active])},
        )
    except Exception as exc:
        errors.append(f"kill_zone_calculator error: {exc}")
        logger.warning("Kill zone detection failed", extra={"error": str(exc)})

    # ── Step 3: Liquidity Level Detection ─────────────────────────────
    try:
        liquidity_levels = detect_liquidity_levels(
            candles,
            cfg.ict,
            pivot_window=pivot_window,
        )
        for liq in liquidity_levels:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="LIQUIDITY",
                value={
                    "liquidity_type": liq.liquidity_type.value,
                    "price": liq.price,
                    "swept": liq.swept,
                    "size": liq.size,
                },
                calc_input=calc_input,
                input_hash=input_hash,
                timestamp=liq.timestamp,
            ))

        # Classify overall liquidity context
        buy_side = [l for l in liquidity_levels if l.liquidity_type == LiquidityType.BUY_SIDE]
        sell_side = [l for l in liquidity_levels if l.liquidity_type == LiquidityType.SELL_SIDE]
        context = classify_liquidity(buy_side, sell_side)

        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="LIQUIDITY_CONTEXT",
            value={
                "context": context.value,
                "buy_side_active": sum(1 for l in buy_side if not l.swept),
                "sell_side_active": sum(1 for l in sell_side if not l.swept),
                "total_levels": len(liquidity_levels),
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))

        logger.debug(
            "Liquidity detection complete",
            extra={
                "levels": len(liquidity_levels),
                "context": context.value,
            },
        )
    except Exception as exc:
        errors.append(f"liquidity_calculator error: {exc}")
        logger.warning("Liquidity detection failed", extra={"error": str(exc)})

    # ── Build Report ──────────────────────────────────────────────────
    duration_ms = (time.time() - start_time) * 1000
    signal_ids = [s.signal_id for s in signals]

    status = EngineStatus.ERROR if errors else EngineStatus.COMPLETE
    return EngineRunReport(
        engine_name=ENGINE_NAME,
        domain=CalculationDomain.ICT,
        status=status,
        signals_generated=signal_ids,
        signals=signals,
        duration_ms=round(duration_ms, 2),
        errors=errors,
    )


def _build_signal(
    signal_id: str,
    indicator_type: str,
    value: Any,
    calc_input: CalculationInput,
    input_hash: str,
    timestamp: datetime | None = None,
) -> CalculatedSignal:
    """Build a CalculatedSignal with proper metadata.

    Args:
        signal_id: Unique signal identifier.
        indicator_type: ICT indicator/pattern type.
        value: The calculated value dict.
        calc_input: Original CalculationInput for metadata.
        input_hash: Input data hash for replay verification.
        timestamp: Optional override timestamp. Falls back to calc_input timestamp.

    Returns:
        A fully formed CalculatedSignal.
    """
    cal_log = CalculationLog(
        signal_id=signal_id,
        domain=CalculationDomain.ICT,
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        parameters_used=[{"domain": "ICT"}],
        calculation_steps=[{"step": indicator_type, "status": "COMPLETE"}],
        warnings=[],
    )
    quality = CalculationQuality.NOMINAL
    return CalculatedSignal(
        signal_id=signal_id,
        domain=CalculationDomain.ICT,
        indicator_type=indicator_type,
        value=value,
        timestamp=timestamp or calc_input.timestamp,
        quality=quality,
        metadata={
            "symbol": calc_input.symbol,
            "market_phase": calc_input.market_phase.value,
            "packet_ref": calc_input.packet_envelope_id,
        },
        calculation_log=cal_log,
    )
