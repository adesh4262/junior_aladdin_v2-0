"""Support Metrics — Floor 3 domain for psychology/behavior support.

This domain is intentionally MINIMAL.
It provides 4 support calculators for the Floor 4 Psychology Head:

1. trap_metrics_engine  — Detects trap patterns (false breaks, repeated setup failures)
2. loss_metrics_engine  — Tracks consecutive losses and loss count
3. cooldown_metrics_engine — Manages cooldown timer after losses/errors
4. overtrade_metrics_engine — Detects overtrading patterns

Architecture rules:
- Pure functions — no state, no external calls.
- No interpretation — only structured data.
- Supports Floor 4 Psychology Head but does NOT replace it.
- No Maps, no Scores, no Candidate Outputs (per Plan Section 17).
"""

from junior_aladdin.floor_3_calculations.support_metrics.trap_metrics_engine import (
    detect_trap_pressure,
)
from junior_aladdin.floor_3_calculations.support_metrics.loss_metrics_engine import (
    compute_loss_report,
)
from junior_aladdin.floor_3_calculations.support_metrics.cooldown_metrics_engine import (
    compute_cooldown_status,
)
from junior_aladdin.floor_3_calculations.support_metrics.overtrade_metrics_engine import (
    detect_overtrade,
)
from junior_aladdin.floor_3_calculations.support_metrics.support_metrics_engine import (
    run as support_metrics_run,
)

__all__ = [
    "detect_trap_pressure",
    "compute_loss_report",
    "compute_cooldown_status",
    "detect_overtrade",
    "support_metrics_run",
]
