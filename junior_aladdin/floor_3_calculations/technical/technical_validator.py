"""Technical — Domain-specific Validation Layer.

Validates Technical-domain signals before they are accepted into the OutputContract.

Domain-specific validation rules:
- RSI: rsi_value must be in [0, 100], oversold/overbought bool, classification string valid.
- MA_FAST / MA_SLOW: period must be int >= 1, latest_value numeric, total_values int >= 0.
- MA_CROSS: cross string, fast/slow periods int >= 1, values numeric.
- ATR: period int >= 1, latest_value >= 0, total_values int >= 0.
- VOLUME_PROFILE: poc/vah/val numeric, value_area_volume >= 0, total_volume >= 0.

Architecture rules:
- Pure validation — no modification of signals.
- Violations are LOGGED, never silently ignored.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
)
VALIDATOR_VERSION = "1.0"


class ValidationResult:
    """Result of Technical domain validation."""

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


def validate_technical_signals(signals: list[CalculatedSignal]) -> ValidationResult:
    """Validate all Technical-domain signals in a list.

    Args:
        signals: List of CalculatedSignal objects (only Technical should be passed).

    Returns:
        ValidationResult with per-signal validation details.
    """
    result = ValidationResult()

    for signal in signals:
        if signal.domain != CalculationDomain.TECHNICAL:
            continue

        result.total_checks += 1
        indicator = signal.indicator_type
        value = signal.value if isinstance(signal.value, dict) else {}

        if indicator == "RSI":
            _validate_rsi(signal, value, result)
        elif indicator in ("MA_FAST", "MA_SLOW"):
            _validate_ma(signal, value, indicator, result)
        elif indicator == "MA_CROSS":
            _validate_ma_cross(signal, value, result)
        elif indicator == "ATR":
            _validate_atr(signal, value, result)
        elif indicator == "VOLUME_PROFILE":
            _validate_volume_profile(signal, value, result)
        else:
            result.flag_errors.append({
                "check": "unknown_indicator",
                "signal_id": signal.signal_id,
                "indicator_type": indicator,
                "reason": f"Unknown Technical indicator type: {indicator}",
            })

    result.valid = len(result.halt_errors) == 0
    return result


def quick_validate(signals: list[CalculatedSignal]) -> bool:
    """Quick pass/fail — only HALT-level errors."""
    result = validate_technical_signals(signals)
    return result.valid


# =============================================================================
# DOMAIN-SPECIFIC VALIDATORS
# =============================================================================

_VALID_RSI_CLASSIFICATIONS = {"OVERSOLD", "OVERBOUGHT", "NEUTRAL", "BULLISH", "BEARISH"}


def _validate_rsi(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate an RSI signal."""
    rsi_val = value.get("rsi_value")
    if not isinstance(rsi_val, (int, float)) or rsi_val < 0 or rsi_val > 100:
        result.halt_errors.append({
            "check": "rsi",
            "field": "rsi_value",
            "signal_id": signal.signal_id,
            "reason": f"rsi_value must be in [0, 100], got {rsi_val}",
        })

    oversold = value.get("oversold")
    if not isinstance(oversold, bool):
        result.flag_errors.append({
            "check": "rsi",
            "field": "oversold",
            "signal_id": signal.signal_id,
            "reason": f"oversold must be bool, got {type(oversold).__name__}",
        })

    overbought = value.get("overbought")
    if not isinstance(overbought, bool):
        result.flag_errors.append({
            "check": "rsi",
            "field": "overbought",
            "signal_id": signal.signal_id,
            "reason": f"overbought must be bool, got {type(overbought).__name__}",
        })

    classification = value.get("classification", "")
    if classification and classification not in _VALID_RSI_CLASSIFICATIONS:
        result.flag_errors.append({
            "check": "rsi",
            "field": "classification",
            "signal_id": signal.signal_id,
            "reason": f"Invalid classification: {classification!r}",
        })


def _validate_ma(
    signal: CalculatedSignal,
    value: dict[str, Any],
    indicator: str,
    result: ValidationResult,
) -> None:
    """Validate an MA_FAST or MA_SLOW signal."""
    period = value.get("period", -1)
    if not isinstance(period, int) or period < 1:
        result.halt_errors.append({
            "check": "ma",
            "field": "period",
            "signal_id": signal.signal_id,
            "reason": f"period must be int >= 1, got {period}",
        })

    lv = value.get("latest_value")
    if not isinstance(lv, (int, float)):
        result.halt_errors.append({
            "check": "ma",
            "field": "latest_value",
            "signal_id": signal.signal_id,
            "reason": f"latest_value must be numeric, got {type(lv).__name__}",
        })

    tv = value.get("total_values", -1)
    if not isinstance(tv, int) or tv < 0:
        result.flag_errors.append({
            "check": "ma",
            "field": "total_values",
            "signal_id": signal.signal_id,
            "reason": f"total_values must be int >= 0, got {tv}",
        })


_CROSS_TYPES = {"BULLISH_CROSS", "BEARISH_CROSS", "NO_CROSS", "TOUCH"}


def _validate_ma_cross(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate an MA_CROSS signal."""
    cross = value.get("cross", "")
    if cross and cross not in _CROSS_TYPES:
        result.flag_errors.append({
            "check": "ma_cross",
            "field": "cross",
            "signal_id": signal.signal_id,
            "reason": f"Invalid cross: {cross!r}",
        })

    for field in ("fast_period", "slow_period"):
        p = value.get(field, -1)
        if not isinstance(p, int) or p < 1:
            result.flag_errors.append({
                "check": "ma_cross",
                "field": field,
                "signal_id": signal.signal_id,
                "reason": f"{field} must be int >= 1, got {p}",
            })

    # fast_value and slow_value should be numeric if present
    for field in ("fast_value", "slow_value"):
        fv = value.get(field)
        if fv is not None and not isinstance(fv, (int, float)):
            result.flag_errors.append({
                "check": "ma_cross",
                "field": field,
                "signal_id": signal.signal_id,
                "reason": f"{field} must be numeric, got {type(fv).__name__}",
            })


def _validate_atr(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate an ATR signal."""
    period = value.get("period", -1)
    if not isinstance(period, int) or period < 1:
        result.halt_errors.append({
            "check": "atr",
            "field": "period",
            "signal_id": signal.signal_id,
            "reason": f"period must be int >= 1, got {period}",
        })

    lv = value.get("latest_value")
    if not isinstance(lv, (int, float)) or lv < 0:
        result.halt_errors.append({
            "check": "atr",
            "field": "latest_value",
            "signal_id": signal.signal_id,
            "reason": f"latest_value must be numeric >= 0, got {lv}",
        })

    tv = value.get("total_values", -1)
    if not isinstance(tv, int) or tv < 0:
        result.flag_errors.append({
            "check": "atr",
            "field": "total_values",
            "signal_id": signal.signal_id,
            "reason": f"total_values must be int >= 0, got {tv}",
        })


def _validate_volume_profile(
    signal: CalculatedSignal,
    value: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate a VOLUME_PROFILE signal."""
    poc = value.get("poc")
    if not isinstance(poc, (int, float)) or poc <= 0:
        result.halt_errors.append({
            "check": "volume_profile",
            "field": "poc",
            "signal_id": signal.signal_id,
            "reason": f"poc must be numeric > 0, got {poc}",
        })

    vah = value.get("vah")
    if not isinstance(vah, (int, float)) or vah <= 0:
        result.halt_errors.append({
            "check": "volume_profile",
            "field": "vah",
            "signal_id": signal.signal_id,
            "reason": f"vah must be numeric > 0, got {vah}",
        })

    val = value.get("val")
    if not isinstance(val, (int, float)) or val <= 0:
        result.halt_errors.append({
            "check": "volume_profile",
            "field": "val",
            "signal_id": signal.signal_id,
            "reason": f"val must be numeric > 0, got {val}",
        })

    # VAH > VAL sanity check
    if isinstance(vah, (int, float)) and isinstance(val, (int, float)):
        if vah <= val:
            result.flag_errors.append({
                "check": "volume_profile",
                "field": "vah_val",
                "signal_id": signal.signal_id,
                "reason": f"vah ({vah}) should be > val ({val})",
            })

    for field, name in [("value_area_volume", "value_area_volume"),
                        ("total_volume", "total_volume")]:
        v = value.get(field, -1)
        if not isinstance(v, (int, float)) or v < 0:
            result.flag_errors.append({
                "check": "volume_profile",
                "field": name,
                "signal_id": signal.signal_id,
                "reason": f"{name} must be >= 0, got {v}",
            })
