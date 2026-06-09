"""Floor 4 — Head Report Schema & Contract Validation.

Defines the standard report contract that ALL Department Heads must follow.
``ReportValidator`` enforces architecture-locked rules at runtime.

Contract rules (LOCKED, enforced via HALT rejection):
1. **Invalidation mandatory** — Every Head must provide invalidation.
   - If missing or empty dict → HALT, report not forwarded to Captain.
2. **SMC/ICT context_quality_score mandatory** — Must be a float (0.0–1.0).
   - If missing or None → HALT.
3. **Macro/Psychology NO setups** — primary_setup AND backup_setup must be None.
   - If either is not None → HALT (locked rule violation).
4. **HeadState must be valid** — Must be READY / UNCERTAIN / STALE.
   - If undefined → HALT.

Usage::

    validator = ReportValidator()
    report = smc_head.refresh(output_contract)
    result = validator.validate(report)
    if not result.valid:
        logger.error(f"Report rejected: {result.reasons}")
        # Do NOT forward to Captain
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.types import HeadReport, HeadState

logger = get_logger("head_report_schema")

# ── Head name constants ─────────────────────────────────────────────────────

HEAD_SMC = "SMC Head"
HEAD_ICT = "ICT Head"
HEAD_TECHNICAL = "Technical Head"
HEAD_OPTIONS = "Options Head"
HEAD_MACRO = "Macro Head"
HEAD_PSYCHOLOGY = "Psychology Head"

# Heads that REQUIRE context_quality_score
_CONTEXT_QUALITY_HEADS = {HEAD_SMC, HEAD_ICT}

# Heads that are LOCKED to NO setups
_NO_SETUP_HEADS = {HEAD_MACRO, HEAD_PSYCHOLOGY}

# All recognised head names
_ALL_HEADS = {
    HEAD_SMC, HEAD_ICT, HEAD_TECHNICAL,
    HEAD_OPTIONS, HEAD_MACRO, HEAD_PSYCHOLOGY,
}


# =============================================================================
# Validation Result
# =============================================================================


@dataclass
class ReportValidationResult:
    """Result of a HeadReport contract validation.

    Fields:
        valid: Whether the report passed all contract checks.
        reasons: Human-readable list of reasons if validation failed.
        field_errors: Dict mapping field names to specific error messages.
    """
    valid: bool = True
    reasons: list[str] = field(default_factory=list)
    field_errors: dict[str, str] = field(default_factory=dict)

    def fail(self, reason: str, field: str = "") -> None:
        """Mark this validation as failed with a reason."""
        self.valid = False
        self.reasons.append(reason)
        if field:
            self.field_errors[field] = reason


# =============================================================================
# Report Validator
# =============================================================================


class ReportValidator:
    """Validates HeadReports against the standard contract.

    Enforces the 4 locked architecture rules:
    1. invalidation mandatory (never None/empty)
    2. SMC/ICT → context_quality_score mandatory
    3. Macro/Psychology → primary_setup must be None
    4. Macro/Psychology → backup_setup must be None

    Also validates:
    - head_name is recognised
    - state is a valid HeadState enum member
    - bias, confidence, freshness fields are present

    Example::

        validator = ReportValidator()
        result = validator.validate(report)
        if not result.valid:
            print(f"Contract violation: {result.reasons}")
    """

    def validate(self, report: HeadReport) -> ReportValidationResult:
        """Validate a HeadReport against the standard contract.

        Args:
            report: The HeadReport to validate.

        Returns:
            A ``ReportValidationResult`` with ``.valid`` and ``.reasons``.
        """
        result = ReportValidationResult()

        # ── Rule 0: Recognised head_name ─────────────────────────────
        if report.head_name not in _ALL_HEADS:
            result.fail(
                f"Unknown head_name '{report.head_name}'. "
                f"Must be one of {sorted(_ALL_HEADS)}.",
                field="head_name",
            )
            # If head_name is unknown, skip further checks
            return result

        # ── Rule 1: Invalidation mandatory ───────────────────────────
        if not report.invalidation:
            result.fail(
                f"{report.head_name}: invalidation is empty or missing. "
                "Every Head must produce invalidation.",
                field="invalidation",
            )
        elif not isinstance(report.invalidation, dict):
            result.fail(
                f"{report.head_name}: invalidation must be a dict, "
                f"got {type(report.invalidation).__name__}.",
                field="invalidation",
            )
        elif not report.invalidation.get("rules"):
            result.fail(
                f"{report.head_name}: invalidation.rules is empty. "
                "At least one invalidation rule is required.",
                field="invalidation",
            )

        # ── Rule 2: SMC/ICT context_quality_score mandatory ──────────
        if report.head_name in _CONTEXT_QUALITY_HEADS:
            if report.context_quality_score is None:
                result.fail(
                    f"{report.head_name}: context_quality_score is required "
                    "but is None. SMC/ICT must always provide this field.",
                    field="context_quality_score",
                )
            elif not isinstance(report.context_quality_score, (int, float)):
                result.fail(
                    f"{report.head_name}: context_quality_score must be a "
                    f"numeric value, got {type(report.context_quality_score).__name__}.",
                    field="context_quality_score",
                )
            elif not (0.0 <= report.context_quality_score <= 1.0):
                result.fail(
                    f"{report.head_name}: context_quality_score must be "
                    f"between 0.0 and 1.0, got {report.context_quality_score}.",
                    field="context_quality_score",
                )

        # ── Rules 3 & 4: Macro/Psychology NO setups ──────────────────
        if report.head_name in _NO_SETUP_HEADS:
            if report.primary_setup is not None:
                result.fail(
                    f"{report.head_name}: primary_setup must be None "
                    f"(locked rule), got '{report.primary_setup}'.",
                    field="primary_setup",
                )
            if report.backup_setup is not None:
                result.fail(
                    f"{report.head_name}: backup_setup must be None "
                    f"(locked rule), got '{report.backup_setup}'.",
                    field="backup_setup",
                )

        # ── Rule 5: State must be valid ──────────────────────────────
        if not isinstance(report.state, HeadState):
            try:
                HeadState(report.state)
            except (ValueError, TypeError):
                result.fail(
                    f"{report.head_name}: state must be a valid HeadState "
                    f"(READY/UNCERTAIN/STALE), got '{report.state}'.",
                    field="state",
                )

        # ── Rule 6: Freshness fields present ─────────────────────────
        if not (0.0 <= report.freshness_score <= 1.0):
            result.fail(
                f"{report.head_name}: freshness_score must be 0.0–1.0, "
                f"got {report.freshness_score}.",
                field="freshness_score",
            )

        # ── Rule 7: Confidence must be 0.0–1.0 ──────────────────────
        if not (0.0 <= report.confidence <= 1.0):
            result.fail(
                f"{report.head_name}: confidence must be 0.0–1.0, "
                f"got {report.confidence}.",
                field="confidence",
            )

        # ── Log result ───────────────────────────────────────────────
        if not result.valid:
            logger.warning(
                "Report contract violation",
                extra={
                    "head": report.head_name,
                    "reasons": result.reasons,
                    "field_errors": result.field_errors,
                },
            )

        return result


# =============================================================================
# Convenience function
# =============================================================================


def validate_report_contract(
    report: HeadReport,
    validator: ReportValidator | None = None,
) -> ReportValidationResult:
    """Validate a HeadReport against the standard contract (convenience wrapper).

    Args:
        report: The HeadReport to validate.
        validator: Optional ``ReportValidator`` instance. Creates one if None.

    Returns:
        A ``ReportValidationResult``.
    """
    if validator is None:
        validator = ReportValidator()
    return validator.validate(report)
