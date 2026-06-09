"""Floor 2 Metadata — quality fact builder.

Builds ``QualityFacts`` dataclasses from validation results, cleaning
results, and source health information.

**ALLOWED** facts:
- ``packet_completeness = 96%`` — how complete the data is.
- ``validation_confidence = 0.95`` — proportion of validators that passed.
- ``continuity_status = GOOD`` — current continuity of the data stream.
- ``source_health_state = HEALTHY`` — source connection health.

**FORBIDDEN** facts:
- ``this feed is good for trading`` — never.
- ``this setup looks strong`` — belongs to Floor 3+.
- ``the market is bullish`` — belongs to Floor 4+.

Architecture rules:
- ALL facts are DESCRIPTIVE, never prescriptive.
- ``validation_confidence`` describes process confidence, not market
  confidence.
- If no validation/cleaning data is available, defaults are used with
  reduced confidence.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AggregateValidation,
    CleaningResult,
    ContinuityStatus,
    QualityFacts,
    ValidationDecision,
)


def build_quality_facts(
    aggregate_validation: AggregateValidation | None = None,
    cleaning_result: CleaningResult | None = None,
    source_health_state: str = "HEALTHY",
) -> QualityFacts:
    """Build ``QualityFacts`` from available pipeline results.

    Args:
        aggregate_validation: The result from ``ValidationRouter.validate()``.
            If ``None``, validation confidence defaults to 0.5 (not validated).
        cleaning_result: The result from a cleaner or anomaly repair.
            If ``None``, no cleaning-specific facts are included.
        source_health_state: Current source health string
            (e.g., ``\"HEALTHY\"``, ``\"DEGRADED\"``).

    Returns:
        A ``QualityFacts`` instance with all fields populated.
    """
    # ── validation_confidence ──────────────────────────────────────────
    if aggregate_validation is not None:
        validation_confidence = aggregate_validation.validation_confidence
    else:
        validation_confidence = 0.5  # Not yet validated

    # ── raw_trust_level ────────────────────────────────────────────────
    # Based on whether validation passed and whether cleaning removed data
    raw_trust_level = _compute_raw_trust_level(
        aggregate_validation, cleaning_result,
    )

    # ── packet_completeness ────────────────────────────────────────────
    packet_completeness = _compute_packet_completeness(cleaning_result)

    # ── continuity_status ──────────────────────────────────────────────
    continuity_status = ContinuityStatus.GOOD
    if aggregate_validation:
        for result in aggregate_validation.results:
            if result.validator_name == "continuity":
                status_str = result.details.get("continuity_status")
                if status_str:
                    try:
                        continuity_status = ContinuityStatus(status_str)
                    except (ValueError, TypeError):
                        pass
                break

    return QualityFacts(
        raw_trust_level=raw_trust_level,
        validation_confidence=validation_confidence,
        packet_completeness=packet_completeness,
        continuity_status=continuity_status,
        source_health_state=source_health_state,
    )


def _compute_raw_trust_level(
    aggregate_validation: AggregateValidation | None,
    cleaning_result: CleaningResult | None,
) -> float:
    """Compute raw_trust_level (0.0-1.0) from available data.

    - Starts at 1.0 (fully trusted).
    - Reduced by 0.3 if validation failed (FAIL decision).
    - Reduced by 0.1 if validation flagged (FLAG decision).
    - Reduced by 0.1 if cleaning removed data.
    - Reduced by 0.05 if cleaning repaired data.
    """
    trust = 1.0

    if aggregate_validation:
        if aggregate_validation.decision == ValidationDecision.FAIL:
            trust -= 0.3
        elif aggregate_validation.decision == ValidationDecision.FLAG:
            trust -= 0.1

    if cleaning_result:
        if cleaning_result.removed:
            trust -= 0.1
        if cleaning_result.repaired:
            trust -= 0.05

    return max(0.0, round(trust, 2))


def _compute_packet_completeness(
    cleaning_result: CleaningResult | None,
) -> float:
    """Compute packet_completeness (0.0-1.0) from cleaning result.

    - If no cleaning data, completeness defaults to 0.8 (moderate trust).
    - If cleaning removed the packet, completeness = 0.0.
    - If cleaning repaired data, completeness reduced proportionally to
      number of anomaly flags.
    - If no anomalies, completeness = 1.0.
    """
    if cleaning_result is None:
        return 0.8

    if cleaning_result.removed:
        return 0.0

    total_anomalies = len(cleaning_result.anomaly_flags)
    if total_anomalies == 0:
        return 1.0

    # Each anomaly reduces completeness by 0.15, minimum 0.1
    completeness = max(0.1, 1.0 - (total_anomalies * 0.15))
    return round(completeness, 2)
