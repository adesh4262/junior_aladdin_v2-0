"""Floor 3 — Domain Orchestrator.

Routes incoming data to the appropriate domain engines based on market
phase and data type. Orchestrates the full calculation cycle:

1. Receive data from Floor 2 (via f3_ingress)
2. Route to domain engines based on market phase:
   - PRE_OPEN:  SMC + ICT (structure prep + kill zones)
   - OPEN:      ALL domains (SMC + ICT + Technical)
   - LUNCH:     ALL domains
   - CLOSING:   SMC + Technical (structure update + analysis)
   - POST_CLOSE: No calculations (empty summary)
3. Collect results with timeout protection
4. Build OutputContract + Floor3Summary
5. Return for validation and dispatch to Floor 4

Architecture rules:
- Pure orchestration — no calculation logic.
- Error isolation — one engine failure does not block others.
- Timeout protection — engine exceeding timeout_ms is marked ERROR.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    CalculationInput,
    EngineRunReport,
    EngineStatus,
    Floor3Summary,
    MarketPhase,
    DataHealth,
)
from junior_aladdin.floor_3_calculations.f3_config import F3Config
from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.ict.ict_engine import run as ict_run
from junior_aladdin.floor_3_calculations.options.options_engine import run as options_run
from junior_aladdin.floor_3_calculations.smc.smc_engine import run as smc_run
from junior_aladdin.floor_3_calculations.technical.technical_engine import (
    run as technical_run,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("f3_orchestrator")

ORCHESTRATOR_VERSION = "1.0"


# ── Market phase → active domains mapping ───────────────────────────────────
# PRE_OPEN: prepare structure and kill zones before market opens
# OPEN + LUNCH: full analysis
# CLOSING: structure update and technical wrap-up
# POST_CLOSE: no calculations needed

_PHASE_DOMAIN_MAP: dict[MarketPhase, list[CalculationDomain]] = {
    MarketPhase.PRE_OPEN: [
        CalculationDomain.SMC,
        CalculationDomain.ICT,
    ],
    MarketPhase.OPEN: [
        CalculationDomain.SMC,
        CalculationDomain.ICT,
        CalculationDomain.TECHNICAL,
        CalculationDomain.OPTIONS,
    ],
    MarketPhase.LUNCH: [
        CalculationDomain.SMC,
        CalculationDomain.ICT,
        CalculationDomain.TECHNICAL,
        CalculationDomain.OPTIONS,
    ],
    MarketPhase.CLOSING: [
        CalculationDomain.SMC,
        CalculationDomain.TECHNICAL,
    ],
    MarketPhase.POST_CLOSE: [],  # No calculations
}


# ── Domain → engine runner mapping ─────────────────────────────────────────
_DOMAIN_RUNNER_MAP: dict[CalculationDomain, Any] = {
    CalculationDomain.SMC: smc_run,
    CalculationDomain.ICT: ict_run,
    CalculationDomain.TECHNICAL: technical_run,
    CalculationDomain.OPTIONS: options_run,
}


# =============================================================================
# PUBLIC API
# =============================================================================


def route_to_domain(
    calc_input: CalculationInput,
    domain: CalculationDomain,
    config: F3Config | None = None,
) -> EngineRunReport:
    """Route a CalculationInput to a specific domain engine.

    Args:
        calc_input: The validated input data.
        domain: Target calculation domain.
        config: Optional F3Config. Uses defaults if None.

    Returns:
        The EngineRunReport from the domain engine.
    """
    runner = _DOMAIN_RUNNER_MAP.get(domain)
    if runner is None:
        return EngineRunReport(
            engine_name=f"unknown_{domain.value}",
            domain=domain,
            status=EngineStatus.ERROR,
            signals_generated=[],
            duration_ms=0.0,
            errors=[f"No engine registered for domain {domain.value}"],
        )

    return runner(calc_input, config)


def handle_calculation_cycle(
    calc_input: CalculationInput,
    config: F3Config | None = None,
) -> OutputContract:
    """Run a full Floor 3 calculation cycle.

    Determines which domain engines to activate based on the market phase,
    runs them with timeout protection, collects results, and builds the
    output contract.

    Args:
        calc_input: The validated CalculationInput with candle data.
        config: Optional F3Config. Uses defaults if None.

    Returns:
        An OutputContract containing all signals, engine reports, and
        the Floor3Summary.
    """
    cfg = config or F3Config()
    cycle_start = time.time()

    market_phase = calc_input.market_phase
    active_domains = _PHASE_DOMAIN_MAP.get(market_phase, [])

    if not active_domains:
        # POST_CLOSE or unknown phase — no calculations
        return OutputContract(
            signals=[],
            engine_reports=[],
            floor_summary=_build_empty_summary(calc_input, market_phase),
        )

    # Run each active domain engine with timeout protection
    timeout_ms = cfg.general.calculation_timeout_ms

    all_signals: list[CalculatedSignal] = []
    all_reports: list[EngineRunReport] = []
    domain_summaries: dict[str, Any] = {}

    for domain in active_domains:
        domain_start = time.time()
        try:
            report = _run_with_timeout(
                calc_input, domain, cfg, timeout_ms
            )
            elapsed = (time.time() - domain_start) * 1000
            all_reports.append(report)
            all_signals.extend(report.signals)
            domain_summaries[domain.value] = {
                "status": report.status.value,
                "signals_count": len(report.signals_generated),
                "duration_ms": report.duration_ms,
                "errors": report.errors,
            }
            logger.debug(
                "Domain engine complete",
                extra={
                    "domain": domain.value,
                    "signals": len(report.signals_generated),
                    "duration_ms": round(elapsed, 2),
                },
            )
        except Exception as exc:
            elapsed = (time.time() - domain_start) * 1000
            error_msg = f"Domain {domain.value} failed: {exc}"
            logger.warning(error_msg)
            all_reports.append(EngineRunReport(
                engine_name=f"{domain.value.lower()}_engine",
                domain=domain,
                status=EngineStatus.ERROR,
                signals_generated=[],
                duration_ms=round(elapsed, 2),
                errors=[error_msg],
            ))
            domain_summaries[domain.value] = {
                "status": "ERROR",
                "signals_count": 0,
                "duration_ms": round(elapsed, 2),
                "errors": [error_msg],
            }

    # Build Floor3Summary
    total_signals = len(all_signals)
    engine_statuses = {
        r.engine_name: r.status.value
        for r in all_reports
    }
    all_errors = [e for r in all_reports for e in r.errors]
    data_health = _compute_data_health(all_errors)

    floor_summary = Floor3Summary(
        domain_summaries=domain_summaries,
        signals_count=total_signals,
        engine_statuses=engine_statuses,
        data_health=data_health,
    )

    cycle_duration = (time.time() - cycle_start) * 1000
    logger.info(
        "Calculation cycle complete",
        extra={
            "market_phase": market_phase.value,
            "domains": len(active_domains),
            "total_signals": total_signals,
            "duration_ms": round(cycle_duration, 2),
            "data_health": data_health.value,
        },
    )

    return OutputContract(
        signals=all_signals,
        engine_reports=all_reports,
        floor_summary=floor_summary,
    )


# =============================================================================
# INTERNAL
# =============================================================================


def _run_with_timeout(
    calc_input: CalculationInput,
    domain: CalculationDomain,
    config: F3Config,
    timeout_ms: int,
) -> EngineRunReport:
    """Run a domain engine with a simple timeout guard.

    Args:
        calc_input: Input data for the engine.
        domain: Which domain engine to run.
        config: F3Config with all parameters.
        timeout_ms: Maximum allowed time in milliseconds.

    Returns:
        The EngineRunReport from the engine, or an ERROR report if
        the engine times out.
    """
    runner = _DOMAIN_RUNNER_MAP.get(domain)
    if runner is None:
        return EngineRunReport(
            engine_name=f"{domain.value.lower()}_engine",
            domain=domain,
            status=EngineStatus.ERROR,
            signals_generated=[],
            duration_ms=0.0,
            errors=[f"No engine registered for domain {domain.value}"],
        )

    start = time.time()
    report = runner(calc_input, config)
    elapsed = (time.time() - start) * 1000

    if elapsed > timeout_ms:
        logger.warning(
            "Engine timeout",
            extra={
                "domain": domain.value,
                "elapsed_ms": round(elapsed, 2),
                "timeout_ms": timeout_ms,
            },
        )
        return EngineRunReport(
            engine_name=report.engine_name,
            domain=domain,
            status=EngineStatus.ERROR,
            signals_generated=report.signals_generated,
            duration_ms=round(elapsed, 2),
            errors=report.errors + [f"Engine exceeded timeout ({elapsed:.0f}ms > {timeout_ms}ms)"],
        )

    return report



def _build_empty_summary(
    calc_input: CalculationInput,
    market_phase: MarketPhase,
) -> Floor3Summary:
    """Build an empty Floor3Summary for phases with no calculations.

    Args:
        calc_input: The original input (for basic metadata).
        market_phase: The current market phase.

    Returns:
        A Floor3Summary with zero signals and GOOD data health.
    """
    return Floor3Summary(
        domain_summaries={
            "reason": f"No active domains for market phase {market_phase.value}",
        },
        signals_count=0,
        engine_statuses={},
        data_health=DataHealth.GOOD,
    )


def _compute_data_health(errors: list[str]) -> DataHealth:
    """Compute aggregate data health from engine errors.

    Args:
        errors: List of all error messages across all engines.

    Returns:
        DataHealth.GOOD if no errors, DataHealth.CAUTION if errors exist.
    """
    if errors:
        return DataHealth.CAUTION
    return DataHealth.GOOD
