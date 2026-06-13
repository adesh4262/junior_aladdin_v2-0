"""Support Metrics — Main calculation engine.

Orchestrates all 4 support calculators in a single run cycle:
1. Trap detection — mistake history analysis
2. Loss reporting — consecutive loss tracking
3. Cooldown status — time-based brake management
4. Overtrade detection — excessive trade frequency check

Produces PSYCHOLOGY-domain CalculatedSignal objects consumed by
Floor 4 Psychology Head.

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
    generate_signal_id,
    compute_input_hash,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.support_metrics.trap_metrics_engine import (
    detect_trap_pressure,
)
from junior_aladdin.floor_3_calculations.support_metrics.loss_metrics_engine import (
    compute_loss_report,
)
from junior_aladdin.floor_3_calculations.support_metrics.cooldown_metrics_engine import (
    compute_cooldown_status,
)
from junior_aladdin.floor_3_calculations.support_metrics.overtrade_metrics_engine import (
    detect_overtrade,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("support_metrics_engine")

ENGINE_NAME = "support_metrics_engine"
ENGINE_VERSION = "1.0"


def run(
    calc_input: CalculationInput,
    config: F3Config | None = None,
) -> EngineRunReport:
    """Run the Support Metrics calculation engine for one cycle.

    Executes all 4 calculators in order:
    1. Trap detection — analyzes mistake patterns
    2. Loss reporting — tracks consecutive losses
    3. Cooldown status — manages brake timer
    4. Overtrade detection — excessive trade frequency

    Each step is isolated — an error in one does not block the others.

    Args:
        calc_input: CalculationInput with psychology/trade data.
        config: Optional F3Config. Uses defaults if None.

    Returns:
        EngineRunReport with PSYCHOLOGY-domain signals.
    """
    cfg = config or F3Config()
    start_time = time.time()
    signals: list[CalculatedSignal] = []
    errors: list[str] = []

    # Extract input data — support metrics reads from system state
    mistake_history = calc_input.data.get("mistake_history", [])
    recent_trades = calc_input.data.get("recent_trades", [])
    loss_count = calc_input.data.get("loss_count", 0)
    sequence_length = calc_input.data.get("sequence_length", 0)
    same_zone_failures = calc_input.data.get("same_zone_failures", 0)
    cooldown_remaining = calc_input.data.get("cooldown_remaining_s", 0.0)
    trade_count_today = calc_input.data.get("trade_count_today", 0)

    # Compute input hash for replay verification
    input_hash = compute_input_hash(calc_input.data)

    ref_ts = calc_input.timestamp or datetime.utcnow()

    # ── Step 1: Trap Detection ──────────────────────────────────────────
    try:
        trap_result = detect_trap_pressure(
            mistake_history=mistake_history if mistake_history else None,
            same_zone_failures=same_zone_failures,
            total_mistakes=len(mistake_history) if mistake_history else 0,
        )
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="TRAP_ALERT",
            value={
                "trap_pressure": trap_result["trap_pressure"],
                "trap_density": trap_result["trap_density"],
                "trap_count": trap_result["trap_count"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "Trap analysis complete",
            extra={"trap_pressure": trap_result["trap_pressure"],
                   "density": trap_result["trap_density"]},
        )
    except Exception as exc:
        errors.append(f"trap_metrics error: {exc}")

    # ── Step 2: Loss Reporting ──────────────────────────────────────────
    try:
        loss_result = compute_loss_report(
            recent_trades=recent_trades if recent_trades else None,
            loss_count=loss_count,
            sequence_length=sequence_length,
        )
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="LOSS_REPORT",
            value={
                "loss_count": loss_result["loss_count"],
                "sequence_length": loss_result["sequence_length"],
                "has_loss_streak": loss_result["has_loss_streak"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "Loss report complete",
            extra={"loss_count": loss_result["loss_count"],
                   "sequence": loss_result["sequence_length"]},
        )
    except Exception as exc:
        errors.append(f"loss_metrics error: {exc}")

    # ── Step 3: Cooldown Status ─────────────────────────────────────────
    try:
        cooldown_result = compute_cooldown_status(
            remaining_seconds=cooldown_remaining,
            sequence_length=sequence_length,
            current_time=ref_ts,
        )
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="COOLDOWN_STATUS",
            value={
                "cooldown_active": cooldown_result["cooldown_active"],
                "cooldown_remaining_s": cooldown_result["cooldown_remaining_s"],
                "cooldown_total_s": cooldown_result["cooldown_total_s"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "Cooldown status computed",
            extra={"active": cooldown_result["cooldown_active"],
                   "remaining": cooldown_result["cooldown_remaining_s"]},
        )
    except Exception as exc:
        errors.append(f"cooldown_metrics error: {exc}")

    # ── Step 4: Overtrade Detection ─────────────────────────────────────
    try:
        overtrade_result = detect_overtrade(
            recent_trades=recent_trades if recent_trades else None,
            trade_count_today=trade_count_today,
            current_time=ref_ts,
        )
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="DISCIPLINE_REPORT",
            value={
                "trade_allowed": not overtrade_result["overtrade_flag"],
                "block_reason": (
                    "Overtrading detected — max trades exceeded"
                    if overtrade_result["overtrade_flag"]
                    else ""
                ),
                "trade_frequency": overtrade_result["trade_frequency"],
                "trades_in_window": overtrade_result["trades_in_window"],
                "max_trades_allowed": overtrade_result["max_trades_allowed"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "Overtrade check complete",
            extra={"overtrade": overtrade_result["overtrade_flag"],
                   "trades": overtrade_result["trades_in_window"]},
        )
    except Exception as exc:
        errors.append(f"overtrade_metrics error: {exc}")

    # ── Build Report ──────────────────────────────────────────────────
    duration_ms = (time.time() - start_time) * 1000
    signal_ids = [s.signal_id for s in signals]

    status = EngineStatus.ERROR if errors else EngineStatus.COMPLETE
    return EngineRunReport(
        engine_name=ENGINE_NAME,
        domain=CalculationDomain.PSYCHOLOGY,
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
    """Build a PSYCHOLOGY-domain CalculatedSignal.

    Args:
        signal_id: Unique signal identifier.
        indicator_type: Psychology indicator type.
        value: The calculated value dict.
        calc_input: Original CalculationInput for metadata.
        input_hash: Input data hash for replay verification.

    Returns:
        A fully formed CalculatedSignal.
    """
    cal_log = CalculationLog(
        signal_id=signal_id,
        domain=CalculationDomain.PSYCHOLOGY,
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        parameters_used=[{"domain": "PSYCHOLOGY"}],
        calculation_steps=[{"step": indicator_type, "status": "COMPLETE"}],
        warnings=[],
    )
    quality = CalculationQuality.NOMINAL
    return CalculatedSignal(
        signal_id=signal_id,
        domain=CalculationDomain.PSYCHOLOGY,
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
