"""SMC — Main calculation engine.

Orchestrates all SMC sub-calculators in a single run cycle:
1. Market Structure analysis (swing points, structure type)
2. Fair Value Gap detection
3. Order Block detection
4. Change of Character detection

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
    Floor3Summary,
    MarketStructureType,
    compute_input_hash,
    generate_signal_id,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.smc.choch_calculator import detect_choch
from junior_aladdin.floor_3_calculations.smc.fvg_calculator import (
    check_mitigation,
    detect_fvg,
)
from junior_aladdin.floor_3_calculations.smc.market_structure import (
    analyze_structure,
)
from junior_aladdin.floor_3_calculations.smc.ob_calculator import (
    detect_order_blocks,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("smc_engine")

ENGINE_NAME = "smc_engine"
ENGINE_VERSION = "1.0"


def run(
    calc_input: CalculationInput,
    config: F3Config | None = None,
) -> EngineRunReport:
    """Run the SMC calculation engine for one cycle.

    Executes all 4 sub-calculators in order:
    1. Market Structure → structure type + swing points
    2. FVG Detection → Fair Value Gaps
    3. Order Block Detection → Bullish/Bearish OBs
    4. CHOCH Detection → Changes of Character

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
            domain=CalculationDomain.SMC,
            status=EngineStatus.COMPLETE,
            signals_generated=[],
            duration_ms=0.0,
            errors=["No candle data provided"],
        )

    params = cfg.get_params_for_domain(CalculationDomain.SMC)
    pivot_window = 2
    lookback = params.get("market_structure_lookback", 50)
    min_gap = params.get("fvg_min_gap_pips", 0.5)
    consecutive = params.get("choch_required_consecutive", 2)

    # Compute input hash for replay verification
    input_hash = compute_input_hash(calc_input.data)

    # Default structure result for subsequent steps even if analysis fails
    struct_result = {
        "structure_type": MarketStructureType.CHOP,
        "valid": False,
        "swing_points": [],
        "swing_high_count": 0,
        "swing_low_count": 0,
    }
    structure_type = MarketStructureType.CHOP

    # ── Step 1: Market Structure ──────────────────────────────────────
    try:
        struct_result = analyze_structure(
            candles, lookback=lookback, pivot_window=pivot_window
        )
        structure_type = struct_result["structure_type"]
        swing_points = struct_result["swing_points"]

        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="MARKET_STRUCTURE",
            value={
                "structure_type": structure_type.value,
                "structure_valid": struct_result["valid"],
                "swing_high_count": struct_result["swing_high_count"],
                "swing_low_count": struct_result["swing_low_count"],
                "description": _describe_structure_type(structure_type),
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "Market structure analysed",
            extra={"structure": structure_type.value, "swings": len(swing_points)},
        )
    except Exception as exc:
        errors.append(f"market_structure error: {exc}")
        logger.warning("Market structure analysis failed", extra={"error": str(exc)})

    # ── Step 2: FVG Detection ─────────────────────────────────────────
    try:
        fvgs = detect_fvg(candles, min_gap_pips=min_gap)
        for fvg in fvgs:
            sid = generate_signal_id()
            mitigated, _ = check_mitigation(fvg, candles)
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="FVG",
                value={
                    "fvg_type": fvg.fvg_type.value,
                    "top": fvg.top,
                    "bottom": fvg.bottom,
                    "gap_size_pips": fvg.gap_size_pips,
                    "mitigated": mitigated,
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))
        logger.debug("FVG detection complete", extra={"fvgs_found": len(fvgs)})
    except Exception as exc:
        errors.append(f"fvg_calculator error: {exc}")

    # ── Step 3: Order Block Detection ─────────────────────────────────
    try:
        obs = detect_order_blocks(
            candles,
            trend=structure_type if struct_result["valid"] else None,
            pivot_window=pivot_window,
            lookback=lookback,
        )
        for ob in obs:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="ORDER_BLOCK",
                value={
                    "ob_type": ob.ob_type.value,
                    "price": ob.price,
                    "strength": ob.strength,
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))
        logger.debug("Order block detection complete", extra={"obs_found": len(obs)})
    except Exception as exc:
        errors.append(f"ob_calculator error: {exc}")

    # ── Step 4: CHOCH Detection ───────────────────────────────────────
    try:
        chochs = detect_choch(
            candles,
            pivot_window=pivot_window,
            lookback=lookback,
            consecutive_required=consecutive,
        )
        for choch in chochs:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="CHOCH",
                value={
                    "choch_type": choch.choch_type.value,
                    "break_price": choch.break_price,
                    "prior_structure": choch.prior_structure.value,
                    "confirmed": choch.confirmed,
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))
        logger.debug("CHOCH detection complete", extra={"chochs_found": len(chochs)})
    except Exception as exc:
        errors.append(f"choch_calculator error: {exc}")

    # ── Build Report ──────────────────────────────────────────────────
    duration_ms = (time.time() - start_time) * 1000
    signal_ids = [s.signal_id for s in signals]

    status = EngineStatus.ERROR if errors else EngineStatus.COMPLETE
    return EngineRunReport(
        engine_name=ENGINE_NAME,
        domain=CalculationDomain.SMC,
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
) -> CalculatedSignal:
    """Build a CalculatedSignal with proper metadata.

    Args:
        signal_id: Unique signal identifier.
        indicator_type: SMC indicator/pattern type.
        value: The calculated value dict.
        calc_input: Original CalculationInput for metadata.
        input_hash: Input data hash for replay verification.

    Returns:
        A fully formed CalculatedSignal.
    """
    cal_log = CalculationLog(
        signal_id=signal_id,
        domain=CalculationDomain.SMC,
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        parameters_used=[{"domain": "SMC"}],
        calculation_steps=[{"step": indicator_type, "status": "COMPLETE"}],
        warnings=[],
    )
    quality = CalculationQuality.NOMINAL
    return CalculatedSignal(
        signal_id=signal_id,
        domain=CalculationDomain.SMC,
        indicator_type=indicator_type,
        value=value,
        timestamp=calc_input.timestamp,
        quality=quality,
        metadata={
            "symbol": calc_input.symbol,
            "market_phase": calc_input.market_phase.value,
            "packet_ref": calc_input.packet_envelope_id,
        },
        calculation_log=cal_log,
    )


def _describe_structure_type(st: MarketStructureType) -> str:
    """Get a short human-readable description of a structure type."""
    descriptions = {
        MarketStructureType.BULLISH_HH_HL: "Uptrend (Higher Highs + Higher Lows)",
        MarketStructureType.BEARISH_LH_LL: "Downtrend (Lower Highs + Lower Lows)",
        MarketStructureType.CHOP: "Range-bound / Choppy",
        MarketStructureType.BREAKOUT: "Breakout from prior range",
    }
    return descriptions.get(st, st.value)
