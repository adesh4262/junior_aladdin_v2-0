"""Macro — Calendar State Engine.

Transforms shared TradingCalendar data into MACRO-domain CalculatedSignals
for Floor 4 Macro Head consumption.

Produces:
- EVENT_CALENDAR: Current events, expiry, holidays, next event
- MACRO_CONTEXT: Aggregated macro context summary

Pure function — wraps shared/trading_calendar.py, no state.
"""

from __future__ import annotations

from datetime import datetime

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
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.trading_calendar import (
    get_market_session,
    format_market_session,
    IST,
)

logger = get_logger("calendar_state_engine")

ENGINE_NAME = "calendar_state_engine"
ENGINE_VERSION = "1.0"


def run(
    calc_input: CalculationInput,
    config: object | None = None,
) -> EngineRunReport:
    """Run the Calendar State Engine for one cycle.

    Reads the shared TradingCalendar and produces MACRO-domain signals.

    Args:
        calc_input: CalculationInput (timestamp used for context).
        config: Optional config (unused — calendar is static).

    Returns:
        EngineRunReport with EVENT_CALENDAR and MACRO_CONTEXT signals.
    """
    signals: list[CalculatedSignal] = []
    errors: list[str] = []

    # Use input timestamp or current IST time
    ref_dt = calc_input.timestamp
    if ref_dt is None or ref_dt.tzinfo is None:
        ref_dt = datetime.now(IST)

    # Ensure IST timezone
    if ref_dt.tzinfo != IST:
        ref_dt = ref_dt.astimezone(IST)

    input_hash = compute_input_hash(calc_input.data)

    try:
        # Get complete market session info
        session = get_market_session(ref_dt)

        # ── Signal 1: EVENT_CALENDAR ─────────────────────────────────
        sid1 = generate_signal_id()
        event_signal = CalculatedSignal(
            signal_id=sid1,
            domain=CalculationDomain.MACRO,
            indicator_type="EVENT_CALENDAR",
            value={
                "session_state": session.session_state.value,
                "is_market_open": session.is_market_open,
                "is_holiday_today": session.is_holiday_today,
                "is_expiry_today": session.is_expiry_today,
                "is_expiry_week": session.is_expiry_week,
                "is_rollover_week": session.is_rollover_week,
                "events_today": session.events_today,
                "next_event": session.next_event,
                "next_event_date": session.next_event_date,
                "days_until_event": session.days_to_next_event,
                "time_to_market_open_s": session.time_to_market_open,
                "time_to_market_close_s": session.time_to_market_close,
            },
            timestamp=ref_dt,
            quality=CalculationQuality.NOMINAL,
            metadata={
                "symbol": calc_input.symbol,
                "market_phase": calc_input.market_phase.value,
                "packet_ref": calc_input.packet_envelope_id,
            },
            calculation_log=CalculationLog(
                signal_id=sid1,
                domain=CalculationDomain.MACRO,
                engine_version=ENGINE_VERSION,
                input_hash=input_hash,
                parameters_used=[{"domain": "MACRO"}],
                calculation_steps=[{"step": "calendar_query", "status": "COMPLETE"}],
                warnings=[],
            ),
        )
        signals.append(event_signal)

        # ── Signal 2: MACRO_CONTEXT (aggregated) ──────────────────────
        sid2 = generate_signal_id()
        summary_str = format_market_session(session)

        macro_bias = "neutral"
        caution_level = 0.0
        if session.is_holiday_today:
            macro_bias = "bearish"
            caution_level = 1.0
        elif session.is_expiry_today:
            macro_bias = "neutral"
            caution_level = 0.4
        elif session.is_expiry_week:
            macro_bias = "neutral"
            caution_level = 0.25
        elif session.is_rollover_week:
            macro_bias = "neutral"
            caution_level = 0.2

        ctx_signal = CalculatedSignal(
            signal_id=sid2,
            domain=CalculationDomain.MACRO,
            indicator_type="MACRO_CONTEXT",
            value={
                "context_summary": summary_str,
                "macro_bias": macro_bias,
                "caution_level": caution_level,
                "event_risk_flag": session.is_expiry_today or session.is_holiday_today,
            },
            timestamp=ref_dt,
            quality=CalculationQuality.NOMINAL,
            metadata={
                "symbol": calc_input.symbol,
                "market_phase": calc_input.market_phase.value,
                "packet_ref": calc_input.packet_envelope_id,
            },
            calculation_log=CalculationLog(
                signal_id=sid2,
                domain=CalculationDomain.MACRO,
                engine_version=ENGINE_VERSION,
                input_hash=input_hash,
                parameters_used=[{"domain": "MACRO"}],
                calculation_steps=[{"step": "context_aggregation", "status": "COMPLETE"}],
                warnings=[],
            ),
        )
        signals.append(ctx_signal)

        logger.debug(
            "Calendar state computed",
            extra={
                "session": session.session_state.value,
                "expiry": session.is_expiry_today,
                "events": len(session.events_today),
            },
        )

    except Exception as exc:
        errors.append(f"calendar_state_engine error: {exc}")
        logger.warning("Calendar state engine failed", extra={"error": str(exc)})

    duration_ms = 0.0  # Calendar is instantaneous

    status = EngineStatus.ERROR if errors else EngineStatus.COMPLETE
    return EngineRunReport(
        engine_name=ENGINE_NAME,
        domain=CalculationDomain.MACRO,
        status=status,
        signals_generated=[s.signal_id for s in signals],
        signals=signals,
        duration_ms=duration_ms,
        errors=errors,
    )
