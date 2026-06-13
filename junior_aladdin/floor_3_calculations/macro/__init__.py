"""Macro domain — Calendar State Engine.

Currently provides calendar-based market intelligence:
- EVENT_CALENDAR: trading session, expiry, holiday detection
- MACRO_CONTEXT: aggregated macro context with caution level

VIX, FII/DII, and Global Cues deferred (external data dependent).
"""

from junior_aladdin.floor_3_calculations.macro.calendar_state_engine import (
    run as calendar_run,
)

__all__ = [
    "calendar_run",
]
