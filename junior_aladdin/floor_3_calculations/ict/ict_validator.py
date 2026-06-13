"""ICT — Domain-specific Validation Layer.

Validates ICT-domain signals before they are accepted into the OutputContract.

Domain-specific validation rules:
- PD_ARRAY: pd_type must be valid enum, level > 0, strength in [0.0, 1.0].
- KILL_ZONE / NEXT_KILL_ZONE: kill_zone_type must be valid, time_remaining_s >= 0.
- LIQUIDITY: liquidity_type must be valid, price > 0, swept must be bool.
- LIQUIDITY_CONTEXT: context must be valid, counts >= 0.

Architecture rules:
- Pure validation — no modification of signals.
- Violations are LOGGED, never silently ignored.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
    PdArrayType,
    KillZoneType,
    LiquidityType,
)
VALIDATOR_VERSION = "1.0"


class ValidationResult:
    """Result of ICT domain validation."""

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


def validate_ict_signals(signals: list[CalculatedSignal]) -> ValidationResult:
    """Validate all ICT-domain signals in a list.

    Args:
        signals: List of CalculatedSignal objects (only ICT should be passed).

    Returns:
        ValidationResult with per-signal validation details.
    """
    result = ValidationResult()

    for signal in signals:
        if signal.domain != CalculationDomain.ICT:
            continue

        result.total_checks += 1
        indicator = signal.indicator_type
        value = signal.value if isinstance(signal.value, dict) else {}

        if indicator == "PD_ARRAY":
            _validate_pd_array(signal, value, result)
        elif indicator in ("KILL_ZONE", "NEXT_KILL_ZONE"):
            _validate_kill_zone(signal, value, indicator, result)
        elif indicator == "LIQUIDITY":
            _validate_liquidity(signal, value, result)
        elif indicator == "LIQUIDITY_CONTEXT":
            _validate_liquidity_context(signal, value, result)
        else:
            result.flag_errors.append({
                "check": "unknown_indicator",
                "signal_id": signal.signal_id,
                "indicator_type": indicator,
                "reason": f"Unknown ICT indicator type: {indicator}",
            })

    result.valid = len(result.halt_errors) == 0
    return result


def quick_validate(signals: list[CalculatedSignal]) -> bool:
    """Quick pass/fail — only HALT-level errors."""
    result = validate_ict_signals(signals)
    return result.valid


# =============================================================================
# DOMAIN-SPECIFIC VALIDATORS
# =============================================================================


def _validate_pd_array(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a PD_ARRAY signal."""
    pd_type = value.get("pd_type", "")
    valid_types = {e.value for e in PdArrayType}
    if pd_type not in valid_types:
        result.halt_errors.append({
            "check": "pd_array",
            "field": "pd_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid pd_type: {pd_type!r}, expected one of {valid_types}",
        })

    level = value.get("level")
    if not isinstance(level, (int, float)) or level <= 0:
        result.halt_errors.append({
            "check": "pd_array",
            "field": "level",
            "signal_id": signal.signal_id,
            "reason": f"Invalid level: {level}",
        })

    strength = value.get("strength")
    if isinstance(strength, (int, float)):
        if strength < 0.0 or strength > 1.0:
            result.flag_errors.append({
                "check": "pd_array",
                "field": "strength",
                "signal_id": signal.signal_id,
                "reason": f"strength {strength} outside [0.0, 1.0]",
            })
    elif strength is not None:
        result.flag_errors.append({
            "check": "pd_array",
            "field": "strength",
            "signal_id": signal.signal_id,
            "reason": f"strength must be numeric, got {type(strength).__name__}",
        })


def _validate_kill_zone(
    signal: CalculatedSignal,
    value: dict[str, Any],
    indicator: str,
    result: ValidationResult,
) -> None:
    """Validate a KILL_ZONE or NEXT_KILL_ZONE signal."""
    kz_type = value.get("kill_zone_type", "")
    valid_types = {e.value for e in KillZoneType}
    if kz_type not in valid_types:
        result.halt_errors.append({
            "check": "kill_zone",
            "field": "kill_zone_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid kill_zone_type: {kz_type!r}, expected one of {valid_types}",
        })

    if indicator == "KILL_ZONE":
        active = value.get("active")
        if not isinstance(active, bool):
            result.flag_errors.append({
                "check": "kill_zone",
                "field": "active",
                "signal_id": signal.signal_id,
                "reason": f"active must be bool, got {type(active).__name__}",
            })

        trs = value.get("time_remaining_s")
        if isinstance(trs, (int, float)) and trs < 0:
            result.flag_errors.append({
                "check": "kill_zone",
                "field": "time_remaining_s",
                "signal_id": signal.signal_id,
                "reason": f"time_remaining_s must be >= 0, got {trs}",
            })

    elif indicator == "NEXT_KILL_ZONE":
        tus = value.get("time_until_s")
        if isinstance(tus, (int, float)) and tus < 0:
            result.flag_errors.append({
                "check": "next_kill_zone",
                "field": "time_until_s",
                "signal_id": signal.signal_id,
                "reason": f"time_until_s must be >= 0, got {tus}",
            })


def _validate_liquidity(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a LIQUIDITY signal."""
    liq_type = value.get("liquidity_type", "")
    valid_types = {e.value for e in LiquidityType}
    if liq_type not in valid_types:
        result.halt_errors.append({
            "check": "liquidity",
            "field": "liquidity_type",
            "signal_id": signal.signal_id,
            "reason": f"Invalid liquidity_type: {liq_type!r}, expected one of {valid_types}",
        })

    price = value.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        result.halt_errors.append({
            "check": "liquidity",
            "field": "price",
            "signal_id": signal.signal_id,
            "reason": f"Invalid price: {price}",
        })

    swept = value.get("swept")
    if not isinstance(swept, bool):
        result.flag_errors.append({
            "check": "liquidity",
            "field": "swept",
            "signal_id": signal.signal_id,
            "reason": f"swept must be bool, got {type(swept).__name__}",
        })

    size = value.get("size")
    if isinstance(size, (int, float)) and size < 0:
        result.flag_errors.append({
            "check": "liquidity",
            "field": "size",
            "signal_id": signal.signal_id,
            "reason": f"size must be >= 0, got {size}",
        })


def _validate_liquidity_context(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a LIQUIDITY_CONTEXT signal."""
    ctx = value.get("context", "")
    # Liquidity context uses LiquidityType enum values (BUY_SIDE/SELL_SIDE/DOUBLE_DISTRIBUTION)
    valid_contexts = {e.value for e in LiquidityType}
    if ctx not in valid_contexts:
        result.halt_errors.append({
            "check": "liquidity_context",
            "field": "context",
            "signal_id": signal.signal_id,
            "reason": f"Invalid context: {ctx!r}, expected one of {valid_contexts}",
        })

    buy_active = value.get("buy_side_active", -1)
    sell_active = value.get("sell_side_active", -1)
    for name, val in [("buy_side_active", buy_active), ("sell_side_active", sell_active)]:
        if not isinstance(val, int) or val < 0:
            result.flag_errors.append({
                "check": "liquidity_context",
                "field": name,
                "signal_id": signal.signal_id,
                "reason": f"{name} must be int >= 0, got {val}",
            })

    total = value.get("total_levels", -1)
    if not isinstance(total, int) or total < 0:
        result.flag_errors.append({
            "check": "liquidity_context",
            "field": "total_levels",
            "signal_id": signal.signal_id,
            "reason": f"total_levels must be int >= 0, got {total}",
        })
