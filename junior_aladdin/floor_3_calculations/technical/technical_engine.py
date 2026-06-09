"""Technical — Main calculation engine.

Orchestrates all Technical sub-calculators in a single run cycle:
1. RSI (Relative Strength Index)
2. Moving Average (SMA + EMA)
3. ATR (Average True Range)
4. Volume Profile (POC, VAH, VAL)

Collects all results into CalculatedSignal list + EngineRunReport.
Pure orchestration — no state, no external calls.
"""

from __future__ import annotations

import time
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    CalculationInput,
    CalculationLog,
    CalculationQuality,
    EngineRunReport,
    EngineStatus,
    generate_signal_id,
    compute_input_hash,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.technical.atr_calculator import (
    calculate_atr,
)
from junior_aladdin.floor_3_calculations.technical.ma_calculator import (
    calculate_ma,
    classify_ma_cross,
)
from junior_aladdin.floor_3_calculations.technical.rsi_calculator import (
    calculate_rsi,
    classify_rsi,
)
from junior_aladdin.floor_3_calculations.technical.volume_profile import (
    calculate_volume_profile,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("technical_engine")

ENGINE_NAME = "technical_engine"
ENGINE_VERSION = "1.0"


def run(
    calc_input: CalculationInput,
    config: F3Config | None = None,
) -> EngineRunReport:
    """Run the Technical calculation engine for one cycle.

    Executes all 4 sub-calculators in order:
    1. RSI → Relative Strength Index with oversold/overbought
    2. Moving Averages → SMA fast + slow, EMA, cross classification
    3. ATR → Average True Range with volatility classification
    4. Volume Profile → POC, VAH, VAL

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
            domain=CalculationDomain.TECHNICAL,
            status=EngineStatus.COMPLETE,
            signals_generated=[],
            duration_ms=0.0,
            errors=["No candle data provided"],
        )

    params = cfg.get_params_for_domain(CalculationDomain.TECHNICAL)
    rsi_period = params.get("rsi_period", 14)
    rsi_oversold = params.get("rsi_oversold", 30.0)
    rsi_overbought = params.get("rsi_overbought", 70.0)
    ma_fast_period = params.get("ma_fast_period", 9)
    ma_slow_period = params.get("ma_slow_period", 21)
    atr_period = params.get("atr_period", 14)
    vol_profile_period = params.get("volume_profile_period", 30)

    # Compute input hash for replay verification
    input_hash = compute_input_hash(calc_input.data)

    # ── Step 1: RSI ─────────────────────────────────────────────────
    try:
        rsi_values = calculate_rsi(
            candles,
            period=rsi_period,
            params=cfg.technical,
        )
        for rsi_val in rsi_values:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="RSI",
                value={
                    "rsi_value": rsi_val.value,
                    "oversold": rsi_val.oversold,
                    "overbought": rsi_val.overbought,
                    "classification": classify_rsi(rsi_val.value, rsi_oversold, rsi_overbought),
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))
        logger.debug("RSI calculation complete", extra={"values": len(rsi_values)})
    except Exception as exc:
        errors.append(f"rsi_calculator error: {exc}")
        logger.warning("RSI calculation failed", extra={"error": str(exc)})

    # ── Step 2: Moving Averages ─────────────────────────────────────
    try:
        ma_fast = calculate_ma(candles, period=ma_fast_period, ma_type="SMA")
        ma_slow = calculate_ma(candles, period=ma_slow_period, ma_type="SMA")

        # Fast MA signal (last value summary)
        if ma_fast:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="MA_FAST",
                value={
                    "period": ma_fast_period,
                    "latest_value": ma_fast[-1].value,
                    "total_values": len(ma_fast),
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        # Slow MA signal
        if ma_slow:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="MA_SLOW",
                value={
                    "period": ma_slow_period,
                    "latest_value": ma_slow[-1].value,
                    "total_values": len(ma_slow),
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        # Cross classification (if both have values)
        if ma_fast and ma_slow:
            cross = classify_ma_cross(ma_fast, ma_slow)
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="MA_CROSS",
                value={
                    "fast_period": ma_fast_period,
                    "slow_period": ma_slow_period,
                    "cross": cross,
                    "fast_value": ma_fast[-1].value,
                    "slow_value": ma_slow[-1].value,
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        logger.debug(
            "MA calculation complete",
            extra={"fast": len(ma_fast), "slow": len(ma_slow)},
        )
    except Exception as exc:
        errors.append(f"ma_calculator error: {exc}")
        logger.warning("MA calculation failed", extra={"error": str(exc)})

    # ── Step 3: ATR ────────────────────────────────────────────────
    try:
        atr_values = calculate_atr(candles, period=atr_period)
        if atr_values:
            latest_atr = atr_values[-1].value
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="ATR",
                value={
                    "period": atr_period,
                    "latest_value": latest_atr,
                    "total_values": len(atr_values),
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        logger.debug("ATR calculation complete", extra={"values": len(atr_values)})
    except Exception as exc:
        errors.append(f"atr_calculator error: {exc}")
        logger.warning("ATR calculation failed", extra={"error": str(exc)})

    # ── Step 4: Volume Profile ─────────────────────────────────────
    try:
        vp = calculate_volume_profile(candles, period=vol_profile_period)
        if vp.total_volume > 0:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="VOLUME_PROFILE",
                value={
                    "poc": vp.poc,
                    "vah": vp.vah,
                    "val": vp.val,
                    "value_area_volume": vp.value_area_volume,
                    "total_volume": vp.total_volume,
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        logger.debug(
            "Volume profile complete",
            extra={
                "poc": vp.poc,
                "total_volume": vp.total_volume,
            },
        )
    except Exception as exc:
        errors.append(f"volume_profile error: {exc}")
        logger.warning("Volume profile calculation failed", extra={"error": str(exc)})

    # ── Build Report ────────────────────────────────────────────────
    duration_ms = (time.time() - start_time) * 1000
    signal_ids = [s.signal_id for s in signals]

    status = EngineStatus.ERROR if errors else EngineStatus.COMPLETE
    return EngineRunReport(
        engine_name=ENGINE_NAME,
        domain=CalculationDomain.TECHNICAL,
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
        indicator_type: Technical indicator type.
        value: The calculated value dict.
        calc_input: Original CalculationInput for metadata.
        input_hash: Input data hash for replay verification.

    Returns:
        A fully formed CalculatedSignal.
    """
    cal_log = CalculationLog(
        signal_id=signal_id,
        domain=CalculationDomain.TECHNICAL,
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        parameters_used=[{"domain": "TECHNICAL"}],
        calculation_steps=[{"step": indicator_type, "status": "COMPLETE"}],
        warnings=[],
    )
    quality = CalculationQuality.NOMINAL
    return CalculatedSignal(
        signal_id=signal_id,
        domain=CalculationDomain.TECHNICAL,
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
