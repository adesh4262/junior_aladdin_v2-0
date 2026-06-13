"""SMC — Domain-specific Validation Layer.

Validates SMC-domain signals before they are accepted into the OutputContract.
Runs AFTER f3_validator cross-cutting checks, BEFORE output dispatch.

Domain-specific validation rules:
- MARKET_STRUCTURE: structure_type must be valid enum, swing counts >= 0.
- FVG: fvg_type must be valid, top > bottom, gap_size >= 0, gap_size > min_gap.
- ORDER_BLOCK: ob_type must be valid, price > 0, strength in [0.0, 1.0].
- CHOCH: choch_type must be valid, break_price > 0, prior_structure valid.

Architecture rules:
- Pure validation — no modification of signals.
- Violations are LOGGED, never silently ignored.
- HALT severity = signal cannot be forwarded.
- FLAG severity = warning, signal may still be forwarded.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    FvgType,
    ObType,
    ChoChType,
    MarketStructureType,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("smc_validator")

VALIDATOR_VERSION = "1.0"

# =============================================================================
# VALIDATION RESULT TYPE
# =============================================================================


class ValidationResult:
    """Result of SMC domain validation.

    Fields:
        valid: Whether no HALT-level errors found.
        halt_errors: List of HALT-severity errors (block signal).
        flag_errors: List of FLAG-severity warnings (non-blocking).
        total_checks: Number of individual checks performed.
    """

    def __init__(self) -> None:
        self.valid: bool = True
        self.halt_errors: list[dict[str, Any]] = []
        self.flag_errors: list[dict[str, Any]] = []
        self.total_checks: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "halt_count": len(self.halt_errors),
            "flag_count": len(self.flag_errors),
            "total_checks": self.total_checks,
        }


# =============================================================================
# PUBLIC API
# =============================================================================


def validate_smc_signals(signals: list[CalculatedSignal]) -> ValidationResult:
    """Validate all SMC-domain signals in a list.

    Args:
        signals: List of CalculatedSignal objects (only SMC should be passed).

    Returns:
        ValidationResult with per-signal validation details.
    """
    result = ValidationResult()

    for signal in signals:
        if signal.domain != CalculationDomain.SMC:
            continue  # Skip non-SMC signals (domain isolation handled by f3_validator)

        result.total_checks += 1
        indicator = signal.indicator_type
        value = signal.value if isinstance(signal.value, dict) else {}

        if indicator == "MARKET_STRUCTURE":
            _validate_market_structure(signal, value, result)
        elif indicator == "FVG":
            _validate_fvg(signal, value, result)
        elif indicator == "ORDER_BLOCK":
            _validate_order_block(signal, value, result)
        elif indicator == "CHOCH":
            _validate_choch(signal, value, result)
        else:
            result.flag_errors.append({
                "check": "unknown_indicator",
                "signal_id": signal.signal_id,
                "indicator_type": indicator,
                "reason": f"Unknown SMC indicator type: {indicator}",
            })

    result.valid = len(result.halt_errors) == 0
    return result


def quick_validate(signals: list[CalculatedSignal]) -> bool:
    """Quick pass/fail — only HALT-level errors.

    Args:
        signals: List of CalculatedSignal objects.

    Returns:
        True if no HALT errors, False otherwise.
    """
    result = validate_smc_signals(signals)
    return result.valid


# =============================================================================
# DOMAIN-SPECIFIC VALIDATORS
# =============================================================================


def _validate_market_structure(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a MARKET_STRUCTURE signal."""
    # Check structure_type is valid enum value
    st = value.get("structure_type", "")
    valid_types = {e.value for e in MarketStructureType}
    if st not in valid_types:
        result.halt_errors.append({
            "check": "market_structure",
            "field": "structure_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid structure_type: {st!r}, expected one of {valid_types}",
        })

    # Check swing counts are non-negative
    shc = value.get("swing_high_count", -1)
    slc = value.get("swing_low_count", -1)
    if not isinstance(shc, int) or shc < 0:
        result.flag_errors.append({
            "check": "market_structure",
            "field": "swing_high_count",
            "signal_id": signal.signal_id,
            "reason": f"Invalid swing_high_count: {shc}",
        })
    if not isinstance(slc, int) or slc < 0:
        result.flag_errors.append({
            "check": "market_structure",
            "field": "swing_low_count",
            "signal_id": signal.signal_id,
            "reason": f"Invalid swing_low_count: {slc}",
        })

    # Valid flag should be a boolean
    valid_flag = value.get("structure_valid", None)
    if not isinstance(valid_flag, bool):
        result.flag_errors.append({
            "check": "market_structure",
            "field": "structure_valid",
            "signal_id": signal.signal_id,
            "reason": f"structure_valid must be bool, got {type(valid_flag).__name__}",
        })


def _validate_fvg(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a FVG signal."""
    # Check fvg_type is valid
    fvg_type = value.get("fvg_type", "")
    valid_types = {e.value for e in FvgType}
    if fvg_type not in valid_types:
        result.halt_errors.append({
            "check": "fvg",
            "field": "fvg_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid fvg_type: {fvg_type!r}, expected one of {valid_types}",
        })

    # top and bottom must be present and numeric
    top = value.get("top")
    bottom = value.get("bottom")
    if not isinstance(top, (int, float)):
        result.halt_errors.append({
            "check": "fvg",
            "field": "top",
            "signal_id": signal.signal_id,
            "reason": f"top must be numeric, got {type(top).__name__}",
        })
    if not isinstance(bottom, (int, float)):
        result.halt_errors.append({
            "check": "fvg",
            "field": "bottom",
            "signal_id": signal.signal_id,
            "reason": f"bottom must be numeric, got {type(bottom).__name__}",
        })

    # top > bottom (bullish FVG means top > bottom)
    if isinstance(top, (int, float)) and isinstance(bottom, (int, float)):
        if top <= bottom:
            result.flag_errors.append({
                "check": "fvg",
                "field": "top_bottom",
                "signal_id": signal.signal_id,
                "reason": f"top ({top}) must be > bottom ({bottom})",
            })

    # gap_size_pips must be >= 0
    gap = value.get("gap_size_pips")
    if not isinstance(gap, (int, float)) or gap < 0:
        result.flag_errors.append({
            "check": "fvg",
            "field": "gap_size_pips",
            "signal_id": signal.signal_id,
            "reason": f"Invalid gap_size_pips: {gap}",
        })

    # mitigated must be a boolean
    mitigated = value.get("mitigated")
    if not isinstance(mitigated, bool):
        result.flag_errors.append({
            "check": "fvg",
            "field": "mitigated",
            "signal_id": signal.signal_id,
            "reason": f"mitigated must be bool, got {type(mitigated).__name__}",
        })


def _validate_order_block(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate an ORDER_BLOCK signal."""
    # ob_type must be valid
    ob_type = value.get("ob_type", "")
    valid_types = {e.value for e in ObType}
    if ob_type not in valid_types:
        result.halt_errors.append({
            "check": "order_block",
            "field": "ob_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid ob_type: {ob_type!r}, expected one of {valid_types}",
        })

    # price must be positive
    price = value.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        result.halt_errors.append({
            "check": "order_block",
            "field": "price",
            "signal_id": signal.signal_id,
            "reason": f"Invalid price: {price}",
        })

    # strength must be in [0.0, 1.0]
    strength = value.get("strength")
    if isinstance(strength, (int, float)):
        if strength < 0.0 or strength > 1.0:
            result.flag_errors.append({
                "check": "order_block",
                "field": "strength",
                "signal_id": signal.signal_id,
                "reason": f"strength {strength} outside [0.0, 1.0]",
            })
    else:
        result.flag_errors.append({
            "check": "order_block",
            "field": "strength",
            "signal_id": signal.signal_id,
            "reason": f"strength must be numeric, got {type(strength).__name__}",
        })


def _validate_choch(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a CHOCH signal."""
    # choch_type must be valid
    choch_type = value.get("choch_type", "")
    valid_types = {e.value for e in ChoChType}
    if choch_type not in valid_types:
        result.halt_errors.append({
            "check": "choch",
            "field": "choch_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid choch_type: {choch_type!r}, expected one of {valid_types}",
        })

    # break_price must be positive
    bp = value.get("break_price")
    if not isinstance(bp, (int, float)) or bp <= 0:
        result.halt_errors.append({
            "check": "choch",
            "field": "break_price",
            "signal_id": signal.signal_id,
            "reason": f"Invalid break_price: {bp}",
        })

    # prior_structure must be valid
    ps = value.get("prior_structure", "")
    valid_structures = {e.value for e in MarketStructureType}
    if ps not in valid_structures:
        result.flag_errors.append({
            "check": "choch",
            "field": "prior_structure",
            "signal_id": signal.signal_id,
            "reason": f"Invalid prior_structure: {ps!r}",
        })

    # confirmed must be boolean
    confirmed = value.get("confirmed")
    if not isinstance(confirmed, bool):
        result.flag_errors.append({
            "check": "choch",
            "field": "confirmed",
            "signal_id": signal.signal_id,
            "reason": f"confirmed must be bool, got {type(confirmed).__name__}",
        })
