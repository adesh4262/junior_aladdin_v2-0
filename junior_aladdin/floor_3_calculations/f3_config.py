"""Floor 3 — Calculation parameters and configuration.

Defines ALL calculation parameters used by SMC, ICT, Technical, and
Options domain engines. Loads from YAML/JSON config file with defaults
fallback.

Architecture rules:
- ALL parameters live here — hardcoded values are FORBIDDEN in engine code.
- Timezone-aware — kill zone times defined in IST.
- Loads from config file with environment detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from junior_aladdin.floor_3_calculations.f3_types import CalculationDomain
from junior_aladdin.shared.config import Config
from junior_aladdin.shared.logging import get_logger

logger = get_logger("f3_config")

# Default config section key in YAML
_F3_CONFIG_SECTION = "floor_3"


# =============================================================================
# SMC PARAMETERS
# =============================================================================


@dataclass
class SmcParameters:
    """SMC domain calculation parameters.

    All values have sensible defaults that can be overridden via config file.
    """

    # FVG detection
    fvg_min_gap_pips: float = 0.5
    """Minimum price gap (in pips) to classify as a Fair Value Gap."""
    fvg_max_lookback_candles: int = 20
    """Maximum candles to look back for FVG mitigation detection."""

    # Order Block detection
    ob_lookback_candles: int = 10
    """Candle window for order block formation detection."""

    # Change of Character (CHOCH)
    choch_required_consecutive: int = 2
    """Number of consecutive candles needed to confirm a CHOCH."""

    # Market Structure
    market_structure_lookback: int = 50
    """Number of candles to look back for HH/HL/LH/LL swing detection."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dict for config serialization."""
        return {
            "fvg_min_gap_pips": self.fvg_min_gap_pips,
            "fvg_max_lookback_candles": self.fvg_max_lookback_candles,
            "ob_lookback_candles": self.ob_lookback_candles,
            "choch_required_consecutive": self.choch_required_consecutive,
            "market_structure_lookback": self.market_structure_lookback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmcParameters:
        """Create from a dict (missing keys use defaults)."""
        return cls(
            fvg_min_gap_pips=float(data.get("fvg_min_gap_pips", cls.fvg_min_gap_pips)),
            fvg_max_lookback_candles=int(data.get("fvg_max_lookback_candles", cls.fvg_max_lookback_candles)),
            ob_lookback_candles=int(data.get("ob_lookback_candles", cls.ob_lookback_candles)),
            choch_required_consecutive=int(data.get("choch_required_consecutive", cls.choch_required_consecutive)),
            market_structure_lookback=int(data.get("market_structure_lookback", cls.market_structure_lookback)),
        )

    def validate(self) -> list[str]:
        """Validate parameter values.

        Returns:
            List of validation warning/error messages. Empty list = valid.
        """
        issues: list[str] = []
        if self.fvg_min_gap_pips <= 0:
            issues.append("fvg_min_gap_pips must be > 0")
        if self.fvg_max_lookback_candles < 5:
            issues.append("fvg_max_lookback_candles should be >= 5")
        if self.ob_lookback_candles < 3:
            issues.append("ob_lookback_candles should be >= 3")
        if self.choch_required_consecutive < 1:
            issues.append("choch_required_consecutive must be >= 1")
        if self.market_structure_lookback < 10:
            issues.append("market_structure_lookback should be >= 10")
        return issues


# =============================================================================
# ICT PARAMETERS
# =============================================================================


@dataclass
class IctParameters:
    """ICT domain calculation parameters.

    Time values are in IST (Indian Standard Time, UTC+5:30).
    """

    # PD Array
    pd_array_period: int = 20
    """Lookback period for premium/discount array calculation."""

    # Kill Zone timing (IST)
    kill_zone_buffer_minutes: int = 15
    """Buffer in minutes before/after kill zone boundaries."""

    asian_range_start: str = "02:30"
    """Asian kill zone start time (IST)."""
    asian_range_end: str = "09:15"
    """Asian kill zone end time (IST)."""
    london_open_start: str = "12:30"
    """London Open kill zone start time (IST)."""
    london_open_end: str = "14:30"
    """London Open kill zone end time (IST)."""
    ny_am_open_start: str = "17:30"
    """NY AM Open kill zone start time (IST)."""
    ny_am_open_end: str = "20:00"
    """NY AM Open kill zone end time (IST)."""
    ny_pm_close_start: str = "22:00"
    """NY PM Close kill zone start time (IST)."""
    ny_pm_close_end: str = "23:00"
    """NY PM Close kill zone end time (IST)."""

    # Liquidity detection
    liquidity_sweep_threshold_pips: float = 0.3
    """Minimum price movement beyond a level to consider it swept."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dict for config serialization."""
        return {
            "pd_array_period": self.pd_array_period,
            "kill_zone_buffer_minutes": self.kill_zone_buffer_minutes,
            "asian_range_start": self.asian_range_start,
            "asian_range_end": self.asian_range_end,
            "london_open_start": self.london_open_start,
            "london_open_end": self.london_open_end,
            "ny_am_open_start": self.ny_am_open_start,
            "ny_am_open_end": self.ny_am_open_end,
            "ny_pm_close_start": self.ny_pm_close_start,
            "ny_pm_close_end": self.ny_pm_close_end,
            "liquidity_sweep_threshold_pips": self.liquidity_sweep_threshold_pips,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IctParameters:
        """Create from a dict (missing keys use defaults)."""
        return cls(
            pd_array_period=int(data.get("pd_array_period", cls.pd_array_period)),
            kill_zone_buffer_minutes=int(data.get("kill_zone_buffer_minutes", cls.kill_zone_buffer_minutes)),
            asian_range_start=str(data.get("asian_range_start", cls.asian_range_start)),
            asian_range_end=str(data.get("asian_range_end", cls.asian_range_end)),
            london_open_start=str(data.get("london_open_start", cls.london_open_start)),
            london_open_end=str(data.get("london_open_end", cls.london_open_end)),
            ny_am_open_start=str(data.get("ny_am_open_start", cls.ny_am_open_start)),
            ny_am_open_end=str(data.get("ny_am_open_end", cls.ny_am_open_end)),
            ny_pm_close_start=str(data.get("ny_pm_close_start", cls.ny_pm_close_start)),
            ny_pm_close_end=str(data.get("ny_pm_close_end", cls.ny_pm_close_end)),
            liquidity_sweep_threshold_pips=float(data.get("liquidity_sweep_threshold_pips", cls.liquidity_sweep_threshold_pips)),
        )

    def validate(self) -> list[str]:
        """Validate parameter values.

        Returns:
            List of validation warning/error messages. Empty list = valid.
        """
        issues: list[str] = []
        if self.pd_array_period < 5:
            issues.append("pd_array_period should be >= 5")
        if self.kill_zone_buffer_minutes < 0:
            issues.append("kill_zone_buffer_minutes must be >= 0")
        if self.liquidity_sweep_threshold_pips <= 0:
            issues.append("liquidity_sweep_threshold_pips must be > 0")

        # Validate time format (HH:MM)
        for name, value in [
            ("asian_range_start", self.asian_range_start),
            ("asian_range_end", self.asian_range_end),
            ("london_open_start", self.london_open_start),
            ("london_open_end", self.london_open_end),
            ("ny_am_open_start", self.ny_am_open_start),
            ("ny_am_open_end", self.ny_am_open_end),
            ("ny_pm_close_start", self.ny_pm_close_start),
            ("ny_pm_close_end", self.ny_pm_close_end),
        ]:
            if not _is_valid_time_format(value):
                issues.append(f"{name}: invalid time format {value!r} (expected HH:MM)")
        return issues


# =============================================================================
# TECHNICAL PARAMETERS
# =============================================================================


@dataclass
class TechnicalParameters:
    """Technical Analysis domain calculation parameters."""

    # RSI
    rsi_period: int = 14
    """RSI lookback period."""
    rsi_overbought: float = 70.0
    """RSI overbought threshold."""
    rsi_oversold: float = 30.0
    """RSI oversold threshold."""

    # Moving Averages
    ma_fast_period: int = 9
    """Fast MA period (typically EMA)."""
    ma_slow_period: int = 21
    """Slow MA period (typically EMA)."""

    # ATR
    atr_period: int = 14
    """ATR lookback period."""

    # Volume Profile
    volume_profile_period: int = 30
    """Number of candles per VPVR (Volume Profile Visible Range) session."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dict for config serialization."""
        return {
            "rsi_period": self.rsi_period,
            "rsi_overbought": self.rsi_overbought,
            "rsi_oversold": self.rsi_oversold,
            "ma_fast_period": self.ma_fast_period,
            "ma_slow_period": self.ma_slow_period,
            "atr_period": self.atr_period,
            "volume_profile_period": self.volume_profile_period,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TechnicalParameters:
        """Create from a dict (missing keys use defaults)."""
        return cls(
            rsi_period=int(data.get("rsi_period", cls.rsi_period)),
            rsi_overbought=float(data.get("rsi_overbought", cls.rsi_overbought)),
            rsi_oversold=float(data.get("rsi_oversold", cls.rsi_oversold)),
            ma_fast_period=int(data.get("ma_fast_period", cls.ma_fast_period)),
            ma_slow_period=int(data.get("ma_slow_period", cls.ma_slow_period)),
            atr_period=int(data.get("atr_period", cls.atr_period)),
            volume_profile_period=int(data.get("volume_profile_period", cls.volume_profile_period)),
        )

    def validate(self) -> list[str]:
        """Validate parameter values.

        Returns:
            List of validation warning/error messages. Empty list = valid.
        """
        issues: list[str] = []
        if self.rsi_period < 2:
            issues.append("rsi_period must be >= 2")
        if self.rsi_overbought <= self.rsi_oversold:
            issues.append("rsi_overbought must be > rsi_oversold")
        if self.rsi_oversold < 0 or self.rsi_overbought > 100:
            issues.append("rsi_overbought (0-100) or rsi_oversold (0-100) out of range")
        if self.ma_fast_period < 1:
            issues.append("ma_fast_period must be >= 1")
        if self.ma_slow_period <= self.ma_fast_period:
            issues.append("ma_slow_period must be > ma_fast_period")
        if self.atr_period < 2:
            issues.append("atr_period must be >= 2")
        if self.volume_profile_period < 5:
            issues.append("volume_profile_period should be >= 5")
        return issues


# =============================================================================
# OPTIONS PARAMETERS
# =============================================================================


@dataclass
class OptionsParameters:
    """Options domain calculation parameters."""

    min_oi_change_pct: float = 5.0
    """Minimum OI change percentage to consider significant."""
    iv_high_threshold: float = 30.0
    """IV above this %% is classified as HIGH."""
    iv_low_threshold: float = 15.0
    """IV below this %% is classified as LOW."""
    wall_top_n: int = 3
    """Number of top walls to return per side (CE/PE)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dict for config serialization."""
        return {
            "min_oi_change_pct": self.min_oi_change_pct,
            "iv_high_threshold": self.iv_high_threshold,
            "iv_low_threshold": self.iv_low_threshold,
            "wall_top_n": self.wall_top_n,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptionsParameters:
        """Create from a dict (missing keys use defaults)."""
        return cls(
            min_oi_change_pct=float(data.get("min_oi_change_pct", cls.min_oi_change_pct)),
            iv_high_threshold=float(data.get("iv_high_threshold", cls.iv_high_threshold)),
            iv_low_threshold=float(data.get("iv_low_threshold", cls.iv_low_threshold)),
            wall_top_n=int(data.get("wall_top_n", cls.wall_top_n)),
        )

    def validate(self) -> list[str]:
        """Validate parameter values.

        Returns:
            List of validation warning/error messages. Empty list = valid.
        """
        issues: list[str] = []
        if self.min_oi_change_pct <= 0:
            issues.append("min_oi_change_pct must be > 0")
        if self.iv_high_threshold <= self.iv_low_threshold:
            issues.append("iv_high_threshold must be > iv_low_threshold")
        if self.iv_low_threshold < 0:
            issues.append("iv_low_threshold must be >= 0")
        if self.wall_top_n < 1:
            issues.append("wall_top_n must be >= 1")
        return issues


# =============================================================================
# GENERAL PARAMETERS
# =============================================================================


@dataclass
class GeneralParameters:
    """General Floor 3 calculation parameters."""

    calculation_timeout_ms: int = 5000
    """Maximum time (ms) allowed per engine calculation cycle."""
    max_signals_per_domain_per_cycle: int = 50
    """Maximum signals a single domain engine can produce per cycle."""
    min_data_points_per_calculation: int = 5
    """Minimum data points required for a calculation (else INSUFFICIENT_DATA)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dict for config serialization."""
        return {
            "calculation_timeout_ms": self.calculation_timeout_ms,
            "max_signals_per_domain_per_cycle": self.max_signals_per_domain_per_cycle,
            "min_data_points_per_calculation": self.min_data_points_per_calculation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GeneralParameters:
        """Create from a dict (missing keys use defaults)."""
        return cls(
            calculation_timeout_ms=int(data.get("calculation_timeout_ms", cls.calculation_timeout_ms)),
            max_signals_per_domain_per_cycle=int(data.get("max_signals_per_domain_per_cycle", cls.max_signals_per_domain_per_cycle)),
            min_data_points_per_calculation=int(data.get("min_data_points_per_calculation", cls.min_data_points_per_calculation)),
        )

    def validate(self) -> list[str]:
        """Validate parameter values.

        Returns:
            List of validation warning/error messages. Empty list = valid.
        """
        issues: list[str] = []
        if self.calculation_timeout_ms < 100:
            issues.append("calculation_timeout_ms should be >= 100ms")
        if self.max_signals_per_domain_per_cycle < 1:
            issues.append("max_signals_per_domain_per_cycle must be >= 1")
        if self.min_data_points_per_calculation < 1:
            issues.append("min_data_points_per_calculation must be >= 1")
        return issues


# =============================================================================
# F3 CONFIG — MASTER CONFIGURATION
# =============================================================================


@dataclass
class F3Config:
    """Master configuration for Floor 3 calculation engines.

    Aggregates all domain-specific and general parameters.
    Supports loading from YAML config files with environment detection.

    Usage::

        # Default config (all parameters at built-in defaults)
        config = F3Config()

        # Load from a loaded system config
        system_config = Config(env=\"test\")
        config = F3Config.load(system_config)

        # Access parameters
        config.smc.fvg_min_gap_pips      # 0.5
        config.ict.asian_range_start     # \"02:30\"
        config.technical.rsi_period      # 14
        config.general.calculation_timeout_ms  # 5000
    """

    smc: SmcParameters = field(default_factory=SmcParameters)
    """SMC domain calculation parameters."""
    ict: IctParameters = field(default_factory=IctParameters)
    """ICT domain calculation parameters."""
    technical: TechnicalParameters = field(default_factory=TechnicalParameters)
    """Technical domain calculation parameters."""
    options: OptionsParameters = field(default_factory=OptionsParameters)
    """Options domain calculation parameters."""
    general: GeneralParameters = field(default_factory=GeneralParameters)
    """General calculation parameters."""

    # ── Load/Save ──────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        config: Config | None = None,
        config_path: Path | str | None = None,
    ) -> F3Config:
        """Load Floor 3 config from a system Config object or YAML file.

        Args:
            config: A loaded ``Config`` instance (from ``shared/config.py``).
                If provided, reads the ``floor_3`` section from its config dict.
            config_path: Optional direct path to a YAML config file.
                Used only if ``config`` is not provided.

        Returns:
            A populated ``F3Config`` instance. Missing keys use defaults.
        """
        data: dict[str, Any] = {}

        if config is not None:
            # Read from system Config's YAML data
            raw = config.get(_F3_CONFIG_SECTION, {})
            if isinstance(raw, dict):
                data = raw
            else:
                logger.warning(
                    "Floor 3 config section is not a dict, using defaults",
                    extra={"section": _F3_CONFIG_SECTION},
                )
        elif config_path is not None:
            # Load directly from a YAML file
            path = Path(config_path)
            if path.is_file():
                try:
                    with open(path, encoding="utf-8") as f:
                        raw = yaml.safe_load(f) or {}
                    data = raw.get(_F3_CONFIG_SECTION, {})
                    if not isinstance(data, dict):
                        data = {}
                except Exception as exc:
                    logger.warning(
                        "Failed to load Floor 3 config file",
                        extra={"path": str(path), "error": str(exc)},
                    )
            else:
                logger.warning(
                    "Floor 3 config file not found, using defaults",
                    extra={"path": str(path)},
                )
        else:
            logger.info("No config provided — using all default parameters")

        return cls._from_dict(data)

    def save(self, path: Path | str) -> None:
        """Save the current configuration to a YAML file.

        Args:
            path: Path where the YAML file will be written.
        """
        path = Path(path)
        data = {_F3_CONFIG_SECTION: self.to_dict()}
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info("Floor 3 config saved", extra={"path": str(path)})

    # ── Serialization ──────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Export all parameters as a nested dict.

        Returns:
            Dict with keys ``smc``, ``ict``, ``technical``,
            ``options``, ``general``.
        """
        return {
            "smc": self.smc.to_dict(),
            "ict": self.ict.to_dict(),
            "technical": self.technical.to_dict(),
            "options": self.options.to_dict(),
            "general": self.general.to_dict(),
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> F3Config:
        """Build config from a nested dict (YAML section)."""
        return cls(
            smc=SmcParameters.from_dict(data.get("smc", {})),
            ict=IctParameters.from_dict(data.get("ict", {})),
            technical=TechnicalParameters.from_dict(data.get("technical", {})),
            options=OptionsParameters.from_dict(data.get("options", {})),
            general=GeneralParameters.from_dict(data.get("general", {})),
        )

    # ── Validation ─────────────────────────────────────────────────────

    def validate(self) -> dict[str, list[str]]:
        """Validate ALL parameter groups.

        Returns:
            Dict mapping parameter group names to their issues list.
            Empty lists mean no issues for that group.
        """
        return {
            "smc": self.smc.validate(),
            "ict": self.ict.validate(),
            "technical": self.technical.validate(),
            "options": self.options.validate(),
            "general": self.general.validate(),
        }

    def has_issues(self) -> bool:
        """Check whether any parameter group has validation issues.

        Returns:
            ``True`` if any validation issues exist.
        """
        return any(
            len(issues) > 0
            for issues in self.validate().values()
        )

    def get_params_for_domain(self, domain: CalculationDomain) -> dict[str, Any]:
        """Get parameters relevant to a specific calculation domain.

        Args:
            domain: The calculation domain to get parameters for.

        Returns:
            A flat dict of parameter names and values for the domain.
        """
        if domain == CalculationDomain.SMC:
            return self.smc.to_dict()
        elif domain == CalculationDomain.ICT:
            return self.ict.to_dict()
        elif domain == CalculationDomain.TECHNICAL:
            return self.technical.to_dict()
        elif domain == CalculationDomain.OPTIONS:
            return self.options.to_dict()
        return {}


# =============================================================================
# MODULE-LEVEL DEFAULT INSTANCE
# =============================================================================

_default_config: F3Config | None = None


def get_default_config() -> F3Config:
    """Get or create the module-level default F3Config instance.

    Uses lazy initialization — the config is loaded on first call.

    Returns:
        The default ``F3Config`` instance.
    """
    global _default_config
    if _default_config is None:
        _default_config = F3Config()
    return _default_config


def reset_default_config() -> None:
    """Reset the default config to force re-initialization on next access.

    Useful in tests to ensure a clean config state.
    """
    global _default_config
    _default_config = None


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _is_valid_time_format(value: str) -> bool:
    """Check if a string is in HH:MM 24-hour format.

    Args:
        value: The time string to check.

    Returns:
        ``True`` if the format is valid.
    """
    if not isinstance(value, str) or ":" not in value:
        return False
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        return 0 <= hours <= 23 and 0 <= minutes <= 59
    except (ValueError, TypeError):
        return False
