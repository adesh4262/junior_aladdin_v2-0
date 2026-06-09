"""Floor 3 — Output Builder.

Packs raw calculation results into the OutputContract format for Floor 4
consumption. Provides standalone utility functions for signal packaging,
calculation log construction, and Floor3Summary building.

Can be used independently:
- Directly by the orchestrator during normal cycles.
- Standalone for tests, replays, or debugging.
- By future engines that need to produce OutputContract-compatible output.

Architecture rules:
- Every output MUST have unique signal_id.
- signal_id is immutable — never changes after creation.
- calculation_log.input_hash must match input data hash.
- Empty signal list is valid (not an error).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    CalculationLog,
    CalculationQuality,
    EngineRunReport,
    EngineStatus,
    Floor3Summary,
    DataHealth,
    generate_signal_id,
)
from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.shared.logging import get_logger

logger = get_logger("f3_output_builder")

ENGINE_VERSION = "1.0"


# =============================================================================
# PUBLIC API
# =============================================================================


def build_output(
    signals: list[CalculatedSignal],
    engine_reports: list[EngineRunReport],
    domain_summaries: dict[str, Any] | None = None,
) -> OutputContract:
    """Build a complete OutputContract from engine outputs.

    Convenience wrapper that constructs the Floor3Summary and wraps
    everything into an OutputContract.

    Args:
        signals: All CalculatedSignal objects from all engines.
        engine_reports: All EngineRunReport objects from all engines.
        domain_summaries: Optional pre-built domain summaries.
            If None, built automatically from engine_reports.

    Returns:
        A fully formed OutputContract ready for validation and dispatch.
    """
    if domain_summaries is None:
        domain_summaries = _build_domain_summaries(engine_reports)

    floor_summary = build_floor3_summary(
        signals=signals,
        engine_reports=engine_reports,
        domain_summaries=domain_summaries,
    )

    return OutputContract(
        signals=signals,
        engine_reports=engine_reports,
        floor_summary=floor_summary,
    )


def pack_signal(
    domain: CalculationDomain,
    indicator_type: str,
    value: Any,
    timestamp: datetime | None = None,
    input_hash: str = "",
    metadata: dict[str, Any] | None = None,
    quality: CalculationQuality = CalculationQuality.NOMINAL,
    warnings: list[str] | None = None,
    signal_id: str | None = None,
) -> CalculatedSignal:
    """Create a fully formed CalculatedSignal with proper audit trail.

    Generates a signal_id (UUID v4) unless one is provided (immutable).
    Builds the CalculationLog with engine version and input_hash.

    Args:
        domain: The calculation domain that produced this signal.
        indicator_type: Specific indicator/pattern type (e.g., ``\"RSI\"``).
        value: The calculated value dict.
        timestamp: When the signal was calculated. Uses current time if None.
        input_hash: Hash of the input data (for replay verification).
        metadata: Optional additional context (symbol, market phase, etc.).
        quality: Quality classification. Default NOMINAL.
        warnings: Any warnings from this signal's calculation.
        signal_id: Optional pre-generated signal ID. If None, a new UUID v4
            is generated. Once set, the ID is immutable.

    Returns:
        A fully formed CalculatedSignal.
    """
    sid = signal_id or generate_signal_id()
    cal_log = build_calculation_log(
        signal_id=sid,
        domain=domain,
        input_hash=input_hash,
        steps=[{"step": indicator_type, "status": "COMPLETE"}],
        warnings=warnings or [],
    )

    return CalculatedSignal(
        signal_id=sid,
        domain=domain,
        indicator_type=indicator_type,
        value=value,
        timestamp=timestamp or datetime.min,
        quality=quality,
        metadata=metadata or {},
        calculation_log=cal_log,
    )


def build_calculation_log(
    signal_id: str,
    domain: CalculationDomain,
    input_hash: str = "",
    parameters_used: list[dict[str, Any]] | None = None,
    steps: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> CalculationLog:
    """Build a CalculationLog with full provenance data.

    Args:
        signal_id: The signal_id this log belongs to.
        domain: The domain that produced the signal.
        input_hash: Hash of the input data for replay verification.
        parameters_used: List of parameter sets used during calculation.
        steps: Ordered list of calculation steps.
        warnings: Any warnings generated during calculation.

    Returns:
        A fully formed CalculationLog.
    """
    return CalculationLog(
        signal_id=signal_id,
        domain=domain,
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        parameters_used=parameters_used or [],
        calculation_steps=steps or [],
        warnings=warnings or [],
    )


def build_floor3_summary(
    signals: list[CalculatedSignal],
    engine_reports: list[EngineRunReport],
    domain_summaries: dict[str, Any] | None = None,
) -> Floor3Summary:
    """Build an aggregate Floor3Summary from engine outputs.

    Args:
        signals: All CalculatedSignal objects from this cycle.
        engine_reports: All EngineRunReport objects from this cycle.
        domain_summaries: Optional per-domain summary data.
            If None, built automatically from engine_reports.

    Returns:
        A Floor3Summary with aggregated stats and data health.
    """
    if domain_summaries is None:
        domain_summaries = _build_domain_summaries(engine_reports)

    # Count signals per domain
    domain_signal_counts: dict[str, int] = {}
    for s in signals:
        domain_signal_counts[s.domain.value] = domain_signal_counts.get(s.domain.value, 0) + 1

    # Aggregate engine statuses
    engine_statuses = {
        r.engine_name: r.status.value
        for r in engine_reports
    }

    # Compute data health
    all_errors = [e for r in engine_reports for e in r.errors]
    data_health = _compute_data_health(all_errors)

    return Floor3Summary(
        domain_summaries={
            **domain_summaries,
            "signal_counts_by_domain": domain_signal_counts,
        },
        signals_count=len(signals),
        engine_statuses=engine_statuses,
        data_health=data_health,
    )


def build_domain_summary(
    report: EngineRunReport,
) -> dict[str, Any]:
    """Build a single domain summary dict from an engine report.

    Args:
        report: The EngineRunReport from a domain engine.

    Returns:
        A dict with status, signals count, duration, and errors.
    """
    return {
        "status": report.status.value,
        "signals_count": len(report.signals_generated),
        "duration_ms": report.duration_ms,
        "errors": report.errors,
    }


# =============================================================================
# INTERNAL
# =============================================================================


def _build_domain_summaries(
    reports: list[EngineRunReport],
) -> dict[str, Any]:
    """Build domain summaries dict from a list of engine reports.

    Args:
        reports: List of EngineRunReport objects.

    Returns:
        Dict mapping domain names to their summary dicts.
    """
    summaries: dict[str, Any] = {}
    for report in reports:
        summaries[report.domain.value] = build_domain_summary(report)
    return summaries


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
