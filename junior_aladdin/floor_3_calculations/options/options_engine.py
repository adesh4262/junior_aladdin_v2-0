"""Options — Main calculation engine.

Orchestrates all Options sub-calculators in a single run cycle:
1. OI Changes — CE/PE buying vs unwinding
2. PCR — Put-Call Ratio value and trend
3. IV — Implied Volatility state analysis
4. Walls — CALL_WALL / PUT_WALL strike detection
5. Max Pain — Max Pain strike calculation

Collects all results into CalculatedSignal list + EngineRunReport.
Pure orchestration — no state, no external calls.

Input data format (from ``calc_input.data["options_snapshots"]``)::

    {
        "snapshots": [
            {
                "strike": 19500.0,
                "option_type": "CE",
                "oi": 150000,
                "premium": 185.0,
                "iv": 15.5,
                "change_in_oi": 5000,
                "expiry": "2026-06-25",
                "timestamp": ...
            },
            ...
        ],
        "reference_price": 19520.0,   # optional, for distance calc
    }
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
    compute_input_hash,
    generate_signal_id,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.options.oi_calculator import (
    calculate_oi_changes,
    calculate_oi_summary,
)
from junior_aladdin.floor_3_calculations.options.pcr_calculator import calculate_pcr
from junior_aladdin.floor_3_calculations.options.iv_calculator import calculate_iv
from junior_aladdin.floor_3_calculations.options.wall_calculator import detect_walls
from junior_aladdin.floor_3_calculations.options.max_pain_calculator import (
    calculate_max_pain,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("options_engine")

ENGINE_NAME = "options_engine"
ENGINE_VERSION = "1.0"


def run(
    calc_input: CalculationInput,
    config: F3Config | None = None,
) -> EngineRunReport:
    """Run the Options calculation engine for one cycle.

    Executes all 5 sub-calculators:
    1. OI Changes — detect BUYING/UNWINDING per strike
    2. PCR — Put-Call Ratio
    3. IV — Implied Volatility state
    4. Walls — CALL_WALL / PUT_WALL detection
    5. Max Pain — Max Pain strike

    Args:
        calc_input: CalculationInput with options_snapshots data.
        config: Optional F3Config for parameters. Uses defaults if None.

    Returns:
        EngineRunReport with status, generated signal IDs, and errors.
    """
    cfg = config or F3Config()
    start_time = time.time()
    signals: list[CalculatedSignal] = []
    errors: list[str] = []

    # Extract options snapshot data
    options_data = calc_input.data.get("options_snapshots", {})
    snapshots = options_data.get("snapshots", [])
    reference_price = options_data.get("reference_price", 0.0)

    if not snapshots:
        return EngineRunReport(
            engine_name=ENGINE_NAME,
            domain=CalculationDomain.OPTIONS,
            status=EngineStatus.COMPLETE,
            signals_generated=[],
            duration_ms=0.0,
            errors=["No options snapshot data provided"],
        )

    # Compute input hash for replay verification
    input_hash = compute_input_hash(calc_input.data)

    params = cfg.get_params_for_domain(CalculationDomain.OPTIONS)
    min_oi_change_pct = params.get("min_oi_change_pct", 5.0)
    iv_high = params.get("iv_high_threshold", 30.0)
    iv_low = params.get("iv_low_threshold", 15.0)

    # ── Step 1: OI Changes ────────────────────────────────────────────
    try:
        oi_changes = calculate_oi_changes(snapshots, min_oi_change_pct=min_oi_change_pct)
        oi_summary = calculate_oi_summary(oi_changes)

        for change in oi_changes:
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type="OI_CHANGE",
                value={
                    "oi_direction": change["oi_direction"],
                    "change_pct": change["change_pct"],
                    "strike": change["strike"],
                    "option_type": change["option_type"],
                    "change_in_oi": change["change_in_oi"],
                    "premium": change["premium"],
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        # Emit OI summary as a single aggregate signal
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="OI_SUMMARY",
            value=oi_summary,
            calc_input=calc_input,
            input_hash=input_hash,
        ))

        logger.debug(
            "OI changes computed",
            extra={"significant_changes": len(oi_changes)},
        )
    except Exception as exc:
        errors.append(f"oi_calculator error: {exc}")
        logger.warning("OI calculation failed", extra={"error": str(exc)})

    # ── Step 2: PCR ───────────────────────────────────────────────────
    try:
        pcr_result = calculate_pcr(snapshots)
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="PCR",
            value={
                "pcr_value": pcr_result["pcr_value"],
                "pcr_trend": pcr_result["pcr_trend"],
                "total_ce_oi": pcr_result["total_ce_oi"],
                "total_pe_oi": pcr_result["total_pe_oi"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "PCR computed",
            extra={"pcr": pcr_result["pcr_value"], "trend": pcr_result["pcr_trend"]},
        )
    except Exception as exc:
        errors.append(f"pcr_calculator error: {exc}")

    # ── Step 3: IV ────────────────────────────────────────────────────
    try:
        iv_result = calculate_iv(snapshots, iv_high_threshold=iv_high, iv_low_threshold=iv_low)
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="IV",
            value={
                "iv_value": iv_result["iv_value"],
                "iv_percentile": iv_result["iv_percentile"],
                "iv_context": iv_result["iv_context"],
                "sample_count": iv_result["sample_count"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "IV computed",
            extra={"iv": iv_result["iv_value"], "context": iv_result["iv_context"]},
        )
    except Exception as exc:
        errors.append(f"iv_calculator error: {exc}")

    # ── Step 4: Walls ─────────────────────────────────────────────────
    try:
        walls = detect_walls(snapshots, reference_price=reference_price)

        for wall in walls:
            indicator = wall["wall_type"]  # CALL_WALL or PUT_WALL
            sid = generate_signal_id()
            signals.append(_build_signal(
                signal_id=sid,
                indicator_type=indicator,
                value={
                    "wall_strike": wall["wall_strike"],
                    "wall_strength": wall["wall_strength"],
                    "distance_pct": wall["distance_pct"],
                },
                calc_input=calc_input,
                input_hash=input_hash,
            ))

        logger.debug(
            "Walls detected",
            extra={"walls_found": len(walls)},
        )
    except Exception as exc:
        errors.append(f"wall_calculator error: {exc}")

    # ── Step 5: Max Pain ──────────────────────────────────────────────
    try:
        max_pain_result = calculate_max_pain(snapshots, reference_price=reference_price)
        sid = generate_signal_id()
        signals.append(_build_signal(
            signal_id=sid,
            indicator_type="MAX_PAIN",
            value={
                "max_pain_strike": max_pain_result["max_pain_strike"],
                "max_pain_oi": max_pain_result["max_pain_oi"],
                "distance_pct": max_pain_result["distance_pct"],
            },
            calc_input=calc_input,
            input_hash=input_hash,
        ))
        logger.debug(
            "Max pain computed",
            extra={"strike": max_pain_result["max_pain_strike"]},
        )
    except Exception as exc:
        errors.append(f"max_pain_calculator error: {exc}")

    # ── Build Report ──────────────────────────────────────────────────
    duration_ms = (time.time() - start_time) * 1000
    signal_ids = [s.signal_id for s in signals]

    status = EngineStatus.ERROR if errors else EngineStatus.COMPLETE
    return EngineRunReport(
        engine_name=ENGINE_NAME,
        domain=CalculationDomain.OPTIONS,
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
        indicator_type: Options indicator type (OI_CHANGE, PCR, IV, etc.).
        value: The calculated value dict.
        calc_input: Original CalculationInput for metadata.
        input_hash: Input data hash for replay verification.

    Returns:
        A fully formed CalculatedSignal.
    """
    cal_log = CalculationLog(
        signal_id=signal_id,
        domain=CalculationDomain.OPTIONS,
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        parameters_used=[{"domain": "OPTIONS"}],
        calculation_steps=[{"step": indicator_type, "status": "COMPLETE"}],
        warnings=[],
    )
    quality = CalculationQuality.NOMINAL
    return CalculatedSignal(
        signal_id=signal_id,
        domain=CalculationDomain.OPTIONS,
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
