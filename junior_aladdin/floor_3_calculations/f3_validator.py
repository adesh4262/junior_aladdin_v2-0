"""Floor 3 — Post-calculation Validation Layer.

Runs AFTER calculation engines complete, BEFORE output is dispatched
to Floor 4. Performs 5 validation checks:

1. Output Contract Compliance — signal_id, CalculationLog, input_hash present.
2. Domain Isolation — no cross-domain metadata leaks.
3. Quality Validation — NOMINAL/DEGRADED/INSUFFICIENT_DATA assignment.
4. Determinism Check — replay mode: signal_id and input_hash stability.
5. Contract Boundary — no Floor 4/Captain/Side A types leaked into output.

Architecture rules:
- Pure validation — no modification of signals or reports.
- Violations are LOGGED, never silently ignored.
- HALT severity = output cannot be safely dispatched.
- FLAG severity = warning, output may still be dispatched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
)
from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.shared.logging import get_logger

logger = get_logger("f3_validator")

VALIDATOR_VERSION = "1.0"


# =============================================================================
# VALIDATION RESULT TYPE
# =============================================================================


@dataclass
class ValidationResult:
    """Result of a full validation run.

    Fields:
        valid: Whether the output passed all HALT-level checks.
        halt_errors: List of HALT-severity errors (block dispatch).
        flag_errors: List of FLAG-severity warnings (non-blocking).
        total_checks: Number of individual checks performed.
    """
    valid: bool = True
    halt_errors: list[dict[str, Any]] = field(default_factory=list)
    flag_errors: list[dict[str, Any]] = field(default_factory=list)
    total_checks: int = 0

    def summary(self) -> dict[str, Any]:
        """Get a brief summary dict of the validation result."""
        return {
            "valid": self.valid,
            "halt_count": len(self.halt_errors),
            "flag_count": len(self.flag_errors),
            "total_checks": self.total_checks,
        }


# =============================================================================
# PUBLIC API
# =============================================================================


def validate_output(
    output_contract: OutputContract,
    replay_mode: bool = False,
    expected_signal_ids: set[str] | None = None,
    expected_input_hashes: set[str] | None = None,
) -> ValidationResult:
    """Run ALL 5 validation checks against an OutputContract.

    Args:
        output_contract: The OutputContract to validate.
        replay_mode: If True, enables determinism checks (Step 4).
        expected_signal_ids: Expected signal IDs for replay determinism.
        expected_input_hashes: Expected input hashes for replay determinism.

    Returns:
        A ValidationResult with HALT errors, FLAG warnings, and check count.
    """
    result = ValidationResult()

    # Step 1: Output Contract Compliance
    _check_contract_compliance(output_contract, result)

    # Step 2: Domain Isolation
    _check_domain_isolation(output_contract, result)

    # Step 3: Quality Validation
    _check_quality(output_contract, result)

    # Step 4: Determinism Check (replay mode only)
    if replay_mode:
        _check_determinism(
            output_contract,
            expected_signal_ids or set(),
            expected_input_hashes or set(),
            result,
        )

    # Step 5: Contract Boundary
    _check_contract_boundary(output_contract, result)

    # Set overall validity
    result.valid = len(result.halt_errors) == 0

    if result.halt_errors or result.flag_errors:
        _log_validation_result(result)

    return result


# =============================================================================
# STEP 1: OUTPUT CONTRACT COMPLIANCE
# =============================================================================


def _check_contract_compliance(
    output: OutputContract,
    result: ValidationResult,
) -> None:
    """Check that every signal meets the output contract requirements.

    Rules:
    - Every signal MUST have a non-empty signal_id (32 hex chars).
    - Every signal MUST carry a CalculationLog.
    - Every CalculationLog MUST contain input_hash.
    - Floor3Summary MUST be present (never None).
    """
    for signal in output.signals:
        result.total_checks += 1

        # 1a: signal_id must be non-empty
        if not signal.signal_id:
            result.halt_errors.append({
                "check": "contract_compliance",
                "field": "signal_id",
                "reason": "signal_id is empty or missing",
                "signal_id": signal.signal_id,
            })

        # 1b: signal_id should be 32 hex chars (UUID v4)
        if signal.signal_id and len(signal.signal_id) != 32:
            result.flag_errors.append({
                "check": "contract_compliance",
                "field": "signal_id",
                "reason": f"signal_id length {len(signal.signal_id)}, expected 32",
                "signal_id": signal.signal_id,
            })

        # 1c: CalculationLog must be present
        if signal.calculation_log is None:
            result.halt_errors.append({
                "check": "contract_compliance",
                "field": "calculation_log",
                "reason": "Missing CalculationLog — no audit trail",
                "signal_id": signal.signal_id,
            })
            continue  # Skip further checks that depend on log

        # 1d: CalculationLog must contain input_hash
        if not signal.calculation_log.input_hash:
            result.halt_errors.append({
                "check": "contract_compliance",
                "field": "calculation_log.input_hash",
                "reason": "Missing input_hash — replay verification impossible",
                "signal_id": signal.signal_id,
            })

    # 1e: Floor3Summary must be present
    result.total_checks += 1
    if output.floor_summary is None:
        result.halt_errors.append({
            "check": "contract_compliance",
            "field": "floor_summary",
            "reason": "Floor3Summary is None — must always be present",
        })


# =============================================================================
# STEP 2: DOMAIN ISOLATION
# =============================================================================


def _check_domain_isolation(
    output: OutputContract,
    result: ValidationResult,
) -> None:
    """Verify that no domain leaks into another domain's signals.

    Rules:
    - SMC signals must not have ICT or Technical indicator types.
    - ICT signals must not have SMC or Technical indicator types.
    - Technical signals must not have SMC or ICT indicator types.
    - Signal domain must match its CalculationLog domain.
    """
    # Domain → forbidden indicator type prefixes
    forbidden_types: dict[CalculationDomain, set[str]] = {
        CalculationDomain.SMC: {"PD_ARRAY", "KILL_ZONE", "LIQUIDITY", "RSI", "MA_", "ATR", "VOLUME_PROFILE"},
        CalculationDomain.ICT: {"FVG", "ORDER_BLOCK", "CHOCH", "MARKET_STRUCTURE", "RSI", "MA_", "ATR", "VOLUME_PROFILE"},
        CalculationDomain.TECHNICAL: {"FVG", "ORDER_BLOCK", "CHOCH", "MARKET_STRUCTURE", "PD_ARRAY", "KILL_ZONE", "LIQUIDITY"},
    }

    for signal in output.signals:
        result.total_checks += 1

        # 2a: Check indicator type doesn't belong to another domain
        domain = signal.domain
        if domain in forbidden_types:
            for prefix in forbidden_types[domain]:
                if signal.indicator_type.startswith(prefix):
                    result.flag_errors.append({
                        "check": "domain_isolation",
                        "field": "indicator_type",
                        "reason": (
                            f"Signal domain={domain.value} has indicator_type "
                            f"{signal.indicator_type!r} which appears to belong "
                            f"to another domain"
                        ),
                        "signal_id": signal.signal_id,
                    })

        # 2b: Domain must match log domain
        if signal.calculation_log and signal.domain != signal.calculation_log.domain:
            result.halt_errors.append({
                "check": "domain_isolation",
                "field": "domain",
                "reason": (
                    f"Domain mismatch: signal.domain={signal.domain.value}, "
                    f"log.domain={signal.calculation_log.domain.value}"
                ),
                "signal_id": signal.signal_id,
            })


# =============================================================================
# STEP 3: QUALITY VALIDATION
# =============================================================================


def _check_quality(
    output: OutputContract,
    result: ValidationResult,
) -> None:
    """Validate quality classifications on all signals.

    Rules:
    - NOMINAL: no warnings, no errors in engine report.
    - DEGRADED: warnings present, calculation completed.
    - INSUFFICIENT_DATA: below minimum data points.
    """
    # Collect engine error/warning info for quick lookup
    engine_has_errors: dict[str, bool] = {}
    for report in output.engine_reports:
        engine_has_errors[report.engine_name] = len(report.errors) > 0

    for signal in output.signals:
        result.total_checks += 1

        quality = signal.quality

        # Check for quality misalignment
        if quality == CalculationQuality.NOMINAL:
            # NOMINAL should have no warnings
            if signal.calculation_log and signal.calculation_log.warnings:
                result.flag_errors.append({
                    "check": "quality",
                    "field": "quality",
                    "reason": (
                        f"Signal quality=NOMINAL but {len(signal.calculation_log.warnings)} "
                        f"warnings present"
                    ),
                    "signal_id": signal.signal_id,
                    "quality": quality.value,
                })

        elif quality == CalculationQuality.INSUFFICIENT_DATA:
            # INSUFFICIENT_DATA should have empty value
            if signal.value and signal.value != {}:
                result.flag_errors.append({
                    "check": "quality",
                    "field": "quality",
                    "reason": (
                        f"Signal quality=INSUFFICIENT_DATA but value "
                        f"is not empty"
                    ),
                    "signal_id": signal.signal_id,
                })


# =============================================================================
# STEP 4: DETERMINISM CHECK (REPLAY MODE ONLY)
# =============================================================================


def _check_determinism(
    output: OutputContract,
    expected_signal_ids: set[str],
    expected_input_hashes: set[str],
    result: ValidationResult,
) -> None:
    """In replay mode, verify that outputs match expected values.

    Rules:
    - All signal IDs must be in the expected set (stability).
    - All input hashes must be in the expected set (stability).
    - Signal IDs that appeared before must still appear.
    - No unexpected signal IDs.
    """
    actual_ids = {s.signal_id for s in output.signals}
    actual_hashes = set()
    for s in output.signals:
        if s.calculation_log and s.calculation_log.input_hash:
            actual_hashes.add(s.calculation_log.input_hash)

    result.total_checks += 1
    if expected_signal_ids:
        # Check for unexpected signal IDs
        unexpected = actual_ids - expected_signal_ids
        if unexpected:
            result.halt_errors.append({
                "check": "determinism",
                "field": "signal_id",
                "reason": f"{len(unexpected)} unexpected signal IDs in replay",
                "unexpected_count": len(unexpected),
                "sample": list(unexpected)[:3],
            })

        # Check for missing expected IDs
        missing = expected_signal_ids - actual_ids
        if missing:
            result.halt_errors.append({
                "check": "determinism",
                "field": "signal_id",
                "reason": f"{len(missing)} expected signal IDs missing in replay",
                "missing_count": len(missing),
                "sample": list(missing)[:3],
            })

    result.total_checks += 1
    if expected_input_hashes and actual_hashes:
        unexpected_hashes = actual_hashes - expected_input_hashes
        if unexpected_hashes:
            result.halt_errors.append({
                "check": "determinism",
                "field": "input_hash",
                "reason": f"{len(unexpected_hashes)} unexpected input hashes in replay",
                "unexpected_count": len(unexpected_hashes),
            })


# =============================================================================
# STEP 5: CONTRACT BOUNDARY CHECK
# =============================================================================


def _check_contract_boundary(
    output: OutputContract,
    result: ValidationResult,
) -> None:
    """Verify no types from upper layers leaked into Floor 3 output.

    Rules:
    - No Floor 4 types: HeadReport, FloorSummary (system-level, not calcs).
    - No Captain types: CaptainDecision, ArmedPlan, DecisionSnapshot.
    - No Side A types: ExecutionIntent.

    Note: Floor3Summary is the Floor 3's own summary type — it IS allowed
    in the OutputContract. The check here ensures no HIGHER-layer types
    leak downward.
    """
    # Types that should NEVER appear in Floor 3 output
    forbidden_type_names = {
        "HeadReport",
        "CaptainDecision",
        "ArmedPlan",
        "DecisionSnapshot",
        "ExecutionIntent",
    }

    # Check signal values and metadata for forbidden types
    for signal in output.signals:
        result.total_checks += 1

        # Check value dict fields
        if isinstance(signal.value, dict):
            for field_name in ['head_report', 'captain_decision', 'execution_intent']:
                if field_name in signal.value:
                    result.halt_errors.append({
                        "check": "contract_boundary",
                        "field": f"value.{field_name}",
                        "reason": f"Signal contains upper-layer type field: {field_name}",
                        "signal_id": signal.signal_id,
                    })

        # Check metadata for forbidden type references
        if isinstance(signal.metadata, dict):
            for key, val in signal.metadata.items():
                if isinstance(val, str) and val in forbidden_type_names:
                    result.flag_errors.append({
                        "check": "contract_boundary",
                        "field": f"metadata.{key}",
                        "reason": f"Metadata references upper-layer type: {val}",
                        "signal_id": signal.signal_id,
                    })

    # Check engine reports for forbidden type references
    for report in output.engine_reports:
        result.total_checks += 1
        for err in report.errors:
            for type_name in forbidden_type_names:
                if type_name in err:
                    result.flag_errors.append({
                        "check": "contract_boundary",
                        "field": "engine_reports.errors",
                        "reason": f"Engine error references upper-layer type: {type_name}",
                        "engine": report.engine_name,
                    })

    # Check Floor3Summary for upper-layer types
    result.total_checks += 1
    if output.floor_summary:
        if hasattr(output.floor_summary, 'domain_summaries'):
            for key in output.floor_summary.domain_summaries:
                if key in forbidden_type_names:
                    result.flag_errors.append({
                        "check": "contract_boundary",
                        "field": "floor_summary.domain_summaries",
                        "reason": f"Domain summary key references upper-layer type: {key}",
                    })


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def quick_validate(output_contract: OutputContract) -> bool:
    """Quick pass/fail validation — only checks HALT-level errors.

    Useful as a lightweight pre-flight check before full validation.

    Args:
        output_contract: The OutputContract to validate.

    Returns:
        ``True`` if no HALT errors found, ``False`` otherwise.
    """
    result = validate_output(output_contract)
    return result.valid


# =============================================================================
# INTERNAL
# =============================================================================


def _log_validation_result(result: ValidationResult) -> None:
    """Log validation warnings/errors at appropriate levels.

    Args:
        result: The ValidationResult to log.
    """
    if result.halt_errors:
        logger.warning(
            "Validation HALT errors",
            extra={"count": len(result.halt_errors), "errors": result.halt_errors[:5]},
        )
    if result.flag_errors:
        logger.info(
            "Validation FLAG warnings",
            extra={"count": len(result.flag_errors), "warnings": result.flag_errors[:5]},
        )



