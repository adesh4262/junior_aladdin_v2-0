"""Options — Calculation Engine.

Transforms Floor 2 OptionsSnapshot data into structured CalculatedSignal
outputs for Floor 4 Options Head consumption.

Calculators:
- oi_calculator: OI_CHANGE — CE/PE buying vs unwinding detection
- pcr_calculator: PCR — Put-Call Ratio value and trend
- iv_calculator: IV — Implied Volatility state analysis
- wall_calculator: CALL_WALL / PUT_WALL — wall strike detection
- max_pain_calculator: MAX_PAIN — max pain strike calculation

Architecture rules:
- Pure calculations — no interpretation, no confidence.
- No state — each run is independent and deterministic.
- data is consumed via ``calc_input.data["options_snapshots"]`` dict.
"""

from junior_aladdin.floor_3_calculations.options.options_engine import run

__all__ = ["run"]
